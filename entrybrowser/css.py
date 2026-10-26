"""entrybrowser.css — CSS subset: tokenizer, parser, selector matching, cascade.

Supports: element/class/id/descendant/child selectors, grouped selectors,
the box-model + typography + color + flexbox-row properties that layout.py
implements, !important, specificity-ordered cascade, style="" attributes,
inheritance for inherited properties.
"""
from __future__ import annotations
import re

INHERITED = {
    "color","font-family","font-size","font-weight","font-style","line-height",
    "text-align","text-decoration","letter-spacing","text-transform",
    "white-space","visibility","cursor",
}

# property names we understand (everything else parses but is ignored)
_KNOWN = {
    "display","position","margin","margin-top","margin-right","margin-bottom","margin-left",
    "padding","padding-top","padding-right","padding-bottom","padding-left","aspect-ratio",
    "border","border-width","border-style","border-color",
    "width","height","min-width","max-width","min-height","max-height",
    "background","background-color","background-image","background-size","color","font-family","font-size","font-weight",
    "font-style","line-height","text-align","text-decoration","letter-spacing",
    "text-transform","white-space","overflow","flex-direction","gap","justify-content",
    "align-items","border-radius","box-sizing","visibility","opacity","z-index",
    "flex-wrap","flex-grow","flex-basis","flex-shrink","align-self","text-shadow",
    "object-position","list-style","list-style-type","column-count","column-gap",
    "grid-template-columns","grid-template-rows","grid-column","grid-row",
    "grid-template","grid-area","grid-template-areas",
    "top","left","right","bottom","inset","clear",
    "vertical-align","object-fit","float","clear",
    "transform","transition","transition-duration","transition-property",
}

_NAMED = {
    "black":"#000000","white":"#ffffff","red":"#ff0000","green":"#008000","lime":"#00ff00",
    "blue":"#0000ff","yellow":"#ffff00","cyan":"#00ffff","aqua":"#00ffff","magenta":"#ff00ff",
    "fuchsia":"#ff00ff","gray":"#808080","grey":"#808080","silver":"#c0c0c0","maroon":"#800000",
    "olive":"#808000","navy":"#000080","teal":"#008080","purple":"#800080","orange":"#ffa500",
    "transparent":"#00000000","pink":"#ffc0cb","gold":"#ffd700","brown":"#a52a2a",
    "lightgray":"#d3d3d3","lightgrey":"#d3d3d3","darkgray":"#a9a9a9","darkgrey":"#a9a9a9",
    "whitesmoke":"#f5f5f5","gainsboro":"#dcdcdc","azure":"#f0ffff","beige":"#f5f5dc",
}

def parse_color(v: str) -> tuple[int,int,int,int] | None:
    v = v.strip().lower()
    if v in _NAMED:
        v = _NAMED[v]
    m = re.fullmatch(r"#([0-9a-f]{3})", v)
    if m:
        r,g,b = m.group(1); return (int(r*2,16), int(g*2,16), int(b*2,16), 255)
    m = re.fullmatch(r"#([0-9a-f]{4})", v)
    if m:
        r,g,b,a = m.group(1); return (int(r*2,16), int(g*2,16), int(b*2,16), int(a*2,16))
    m = re.fullmatch(r"#([0-9a-f]{6})", v)
    if m:
        return (int(m.group(1)[0:2],16), int(m.group(1)[2:4],16), int(m.group(1)[4:6],16), 255)
    m = re.fullmatch(r"#([0-9a-f]{8})", v)
    if m:
        h = m.group(1); return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16))
    m = re.fullmatch(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        rgb = [int(float(p)) for p in parts[:3]]
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (rgb[0], rgb[1], rgb[2], int(a*255))
    m = re.fullmatch(r"hsla?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).replace("%","").split(",")]
        h,s,l = float(parts[0]), float(parts[1])/100, float(parts[2])/100
        import colorsys
        r,g,b = colorsys.hls_to_rgb(h/360, l, s)
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (int(r*255), int(g*255), int(b*255), int(a*255))
    return None

LEN_RE = re.compile(r"^(-?[\d.]+)(px|pt|em|rem|%|vw|vh)?$")

def parse_length(v: str, em=16.0, base=16.0, total=None):
    """Return (value, unit) where value is a float; None for 'auto'."""
    v = v.strip()
    if v in ("auto", ""): return None
    m = LEN_RE.match(v)
    if not m: return None
    val, unit = float(m.group(1)), m.group(2) or "px"
    if unit == "pt": val = val * 96/72
    elif unit == "em": val = val * em
    elif unit == "rem": val = val * base
    elif unit == "%":
        if total: val = val/100*total
        else: return ("pct", val)
    return (val, "px")

def parse_length_shorthand(v, em=16.0, total=None):
    parts = v.split()
    if not parts: return None
    vals = [parse_length(p, em, total=total) for p in parts]
    if len(vals) == 1: t=r=b=l = vals[0]
    elif len(vals) == 2: t=b=vals[0]; r=l=vals[1]
    elif len(vals) == 3: t=vals[0]; r=l=vals[1]; b=vals[2]
    else: t,r,b,l = vals[:4]
    return {"top":t,"right":r,"bottom":b,"left":l}

def expand_border(v):
    """border: 1px solid #ccc -> width/style/color dict."""
    toks = v.split()
    out = {}
    for t in toks:
        L = parse_length(t)
        if L and L[1] == "px": out["width"] = L[0]
        elif t in ("none","hidden"): out["style"] = "none"
        elif t in ("solid","dashed","dotted","double"): out["style"] = t
        else:
            c = parse_color(t)
            if c: out["color"] = c
    out.setdefault("width", 0 if out.get("style") in (None,"none") else 2)
    out.setdefault("style", "solid" if out.get("width",0) else "none")
    out.setdefault("color", (0,0,0,255))
    return out

# ---------------- selectors ----------------

class SimpleSel:
    __slots__ = ("tag","classes","ids","pseudo","_universal")
    def __init__(self):
        self.tag = None; self.classes = []; self.ids = []; self.pseudo = None
        self._universal = False
    def specificity(self):
        tag_pts = 0 if getattr(self, "_universal", False) else (1 if self.tag else 0)
        return (len(self.ids), len(self.classes) + (1 if self.pseudo else 0), tag_pts)
    def matches(self, node) -> bool:
        if self.tag and node.tag != self.tag: return False
        if self.ids:
            idv = node.attr("id")
            if not idv or not all(i in idv.split() for i in self.ids): return False
        if self.classes:
            cv = node.attr("class") or ""
            classes = cv.split()
            if not all(c in classes for c in self.classes): return False
        if self.pseudo:
            p = self.pseudo
            state = getattr(node, "_pseudo_state", None) or {}
            if p == "hover" and not state.get("hover"): return False
            if p == "focus" and not state.get("focus"): return False
            if p == "active" and not state.get("active"): return False
            if p == "checked" and node.attr("checked") is None: return False
            if p == "disabled" and node.attr("disabled") is None: return False
            if p in ("first-child", "last-child"):
                par = node.parent
                sibs = [c for c in (par.children if par else []) if c.tag != "#text"]
                if not sibs or sibs[0] is not node if p == "first-child" else sibs[-1] is not node:
                    if p == "first-child" and (not sibs or sibs[0] is not node): return False
                    if p == "last-child" and (not sibs or sibs[-1] is not node): return False
        return True

_SEL_PART = re.compile(
    r"(\*|[a-zA-Z][\w-]*)?"        # tag (\* = universal selector)
    r"(?:\.([\w-]+))?"             # .class
    r"(?:#([\w-]+))?"              # #id
    r"(?::(hover|focus|active|first-child|last-child|checked|disabled))?"  # pseudo
)

def parse_selector(sel: str):
    """Return list of compound selectors joined by combinators.
    We support: descendant (space), child (>), adjacent (+), general sibling (~).
    Output: list of (combinator, SimpleSel) with combinator of first = None."""
    out = []
    sel = re.sub(r"\s*>\s*", ">", sel.strip())
    sel = re.sub(r"\s*~\s*", "~", sel)
    sel = re.sub(r"\s*\+\s*", "+", sel)
    parts = re.split(r"(\s|>|~|\+)", sel)
    comb = None
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in (" ", "", ">", "~", "+"):
            if p == ">": comb = "child"
            elif p == "~": comb = "sibling"
            elif p == "+": comb = "adjacent"
            i += 1; continue
        m = _SEL_PART.fullmatch(p)
        if not m: return None
        s = SimpleSel()
        s.tag = (m.group(1) or None)
        if s.tag == "*": s.tag = None   # universal: matches all, zero tag specificity
        # mark universal so specificity stays (0,0,0)
        if m.group(1) == "*": s._universal = True
        if m.group(2): s.classes.append(m.group(2))
        if m.group(3): s.ids.append(m.group(3))
        if m.group(4): s.pseudo = m.group(4)
        out.append((comb, s))
        comb = None  # descendant by default
        i += 1
    return out or None

def selector_matches(compound, node):
    """compound: list of (combinator, SimpleSel); last must match node."""
    if not compound: return False
    comb, sel = compound[-1]
    if not sel.matches(node): return False
    if len(compound) == 1: return True
    rest = compound[:-1]
    prev_comb = compound[-1][0]
    if prev_comb == "child":
        p = node.parent
        return p is not None and selector_matches(rest, p)
    if prev_comb in ("sibling", "adjacent"):
        p = node.parent
        if p is None: return False
        sibs = [c for c in p.children if c.tag != "#text"]
        try: idx = sibs.index(node)
        except ValueError: return False
        if prev_comb == "adjacent":
            return idx > 0 and selector_matches(rest, sibs[idx-1])
        return any(selector_matches(rest, sb) for sb in sibs[:idx])
    # descendant: walk all ancestors
    p = node.parent
    while p is not None and p.tag != "#document":
        if selector_matches(rest, p): return True
        p = p.parent
    return False

# ---------------- stylesheet ----------------

class Rule:
    __slots__ = ("selectors","decls","order","keys")
    def __init__(self, selectors, decls, order):
        self.selectors = selectors  # list of compound selector lists
        self.decls = decls          # dict prop -> (value, important)
        self.order = order
        # index keys: (tag, class, id, universal) of each compound's rightmost sel
        self.keys = set()
        if not selectors:   # inline-style pseudo-rule: never bucketed
            return
        for compound in selectors:
            tag, cls, id_ = compound[-1][1].tag, None, None
            if compound[-1][1].classes: cls = compound[-1][1].classes[0]
            if compound[-1][1].ids: id_ = compound[-1][1].ids[0]
            if id_: self.keys.add(("ID", id_))
            elif cls: self.keys.add(("CLASS", cls))
            elif tag: self.keys.add(("TAG", tag))
            else: self.keys.add(("*", ""))

class Stylesheet:
    def __init__(self):
        self.rules: list[Rule] = []
        self._buckets: dict[tuple, list[Rule]] = {}
    def _rebuild(self):
        self._buckets = {}
        for r in self.rules:
            for k in r.keys:
                self._buckets.setdefault(k, []).append(r)
        # universal rules apply to everything
        self._universal = self._buckets.get(("*", ""), [])
    def candidate_rules(self, node):
        """Rules whose rightmost selector COULD match node (superset, cheap)."""
        if not self._buckets: self._rebuild()
        out = list(self._universal)
        b = self._buckets
        out += b.get(("TAG", node.tag), [])
        idv = node.attrs.get("id")
        if idv:
            for i in idv.split(): out += b.get(("ID", i), [])
        cv = node.attrs.get("class")
        if cv:
            for c in cv.split(): out += b.get(("CLASS", c), [])
        return out
    @classmethod
    def parse(cls, css: str, viewport_w: float | None = None) -> "Stylesheet":
        ss = cls()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        order = 0

        def _emit(rules_css, media_ok=True):
            nonlocal order
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", rules_css):
                sel_txt, body = m.group(1).strip(), m.group(2)
                if not media_ok:
                    continue
                _rule(sel_txt, body)

        def _rule(sel_txt, body):
            nonlocal order
            decls = {}
            for d in body.split(";"):
                if ":" not in d: continue
                prop, val = d.split(":", 1)
                prop, val = prop.strip().lower(), val.strip()
                important = False
                if val.endswith("!important"):
                    important = True; val = val[:-10].strip()
                if prop in _KNOWN or prop.startswith("-"):
                    decls[prop] = (val, important)
            sels = []
            for s_ in sel_txt.split(","):
                c = parse_selector(s_)
                if c: sels.append(c)
            if sels and decls:
                ss.rules.append(Rule(sels, decls, order)); order += 1

        def _walk(css_text, media_ok=True):
            i = 0
            n = len(css_text)
            while i < n:
                brace = css_text.find("{", i)
                if brace == -1:
                    break
                sel = css_text[i:brace].strip()
                depth = 1
                j = brace + 1
                while j < n and depth:
                    if css_text[j] == "{": depth += 1
                    elif css_text[j] == "}": depth -= 1
                    j += 1
                body = css_text[brace+1:j-1]
                if sel.startswith("@media"):
                    cond = sel[6:].strip()
                    ok = media_ok and _media_ok(cond, viewport_w)
                    _walk(body, ok)
                elif sel.startswith("@"):
                    pass  # skip other at-rules
                else:
                    if "{" in body:
                        # shouldn't happen for plain rules; recurse defensively
                        _walk(sel + "{" + body + "}", media_ok)
                    else:
                        if media_ok:
                            _rule(sel, body)
                i = j

        def _media_ok(cond, vw):
            # media TYPE check: print/handled/etc -> not screen; 'not print...' style lists
            types = re.findall(r"\b(print|screen|all|braille|embossed|speech|tty|tv|handheld|projection)\b", cond)
            nots = re.findall(r"\bnot\s+(\w+)", cond)
            if types:
                visible = [t for t in types if t in ("screen","all")]
                # 'not print, braille' == only exclude those; ok if a screen type present
                if not visible and not all(t in ("print","braille","embossed","speech","tty") for t in types):
                    pass
            for n in nots:
                if n in ("screen","all"):
                    return False
            if types and not any(t in ("screen","all") for t in types):
                return False  # print-only etc.
            if vw is None: return True
            ok = True
            for part in re.split(r"\s*(?:,|\band\b)\s*", cond.strip("() ")):
                if not part: continue
                neg = part.startswith("not")
                p = part[3:].strip() if neg else part
                m = re.match(r"\(?([\w-]+)\s*:\s*([\d.]+)(px|em)\)?", p)
                if not m:
                    m = re.match(r"\(?([\w-]+)\)?", p)
                    continue
                feat, val = m.group(1), float(m.group(2)) * (16 if m.group(2) and m.group(2) and False else 1)
                if p.endswith("em") or (m.lastindex or 0) >= 3 and m.group(3) == "em": val = float(m.group(2)) * 16
                if feat == "min-width": r_ = vw >= val
                elif feat == "max-width": r_ = vw <= val
                else: continue
                ok = ok and (not r_ if neg else r_)
            return ok

        _walk(css)
        return ss
    def computed(self, node, parent_style=None, em=16.0, base=None):
        """Cascade declarations onto node; base (e.g. UA result) wins over defaults."""
        style = dict(base) if base else dict(DEFAULT_STYLE)
        # inheritance
        if parent_style:
            for k in INHERITED:
                if k in parent_style and parent_style[k] is not None:
                    style[k] = parent_style[k]
        # HTML presentational attributes (HTML4 era: bgcolor/width/align/border/valign...)
        # lowest precedence — any real CSS overrides them
        _pa = {}
        def _want(k, v):
            if v and k in _KNOWN:
                _pa[k] = v
        _bg = node.attr("bgcolor")
        if _bg: _want("background-color", _bg)
        _c = node.attr("color")
        if _c and node.tag == "font": _want("color", _c)
        _fc = node.attr("face")
        if _fc and node.tag == "font": _want("font-family", _fc)
        _al = (node.attr("align") or "").lower()
        if _al in ("left","right","center","justify"):
            if node.tag in ("table","td","th","tr","p","div","h1","h2","h3","h4","h5","h6"):
                _want("text-align", _al)
        _vl = (node.attr("valign") or "").lower()
        if _vl in ("top","middle","bottom"):
            _want("vertical-align", _vl)
        _w = node.attr("width")
        if _w and _w.isdigit():
            _want("width", _w + "px")
        _h = node.attr("height")
        if _h and _h.isdigit():
            _want("height", _h + "px")
        if _pa:
            for prop, val in _pa.items():
                style[prop] = val
        matched = []
        seen = set()
        for rule in self.candidate_rules(node):
            if id(rule) in seen: continue
            seen.add(id(rule))
            for compound in rule.selectors:
                if selector_matches(compound, node):
                    spec = max(sp.specificity() for _, sp in compound)
                    matched.append((spec, rule.order, rule))
                    break
        # style="" attribute: highest precedence except !important
        sa = node.attr("style")
        if sa:
            for d in sa.split(";"):
                if ":" in d:
                    prop, val = d.split(":", 1)
                    prop, val = prop.strip().lower(), val.strip()
                    if prop in _KNOWN:
                        matched.append(((9,9,9), 10**9, Rule(None, {prop: (val, False)}, 10**9)))
        matched.sort(key=lambda t: (t[2] is not None and any(imp for _, imp in [t[2].decls.get(p,(None,False))]), ) if False else t[1])
        # apply in specificity+order order; !important wins within property
        matched.sort(key=lambda t: (tuple(1 for _ in ()) ,))
        for spec, order, rule in sorted(matched, key=lambda t: (0 if not any(imp for _, imp in t[2].decls.values()) else 1, t[0], t[1])):
            for prop, (val, imp) in rule.decls.items():
                style[prop] = val
        return self._resolve(style, em)
    def _resolve(self, style, em):
        """Turn raw strings into typed values where layout needs them."""
        s = dict(style)
        for k in ("width","height","min-width","max-width","min-height","max-height",
                  "top","left","right","bottom"):
            if isinstance(s.get(k), str):
                s[k] = parse_length(s[k], em=em)
        for k in ("margin","padding"):
            if isinstance(s.get(k), str):
                m = parse_length_shorthand(s[k], em=em)
                s[k] = m
                if k == "margin":
                    for side in "top right bottom left".split():
                        s[f"margin-{side}"] = m[side]
                else:
                    for side in "top right bottom left".split():
                        s[f"padding-{side}"] = m[side]
        # side longhands may arrive as raw strings (inline styles, presentational hints)
        for k in list(s.keys()):
            for pre in ("margin-","padding-"):
                if k.startswith(pre) and isinstance(s[k], str):
                    try:
                        s[k] = parse_length(s[k], em=em)
                    except Exception:
                        pass
        if isinstance(s.get("border"), str):
            s["border"] = expand_border(s["border"])
        for k in ("font-size","line-height","letter-spacing"):
            if isinstance(s.get(k), str):
                L = parse_length(s[k], em=em)
                if L is None:
                    s[k] = 16.0 if k == "font-size" else s.get(k)
                elif isinstance(L, tuple) and L[0] == "pct":
                    s[k] = 16.0 * L[1] / 100 if k == "font-size" else L[1]
                else:
                    s[k] = L[0]
        if isinstance(s.get("color"), str):
            c = parse_color(s["color"])
            s["color"] = c if c else None  # layout falls back to parent/UA black
        for deco_key in ("text-decoration",):
            if isinstance(s.get(deco_key), str) and s[deco_key] in ("inherit","initial"):
                s[deco_key] = None
        if isinstance(s.get("background-color"), str):
            s["background-color"] = parse_color(s["background-color"])
        return s

DEFAULT_STYLE = {
    "display": "inline", "position": "static",
    "margin-top": None, "margin-right": None, "margin-bottom": None, "margin-left": None,
    "padding-top": 0.0, "padding-right": 0.0, "padding-bottom": 0.0, "padding-left": 0.0,
    "width": None, "height": None, "background": None, "background-color": None,
    "color": (0,0,0,255), "font-size": 16.0, "font-weight": "normal",
    "font-family": "sans-serif", "line-height": 1.2, "text-align": "left",
    "text-decoration": "none", "border": None, "border-radius": 0.0,
    "white-space": "normal", "overflow": "visible", "visibility": "visible",
    "flex-direction": "row", "gap": 0.0, "float": "none", "clear": "none", "flex-grow": "0",
    "flex-basis": None, "flex-wrap": "nowrap", "opacity": "1", "z-index": None,
    "position": "static", "box-sizing": "content-box", "list-style-type": "disc",
    "grid-template-columns": None, "grid-template-rows": None,
    "grid-template": None, "grid-area": None, "grid-template-areas": None,
}

# UA stylesheet — the default look, override-able by page CSS
UA_CSS = """
html { display: block; }
body { display: block; margin: 8px; background-color: #ffffff; color: #000000;
       font-size: 16px; line-height: 1.2; }
h1 { display: block; font-size: 32px; font-weight: bold; margin: 21.44px 0; }
h2 { display: block; font-size: 24px; font-weight: bold; margin: 19.92px 0; }
h3 { display: block; font-size: 18.72px; font-weight: bold; margin: 18.72px 0; }
h4 { display: block; font-size: 16px; font-weight: bold; margin: 21.44px 0; }
h5, h6 { display: block; font-size: 13.28px; font-weight: bold; margin: 22.24px 0; }
p, ul, ol, blockquote, pre, table { display: block; margin: 16px 0; }
ul, ol { padding-left: 40px; }
li { display: list-item; margin: 0; }
blockquote { margin: 16px 40px; }
pre, code { font-family: monospace; font-size: 13px; }
pre { white-space: pre; }
strong, b { font-weight: bold; }
em, i { font-style: italic; }
a { color: #0000ee; text-decoration: underline; }
hr { display: block; margin: 8px 0; }
img { display: inline-block; }
div, section, article, header, footer, nav, aside, main, figure, form, fieldset,
dl, dt, dd, address, details, summary, center, dir, menu, noframes, xmp,
optgroup, option { display: block; }
figure { margin: 16px 40px; }
caption { display: block; text-align: center; }
thead, tbody, tfoot { display: table-row-group; }
colgroup, col { display: table-column-group; }
fieldset { margin: 8px 0; padding: 8px; }
br { display: inline; }
table { border-collapse: collapse; }
td, th { display: table-cell; padding: 1px; }
tr { display: table-row; }
span, small, big, sub, sup, abbr, cite, q, dfn, var, kbd, samp, time, mark,
label, output, bdi, bdo, wbr, data { display: inline; }
sup { font-size: 75%; vertical-align: super; }
sub { font-size: 75%; vertical-align: sub; }
b, strong { font-weight: bold; }
i, em, cite, var, dfn { font-style: italic; }
u, ins { text-decoration: underline; }
button, input, select, textarea { display: inline-block; }
ul { list-style-type: disc; }
ol { list-style-type: decimal; }
"""

UA = Stylesheet.parse(UA_CSS)
