"""entrybrowser.render — rasterizer: box tree -> PNG.

Pillow-based painter: backgrounds, borders, text lines, images.
"""
from __future__ import annotations
from .layout import Box, _find_font

def render(box: Box, width: int, height: int, out_path: str):
    from PIL import Image, ImageDraw, ImageFont
    # measure content height first pass if height not given
    img = Image.new("RGBA", (int(width), int(height)), (255,255,255,255))
    d = ImageDraw.Draw(img)
    _paint(img, d, box)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    bg.save(out_path)
    return out_path

def content_height(box: Box) -> int:
    h = box.h
    for c in box.children:
        h = max(h, c.y + c.h)
    return int(h + 1)

def _widget_font(size):
    from PIL import ImageFont
    return ImageFont.truetype(_find_font(None, False, False), int(round(size)))

_SF = None
def _small_font():
    global _SF
    if _SF is None:
        from PIL import ImageFont
        from .layout import DEFAULT_FONT
        try:
            _SF = ImageFont.truetype(DEFAULT_FONT, 14)
        except Exception:
            _SF = ImageFont.load_default()
    return _SF


def _paint_layer_children(layer, ld, box, x0, y0):
    """Paint child boxes into a clipped layer, translating absolute coords."""
    dx, dy = -x0, -y0
    import copy
    for c in box.children:
        try:
            c2 = copy.copy(c)
            c2.x = c.x + dx; c2.y = c.y + dy
            if getattr(c, "spans", None):
                c2.spans = []
                for sp in c.spans:
                    sp2 = list(sp)
                    sp2[1] = sp[1] + dx   # tx
                    sp2[2] = sp[2] + dy   # baseline
                    c2.spans.append(tuple(sp2))
            c2.children = c.children  # nested handled by _paint recursion with shift?
            _paint(layer, ld, c2)
        except Exception:
            pass

_LAYER_SHIFT = []  # (dx,dy) applied to all absolute coords painted into clipped layers

def _shift_pt(x, y):
    if _LAYER_SHIFT:
        dx, dy = _LAYER_SHIFT[-1]
        return x + dx, y + dy
    return x, y

def _paint(img, d: ImageDraw.ImageDraw, box: Box):
    global _LAYER_SHIFT
    tr = getattr(box, "transform", None)
    if tr and (tr[0] or tr[1] or tr[2] or tr[3] != 1.0):
        _paint_transformed(img, box)
        return
    ovf = box.style.get("overflow") if isinstance(box.style, dict) else None
    if ovf == "hidden" and box.children:
        # paint into clipped layer
        try:
            # crop coords must be in the CURRENT surface's space: when painting into
            # a parent layer, absolute coords were shifted — apply the same shift.
            _bx, _by = box.x, box.y
            if _LAYER_SHIFT:
                _dx, _dy = _LAYER_SHIFT[-1]
                _bx, _by = _bx + _dx, _by + _dy
            x0, y0 = max(0, int(_bx)), max(0, int(_by))
            x1, y1 = int(_bx + box.w), int(_by + box.h)
            if x1 > x0 and y1 > y0 and x1 <= img.width and y1 <= img.height:
                layer = img.crop((x0, y0, x1, y1))
                ld = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(layer)
                # paint children with coordinates translated into layer space
                _LAYER_SHIFT.append((-x0, -y0))
                try:
                    _paint_plain(layer, ld, box)
                finally:
                    _LAYER_SHIFT.pop()
                img.paste(layer, (x0, y0))
                return
        except Exception:
            pass
    _paint_plain(img, d, box, _top=False)

def _paint_transformed(img, box):
    """Render a transformed box (translate/rotate/scale) into an offscreen layer."""
    from PIL import Image as _Image, ImageDraw as _ImageDraw
    tx, ty, deg, sc = box.transform
    pad = int(max(abs(box.w), abs(box.h)) * (abs(sc - 1) + 0.6)) + 8
    lw, lh = int(box.w + 2*pad), int(box.h + 2*pad)
    layer = _Image.new("RGBA", (max(1, lw), max(1, lh)), (0, 0, 0, 0))
    ld = _ImageDraw.Draw(layer)
    # draw box contents into a sub-image then paste with transform
    ox, oy = box.x, box.y
    box.x = pad; box.y = pad
    # keep children coordinates relative: shift subtree by (-ox+pad, -oy+pad)
    def shift(b, dx, dy):
        b.x += dx; b.y += dy
        for c in b.children:
            shift(c, dx, dy)
    shift(box, -ox + pad, -oy + pad)
    try:
        _paint_plain(layer, ld, box)
    finally:
        shift(box, ox - pad, oy - pad)
        box.x, box.y = ox, oy
    if deg:
        layer = layer.rotate(-deg, expand=True, resample=_Image.BICUBIC)
    if sc != 1.0:
        layer = layer.resize((max(1, int(layer.width * sc)), max(1, int(layer.height * sc))), _Image.BICUBIC)
    px = int(ox + tx + pad - (layer.width - lw) / 2)
    py = int(oy + ty + pad - (layer.height - lh) / 2)
    img.paste(layer, (px, py), layer)
    # re-bind draw to img
    dd = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img)
    _PAINT_DRAW[0] = dd

_PAINT_DRAW = [None]



def _svg_f(v, default=0.0):
    try:
        return float(str(v).replace("%", "").strip())
    except Exception:
        return default

def _paint_svg(img, d, box):
    """Minimal inline-SVG painter: rect/circle/ellipse/line/polyline/polygon/path
    (M L H V C S Q T Z absolute+relative), stroke=currentColor / fill, viewBox scaling."""
    node = box.node
    if node is None or node.tag != "svg" or box.w <= 0 or box.h <= 0:
        return False
    st = box.style or {}
    color = st.get("color") or (0, 0, 0, 255)
    if isinstance(color, tuple) and len(color) == 4:
        cur = color
    else:
        cur = (0, 0, 0, 255)
    stroke_w = st.get("stroke-width") or 2
    try: stroke_w = float(stroke_w)
    except (TypeError, ValueError): stroke_w = 2.0
    try:
        vb = (node.attrs.get("viewBox") or "").replace(",", " ").split()
        vbx, vby, vbw, vbh = (float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])) if len(vb) == 4 else (0, 0, float(node.attrs.get("width", box.w)), float(node.attrs.get("height", box.h)))
    except (ValueError, IndexError):
        vbx, vby, vbw, vbh = 0, 0, box.w, box.h
    if vbw <= 0 or vbh <= 0: return True
    sx = box.w / vbw; sy = box.h / vbh
    def T(x, y): return (box.x + (x - vbx) * sx, box.y + (y - vby) * sy)
    def col(v, default):
        if v in (None, "none", "transparent"): return None
        if v == "currentColor": return tuple(cur)
        from .css import parse_color as _pc
        c = _pc(v)
        return tuple(c) if c else default
    def walk_children(n):
        for c in n.children:
            tag = c.tag
            a = c.attrs
            sw = a.get("stroke-width")
            try: sw = float(sw) if sw is not None else stroke_w
            except ValueError: sw = stroke_w
            stroke = col(a.get("stroke"), None) if a.get("stroke") else (tuple(cur) if a.get("fill") is None and a.get("stroke") != "none" else None)
            # lucide convention: fill=none stroke=currentColor on the svg root; shapes inherit
            root_fill = a.get("fill")
            fill = col(root_fill, None) if root_fill else None
            st_ = None
            if tag == "rect":
                x, y = _svg_f(a.get("x", 0)), _svg_f(a.get("y", 0))
                w2, h2 = _svg_f(a.get("width", 0)), _svg_f(a.get("height", 0))
                rx = float(a.get("rx", 0) or 0)
                p1, p2 = T(x, y), T(x + w2, y + h2)
                st_ = [p1, p2]
                if stroke and fill is None:
                    if rx: d.rounded_rectangle([p1[0], p1[1], p2[0], p2[1]], radius=rx*min(sx,sy), outline=stroke, width=max(1, int(sw*min(sx,sy))))
                    else: d.rectangle([p1[0], p1[1], p2[0], p2[1]], outline=stroke, width=max(1, int(sw*min(sx,sy))))
                elif fill:
                    if rx: d.rounded_rectangle([p1[0], p1[1], p2[0], p2[1]], radius=rx*min(sx,sy), fill=fill)
                    else: d.rectangle([p1[0], p1[1], p2[0], p2[1]], fill=fill)
            elif tag == "circle":
                cx, cy, r = _svg_f(a.get("cx", 0)), _svg_f(a.get("cy", 0)), _svg_f(a.get("r", 0))
                p1, p2 = T(cx - r, cy - r), T(cx + r, cy + r)
                if fill: d.ellipse([p1[0], p1[1], p2[0], p2[1]], fill=fill)
                elif stroke: d.ellipse([p1[0], p1[1], p2[0], p2[1]], outline=stroke, width=max(1, int(sw*min(sx,sy))))
            elif tag == "line":
                p1, p2 = T(_svg_f(a.get("x1", 0)), _svg_f(a.get("y1", 0))), T(_svg_f(a.get("x2", 0)), _svg_f(a.get("y2", 0)))
                if stroke: d.line([p1[0], p1[1], p2[0], p2[1]], fill=stroke, width=max(1, int(sw*min(sx,sy))))
            elif tag in ("polyline", "polygon"):
                pts = a.get("points", "").replace(",", " ").split()
                xy = [T(float(pts[i]), float(pts[i+1])) for i in range(0, len(pts) - 1, 2)]
                if xy:
                    if tag == "polygon" and fill: d.polygon(xy, fill=fill)
                    elif stroke: d.line([c2 for p2 in xy for c2 in p2], fill=stroke, width=max(1, int(sw*min(sx,sy))), joint="curve")
            elif tag == "path" and a.get("d"):
                _paint_svg_path(d, a["d"], T, stroke or tuple(cur), max(1, int(sw*min(sx,sy))), fill)
            walk_children(c)
    walk_children(node)
    return True

def _paint_svg_path(d, dd, T, stroke, width, fill=None):
    """Path: M/m L/l H/h V/v C/c S/s Q/q T/t A(->line)/Z/z."""
    import re as _re
    for _ in range(4):
        dd = _re.sub(r"(\d)\.(\d+)\.(\d)", r"\1.\2 \3", dd)  # compact "4.5.5" => "4.5 .5"
    toks = _re.findall(r"([MLHVCSQTAZmlhvcsqtaz])([^MLHVCSQTAZmlhvcsqtaz]*)", dd)
    def nums(s2):
        out = []
        for m3 in _re.finditer(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", s2):
            try: out.append(float(m3.group(0)))
            except ValueError: pass
        return out
    cx = cy = 0.0; sxp = syp = 0.0
    pts = []
    subs = []
    for cmd, arg in toks:
        v = nums(arg)
        if cmd in "Mm":
            if pts: subs.append(pts); pts = []
            for i in range(0, len(v) - 1, 2):
                if cmd == "M": cx, cy = v[i], v[i+1]
                else: cx, cy = cx + v[i], cy + v[i+1]
                pts.append(T(cx, cy)); sxp, syp = cx, cy
        elif cmd in "Ll":
            for i in range(0, len(v) - 1, 2):
                if cmd == "L": cx, cy = v[i], v[i+1]
                else: cx, cy = cx + v[i], cy + v[i+1]
                pts.append(T(cx, cy))
        elif cmd in "Hh":
            for x2 in v:
                cx = x2 if cmd == "H" else cx + x2
                pts.append(T(cx, cy))
        elif cmd in "Vv":
            for y2 in v:
                cy = y2 if cmd == "V" else cy + y2
                pts.append(T(cx, cy))
        elif cmd in "CcSsQqTt":
            # cubic/quadratic: sample control polygon
            if cmd in "Cc":
                for i in range(0, len(v) - 5, 6):
                    x1, y1, x2, y2, x3, y3 = (v[i:i+6] if cmd == "C" else
                        [cx+v[i], cy+v[i+1], cx+v[i+2], cy+v[i+3], cx+v[i+4], cy+v[i+5]])
                    for k in range(1, 9):
                        tt = k / 8
                        mx_ = (1-tt)**3*cx + 3*(1-tt)**2*tt*x1 + 3*(1-tt)*tt*tt*x2 + tt**3*x3
                        my_ = (1-tt)**3*cy + 3*(1-tt)**2*tt*y1 + 3*(1-tt)*tt*tt*y2 + tt**3*y3
                        pts.append(T(mx_, my_))
                    cx, cy = x3, y3
            else:
                for i in range(0, len(v) - 3, 4):
                    x1, y1, x2, y2 = (v[i:i+4] if cmd == "Q" else
                        [cx+v[i], cy+v[i+1], cx+v[i+2], cy+v[i+3]])
                    for k in range(1, 9):
                        tt = k / 8
                        mx_ = (1-tt)**2*cx + 2*(1-tt)*tt*x1 + tt**2*x2
                        my_ = (1-tt)**2*cy + 2*(1-tt)*tt*y1 + tt**2*y2
                        pts.append(T(mx_, my_))
                    cx, cy = x2, y2
        elif cmd in "Zz":
            if pts: pts.append(pts[0])
        elif cmd in "Aa":
            # arc: approximate with line to end point
            for i in range(0, len(v) - 6, 7):
                if cmd == "A": cx, cy = v[i+5], v[i+6]
                else: cx, cy = cx + v[i+5], cy + v[i+6]
                pts.append(T(cx, cy))
        if cmd in "Mm": pass
    if pts: subs.append(pts)
    for pts2 in subs:
        if len(pts2) >= 2:
            flat = [c2 for p2 in pts2 for c2 in p2]
            if fill is not None and len(pts2) >= 3:
                d.polygon(pts2, fill=fill, outline=stroke)
            else:
                d.line(flat, fill=stroke, width=width, joint="curve")


def _paint_gradient(img, box, grad):
    """Paint a linear-gradient tuple (angle, [(color, pos), ...]) over the box area."""
    from PIL import Image as _PILImage
    import math as _math
    angle, stops = grad
    x0, y0 = max(0, int(box.x)), max(0, int(box.y))
    x1, y1 = int(box.x + box.w), int(box.y + box.h)
    if x1 <= x0 or y1 <= y0:
        return
    w, h = x1 - x0, y1 - y0
    # projection axis: unit vector along gradient direction; default to bottom (90deg)
    if angle is None:
        ux, uy = 0.0, 1.0
    else:
        ux, uy = _math.cos(angle), _math.sin(angle)
    # gradient line length through the box (CSS formula approximation)
    glen = abs(w * ux) + abs(h * uy)
    if glen <= 0:
        return
    stops = sorted(stops, key=lambda s2: s2[1])
    if stops[0][1] > 0:
        stops.insert(0, (stops[0][0], 0.0))
    if stops[-1][1] < 1:
        stops.append((stops[-1][0], 1.0))
    # build a 1D gradient strip then scale — cheap and smooth
    strip = _PILImage.new("RGB", (int(glen) or 1, 1))
    px = strip.load()
    si = 0
    for i2 in range(strip.size[0]):
        t = i2 / max(strip.size[0] - 1, 1)
        while si < len(stops) - 2 and t > stops[si + 1][1]:
            si += 1
        c0, p0 = stops[si]; c1, p1 = stops[min(si + 1, len(stops) - 1)]
        span = (p1 - p0) or 1.0
        f = max(0.0, min(1.0, (t - p0) / span))
        px[i2, 0] = (int(c0[0] + (c1[0] - c0[0]) * f),
                     int(c0[1] + (c1[1] - c0[1]) * f),
                     int(c0[2] + (c1[2] - c0[2]) * f))
    # orient strip along direction: rotate the strip then crop center
    deg = _math.degrees(_math.atan2(uy, ux))
    diag = int(_math.hypot(w, h)) + 2
    big = strip.resize((diag, 1)).rotate(-deg, expand=True)
    bw, bh = big.size
    cx, cy = (bw - w) // 2, (bh - h) // 2
    patch = big.convert("RGB").crop((cx, cy, cx + w, cy + h))
    if getattr(box, "radius", 0) and box.radius > 0:
        mask = _PILImage.new("L", (w, h), 0)
        from PIL import ImageDraw as _ID
        _ID.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=box.radius, fill=255)
        img.paste(patch, (x0, y0), mask)
    else:
        img.paste(patch, (x0, y0))
    return


def _paint_plain(img, d: ImageDraw.ImageDraw, box: Box, _top=True):
    if _LAYER_SHIFT:
        import copy as _copy
        box = _copy.copy(box)
        dx, dy = _LAYER_SHIFT[-1]
        box.x += dx; box.y += dy
        if getattr(box, "spans", None):
            box.spans = [tuple([sp[0], sp[1]+dx, sp[2]+dy] + list(sp[3:])) for sp in box.spans]
    # opacity:0 boxes are fully invisible (common for CSS checkbox hacks) — skip painting
    try:
        if float(box.style.get("opacity", 1) or 1) <= 0 and not (box.children or getattr(box, "spans", None)):
            return
    except (TypeError, ValueError):
        pass
    # visually-hidden pattern: clip: rect(0,0,0,0) / clip-path: inset(50%) -> invisible
    _cp = str(box.style.get("clip-path") or "")
    _cl = str(box.style.get("clip") or "")
    if "inset(50%" in _cp or _cl.replace(" ", "").startswith("rect(0,0,0,0"):
        return
    if _paint_svg(img, d, box):
        return
    # linear-gradient background-image (typed tuple from css._parse_linear_gradient)
    _bgi = box.style.get("background-image")
    if isinstance(_bgi, tuple) and _bgi and box.w > 0 and box.h > 0:
        try:
            _paint_gradient(img, box, _bgi)
        except Exception as _ge:
            import sys as _sys
            print("gradient fail:", _ge, file=_sys.stderr)
    if box.bg and box.w > 0 and box.h > 0 and not (len(box.bg) == 4 and box.bg[3] == 0):
        col = tuple(box.bg) if len(box.bg) == 4 else (*box.bg, 255)
        try:
            op = float(box.style.get("opacity", 1) or 1)
            if op < 1: col = (*col[:3], int(col[3]*op))
        except (TypeError, ValueError):
            pass
        x0, y0 = max(0, int(box.x)), max(0, int(box.y))
        x1, y1 = int(box.x + box.w), int(box.y + box.h)
        if x1 > x0 and y1 > y0:
            # RGBA on an RGB base ignores alpha in PIL — pre-blend against the base
            if len(col) == 4 and col[3] < 255:
                try:
                    from PIL import Image as _PILImage
                    Image = _PILImage
                    _crop = img.crop((x0, y0, x1, y1)).convert("RGBA")
                    _ov = Image.new("RGBA", _crop.size, col)
                    # blend color channel-wise against base RGB, keep base alpha
                    _b = Image.alpha_composite(_crop, _ov)
                    _out = Image.merge("RGBA", (*_b.split()[0:3], _crop.split()[3]))
                    img.paste(_out, (x0, y0))
                    col = None
                except Exception as _be:
                    import sys as _sys
                    print("BG-blend fail:", _be, file=_sys.stderr)
                    col = (*col[:3],)
            if col is not None:
                if box.radius and box.radius > 0:
                    d.rounded_rectangle([x0, y0, x1, y1], radius=box.radius, fill=col)
                else:
                    d.rectangle([x0, y0, x1, y1], fill=col)
    if box.bg_img and box.w > 2 and box.h > 2:
        try:
            from PIL import Image as _PILImage
            if not isinstance(box.bg_img[0], _PILImage.Image):
                raise ValueError
            bim, bsize = box.bg_img
            iw, ih = int(box.w), int(box.h)
            if isinstance(bsize, str) and "contain" in bsize:
                sc = min(box.w / bim.width, box.h / bim.height)
                iw, ih = max(1, int(bim.width * sc)), max(1, int(bim.height * sc))
            elif isinstance(bsize, str) and "cover" in bsize:
                sc = max(box.w / bim.width, box.h / bim.height)
                iw, ih = max(1, int(bim.width * sc)), max(1, int(bim.height * sc))
            r_im = bim.resize((max(1, iw), max(1, ih)))
            img.paste(r_im, (int(box.x), int(box.y)), r_im)
            d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img)
        except Exception:
            pass
    if box.border and isinstance(box.border, dict) and box.border.get("width",0) > 0:
        bcol = box.border.get("color", (0,0,0,255))
        x0, y0 = max(0, int(box.x)), max(0, int(box.y))
        x1, y1 = int(box.x + box.w), int(box.y + box.h)
        if x1 > x0 and y1 > y0:
            d.rectangle([x0, y0, x1, y1], outline=tuple(bcol), width=int(box.border["width"]))
    # form widget chrome
    if getattr(box, "is_widget", False) and box.node is not None and box.w > 0:
        # hidden widgets (opacity:0 checkbox hacks) paint nothing
        try:
            if float(box.style.get("opacity", 1) or 1) <= 0:
                return
        except (TypeError, ValueError):
            pass
        nd = box.node
        t = nd.tag
        color = box.style.get("color") or (0, 0, 0, 255)
        try: fs = float(box.style.get("font-size", 13.0) or 13.0)
        except (TypeError, ValueError): fs = 13.0
        if t == "input":
            typ = (nd.attr("type") or "text").lower()
            if typ == "checkbox":
                d.rectangle([box.x+1, box.y+1, box.x+box.w-1, box.y+box.h-1],
                            outline=(90,90,90,255), width=1)
                if nd.attr("checked") is not None:
                    d.line([box.x+3, box.y+box.h/2, box.x+box.w/2, box.y+box.h-3],
                           fill=(20,90,200,255), width=2)
                    d.line([box.x+box.w/2, box.y+box.h-3, box.x+box.w-3, box.y+3],
                           fill=(20,90,200,255), width=2)
            elif typ == "radio":
                d.ellipse([box.x+1, box.y+1, box.x+box.w-1, box.y+box.h-1],
                          outline=(90,90,90,255), width=1)
                if nd.attr("checked") is not None:
                    d.ellipse([box.x+4, box.y+4, box.x+box.w-4, box.y+box.h-4],
                              fill=(20,90,200,255))
            else:
                val = nd.attr("value") or ""
                try: font = _widget_font(fs)
                except Exception: font = _small_font()
                d.text((box.x+5, box.y + (box.h-fs)/2), val, font=font, fill=tuple(color))
                if nd is getattr(_paint, "_focused", None):
                    cx = box.x + 5 + font.getlength(val) if val else box.x + 5
                    d.line([cx, box.y+3, cx, box.y+box.h-3], fill=(0,0,0,255), width=1)
        elif t == "textarea":
            val = "".join(c.text or "" for c in nd.children if c.tag == "#text").strip()
            try: font = _widget_font(fs)
            except Exception: font = _small_font()
            d.multiline_text((box.x+5, box.y+4), val, font=font, fill=tuple(color))
        elif t == "button":
            label = "".join(c.text or "" for c in nd.children if c.tag == "#text").strip()
            try: font = _widget_font(fs)
            except Exception: font = _small_font()
            tw = font.getlength(label)
            d.text((box.x + (box.w-tw)/2, box.y + (box.h-fs)/2), label, font=font, fill=tuple(color))
        elif t == "select":
            val = ""
            for o in nd.children:
                if o.tag == "option":
                    val = (o.text or "").strip() or val
                    if o.attr("selected") is not None:
                        val = (o.text or "").strip(); break
            try: font = _widget_font(fs)
            except Exception: font = _small_font()
            d.text((box.x+5, box.y + (box.h-fs)/2), val, font=font, fill=tuple(color))
            ax = box.x + box.w - 14
            ay = box.y + box.h/2
            d.polygon([(ax, ay-2), (ax+8, ay-2), (ax+4, ay+3)], fill=(60,60,60,255))
    # list bullets / numbers
    if box.node is not None and box.node.tag == "li":
        _ls_skip = False
        try:
            _ls = str(box.style.get("list-style-type") or "").strip().lower()
            if _ls == "none":
                _ls_skip = True
            else:
                _p = box.node.parent
                # parent li boxes carry the ul/ol list-style — check nearest ul/ol
                # ancestor's computed style via the layout cache on its box
                while _p is not None and _p.tag not in ("ul", "ol"):
                    _p = _p.parent
                if _p is not None and getattr(_p, "_box", None) is not None:
                    _pls = str(_p._box.style.get("list-style-type") or "").strip().lower()
                    if _pls == "none":
                        _ls_skip = True
        except Exception:
            _ls_skip = False
        if not _ls_skip:
            try:
                from .layout import Layout as _L
            except Exception:
                pass
            parent = box.node.parent
            # find our index among li siblings
            idx = 0
            if parent is not None:
                for c in parent.children:
                    if c.tag == "li":
                        idx += 1
                    if c is box.node:
                        break
            marker = f"{idx}."
            lt = (parent.attrs.get("type") if parent is not None else None)
            ul = parent is not None and parent.tag == "ul"
            color = box.style.get("color") or (0,0,0,255)
            mx = max(0.0, box.x - 14)
            d.text((mx, (box.text_lines[0][2] if box.text_lines else box.y + 14)),
                   "•" if ul else marker, font=_small_font(), fill=tuple(color))
    if box.spans:
        from PIL import ImageFont
        cache = {}
        for text, tx, baseline, fpath, size, color, underline, sup, *rest in box.spans:
            ls = rest[1] if len(rest) > 1 and isinstance(rest[1], (int, float)) else 0.0
            key = (fpath, int(round(size)))
            if key not in cache:
                try:
                    cache[key] = ImageFont.truetype(fpath, int(round(size)))
                except Exception:
                    cache[key] = ImageFont.load_default()
            font = cache[key]
            if ls:
                cx2 = tx
                for ch in text:
                    d.text((cx2, baseline), ch, font=font, fill=tuple(color if color else (0,0,0,255)))
                    cx2 += font.getlength(ch) + ls
                tw = cx2 - tx
            else:
                d.text((tx, baseline), text, font=font, fill=tuple(color if color else (0,0,0,255)))
                tw = font.getlength(text)
            if underline:
                ly = baseline + size * 0.18
                d.line([tx, ly, tx + tw, ly], fill=tuple(color if color else (0,0,0,255)), width=max(1, int(size/16)))
    if box.img:
        im, ix, iy, iw, ih = box.img
        if iw > 2 * 1280 or ih > 4 * 1000:  # absurd size guard
            im, iw, ih = None, 0, 0
    if box.img and im is not None:
        try:
            img.paste(im.resize((max(1,int(iw)), max(1,int(ih)))), (int(ix), int(iy)), im.resize((max(1,int(iw)), max(1,int(ih)))))
        except ValueError:
            img.paste(im.resize((max(1,int(iw)), max(1,int(ih)))), (int(ix), int(iy)))
        d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img)  # re-bind after paste
    # CSS2.1 Appendix E paint order: negative z, blocks, floats, inlines,
    # positioned z=0/auto, positive z.
    def _z(c):
        try:
            return int(float(c.style.get("z-index") or 0))
        except (TypeError, ValueError):
            return 0

    def _phase(c):
        st = c.style if isinstance(c.style, dict) else {}
        pos = st.get("position")
        zi = _z(c)
        if pos in ("absolute", "fixed", "relative") or (zi and st.get("z-index") not in (None, "auto")):
            return (-1, c.y) if zi < 0 else ((4, c.y) if zi > 0 else (3, c.y))
        if st.get("float") in ("left", "right"):
            return (1, c.y)
        if st.get("display") in ("inline", "inline-block") or c.node is not None and getattr(c.node, "tag", "") == "span":
            return (2, c.y)
        return (0, c.y)
    kids = sorted(box.children, key=lambda c: (_phase(c), _z(c)))
    for c in kids:
        _paint(img, d, c)
