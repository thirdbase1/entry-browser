"""entrybrowser.layout — box layout engine.

Block layout with inline text wrapping, plus the CSS boxes layout.py implements:
margins/padding/borders, explicit width/height, text-align, line boxes with
font metrics, and a simplified flexbox row. Output: a box tree with absolute
(x, y, w, h) rectangles ready for the rasterizer.
"""
from __future__ import annotations
from .html import Node
from .css import Stylesheet, UA, parse_color

class Box:
    __slots__ = ("node","x","y","w","h","children","style","text_lines","_is_float",
                 "bg","border","radius","is_text","spans","img","is_widget","transform","bg_img")
    def __init__(self, node=None, style=None):
        self.node = node; self.style = style or {}
        self.x = self.y = self.w = self.h = 0.0
        self.children: list[Box] = []
        self._is_float = False
        self.is_widget = False
        self.transform = None
        self.text_lines: list[tuple[str,float,float]] = []  # (text, x, baseline_y)
        self.spans: list[tuple] = []  # (text, x, baseline, font_path, size, color, underline, superscript)
        self.img = None               # (PIL.Image, x, y, w, h) for painted images
        self.bg = None; self.border = None; self.radius = 0.0; self.bg_img = None
        self.is_text = False
    def __repr__(self):
        return f"Box({self.node.tag if self.node else 'anon'} {self.x:.0f},{self.y:.0f} {self.w:.0f}x{self.h:.0f})"

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_ITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"
FONT_BOLDITALIC = "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

def _find_font(family: str, bold=False, italic=False) -> str:
    import os
    want_mono = family and "mono" in family.lower()
    want_serif = family and "serif" in family.lower() and "sans" not in family.lower()
    if want_serif:
        serif = "/usr/share/fonts/truetype/dejavu/DejaVuSerif%s.ttf"
        base = serif % ("-Bold" if bold and not italic else
                        "-BoldOblique" if bold and italic else
                        "Italic" if italic else "")
        cands = [f"/usr/share/fonts/truetype/dejavu/DejaVuSerif{'-Bold' if bold else ''}{'' if not bold and not italic else ''}.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]
    else:
        if want_mono:
            cands = [[FONT_MONO, "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"][bold]]
        elif bold and italic: cands = [FONT_BOLDITALIC, FONT_BOLD, DEFAULT_FONT]
        elif bold: cands = [FONT_BOLD, DEFAULT_FONT]
        elif italic: cands = [FONT_ITALIC, DEFAULT_FONT]
        else: cands = [DEFAULT_FONT]
    cands += [DEFAULT_FONT,
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
              "/usr/share/fonts/truetype/freefont/FreeSans.ttf"]
    for c in cands:
        if os.path.exists(c): return c
    import glob
    g = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return g[0] if g else ""

class Layout:
    def __init__(self, doc: Node, stylesheet: Stylesheet | None = None,
                 viewport_w=800.0, base_url=""):
        self.doc = doc
        self.ss = stylesheet
        self.vw = viewport_w
        self.viewport_w = viewport_w
        self.viewport_h = 800.0   # vh unit baseline (window height approximation)
        self.base_url = base_url
        self._font_cache: dict[tuple, object] = {}
        self._measure_cache: dict[tuple, float] = {}
        self._floats: list = []   # active float boxes (cleared per block context; approximate)
    def _font(self, family, size, bold=False, italic=False):
        from PIL import ImageFont
        key = (family, round(size), bold, italic)
        if key not in self._font_cache:
            path = _find_font(family, bold, italic)
            try:
                self._font_cache[key] = ImageFont.truetype(path, int(round(size)))
            except Exception:
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]
    def _text_w(self, text, family, size, bold=False, italic=False):
        key = ("W", text, family, round(size), bold, italic)
        if key not in self._measure_cache:
            f = self._font(family, size, bold, italic)
            self._measure_cache[key] = f.getlength(text)
        return self._measure_cache[key]

    def build(self) -> Box:
        self._style_cache = {}   # id(node) -> (parent_style_id, style)
        # NOTE: floats intentionally persist across builds (incremental relayouts);
        # replace-stale on register + cy-expiry keep the list honest.
        body = next((n for n in self.doc.query_all("body")), self.doc)
        root_style = {}
        root = self._layout_block(body, root_style, 0.0, 0.0, self.vw)
        root.w = self.vw
        # second pass to fix heights bottom-up happens in _layout_block already
        return root

    # ---- style ----
    def style_for(self, node, parent_style):
        # computed style depends on (node, parent's INHERITED style). Parent NODE identity
        # is the stable key: re-lays pass fresh dict instances for the same parent node.
        pk = id(getattr(node, "parent", None) or 0)
        cache = getattr(self, "_style_cache", None)
        if cache is not None:
            key = (id(node), pk)
            hit = cache.get(key)
            if hit is not None:
                return hit
        em = parent_style.get("font-size", 16.0)
        st = UA.computed(node, parent_style, em=em)
        if self.ss:
            st = self.ss.computed(node, st, em=st.get("font-size", 16.0), base=st)
        if cache is not None:
            cache[(id(node), pk)] = st
        return st

    def _display(self, style):
        return style.get("display", "inline")
    def _pos(self, style):
        return style.get("position", "static")

    # ---- block layout ----
    _TRANS_RE = None

    def _parse_transform(self, v):
        """Parse transform: translate(x,y) rotate(deg) scale(n) -> (tx, ty, deg, scale)."""
        if not v or not isinstance(v, str):
            return None
        import re as _re
        tx = ty = 0.0; deg = 0.0; sc = 1.0
        found = False
        for name, arg in _re.findall(r"(translate|rotate|scale)\(([^)]+)\)", v):
            found = True
            args = [a.strip() for a in arg.split(",")]
            if name == "translate":
                def _n(t):
                    t = t.strip()
                    if t.endswith("px"):
                        try: return float(t[:-2])
                        except ValueError: return 0.0
                    try: return float(t)
                    except ValueError: return 0.0
                tx = _n(args[0]) if args else 0.0
                ty = _n(args[1]) if len(args) > 1 else 0.0
            elif name == "rotate":
                a = args[0] if args else "0"
                try:
                    deg = float(a.rstrip("deg ").strip() or 0)
                except ValueError:
                    deg = 0.0
            elif name == "scale":
                try: sc = float(args[0])
                except (ValueError, IndexError): sc = 1.0
        return (tx, ty, deg, sc) if found else None

    def _layout_block(self, node, parent_style, x, y, cw):
        """Layout a block container; returns its Box with height set."""
        style = self.style_for(node, parent_style)
        box = Box(node, style)
        box.x = x; box.y = y
        box.bg = style.get("background-color")
        bi = style.get("background-image")
        if isinstance(bi, str) and "url(" in bi:
            try:
                from urllib.parse import urljoin as _uj
                u = bi[bi.index("url(") + 4: bi.index(")", bi.index("url("))].strip().strip("'\"")
                if u.startswith("//"): u = "https:" + u
                elif not u.startswith("http"): u = _uj(getattr(self, "base_url", "") or "", u)
                box.bg_img = (u, style.get("background-size"))  # resolved to Image at image-load pass
            except Exception:
                pass
        box.border = style.get("border")
        box.radius = style.get("border-radius", 0.0) or 0.0
        if isinstance(box.radius, str):
            box.radius = 0.0
        box.transform = self._parse_transform(style.get("transform"))
        mt, mr, mb, ml = (self._len(style.get(f"margin-{k}"), cw) for k in ("top","right","bottom","left"))
        pt, pr, pb, pl = (self._len(style.get(f"padding-{k}"), cw) for k in ("top","right","bottom","left"))
        bw = style.get("border") or {}
        bt = bw.get("width", 0) if isinstance(bw, dict) else 0
        box.x += mt; box.y = y + mt; y = box.y
        content_x = box.x + ml + pl + bt
        content_y = y + pt + bt
        content_w = cw - ml - mr - pl - pr - 2*bt
        W = style.get("width")
        if W:
            wv = self._len(W, cw)
            if str(style.get("box-sizing", "content-box")) == "border-box":
                content_w = max(0.0, wv - pl - pr - 2*bt)
            else:
                content_w = wv
        disp = self._display(style)
        if disp == "none" or style.get("visibility") == "hidden":
            box.w = box.h = 0
            return box
        # flex row container?
        if style.get("display") == "flex":
            self._layout_flex(node, box, style, content_x, content_y, content_w)
        elif style.get("display") == "grid":
            self._layout_grid(node, box, style, content_x, content_y, content_w)
        elif node.tag == "table":
            self._layout_table(node, box, style, content_x, content_y, content_w)
        else:
            # separate children into block vs inline runs
            cy = content_y
            inline_run = []
            for child in node.children:
                if child.tag in ("style","script","title","head","meta","link"):
                    continue
                if child.tag == "#text":
                    if child.text.strip(): inline_run.append(child)
                    elif child.text.strip() == "" and not inline_run:
                        continue
                    else:
                        inline_run.append(child)  # whitespace between inlines
                    continue
                if child.tag == "picture":
                    # <picture> is a transparent wrapper — lay its <img> directly, with
                    # the picture's aspect-ratio applied to the image sizing
                    _imgk = [k for k in child.children if k.tag == "img"]
                    if _imgk:
                        _picstyle = self.style_for(child, style)
                        _ar = _picstyle.get("aspect-ratio")
                        _istyle = self.style_for(_imgk[0], style)
                        if _ar and not _istyle.get("height"):
                            try:
                                _pa, _pb = str(_ar).split("/")
                                _iar = float(_pa) / float(_pb)
                                _iw = self._len(_istyle.get("width"), content_w) or float(_imgk[0].attr("width") or 0) or 300
                                if _iw > content_w:
                                    _iw = content_w
                                _imgk[0].attr("height", str(int(_iw / _iar)))
                                _imgk[0].attr("width", str(int(_iw)))
                            except Exception: pass
                        child = _imgk[0]
                cstyle = self.style_for(child, style)
                if self._display(cstyle) == "inline" or self._display(cstyle) == "inline-block":
                    # CSS: a block-level descendant inside an inline element forces the
                    # inline to split into anonymous blocks; approximate by laying the
                    # whole inline element as a block when it contains block children.
                    _kids = [gc for gc in getattr(child, "children", []) if gc.tag != "#text"]
                    _has_blk = any(
                        self._display(self.style_for(gc, cstyle)) not in ("inline", "inline-block")
                        for gc in _kids)
                    if _has_blk and child.tag not in ("span", "b", "i", "em", "strong", "u", "small", "code", "select", "button", "textarea", "input", "option"):
                        if inline_run:
                            cy = self._layout_inline_run(inline_run, box, style, content_x, cy, content_w,
                                                         floats=self._floats)
                            inline_run = []
                        cb = self._layout_block(child, style, content_x, cy, content_w)
                        box.children.append(cb)
                        cy = cb.y + cb.h
                        continue
                    inline_run.append(child)
                    continue
                # flush inline run
                if inline_run:
                    cy = self._layout_inline_run(inline_run, box, style, content_x, cy, content_w,
                                                 floats=box.children)
                    inline_run = []
                fl = self._len(cstyle.get("float") or "none", content_w) if isinstance(cstyle.get("float"), str) else 0
                cfloat = (cstyle.get("float") or "none")
                # floats whose bottom is above the current y no longer constrain anything
                if self._floats and cy > 0:
                    self._floats = [fb for fb in self._floats if fb.y + fb.h > cy - 1]
                if child is not None and child.tag == "details" and child.attr("open") is None:
                    # <details> collapsed: lay only the <summary> line
                    for sub in child.children:
                        if sub.tag == "summary":
                            cb = self._layout_block(sub, style, content_x, cy, content_w)
                            box.children.append(cb)
                            cy = cb.y + cb.h
                            inline_run = []
                            break
                    continue
                if str(cstyle.get("display") or "") == "contents":
                    # display:contents — the element's box vanishes; its children are
                    # laid directly into this container's flow (CSS display L3)
                    sub = self._layout_block(child, style, content_x, cy, content_w)
                    for gc in sub.children:
                        box.children.append(gc)
                    cy = sub.y + sub.h
                    continue
                if cfloat in ("left","right") or self._pos(cstyle) in ("absolute","fixed"):
                    _floats_save = self._floats
                    self._floats = list(_floats_save)   # float context is per containing block
                    cb = self._layout_block(child, style, content_x, cy, content_w)
                    self._floats = _floats_save
                    if self._pos(cstyle) in ("absolute","fixed") and not cstyle.get("width") \
                            and cb.w > content_w:
                        # absolute width:auto never exceeds the containing block (shrink-to-fit
                        # against available width; images cap at natural->available)
                        cb = self._layout_block(child, style, content_x, cy, content_w)
                    if self._pos(cstyle) in ("absolute","fixed") and not cstyle.get("width") \
                            and (cb.w >= content_w * 0.98) and cb.children:
                        # absolute with width:auto shrink-wraps to content (CSS 10.3.7)
                        mcw = max((sp[1] + self._text_w(sp[0], "sans-serif", sp[4] or 16.0)
                                   for c2 in [cb] for sp in getattr(c2, "spans", [])), default=0)
                        def _deepest(b):
                            m = 0.0
                            for sp in getattr(b, "spans", []):
                                m = max(m, sp[1] - cb.x + self._text_w(sp[0], "sans-serif", sp[4] or 16.0))
                            for k in b.children:
                                m = max(m, _deepest(k))
                            return m
                        mw = min(_deepest(cb) + 24, content_w)
                        if 0 < mw < cb.w * 0.98:
                            cb2 = self._layout_block(child, style, content_x, cy, mw)
                            cb = cb2
                    if cfloat == "left":
                        # stack left floats: bump right until no float overlaps the rect
                        fx = content_x
                        for _ in range(64):  # bounded
                            hit = None
                            for fb in self._floats:
                                if fb.w > 0 and fb.y < cy + max(cb.h, 1) and cy < fb.y + fb.h and fx < fb.x + fb.w and fx + cb.w > fb.x:
                                    if hit is None or fb.x + fb.w > hit:
                                        hit = fb.x + fb.w
                            if hit is None:
                                break
                            fx = hit
                        _ox = cb.x
                        if fx != _ox:
                            Layout._shift_tree(cb, fx - _ox, 0)   # moves cb.x itself
                        cb.y = cy
                    elif cfloat == "right":
                        _ox = cb.x
                        _rx = content_x + content_w - cb.w
                        for fb in self._floats:
                            if fb.w > 0 and fb.y <= cy < fb.y + fb.h and _rx >= fb.x and _rx < fb.x + fb.w:
                                _rx = fb.x - cb.w
                                break
                        _dx = _rx - _ox
                        if _dx:
                            Layout._shift_tree(cb, _dx, 0)
                    # absolute/fixed: honor top/left/right/bottom relative to containing box
                    pos = self._pos(cstyle)
                    if pos in ("absolute","fixed"):
                        ch_ = box.h  # percentages of top/bottom resolve against parent HEIGHT
                        def _px(v, base, pct_base=None):
                            if isinstance(v, tuple):
                                pb = pct_base if pct_base is not None else cw
                                return base + (v[1]/100*pb if v[0] == "pct" else v[0])
                            if isinstance(v, (int, float)): return base + v
                            return None
                        ty = _px(cstyle.get("top"), 0, ch_)
                        lx = _px(cstyle.get("left"), 0)
                        rx = _px(cstyle.get("right"), 0)
                        # left+right both set with width:auto -> span the interval (CSS 10.3.7)
                        if lx is not None and rx is not None and not cstyle.get("width"):
                            _nw = cw - lx - rx
                            if _nw > 40 and cb.w < _nw - 8:
                                cb = self._layout_block(child, style, content_x + lx, cy, _nw)
                        ox, oy = cb.x, cb.y
                        dx, dy = 0, 0
                        if ty is not None: dy = box.y + ty - cb.y
                        if lx is not None: dx = box.x + lx - cb.x
                        elif rx is not None: dx = box.x + cw - cb.w - rx - cb.x
                        if dx or dy:
                            Layout._shift_tree(cb, dx, dy)
                    box.children.append(cb)
                    if cfloat in ("left","right") and cb.w > 0:
                        # replace stale registration of the same node (probe re-lays)
                        self._floats = [fb for fb in self._floats if fb.node is not node]
                        cb._is_float = True
                        self._floats.append(cb)   # register for text wrap
                    continue
                clr = cstyle.get("clear") or "none"
                if clr in ("both","left"):
                    for fb in self._floats:
                        if fb.y + fb.h > cy and fb.x <= content_x + 50:
                            cy = max(cy, fb.y + fb.h)
                elif clr == "right":
                    for fb in self._floats:
                        if fb.y + fb.h > cy and fb.x > content_x + 50:
                            cy = max(cy, fb.y + fb.h)
                cb = self._layout_block(child, style, content_x, cy, content_w)
                # CSS float model: block BORDER boxes may overlap float bands; only the
                # inline content inside wraps. But if the block is a leaf with its own
                # background/border and a float intersects it, shift sideways when it fits.
                _intersects = [fb for fb in self._floats
                               if fb.w > 0 and fb.h > 0 and fb.y < cy + cb.h and cy < fb.y + fb.h]
                if _intersects and not cb.children and not (getattr(cb, "spans", None)):
                    for fb in _intersects:
                        if fb.x <= cb.x:
                            nx = fb.x + fb.w
                            if nx + cb.w <= self.vw * 0.98:
                                cb.x = nx
                                break
                cy = cb.y + cb.h
                box.children.append(cb)
            if inline_run:
                cy = self._layout_inline_run(inline_run, box, style, content_x, cy, content_w,
                                             floats=self._floats)
            H = style.get("height")
            # Float containment: a block whose children are (all) floated never grew —
            # standard clearfix / overflow:hidden cases leave parent h=0. When the block
            # establishes a BFC-ish context (overflow hidden/auto) OR ends with floated
            # children only, extend height to cover float bottoms.
            _fl_kids = [c for c in box.children if c.w > 0 and getattr(c, "_is_float", False)]
            if _fl_kids:
                _bfc = str(style.get("overflow", "visible")) not in ("visible", None, "None")
                _flow_kids = [c for c in box.children if not getattr(c, "_is_float", False)]
                _has_flow_content = any(getattr(c, "spans", None) or getattr(c, "text_lines", None)
                                        or (c.children or (c.node is not None and c.node.tag in
                                        ("p","ul","ol","table","img","h1","h2","h3","h4","h5","h6","pre","blockquote")))
                                        for c in _flow_kids)
            box.h = (cy + pb + bt) - box.y
            # aspect-ratio: w / h — height derives from width when height is auto
            _ar = style.get("aspect-ratio")
            if _ar and not H and box.w > 0:
                try:
                    parts_ar = str(_ar).split("/")
                    ar = float(parts_ar[0]) / float(parts_ar[1])
                except (ValueError, ZeroDivisionError):
                    ar = None
                if ar:
                    box.h = max(box.h, box.w / ar + pt + bt)
            if _fl_kids:
                _bfc = str(style.get("overflow", "visible")) not in ("visible", None, "None")
                _flow_kids = [c for c in box.children if not getattr(c, "_is_float", False)]
                _has_flow_content = any(getattr(c, "spans", None) or getattr(c, "text_lines", None)
                                        or (c.children or (c.node is not None and c.node.tag in
                                        ("p","ul","ol","table","img","h1","h2","h3","h4","h5","h6","pre","blockquote")))
                                        for c in _flow_kids)
                if _bfc or not _has_flow_content:
                    fb_max = max(c.y + c.h for c in _fl_kids)
                    box.h = max(box.h, (fb_max + pb + bt) - box.y)
            if H:
                box.h = self._len(H, cw)  # explicit height overrides content height
        if node.tag == "body":
            box.w = self.vw
        elif W:
            wv = self._len(W, cw)
            if str(style.get("box-sizing", "content-box")) == "border-box":
                box.w = wv  # includes padding+border
            else:
                box.w = wv + pl + pr + 2*bt
        else:
            box.w = cw
        # max-width clamp (+ auto-margin centering for blocks narrower than container)
        MW = style.get("max-width")
        if MW is not None and not isinstance(MW, str):
            mwv = self._len(MW, cw)
            if str(style.get("box-sizing", "content-box")) != "border-box":
                mwv = mwv + pl + pr + 2*bt
            if box.w > mwv:
                box.w = mwv
                if W is None and style.get("margin-left") is None and style.get("margin-right") is None and style.get("margin-left") != 0:
                    ml_auto = (isinstance(style.get("margin-left"), str) and style["margin-left"] == "auto")
                    mr_auto = (isinstance(style.get("margin-right"), str) and style["margin-right"] == "auto")
                    if ml_auto and mr_auto:
                        box.x += (cw - box.w) / 2
        return box

    @staticmethod
    def _shift_tree(b, dx, dy):
        b.x += dx; b.y += dy
        if getattr(b, "spans", None):
            new_spans = []
            for sp in b.spans:
                t, tx, bl = sp[0], sp[1], sp[2]
                new_spans.append((t, tx + dx, bl + dy) + tuple(sp[3:]))
            b.spans = new_spans
        for c in b.children:
            Layout._shift_tree(c, dx, dy)

    def _layout_flex(self, node, box, style, cx, cy, cw):
        """Flex container: row/column, wrap, gap, justify-content, align-items,
        flex-grow distribution. shrink not implemented (no overflow math)."""
        col = style.get("flex-direction", "row") == "column"
        wrap = style.get("flex-wrap", "nowrap") == "wrap"
        gap = self._len(style.get("gap"), cw) or 0.0
        raw_items = []
        for c0 in node.children:
            if c0.tag == "picture":
                # transparent wrapper: promote its <img> as the flex item
                _ik = [k for k in c0.children if k.tag == "img"]
                if _ik:
                    _pst = self.style_for(c0, style)
                    _ar0 = _pst.get("aspect-ratio")
                    _ist = self.style_for(_ik[0], style)
                    if _ar0 and not _ist.get("height"):
                        try:
                            _q1, _q2 = str(_ar0).split("/")
                            _w0 = self._len(_ist.get("width"), cw) or float(_ik[0].attr("width") or 0) or 300
                            if _w0 > cw: _w0 = cw
                            _ik[0].attr("width", str(int(_w0)))
                            _ik[0].attr("height", str(int(_w0 / (float(_q1) / float(_q2)))))
                        except Exception: pass
                    c0 = _ik[0]
            if c0.tag != "#text" or c0.text.strip():
                raw_items.append(c0)
        # measure natural sizes — shrink-to-fit (max-content capped at container)
        def _max_content_w(b):
            """Max-content width of a laid-out box: longest unwrapped text run."""
            best = 0.0
            if getattr(b, "spans", None):
                # group spans by baseline; sum widths within a line
                lines = {}
                for sp in b.spans:
                    lines.setdefault(round(sp[2], 1), 0.0)
                    lines[round(sp[2], 1)] += sp[4] * 0.62 * len(sp[0]) + sp[9] * len(sp[0]) if len(sp) > 9 else sp[4] * 0.62 * len(sp[0])
                best = max(lines.values()) if lines else 0.0
            for c in b.children:
                best = max(best, _max_content_w(c))
            return best
        items = []
        for child in raw_items:
            cstyle = self.style_for(child, style)
            grow = 0.0
            try: grow = float((cstyle.get("flex-grow") or 0) or 0)
            except (TypeError, ValueError): pass
            basis = cstyle.get("flex-basis")
            # natural content layout at full width for measuring
            cb = self._layout_block(child, style, 0, 0, cw)
            _has_block_kids = any(c.node is not None and c.node.tag not in
                                  ("#text", "span", "a", "em", "strong", "b", "i", "small")
                                  and (getattr(c, "children", None) or getattr(c, "spans", None))
                                  for c in cb.children)
            _explicit_w = cstyle.get("width")
            if not col and not _explicit_w and not _has_block_kids:
                mcw = _max_content_w(cb)
                if mcw > 0 and mcw < cb.w:
                    # re-lay at max-content width (shrink-to-fit); pad for estimator error
                    cb = self._layout_block(child, style, 0, 0, min(mcw * 1.18 + 16, cw))
            elif _explicit_w and not col:
                # explicit width (incl %) wins: re-lay at resolved width
                wv = self._len(_explicit_w, cw)
                if wv and wv > 0:
                    cb = self._layout_block(child, style, 0, 0, min(wv, cw))
            items.append({"box": cb, "grow": grow, "basis": basis, "child": child})
        n = len(items)
        if n == 0:
            box.h = 0
            return
        # main-axis free space distribution
        if col:
            main_total = sum(i["box"].h for i in items) + gap*(n-1)
            free = (box.h or 0) - main_total
        else:
            main_total = sum(i["box"].w for i in items) + gap*(n-1)
            free = cw - main_total
        growers = [i for i in items if i["grow"] > 0]
        if growers and free > 0:
            per = free/len(growers)
            for g in growers:
                if col:
                    g["box"].h += per
                    g["box"] = self._layout_block(g["child"], style, 0, 0, cw)
                else:
                    g["box"].w += per
        # flex-shrink approximation: if non-wrapped items overflow the line, squeeze
        # non-growing items proportionally to their overflow, then re-lay at final width.
        if not col and not wrap:
            total_w = sum(i["box"].w for i in items) + gap * (n - 1)
            shrinkers = [i for i in items
                         if float(i.get("grow") or 0 or 0) == 0
                         and not i.get("basis") and not i["box"].style.get("width")]
            if total_w > cw and shrinkers:
                deficit = total_w - cw
                base = sum(i["box"].w for i in shrinkers)
                for it in shrinkers:
                    cut = deficit * (it["box"].w / base if base else 0)
                    new_w = max(40.0, it["box"].w - cut)
                    it["box"] = self._layout_block(it["child"], style, 0, 0, new_w)
        # place
        jc = style.get("justify-content", "flex-start")
        ai = style.get("align-items", "stretch")
        cross_max = 0
        x, y = cx, cy
        line_used = 0
        line_start_x, line_start_y = x, y
        placed = []
        for idx, it in enumerate(items):
            cb = it["box"]
            w, h = cb.w, cb.h
            if not col and wrap and line_used + w + gap > cw and placed:
                # new line: reset x, advance y by tallest
                x = cx; y += cross_max + gap
                line_used = 0; cross_max = 0
            if jc == "center" and not col:
                pass  # handled via two-pass below
            Layout._shift_tree(cb, x - cb.x, y - cb.y)
            cb.x, cb.y = x, y
            if col:
                y += h + gap
                cross_max = max(cross_max, w)
            else:
                x += w + gap
                line_used += w + gap
                cross_max = max(cross_max, h)
            placed.append(cb)
            box.children.append(cb)
        # Re-lay items at FINAL widths so absolute/float descendants land correctly
        # (probe passes may have crushed nested absolutely-positioned subtrees).
        for idx, it in enumerate(items):
            cb = it["box"]
            if cb.w > 0 and cb.node is not None:
                nb = self._layout_block(it["child"], style, cb.x, cb.y, cb.w)
                nb.x, nb.y = cb.x, cb.y
                items[idx]["box"] = nb
                box.children[box.children.index(cb)] = nb
        # min-height / min-width floors on flex items (buttons, pills, cards)
        for it in items:
            cb = it["box"]
            cstyle = cb.style or {}
            for axis in ("h", "w"):
                mk = "min-height" if axis == "h" else "min-width"
                mv = cstyle.get(mk)
                if mv is None or isinstance(mv, str): continue
                mvv = self._len(mv, cb.w if axis == "h" else cw)
                if mvv > 0 and getattr(cb, axis) < mvv:
                    setattr(cb, axis, mvv)
                    pass
        if not col and jc in ("center","flex-end","space-between") and not wrap:
            total = sum(i["box"].w for i in items) + gap*(n-1 if n else 0)
            if jc == "center": dx = max(0, (cw-total)/2)
            elif jc == "flex-end": dx = max(0, cw-total)
            else: dx = 0
            extra = max(0, cw-total)/(n-1) if (jc=="space-between" and n>1) else 0
            for k, cb in enumerate(placed):
                cb.x += dx + k*extra
        # align-items cross-axis
        if not col:
            line_h = max(i["box"].h for i in items)
            for cb in placed:
                if ai == "center": cb.y += max(0, (line_h-cb.h)/2)
                elif ai == "flex-end": cb.y += max(0, line_h-cb.h)
            box.h = line_h
        else:
            line_w = max(i["box"].w for i in items)
            for cb in placed:
                if ai == "center": cb.x += max(0, (line_w-cb.w)/2)
                elif ai == "flex-end": cb.x += max(0, line_w-cb.w)
            box.h = sum(i["box"].h for i in items) + gap*(n-1 if n else 1) + 2
        box.h += 2

    def _layout_grid(self, node, box, style, cx, cy, cw):
        """Grid layout: tracks (repeat(N,1fr) | minmax(a,b) | px | % | auto),
        grid-template-areas with named areas, gap, source-order fallback."""
        import re as _re
        tmpl = style.get("grid-template-columns") or ""
        gap = self._len(style.get("gap"), cw) or 0.0
        if isinstance(style.get("gap"), str):
            gm = _re.match(r"([\d.]+)px", style["gap"].strip())
            gap = float(gm.group(1)) if gm else gap
        items = [c for c in node.children if c.tag != "#text" or c.text.strip()]
        # display:contents grid items vanish — their children become grid items
        expanded = []
        for it0 in items:
            st0 = self.style_for(it0, style)
            if str(st0.get("display") or "") == "contents":
                expanded += [k for k in it0.children if k.tag != "#text" or k.text.strip()]
            else:
                expanded.append(it0)
        items = expanded
        if not items:
            box.h = 0; return
        def parse_track_list(t):
            """Return list of track strings; supports repeat() and minmax()."""
            tracks, i, n = [], 0, len(t)
            while i < n:
                if t[i] == " ":
                    i += 1; continue
                if t[i] == "(" or t.startswith("minmax", i):
                    depth, j = 0, i
                    while j < n:
                        if t[j] == "(": depth += 1
                        elif t[j] == ")":
                            depth -= 1
                            if depth == 0: break
                        j += 1
                    tracks.append(t[i:j+1]); i = j+1
                elif t.startswith("repeat", i):
                    depth, j = 0, i
                    while j < n:
                        if t[j] == "(": depth += 1
                        elif t[j] == ")":
                            depth -= 1
                            if depth == 0: break
                        j += 1
                    inner = t[i:j+1]
                    m2 = _re.match(r"repeat\(\s*(\d+)\s*,\s*(.+)\)", inner)
                    if m2:
                        tracks += [m2.group(2).strip()] * int(m2.group(1))
                    i = j+1
                else:
                    j = t.find(" ", i)
                    j = n if j == -1 else j
                    tracks.append(t[i:j]); i = j
            return [t2 for t2 in tracks if t2]

        def _slen(t):
            """Parse a raw css length string to px."""
            t = (t or "").strip()
            if not t: return 0.0
            if t.endswith("px"):
                try: return float(t[:-2])
                except ValueError: return 0.0
            if t.endswith("rem"):
                try: return float(t[:-3]) * 16.0
                except ValueError: return 0.0
            if t.endswith("em"):
                try: return float(t[:-2]) * 16.0
                except ValueError: return 0.0
            if t.endswith("%"):
                try: return float(t[:-1]) / 100.0 * cw
                except ValueError: return 0.0
            try: return float(t)
            except ValueError: return 0.0

        def track_w(t, avail):
            t = t.strip()
            mmin = None; is_fr = False
            mm = _re.match(r"minmax\(\s*([^,]+)\s*,\s*(.+)\)", t)
            if mm:
                t = mm.group(2).strip()  # size to max; min handled as floor
                mn = mm.group(1).strip()
                if not mn.endswith("fr") and mn not in ("auto","max-content"):
                    mmin = _slen(mn)
            if t.endswith("fr"):
                is_fr = True; return ("fr", float(t[:-2]), mmin or 0)
            if t in ("auto", "min-content", "max-content"): return ("auto", None, mmin or 0)
            return ("px", _slen(t), mmin or 0)

        tmpl_full = style.get("grid-template") or ""
        gta = style.get("grid-template-areas") or ""
        # grid-template shorthand WITHOUT quotes: '<row sizes> / <col tracks>'
        cols = parse_track_list(tmpl) if tmpl else []
        if not cols and tmpl_full and "/" in tmpl_full and "'" not in tmpl_full and '"' not in tmpl_full:
            cols = parse_track_list(tmpl_full.split("/", 1)[1])
        # rows/areas: grid-template shorthand 'r1' h1 'r2' h2 / cols
        combined_t = (tmpl_full or "") + " " + (gta or "")
        row_strings = []
        _q = None; _buf = ""
        for _ch in combined_t:
            if _q:
                if _ch == _q:
                    row_strings.append(_buf); _q = None; _buf = ""
                else: _buf += _ch
            elif _ch in "\"'":
                _q = _ch
        row_strings = [r for r in row_strings if r.strip()]
        rows_from_areas = None
        if row_strings:
            rows_from_areas = [r.split() for r in row_strings if r.strip()]
        if rows_from_areas and not cols:
            # columns from the part after '/'
            slash = tmpl_full.rfind("/")
            if slash != -1:
                cols = parse_track_list(tmpl_full[slash+1:])
            elif gta:
                cols = ["1fr"] * max(len(r) for r in rows_from_areas)
        if not cols:
            n = max(1, int(len(items) ** 0.5 + 0.999))
            cols = ["1fr"] * n
            ncol = len(cols)
            parsed = [track_w(c, cw) for c in cols]
            fr_total = sum(p_[1] for p_ in parsed if p_[0] == "fr")
            fixed = sum(p_[1] for p_ in parsed if p_[0] == "px")
            fr_avail = max(0, cw - fixed - gap*(ncol-1))
            widths = []
            for kind, val, mn in parsed:
                if kind == "fr":
                    widths.append(max(mn, fr_avail * (val/fr_total if fr_total else 0)))
                elif kind == "auto":
                    widths.append(max(mn, (cw - fixed) / max(1, ncol)))
                else:
                    widths.append(val)
        # named-area map from style (grid-area on children is handled below via raw css)
        ncol = len(cols)
        parsed = [track_w(c, cw) for c in cols]
        # measure natural (max-content) width of each item for min/max-content tracks
        nat_w = [0.0] * ncol
        has_content_track_early = any(k == "auto" for k, v, m in parsed)
        for child in (items if has_content_track_early else []):
            cst = self.style_for(child, style)
            col_spec_n = _line_spec(cst.get("grid-column")) if "_line_spec" in dir() else None
            probe = self._layout_block(child, style, 0, 0, cw)
            def _sub_max(b):
                m = 0.0
                for sp in getattr(b, "spans", []):
                    m = max(m, sp[1] - b.x + self._text_w(sp[0], "sans-serif", sp[4] or 16.0))
                for k in b.children:
                    m = max(m, _sub_max(k))
                return m
            mc = min(max(_sub_max(probe) + 8, probe.w if probe.w < cw else 0), cw * 0.9)
            if probe.w > 0 and probe.w < cw * 0.95:
                mc = probe.w
            nat_w[0] = max(nat_w[0], mc)  # single-column attribution fallback
        has_content_track = any(k in ("auto",) for k, v, m in parsed)
        fr_total = sum(p[1] for p in parsed if p[0] == "fr")
        content_total = sum(nat_w)
        fixed = sum(p[1] for p in parsed if p[0] == "px")
        content_cols = sum(1 for k, v, m in parsed if k == "auto")
        fr_avail = max(0, cw - fixed - content_total - gap*(ncol-1))
        widths = []
        for ci, (kind, val, mn) in enumerate(parsed):
            if kind == "fr":
                widths.append(max(mn, fr_avail * (val/fr_total if fr_total else 0)))
            elif kind == "auto":
                # min-content / max-content / auto tracks size to content
                nat = nat_w[ci] if ci < len(nat_w) else 0
                widths.append(max(mn, nat if nat > 0 else max(mn, (cw - fixed) / max(1, ncol))))
            else:
                widths.append(val)
        if sum(widths) < cw:
            widths[-1] += cw - sum(widths)  # stretch last track (1fr behavior if it was fr)
        # build cell grid: named areas (grid-area: <name>) or source order
        # grid-column / grid-row: "N", "N / span M", "span M", "N / M" (CSS Grid §8)
        def _line_spec(v):
            """Return (start, span) 1-based start or None for auto."""
            if not isinstance(v, str) or not v.strip():
                return None
            parts = [p.strip() for p in v.split("/")]
            start = None; span = 1
            try:
                if parts[0].startswith("span"):
                    span = int(parts[0].split()[1])
                elif parts[0].isdigit():
                    start = int(parts[0])
                if len(parts) > 1:
                    p1 = parts[1].strip()
                    if p1.startswith("span"):
                        span = int(p1.split()[1])
                    elif p1.lstrip("-").isdigit():
                        end = int(p1)
                        if end < 0:
                            # negative line numbers count from the end (-1 = last line)
                            end = None  # resolved by caller via ncol
                        if start is not None and end is not None: span = max(1, end - start)
                        elif start is not None: span = 10**6  # "N / -1" = to the end
                        else: start, span = max(1, (end or 2) - 1), 1
            except (ValueError, IndexError):
                return None
            return (start, span)
        area_of = {}
        cell_grid = {}
        grid = []
        if rows_from_areas:
            area_cells = {}
            for ri, row in enumerate(rows_from_areas):
                for ci, name in enumerate(row):
                    area_cells.setdefault(name, []).append((ri, ci))
            placed = set()
            r_i = 0
            for child in items:
                cst = self.style_for(child, style)
                ga = cst.get("grid-area") or cst.get("_grid_area")
                if isinstance(ga, str) and ga.strip() in area_cells:
                    cells = area_cells[ga.strip()]
                    r0, c0 = cells[0]
                    r1 = max(c[0] for c in cells); c1 = max(c[1] for c in cells)
                    grid.append((r0, c0, r1, c1, child)); placed.add(ga.strip())
                else:
                    grid.append(None)
            # source-order fill for unnamed/auto-placed children
            free = [(ri, ci) for ri, row in enumerate(rows_from_areas)
                    for ci, name in enumerate(row) if name == "."]
            gi = 0
            ncols_a = max(len(r) for r in rows_from_areas)
            used = {(ri, ci) for ri, row in enumerate(rows_from_areas)
                    for ci, name in enumerate(row) if name != "."}
            for k, g in enumerate(grid):
                if g is None:
                    # auto-place: next free (row, col) not claimed by a named area
                    placed = False
                    while gi < len(free):
                        ri, ci = free[gi]; gi += 1
                        if (ri, ci) not in used:
                            grid[k] = (ri, ci, ri, ci, items[k])
                            placed = True
                            break
                    if not placed:
                        # extend past defined rows
                        auto_r = len(rows_from_areas) + (k - gi + 1)
                        grid[k] = (auto_r, 0, auto_r, min(ncols_a - 1, 0), items[k])
            grid = [g for g in grid if g]
        elif not grid:
            col_i = row_i = 0
            occupied_gc: set = set()
            for child in items:
                cst = self.style_for(child, style)
                col_spec = _line_spec(cst.get("grid-column"))
                row_spec = _line_spec(cst.get("grid-row"))
                if col_spec and col_spec[0] is not None:
                    c0 = min(col_spec[0] - 1, ncol - 1)
                    cs = col_spec[1]
                else:
                    # auto-place at next free column in current row
                    c0 = col_i; cs = col_spec[1] if col_spec else 1
                    while any((row_i, c0 + k) in occupied_gc for k in range(cs)) or c0 + cs > ncol:
                        c0 += 1
                        if c0 + cs > ncol:
                            c0 = 0; row_i += 1
                            if row_i > 200: break
                cs = max(1, min(cs, ncol - c0))
                if row_spec and row_spec[0] is not None:
                    r0 = row_spec[0] - 1
                    rs = row_spec[1]
                else:
                    r0 = row_i; rs = row_spec[1] if row_spec else 1
                grid.append((r0, c0, r0 + rs - 1, c0 + cs - 1, child))
                for k in range(cs):
                    occupied_gc.add((row_i, c0 + k))
                col_i = c0 + cs
                if col_i >= ncol:
                    col_i = 0; row_i += rs if rs > 1 else 1
        # row heights: auto — measure each item
        nrows = (max(g[2] for g in grid) + 1) if grid else 1
        row_h = [0.0] * nrows
        # explicit row sizes from grid-template shorthand / grid-template-rows
        row_sizes = []
        if tmpl_full and "/" in tmpl_full:
            pre = tmpl_full.split("/")[0]
            szs = _re.findall(r"\b([\d.]+(?:px|fr|em|%)|auto|min-content|max-content)\b", pre)
            szs = [z for z in szs if not _re.match(r"^\d", z) or "px" in z or "fr" in z or "em" in z or "%" in z or z == "auto"]
            row_sizes = szs[:nrows]
        rt = style.get("grid-template-rows")
        if isinstance(rt, str) and rt.strip():
            row_sizes = parse_track_list(rt)[:nrows]
        for ri in range(min(len(row_sizes), nrows)):
            t_ = row_sizes[ri]
            if isinstance(t_, str) and t_.endswith("fr"):
                continue  # fr rows grow in content pass below
            L = track_w(t_, cw) if isinstance(t_, str) else ("px", 0, 0)
            if L[0] == "px" and L[1]:
                row_h[ri] = L[1]
        cell_boxes = []
        for (r0, c0, r1, c1, child) in grid:
            span_w = sum(widths[c] for c in range(c0, min(c1+1, ncol))) + gap*max(0, c1-c0)
            cb = self._layout_block(child, style, 0, 0, span_w)
            cell_boxes.append((r0, c0, r1, c1, cb))
            for r in range(r0, r1+1):
                row_h[r] = max(row_h[r], cb.h / (r1 - r0 + 1))
        # place
        ys = [cy]
        for h in row_h:
            ys.append(ys[-1] + h + gap)
        for (r0, c0, r1, c1, cb) in cell_boxes:
            nx = cx + sum(widths[:c0]) + gap*c0
            Layout._shift_tree(cb, nx - cb.x, ys[r0] - cb.y)
            cb.x = nx
            cb.y = ys[r0]
            if r1 > r0:  # span rows: stretch
                cb.h = max(cb.h, ys[r1] + row_h[r1] - cb.y - gap)
            box.children.append(cb)
        box.h = (ys[nrows-1] + row_h[nrows-1]) - cy if nrows else 0

    def _layout_table(self, node, box, style, cx, cy, cw):
        """Table layout with rowspan/colspan, cell padding, borders."""
        # presentational table attrs (HTML4)
        try: _cpad = float(node.attr("cellpadding") or 2.0)
        except (TypeError, ValueError): _cpad = 2.0
        try: _cbord = int(node.attr("border") or 0)
        except (TypeError, ValueError): _cbord = 0
        rows = [r for r in node.children if r.tag == "tr"] or [
            r for tr in node.children if tr.tag in ("tbody","thead","tfoot")
            for r in tr.children if r.tag == "tr"]
        if not rows:
            box.h = 0; return
        # occupancy grid honoring rowspan/colspan
        occupied: dict[tuple[int, int], bool] = {}
        grid_rows: list[list[tuple]] = []  # (cell, col0, colspan, rowspan)
        ncols = 0
        for ri, r in enumerate(rows):
            cells = [c for c in r.children if c.tag in ("td", "th")]
            row_slots: list[tuple] = []
            ci = 0
            for cell in cells:
                while occupied.get((ri, ci)):
                    ci += 1
                try: cs = max(1, int(cell.attr("colspan") or 1))
                except (TypeError, ValueError): cs = 1
                try: rs = max(1, int(cell.attr("rowspan") or 1))
                except (TypeError, ValueError): rs = 1
                for dr in range(rs):
                    for dc in range(cs):
                        occupied[(ri + dr, ci + dc)] = True
                row_slots.append((cell, ci, cs, rs))
                ci += cs
            ncols = max(ncols, ci)
            grid_rows.append(row_slots)
        ncols = max(ncols, max((max((c2 + cs for _, c2, cs, _ in slots), default=0) for slots in grid_rows), default=0))
        if ncols == 0:
            box.h = 0; return
        # natural (max-content) width per column from text metrics
        def _txt_w(nd, fs):
            total = 0.0
            for t in nd.walk():
                if t.tag == "#text" and t.text:
                    total += fs * 0.55 * len(t.text)
                if t.tag in ("img",):
                    try: total += max(1, int(t.attr("width") or 40))
                    except ValueError: total += 40
            return total
        col_nat = [30.0] * ncols
        for ri, slots in enumerate(grid_rows):
            for (cell, c0, cs, rs) in slots:
                cell_style = self.style_for(cell, style)
                w = _txt_w(cell, (cell_style.get("font-size") or 16.0) * 0.62)
                per = w / cs
                for k in range(cs):
                    col_nat[c0 + k] = max(col_nat[c0 + k], min(per, cw * 0.6))
        nat_total = sum(col_nat)
        if nat_total > cw:
            scale = cw / nat_total
            col_w_list = [max(18.0, w * scale) for w in col_nat]
        else:
            col_w_list = list(col_nat)
            extra = cw - nat_total
            big = [i for i, w in enumerate(col_nat) if w >= nat_total / max(1, ncols) * 0.6] or list(range(ncols))
            per = extra / len(big)
            for i in big:
                col_w_list[i] += per
        y = cy
        row_hs = []
        # first pass: measure row heights (cells not rowspanned from above)
        cell_boxes = []
        for ri, slots in enumerate(grid_rows):
            for (cell, c0, cs, rs) in slots:
                cell_style = self.style_for(cell, style)
                pad = _cpad
                span_w = sum(col_w_list[c0:c0+cs]) - 2*pad
                cb = self._layout_block(cell, style, 0, 0, span_w)
                cell_boxes.append((ri, c0, cs, rs, cb, cell_style, span_w))
            single = [t[4].h + 2*pad for t in cell_boxes if t[0] == ri and t[3] == 1]
            row_hs.append(max(single) if single else 18.0)
        # second pass: rowspan cells distribute over rows
        for (ri, c0, cs, rs, cb, cell_style, span_w) in cell_boxes:
            if rs > 1:
                span_h = sum(row_hs[ri:ri+rs]) + 2*pad
                if cb.h + 2*pad > span_h:
                    extra = (cb.h + 2*pad - span_h) / rs
                    for dr in range(rs):
                        if ri + dr < len(row_hs):
                            row_hs[ri + dr] += extra
        y = cy
        for ri, slots in enumerate(grid_rows):
            x = cx
            for (cell, c0, cs, rs) in slots:
                match = [t for t in cell_boxes if t[0] == ri and t[1] == c0]
                if not match:
                    x += sum(col_w_list[c0:c0+cs])
                    continue
                _, _, _, _, cb, cell_style, span_w = match[0]
                gb = Box(cell, cell_style)
                gb.x = x; gb.y = y; gb.w = sum(col_w_list[c0:c0+cs]); gb.h = sum(row_hs[ri:ri+rs])
                gb.border = {"width": 1, "style": "solid", "color": (170,170,170,255)} if _cbord else None
                Layout._shift_tree(cb, x + pad - cb.x, y + pad - cb.y)
                cb.x = x + pad; cb.y = y + pad
                gb.children.append(cb)
                box.children.append(gb)
                x += sum(col_w_list[c0:c0+cs])
            y += row_hs[ri]
        box.h = y - cy

    FORM_TAGS = ("input", "button", "select", "textarea")

    def _widget_box(self, nd, parent_style, x, y, cw):
        """Build a form-control widget box (leaf) with default + styled sizing."""
        style = self.style_for(nd, parent_style)
        box = Box(nd, style)
        box.bg = style.get("background-color")
        box.border = style.get("border")
        box.radius = style.get("border-radius", 0.0) or 0.0
        if isinstance(box.radius, str): box.radius = 0.0
        t = nd.tag
        # default sizes
        if t == "input":
            typ = (nd.attr("type") or "text").lower()
            if typ == "checkbox": w, h = 13.0, 13.0
            elif typ == "radio": w, h = 13.0, 13.0
            else:
                try: w = float(nd.attr("size") or 20) * 8.0 + 16.0
                except (TypeError, ValueError): w = 176.0
                h = 22.0
        elif t == "button":
            label = "".join(c.text or "" for c in nd.children if c.tag == "#text").strip()
            try: fsz = float(style.get("font-size", 13.0) or 13.0)
            except (TypeError, ValueError): fsz = 13.0
            w = self._text_w(label, style.get("font-family", "sans-serif"), fsz, False, False) + 24.0
            h = 24.0
        elif t == "select": w, h = 160.0, 22.0
        else:  # textarea
            try: cols = float(nd.attr("cols") or 20); rows = float(nd.attr("rows") or 2)
            except (TypeError, ValueError): cols, rows = 20, 2
            w, h = cols * 8.0 + 18.0, rows * 18.0 + 8.0
        # style overrides
        W = style.get("width"); H = style.get("height")
        if isinstance(W, (int, float)): w = float(W)
        elif isinstance(W, str) and W.endswith("px"):
            try: w = float(W[:-2])
            except ValueError: pass
        if isinstance(H, (int, float)): h = float(H)
        elif isinstance(H, str) and H.endswith("px"):
            try: h = float(H[:-2])
            except ValueError: pass
        box.x, box.y, box.w, box.h = x, y, max(1.0, w), h
        if not box.bg:
            box.bg = (239, 239, 239, 255) if t in ("button", "input", "select") else (255, 255, 255, 255)
            if t == "textarea" or (t == "input" and (nd.attr("type") or "text").lower() not in ("checkbox", "radio", "submit", "button")):
                box.bg = (255, 255, 255, 255)
        if not box.border:
            box.border = {"width": 1.0, "style": "solid", "color": (118, 118, 118, 255)}
        box.is_widget = True
        return box

    def _layout_inline_run(self, nodes, parent_box, parent_style, x, y, cw, floats=None):
        """Lay out a run of inline nodes as wrapped lines with per-word styled spans."""
        floats = floats if floats is not None else getattr(self, "_floats", [])
        def line_span(y_line):
            """(left_inset, width) for this line given active floats."""
            li, ri = 0.0, 0.0
            for fb in floats:
                # overlap test: float vertical band intersects this line
                if fb.y <= y_line < fb.y + fb.h:
                    if fb.x <= x:  # left float
                        li = max(li, fb.x + fb.w - x)
                    else:
                        ri = max(ri, (x + cw) - fb.x)
            return li, max(20.0, cw - li - ri), li
        try:
            font_size = float(parent_style.get("font-size", 16.0) or 16.0)
        except (TypeError, ValueError):
            font_size = 16.0
        family = parent_style.get("font-family", "sans-serif")
        align = parent_style.get("text-align", "left")
        line_h = parent_style.get("line-height", 1.2) or 1.2
        try: line_h = float(line_h)
        except (TypeError, ValueError): line_h = 1.2
        if line_h < 3: line_h = line_h * font_size
        base_style = {
            "family": family, "size": font_size,
            "bold": str(parent_style.get("font-weight","normal")) in ("bold","bolder","700","800","900"),
            "italic": str(parent_style.get("font-style","normal")) in ("italic","oblique"),
            "color": parent_style.get("color") or (0,0,0,255),
            "underline": str(parent_style.get("text-decoration","none")) == "underline",
            "sup": False, "mono": False,
        }
        try:
            _ls = float(parent_style.get("letter-spacing", 0) or 0)
        except (TypeError, ValueError):
            _ls = 0.0
        if _ls:
            base_style["ls"] = _ls
        line_y = y
        max_y = y
        words = []   # list of dicts: text, w, style, space_before(bool)
        line_has_content = False
        pending_space = False
        def flush():
            nonlocal words, line_y, max_y, pending_space
            if not words:
                pending_space = False
                return
            total_w = sum(w["w"] + (space_w(w["style"]) if w["sb"] else 0) for w in words)
            li, avail, loff = line_span(line_y)
            if align == "center": lx = x + loff + max(0, (avail - total_w)/2)
            elif align == "right": lx = x + loff + max(0, avail - total_w)
            else: lx = x + loff
            cur_x = lx
            baseline = line_y + font_size * 0.95
            parent_box.is_text = True
            for w in words:
                if w["sb"]:
                    cur_x += space_w(w["style"])
                st = w["style"]
                size = st["size"] * 0.75 if st["sup"] else st["size"]
                dy = -font_size * 0.35 if st["sup"] else 0
                parent_box.spans.append((w["text"], cur_x, baseline + dy,
                                         _find_font(st["family"], st["bold"], st["italic"]),
                                         size, st["color"], st["underline"], st["sup"], w.get("nd"),
                                         st.get("ls", 0.0)))
                cur_x += w["w"]
            max_y = max(max_y, line_y + line_h)
            words = []
            line_y += line_h
            pending_space = False
        def space_w(st):
            return self._text_w(" ", st["family"], st["size"], st["bold"], st["italic"])
        def add_word(text, st, sb, nd=None):
            nonlocal pending_space
            ww = self._text_w(text, st["family"], st["size"], st["bold"], st["italic"])
            if st.get("ls"):
                ww += st["ls"] * len(text)
            _, avail, _l = line_span(line_y) if words else (0, cw, 0)
            cur_w = sum(w["w"] + (space_w(w["style"]) if w["sb"] else 0) for w in words)
            if words and cur_w + (space_w(st) if sb else 0) + ww > avail:
                flush()
            words.append({"text": text, "w": ww, "style": dict(st), "sb": sb and bool(words), "nd": nd})
        def add_text(raw, st, nd=None):
            nonlocal pending_space
            toks = raw.split(" ")
            for i, tok in enumerate(toks):
                if tok == "":
                    continue
                sb = pending_space or (i > 0 and True) or (i > 0)
                # leading token: space only if pending_space from before
                add_word(tok, st, sb if pending_space or i > 0 else False, nd)
                pending_space = False
            if raw.endswith(" ") or (raw and raw[-1].isspace()):
                pending_space = True
        def node_style(nd, st):
            """Merge an inline element's computed style into the running word style."""
            cstyle = self.style_for(nd, parent_style)
            s2 = dict(st)
            if str(cstyle.get("font-weight","normal")) in ("bold","bolder","700","800","900"):
                s2["bold"] = True
            if str(cstyle.get("font-style","normal")) in ("italic","oblique"):
                s2["italic"] = True
            if cstyle.get("color"): s2["color"] = cstyle["color"]
            if nd.tag == "a":
                if s2.get("color") in (None, (0,0,0,255)): s2["color"] = (0,0,238,255)
                s2["underline"] = True
            if str(cstyle.get("text-decoration","none")) == "underline":
                s2["underline"] = True
            if nd.tag in ("code","kbd","samp","tt","pre"):
                s2["family"] = "monospace"
            if nd.tag in ("sub","sup"):
                s2["sup"] = True
            try:
                _ls2 = float(cstyle.get("letter-spacing", 0) or 0)
            except (TypeError, ValueError):
                _ls2 = 0.0
            if _ls2:
                s2["ls"] = _ls2
            elif st.get("ls"):
                s2["ls"] = st["ls"]
            return s2
        for nd in nodes:
            if nd.tag == "#text":
                if nd.text:
                    add_text(nd.text, base_style, nd)
                continue
            if nd.tag == "br":
                flush(); continue
            if nd.tag == "img":
                ist = self.style_for(nd, parent_style)
                w = self._len(ist.get("width"), cw) or 0
                h = self._len(ist.get("height"), cw) or 0
                if not w:
                    try: w = float(nd.attr("width") or 0)
                    except Exception: w = 0
                if not h:
                    try: h = float(nd.attr("height") or 0)
                    except Exception: h = 0
                if not w or not h:
                    w = w or 300; h = h or (w * 0.66)
                if w > cw:  # images never exceed the available line width
                    h = h * cw / w; w = cw
                cur_w = sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                if words and cur_w + w > cw: flush()
                ib = Box(nd, self.style_for(nd, parent_style))
                ib.x = x + cur_w; ib.y = line_y; ib.w = w; ib.h = h
                ib.bg = (235,235,235,255)
                parent_box.children.append(ib)
                pending_space = True
                continue
            if nd.tag in ("input", "button", "select", "textarea", "option", "label"):
                if nd.tag == "label":
                    st = node_style(nd, base_style)
                    self._inline_children(nd, st, add_text, add_word)
                    continue
                wdg = self._widget_box(nd, parent_style, x, line_y, cw)
                cur_w = sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                if words and cur_w + wdg.w > cw: flush()
                wdg.x = x + cur_w; wdg.y = line_y
                parent_box.children.append(wdg)
                pending_space = True
                continue
            cstyle = self.style_for(nd, parent_style)
            cdisp = self._display(cstyle)
            if cdisp in ("inline","inline-block","list-item"):
                st = node_style(nd, base_style)
                # images nested inside this inline subtree: emit placeholder boxes
                for img_node in nd.walk():
                    if img_node.tag == "img":
                        ist = self.style_for(img_node, parent_style)
                        iw = self._len(ist.get("width"), cw) or 0
                        ih = self._len(ist.get("height"), cw) or 0
                        if not iw:
                            try: iw = float(img_node.attr("width") or 0)
                            except Exception: iw = 0
                        if not ih:
                            try: ih = float(img_node.attr("height") or 0)
                            except Exception: ih = 0
                        if not iw or not ih:
                            iw = iw or 300; ih = ih or (iw * 0.66)
                        if iw > cw:
                            ih = ih * cw / iw; iw = cw
                        if not ih:
                            _par = img_node.parent
                            while _par is not None and _par.tag == "picture":
                                _ar = (self.style_for(_par, parent_style).get("aspect-ratio") or "")
                                if _ar:
                                    try:
                                        pa, pb2 = _ar.split("/")
                                        ih = iw / (float(pa) / float(pb2))
                                    except Exception: pass
                                break
                        cur_w = sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                        if words and cur_w + iw > cw: flush()
                        ib = Box(img_node, self.style_for(img_node, parent_style))
                        ib.x = x + sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                        ib.y = line_y; ib.w = iw; ib.h = ih
                        ib.bg = (235,235,235,255)
                        parent_box.children.append(ib)
                        pending_space = True
                self._inline_children(nd, st, add_text, add_word) 
                continue
            # block child inside inline run
            flush()
            cb = self._layout_block(nd, parent_style, x, line_y, cw)
            line_y = cb.y + cb.h
            max_y = max(max_y, line_y)
            parent_box.children.append(cb)
        flush()
        return max_y

    def _inline_children(self, nd, st, add_text, add_word):
        """Recursively add an inline element's text children with merged style."""
        for c in nd.children:
            if c.tag == "#text":
                if c.text: add_text(c.text, st, nd)
            elif c.tag == "br":
                pass  # handled by caller only at top level; rare inside nested inlines
            else:
                cstyle = self.style_for(c, {"font-size": st["size"], "color": st["color"]})
                # merge deeper styles
                s2 = dict(st)
                if str(cstyle.get("font-weight","normal")) in ("bold","bolder","700","800","900"): s2["bold"] = True
                if str(cstyle.get("font-style","normal")) in ("italic","oblique"): s2["italic"] = True
                if cstyle.get("color"): s2["color"] = cstyle["color"]
                if c.tag == "a":
                    if s2.get("color") in (None, (0,0,0,255)): s2["color"] = (0,0,238,255)
                    s2["underline"] = True
                if str(cstyle.get("text-decoration","none")) == "underline": s2["underline"] = True
                if c.tag in ("code","kbd","samp","tt"): s2["family"] = "monospace"
                if c.tag in ("sub","sup"): s2["sup"] = True
                self._inline_children(c, s2, add_text, add_word)

    def _len(self, v, cw):
        if v is None: return 0.0
        if isinstance(v, (int, float)): return float(v)
        if isinstance(v, tuple):
            if v[0] == "pct": return v[1]/100*cw
            if v[0] == "vh": return v[1]/100 * getattr(self, "viewport_h", cw)
            if v[0] == "vw": return v[1]/100 * getattr(self, "viewport_w", cw)
            return v[0]
        return 0.0
