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
    __slots__ = ("node","x","y","w","h","children","style","text_lines",
                 "bg","border","radius","is_text")
    def __init__(self, node=None, style=None):
        self.node = node; self.style = style or {}
        self.x = self.y = self.w = self.h = 0.0
        self.children: list[Box] = []
        self.text_lines: list[tuple[str,float,float]] = []  # (text, x, baseline_y)
        self.bg = None; self.border = None; self.radius = 0.0
        self.is_text = False
    def __repr__(self):
        return f"Box({self.node.tag if self.node else 'anon'} {self.x:.0f},{self.y:.0f} {self.w:.0f}x{self.h:.0f})"

DEFAULT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

def _find_font(family: str, bold=False) -> str:
    import os
    want_mono = family and "mono" in family.lower()
    cands = []
    if want_mono:
        cands = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else
                 FONT_MONO]
    elif bold:
        cands = [FONT_BOLD, DEFAULT_FONT]
    cands += [DEFAULT_FONT,
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
              "/usr/share/fonts/truetype/freefont/FreeSans.ttf"]
    for c in cands:
        if os.path.exists(c): return c
    # last resort: any ttf
    import glob
    g = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    return g[0] if g else ""

class Layout:
    def __init__(self, doc: Node, stylesheet: Stylesheet | None = None,
                 viewport_w=800.0):
        self.doc = doc
        self.ss = stylesheet
        self.vw = viewport_w
        self._font_cache: dict[tuple, object] = {}
        self._measure_cache: dict[tuple, float] = {}
    def _font(self, family, size, bold=False):
        from PIL import ImageFont
        key = (family, round(size), bold)
        if key not in self._font_cache:
            path = _find_font(family, bold)
            try:
                self._font_cache[key] = ImageFont.truetype(path, int(round(size)))
            except Exception:
                self._font_cache[key] = ImageFont.load_default()
        return self._font_cache[key]
    def _text_w(self, text, family, size, bold=False):
        key = ("W", text, family, round(size), bold)
        if key not in self._measure_cache:
            f = self._font(family, size, bold)
            self._measure_cache[key] = f.getlength(text)
        return self._measure_cache[key]

    def build(self) -> Box:
        body = next((n for n in self.doc.query_all("body")), self.doc)
        root_style = {}
        root = self._layout_block(body, root_style, 0.0, 0.0, self.vw)
        root.w = self.vw
        # second pass to fix heights bottom-up happens in _layout_block already
        return root

    # ---- style ----
    def style_for(self, node, parent_style):
        em = parent_style.get("font-size", 16.0)
        st = UA.computed(node, parent_style, em=em)
        if self.ss:
            st = self.ss.computed(node, st, em=st.get("font-size", 16.0), base=st)
        return st

    def _display(self, style):
        d = style.get("display", "inline")
        if style.get("position") == "absolute": return "block"
        return d

    # ---- block layout ----
    def _layout_block(self, node, parent_style, x, y, cw):
        """Layout a block container; returns its Box with height set."""
        style = self.style_for(node, parent_style)
        box = Box(node, style)
        box.x = x; box.y = y
        box.bg = style.get("background-color")
        box.border = style.get("border")
        box.radius = style.get("border-radius", 0.0) or 0.0
        if isinstance(box.radius, str):
            box.radius = 0.0
        mt, mr, mb, ml = (self._len(style.get(f"margin-{k}"), cw) for k in ("top","right","bottom","left"))
        pt, pr, pb, pl = (self._len(style.get(f"padding-{k}"), cw) for k in ("top","right","bottom","left"))
        bw = style.get("border") or {}
        bt = bw.get("width", 0) if isinstance(bw, dict) else 0
        box.x += mt; y += mt
        content_x = box.x + ml + pl + bt
        content_y = y + pt + bt
        content_w = cw - ml - mr - pl - pr - 2*bt
        W = style.get("width")
        if W: content_w = self._len(W, cw)
        disp = self._display(style)
        if disp == "none" or style.get("visibility") == "hidden":
            box.w = box.h = 0
            return box
        # flex row container?
        if style.get("display") == "flex" and style.get("flex-direction", "row") == "row":
            self._layout_flex_row(node, box, style, content_x, content_y, content_w)
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
                cstyle = self.style_for(child, style)
                if self._display(cstyle) == "inline" or self._display(cstyle) == "inline-block":
                    inline_run.append(child)
                    continue
                # flush inline run
                if inline_run:
                    cy = self._layout_inline_run(inline_run, box, style, content_x, cy, content_w)
                    inline_run = []
                cb = self._layout_block(child, style, content_x, cy, content_w)
                cy = cb.y + cb.h
                box.children.append(cb)
            if inline_run:
                cy = self._layout_inline_run(inline_run, box, style, content_x, cy, content_w)
            H = style.get("height")
            box.h = (cy + pb + bt) - box.y
            if H:
                box.h = max(box.h, self._len(H, cw))
        box.w = cw - mt - (0)  # full available width for blocks
        box.w = self.vw if node.tag == "body" else cw
        return box

    def _layout_flex_row(self, node, box, style, cx, cy, cw):
        items = []
        gap = self._len(style.get("gap"), cw) or 0.0
        for child in node.children:
            if child.tag == "#text" and not child.text.strip(): continue
            cb = self._layout_block(child, style, 0, 0, max(cw/len(node.children), 40))
            items.append(cb)
        total = sum(i.w for i in items) + gap*(len(items)-1 if items else 0)
        x = cx
        jc = style.get("justify-content", "flex-start")
        if jc == "center": x += max(0, (cw-total)/2)
        elif jc == "flex-end": x += max(0, cw-total)
        maxh = 0
        for it in items:
            it.x = x; it.y = cy
            x += it.w + gap
            maxh = max(maxh, it.h)
            box.children.append(it)
        box.h = maxh + 2  # padding approx

    def _layout_inline_run(self, nodes, parent_box, parent_style, x, y, cw):
        """Lay out a run of inline nodes as wrapped text lines."""
        style = self.style_for(nodes[0], parent_style) if nodes else parent_style
        try:
            font_size = float(parent_style.get("font-size", 16.0) or 16.0)
        except (TypeError, ValueError):
            font_size = 16.0
        family = parent_style.get("font-family", "sans-serif")
        bold = str(parent_style.get("font-weight", "normal")) in ("bold","bolder","700","800","900")
        align = parent_style.get("text-align", "left")
        line_h = parent_style.get("line-height", 1.2) or 1.2
        try:
            line_h = float(line_h)
        except (TypeError, ValueError):
            line_h = 1.2
        if line_h < 3: line_h = line_h * font_size
        line_x, line_y = x, y
        line_text = []
        space_w = self._text_w(" ", family, font_size, bold)
        max_y = y
        def flush():
            nonlocal line_x, line_y, max_y
            if not line_text: return
            text = " ".join(t for t, _ in line_text if t)
            w = sum(w for _, w in line_text)
            if align == "center": lx = x + max(0, (cw - w)/2)
            elif align == "right": lx = x + max(0, cw - w)
            else: lx = x
            baseline = line_y + font_size * 0.95
            parent_box.text_lines.append((text, lx, baseline))
            parent_box.is_text = True
            max_y = max(max_y, line_y + line_h)
            line_text.clear()
            line_y += line_h
            line_x = x
        for nd in nodes:
            if nd.tag == "#text":
                raw = nd.text
                words = raw.split()
                if not words:
                    if raw and line_text:  # whitespace-only node = inter-word space
                        line_text.append(("", space_w))
                    continue
                glued = (bool(raw) and not raw[0].isspace()
                         and bool(line_text) and line_text[-1][0] != "")
                for w_i, word in enumerate(words):
                    ww = self._text_w(word, family, font_size, bold)
                    cur_w = sum(w for _, w in line_text) + (space_w if line_text else 0)
                    if cur_w + ww > cw and line_text:
                        flush()
                    if w_i == 0 and glued and line_text:
                        # merge with previous word (no space in source)
                        prev, pw = line_text[-1]
                        merged = prev + word
                        line_text[-1] = (merged, pw + ww)
                    else:
                        line_text.append((word, ww + (space_w if line_text else 0)))
                if len(words) and raw[-1].isspace():
                    line_text.append(("", space_w))
                continue
            cstyle = self.style_for(nd, parent_style)
            cdisp = self._display(cstyle)
            if cdisp in ("inline","inline-block"):
                if nd.tag in ("br",):
                    flush(); continue
                if nd.tag == "img":
                    # draw placeholder box sized from attrs
                    try: w = float(nd.attr("width") or 100)
                    except: w = 100
                    try: h = float(nd.attr("height") or 80)
                    except: h = 80
                    cur_w = sum(w2 for _, w2 in line_text) + (space_w if line_text else 0)
                    if cur_w + w > cw and line_text: flush()
                    ib = Box(nd, cstyle)
                    ib.x = x + cur_w; ib.y = line_y; ib.w = w; ib.h = h
                    ib.bg = (220,220,220,255)
                    parent_box.children.append(ib)
                    line_text.append(("\u00a0"*(int(w/8) or 1), w))
                    continue
                # inline element with text (a, span, strong, em, code, b, i...)
                txt = nd.text_content()
                if nd.tag == "br": flush(); continue
                first = True
                for word in txt.split():
                    ww = self._text_w(word, family, font_size, bold)
                    cur_w = sum(w2 for _, w2 in line_text) + (space_w if line_text else 0)
                    if cur_w + ww > cw and line_text: flush()
                    if first and line_text and txt and not txt[0].isspace() and line_text[-1][0]:
                        prev, pw = line_text[-1]
                        line_text[-1] = (prev + word, pw + ww)
                    else:
                        line_text.append((word, ww + (space_w if line_text else 0)))
                    first = False
                if txt and txt[-1].isspace():
                    line_text.append(("", space_w))
                continue
            else:
                # block child inside inline run: flush and lay out as block
                flush()
                cb = self._layout_block(nd, parent_style, x, line_y, cw)
                line_y = cb.y + cb.h
                max_y = max(max_y, line_y)
                parent_box.children.append(cb)
        flush()
        return max_y

    def _len(self, v, cw):
        if v is None: return 0.0
        if isinstance(v, (int, float)): return float(v)
        if isinstance(v, tuple):
            if v[0] == "pct": return v[1]/100*cw
            return v[0]
        return 0.0
