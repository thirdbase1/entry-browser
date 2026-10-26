"""entrybrowser.js — JavaScript execution with a mini-DOM (QuickJS via quickjs)."""
from __future__ import annotations

def has_js() -> bool:
    try:
        import quickjs
        return True
    except ImportError:
        return False

class JSRuntime:
    def __init__(self, doc):
        self.doc = doc
        self.doc._mutated = False
        self.focused_id = None
        self.console_log: list[str] = []
        self.title = ""
        self.ok = False
        try:
            import quickjs
            self._qjs = quickjs
            self.ok = True
        except ImportError:
            return
        self.ctx = quickjs.Context()
        self._handlers: dict[tuple, object] = {}   # (elem_id, type) -> JS function
        self._timers: dict[int, dict] = {}
        self._timer_seq = 0
        self._bridge = _DomBridge(self)
        for name in ("byId","prop","setProp","title","setTitle","byClass","qs","qsa","log","call",
                     "addEventListener","setTimeoutReg","setIntervalReg","setTimerFn","classListOp"):
            self.ctx.add_callable("__classList" if name == "classListOp" else f"__{name}",
                                  getattr(self._bridge, name))
        self.ctx.eval("""
        function __mk(id) {
          return {
            id: id,
            get textContent() { return __prop(id, 'textContent'); },
            set textContent(v) { __setProp(id, 'textContent', String(v)); },
            get innerHTML() { return __prop(id, 'innerHTML'); },
            set innerHTML(v) { __setProp(id, 'innerHTML', String(v)); },
            get value() { return __prop(id, 'value'); },
            set value(v) { __setProp(id, 'value', String(v)); },
            get checked() { return __prop(id, 'checked') !== ''; },
            set checked(v) { __setProp(id, 'checked', v ? '' : undefined); },
            get tagName() { return __prop(id, 'tagName'); },
            get disabled() { return __prop(id, 'disabled') !== ''; },
            set disabled(v) { __setProp(id, 'disabled', v ? '' : undefined); },
            style: {},
            focus: function() { __call(id, 'focus'); },
            blur: function() { __call(id, 'blur'); },
            click: function() { __call(id, 'click'); },
            remove: function() { __call(id, 'remove'); },
            addEventListener: function(type, fn) { __addEventListener(id, type, fn); },
            classList: {
              add: function(c) { __classList(id, 'add', c); },
              remove: function(c) { __classList(id, 'remove', c); },
              toggle: function(c) { __classList(id, 'toggle', c); },
              contains: function(c) { return __classList(id, 'contains', c); }
            }
          };
        }
        var document = {
          getElementById: function(i){ return __byId(i) ? __mk(i) : null; },
          getElementsByClassName: function(c){ return __byClass(c).map(__mk); },
          querySelector: function(s){ var r=__qs(s); return r ? __mk(r) : null; },
          querySelectorAll: function(s){ return __qsa(s).map(__mk); },
          get title(){ return __title(); },
          set title(v){ __setTitle(String(v)); }
        };
        var __timers = { _n: 0 };
        function setTimeout(fn, ms) { var id = __setTimeoutReg(); __setTimerFn(id, fn, false); return id; }
        function setInterval(fn, ms) { var id = __setIntervalReg(); __setTimerFn(id, fn, true); return id; }
        var console = { log: function(){ __log(Array.prototype.join.call(arguments, ' ')); },
                        warn: function(){ __log('WARN: ' + Array.prototype.join.call(arguments, ' ')); },
                        error: function(){ __log('ERROR: ' + Array.prototype.join.call(arguments, ' ')); } };
        function alert(m){ __log('ALERT: ' + m); }
        """)
    def addEventListener(self, elem_id, type, fn):
        self._handlers[(elem_id, type)] = fn
    def setTimeoutReg(self):
        self._timer_seq += 1
        self._timers[self._timer_seq] = {"fn": None, "fired": False}
        return self._timer_seq
    def setIntervalReg(self):
        self._timer_seq += 1
        self._timers[self._timer_seq] = {"fn": None, "interval": True}
        return self._timer_seq
    def fire_event(self, elem_id: str, type: str = "click") -> bool:
        """Dispatch a DOM event; returns True if a handler ran."""
        fn = self._handlers.get((elem_id, type))
        if fn is None:
            # bubble to ancestors via 'onclick' attributes handled at DOM level
            return False
        try:
            fn()
            return True
        except Exception as e:
            self.console_log.append(f"[event error] {e}")
            return False
    def fire_onclick_attr(self, elem_id: str) -> bool:
        """Run onclick="..." attribute code for a node."""
        n = self._bridge._n(elem_id)
        code = (n.attrs.get("onclick") or "") if n else ""
        if not code:
            return False
        el = self.ctx.eval(f"document.getElementById({elem_id!r})")
        try:
            self.ctx.eval(f"(function(el){{ {code} }})(document.getElementById({elem_id!r}))")
            return True
        except Exception as e:
            self.console_log.append(f"[onclick error] {e}")
            return False
    def run_timers(self, max_steps: int = 20) -> int:
        """Fire pending setTimeout callbacks (and N setInterval rounds). Returns count fired."""
        fired = 0
        for tid, t in list(self._timers.items()):
            if t.get("fn") is None and not isinstance(t.get("interval"), bool):
                continue
            if t.get("fired") and not t.get("interval"):
                continue
            fn = t.get("fn")
            if fn is not None:
                try:
                    fn(); fired += 1
                except Exception as e:
                    self.console_log.append(f"[timer error] {e}")
            t["fired"] = True
            if fired >= max_steps: break
        return fired
    def run(self, code: str, url="<inline>") -> str | None:
        if not self.ok:
            return None
        try:
            out = self.ctx.eval(code)
            return str(out) if out is not None else None
        except Exception as e:
            return f"[js error] {e}"

class _DomBridge:
    def __init__(self, rt: JSRuntime):
        self.rt = rt
    def addEventListener(self, elem_id, type, fn):
        self.rt._handlers[(str(elem_id), str(type))] = fn
    def setTimerFn(self, tid, fn, interval):
        t = self.rt._timers.get(tid)
        if t is not None:
            t["fn"] = fn
            t["interval"] = bool(interval)
    def setTimeoutReg(self):
        return self.rt.setTimeoutReg()
    def setIntervalReg(self):
        return self.rt.setIntervalReg()
    def _n(self, i):
        for n in self.rt.doc.walk():
            if n.attrs.get("id") == i: return n
        return None
    def _id(self, n):
        return n.attrs.get("id") or f"__el{id(n) % 10**10}"
    def byId(self, i):
        return i if self._n(i) else None
    def byClass(self, c):
        return [self._id(n) for n in self.rt.doc.walk() if c in (n.attrs.get("class") or "").split()]
    def qs(self, sel):
        sel = sel.strip()
        if sel.startswith("#"): return self.byId(sel[1:])
        if sel.startswith("."):
            l = self.byClass(sel[1:]); return l[0] if l else None
        for n in self.rt.doc.walk():
            if n.tag == sel.lower(): return self._id(n)
        return None
    def qsa(self, sel):
        sel = sel.strip()
        if sel.startswith("."): return self.byClass(sel[1:])
        if sel.startswith("#"):
            i = self.byId(sel[1:]); return [i] if i else []
        return [self._id(n) for n in self.rt.doc.walk() if n.tag == sel.lower()]
    def title(self): return self.rt.title
    def setTitle(self, v):
        self.rt.title = v; self.rt.doc._mutated = True
    def log(self, msg): self.rt.console_log.append(str(msg))
    def prop(self, i, p):
        n = self._n(i)
        if n is None: return ""
        if p == "textContent": return n.text_content()
        if p == "innerHTML": return n.text_content()
        if p == "tagName": return n.tag.upper()
        if p == "value": return n.attrs.get("value", "".join(c.text or "" for c in n.children if c.tag == "#text") if n.tag == "textarea" else "")
        if p == "checked" or p == "disabled": return n.attrs.get(p, "")
        if p.startswith("style."): return n.attrs.get("style","")
        return n.attrs.get(p, "")
    def setProp(self, i, p, v):
        n = self._n(i)
        if n is None: return
        from entrybrowser.html import Node, parse
        if p == "textContent":
            n.children.clear(); n.append(Node("#text", text=str(v)))
        elif p == "innerHTML":
            frag = parse(f"<div>{v}</div>")
            div = frag.query_all("div")[0]
            n.children.clear()
            for c in div.children: n.append(c)
        elif p.startswith("style."):
            k = p[6:]
            n.attrs["style"] = (n.attrs.get("style","") + f";{k}:{v}").lstrip(";")
        else:
            n.attrs[p] = str(v)
        self.rt.doc._mutated = True
    def classListOp(self, i, op, c):
        n = self._n(i)
        if n is None: return ""
        cls = (n.attrs.get("class") or "").split()
        if op == "add" and c not in cls: cls.append(c)
        elif op == "remove" and c in cls: cls.remove(c)
        elif op == "toggle":
            cls.remove(c) if c in cls else cls.append(c)
        elif op == "contains":
            return c in cls
        n.attrs["class"] = " ".join(cls)
        self.rt.doc._mutated = True
        return ""
    def call(self, i, meth):
        n = self._n(i)
        if n is None: return
        if meth == "focus":
            self.rt.focused_id = i
        elif meth == "blur":
            self.rt.focused_id = None
        elif meth == "click":
            self.rt.fire_event(i, "click")
            code = (n.attrs.get("onclick") or "")
            if code:
                try: self.rt.ctx.eval(f"(function(el){{ {code} }})(document.getElementById({i!r}))")
                except Exception as e: self.rt.console_log.append(f"[click error] {e}")
            self.rt.doc._mutated = True
        if meth == "remove":
            p = n.parent
            if p and n in p.children:
                p.children.remove(n); self.rt.doc._mutated = True
