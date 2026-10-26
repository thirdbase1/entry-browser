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
                 "bg","border","radius","is_text","spans","img")
    def __init__(self, node=None, style=None):
        self.node = node; self.style = style or {}
        self.x = self.y = self.w = self.h = 0.0
        self.children: list[Box] = []
        self.text_lines: list[tuple[str,float,float]] = []  # (text, x, baseline_y)
        self.spans: list[tuple] = []  # (text, x, baseline, font_path, size, color, underline, superscript)
        self.img = None               # (PIL.Image, x, y, w, h) for painted images
        self.bg = None; self.border = None; self.radius = 0.0
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
                 viewport_w=800.0):
        self.doc = doc
        self.ss = stylesheet
        self.vw = viewport_w
        self._font_cache: dict[tuple, object] = {}
        self._measure_cache: dict[tuple, float] = {}
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

    def _layout_table(self, node, box, style, cx, cy, cw):
        """Grid table layout: equal-ish column widths, cell padding, borders."""
        rows = [r for r in node.children if r.tag == "tr"] or [
            r for tr in node.children if tr.tag in ("tbody","thead","tfoot")
            for r in tr.children if r.tag == "tr"]
        if not rows:
            box.h = 0; return
        ncells = max(len([c for c in r.children if c.tag in ("td","th")]) for r in rows)
        if ncells == 0: box.h = 0; return
        col_w = cw / ncells
        y = cy
        max_h = 0
        for r in rows:
            cells = [c for c in r.children if c.tag in ("td","th")]
            x = cx
            row_h = 0
            for cell in cells:
                cell_style = self.style_for(cell, style)
                pad = 2.0
                cb = self._layout_block(cell, style, x + pad, y + pad, col_w - 2*pad)
                # th bold handled via UA? add: cell bg + border
                cellw = col_w
                # draw cell box with border
                gb = Box(cell, cell_style)
                gb.x = x; gb.y = y; gb.w = cellw; gb.h = cb.h + 2*pad
                gb.border = {"width": 1, "style": "solid", "color": (170,170,170,255)}
                gb.children.append(cb)
                # shift cell box contents
                box.children.append(gb)
                row_h = max(row_h, cb.h + 2*pad)
                x += cellw
            y += row_h
            max_h = y - cy
        box.h = max_h

    def _layout_inline_run(self, nodes, parent_box, parent_style, x, y, cw):
        """Lay out a run of inline nodes as wrapped lines with per-word styled spans."""
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
            if align == "center": lx = x + max(0, (cw - total_w)/2)
            elif align == "right": lx = x + max(0, cw - total_w)
            else: lx = x
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
                                         size, st["color"], st["underline"], st["sup"]))
                cur_x += w["w"]
            max_y = max(max_y, line_y + line_h)
            words = []
            line_y += line_h
            pending_space = False
        def space_w(st):
            return self._text_w(" ", st["family"], st["size"], st["bold"], st["italic"])
        def add_word(text, st, sb):
            nonlocal pending_space
            ww = self._text_w(text, st["family"], st["size"], st["bold"], st["italic"])
            cur_w = sum(w["w"] + (space_w(w["style"]) if w["sb"] else 0) for w in words)
            if words and cur_w + (space_w(st) if sb else 0) + ww > cw:
                flush()
            words.append({"text": text, "w": ww, "style": dict(st), "sb": sb and bool(words)})
        def add_text(raw, st):
            nonlocal pending_space
            toks = raw.split(" ")
            for i, tok in enumerate(toks):
                if tok == "":
                    continue
                sb = pending_space or (i > 0 and True) or (i > 0)
                # leading token: space only if pending_space from before
                add_word(tok, st, sb if pending_space or i > 0 else False)
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
            return s2
        for nd in nodes:
            if nd.tag == "#text":
                if nd.text:
                    add_text(nd.text, base_style)
                continue
            if nd.tag == "br":
                flush(); continue
            if nd.tag == "img":
                try: w = float(nd.attr("width") or 0)
                except Exception: w = 0
                try: h = float(nd.attr("height") or 0)
                except Exception: h = 0
                if not w or not h:
                    w = w or 300; h = h or (w * 0.66)
                cur_w = sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                if words and cur_w + w > cw: flush()
                ib = Box(nd, self.style_for(nd, parent_style))
                ib.x = x + cur_w; ib.y = line_y; ib.w = w; ib.h = h
                ib.bg = (210,210,210,255)
                parent_box.children.append(ib)
                pending_space = True
                continue
            cstyle = self.style_for(nd, parent_style)
            cdisp = self._display(cstyle)
            if cdisp in ("inline","inline-block","list-item"):
                st = node_style(nd, base_style)
                # images nested inside this inline subtree: emit placeholder boxes
                for img_node in nd.walk():
                    if img_node.tag == "img":
                        try: iw = float(img_node.attr("width") or 0)
                        except Exception: iw = 0
                        try: ih = float(img_node.attr("height") or 0)
                        except Exception: ih = 0
                        if not iw or not ih:
                            iw = iw or 300; ih = ih or (iw * 0.66)
                        cur_w = sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                        if words and cur_w + iw > cw: flush()
                        ib = Box(img_node, self.style_for(img_node, parent_style))
                        ib.x = x + sum(w2["w"] + (space_w(w2["style"]) if w2["sb"] else 0) for w2 in words)
                        ib.y = line_y; ib.w = iw; ib.h = ih
                        ib.bg = (210,210,210,255)
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
                if c.text: add_text(c.text, st)
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
            return v[0]
        return 0.0
