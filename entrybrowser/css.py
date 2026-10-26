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
    "padding","padding-top","padding-right","padding-bottom","padding-left",
    "border","border-width","border-style","border-color",
    "width","height","min-width","max-width","min-height","max-height",
    "background","background-color","color","font-family","font-size","font-weight",
    "font-style","line-height","text-align","text-decoration","letter-spacing",
    "text-transform","white-space","overflow","flex-direction","gap","justify-content",
    "align-items","border-radius","box-sizing","visibility","opacity","z-index",
    "vertical-align","object-fit","float","clear",
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
    __slots__ = ("tag","classes","ids")
    def __init__(self):
        self.tag = None; self.classes = []; self.ids = []
    def specificity(self):
        return (len(self.ids), len(self.classes), 1 if self.tag else 0)
    def matches(self, node) -> bool:
        if self.tag and node.tag != self.tag: return False
        if self.ids:
            idv = node.attr("id")
            if not idv or not all(i in idv.split() for i in self.ids): return False
        if self.classes:
            cv = node.attr("class") or ""
            classes = cv.split()
            if not all(c in classes for c in self.classes): return False
        return True

_SEL_PART = re.compile(
    r"([a-zA-Z][\w-]*)?"           # tag
    r"(?:\.([\w-]+))?"             # .class
    r"(?:#([\w-]+))?"              # #id
)

def parse_selector(sel: str):
    """Return list of compound selectors joined by combinators.
    We support: descendant (space) and child (>). Output: list of
    (combinator, SimpleSel) with combinator of first = None."""
    out = []
    sel = re.sub(r"\s*>\s*", ">", sel.strip())
    parts = re.split(r"(\s|>)", sel)
    comb = None
    i = 0
    while i < len(parts):
        p = parts[i]
        if p in (" ", "", ">"):
            if p == ">": comb = "child"
            i += 1; continue
        m = _SEL_PART.fullmatch(p)
        if not m: return None
        s = SimpleSel()
        s.tag = (m.group(1) or None)
        if m.group(1) in ("*",""): s.tag = None if m.group(1) == "" else s.tag
        if m.group(2): s.classes.append(m.group(2))
        if m.group(3): s.ids.append(m.group(3))
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
    # descendant: walk all ancestors
    p = node.parent
    while p is not None and p.tag != "#document":
        if selector_matches(rest, p): return True
        p = p.parent
    return False

# ---------------- stylesheet ----------------

class Rule:
    __slots__ = ("selectors","decls","order")
    def __init__(self, selectors, decls, order):
        self.selectors = selectors  # list of compound selector lists
        self.decls = decls          # dict prop -> (value, important)
        self.order = order

class Stylesheet:
    def __init__(self):
        self.rules: list[Rule] = []
    @classmethod
    def parse(cls, css: str) -> "Stylesheet":
        ss = cls()
        css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
        order = 0
        # naive top-level block splitter (no @media support yet)
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            sel_txt, body = m.group(1).strip(), m.group(2)
            if sel_txt.startswith("@"):  # skip at-rules for now
                continue
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
            for s in sel_txt.split(","):
                c = parse_selector(s)
                if c: sels.append(c)
            if sels and decls:
                ss.rules.append(Rule(sels, decls, order)); order += 1
        return ss
    def computed(self, node, parent_style=None, em=16.0, base=None):
        """Cascade declarations onto node; base (e.g. UA result) wins over defaults."""
        style = dict(base) if base else dict(DEFAULT_STYLE)
        # inheritance
        if parent_style:
            for k in INHERITED:
                if k in parent_style and parent_style[k] is not None:
                    style[k] = parent_style[k]
        matched = []
        for rule in self.rules:
            for compound in rule.selectors:
                if selector_matches(compound, node):
                    spec = max(s.specificity() for _, s in compound)
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
        for k in ("width","height","min-width","max-width","min-height","max-height"):
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
            s["color"] = parse_color(s["color"])
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
    "flex-direction": "row", "gap": 0.0, "float": "none",
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
dl, dt, dd, address, details, summary { display: block; }
table { border-collapse: collapse; }
td, th { display: table-cell; padding: 1px; }
tr { display: table-row; }
span, small, big, sub, sup, abbr, cite, q, dfn, var, kbd, samp, time, mark,
label, output, bdi, bdo, wbr, data { display: inline; }
button, input, select, textarea { display: inline-block; }
"""

UA = Stylesheet.parse(UA_CSS)
