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
        self._bridge = _DomBridge(self)
        for name in ("byId","prop","setProp","title","setTitle","byClass","qs","qsa","log","call"):
            self.ctx.add_callable(f"__{name}", getattr(self._bridge, name))
        self.ctx.eval("""
        function __mk(id) {
          return {
            id: id,
            get textContent() { return __prop(id, 'textContent'); },
            set textContent(v) { __setProp(id, 'textContent', String(v)); },
            get innerHTML() { return __prop(id, 'innerHTML'); },
            set innerHTML(v) { __setProp(id, 'innerHTML', String(v)); },
            style: {},
            remove: function() { __call(id, 'remove'); }
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
        var console = { log: function(){ __log(Array.prototype.join.call(arguments, ' ')); },
                        warn: function(){ __log('WARN: ' + Array.prototype.join.call(arguments, ' ')); },
                        error: function(){ __log('ERROR: ' + Array.prototype.join.call(arguments, ' ')); } };
        function alert(m){ __log('ALERT: ' + m); }
        """)
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
    def call(self, i, meth):
        n = self._n(i)
        if n is None: return
        if meth == "remove":
            p = n.parent
            if p and n in p.children:
                p.children.remove(n); self.rt.doc._mutated = True
