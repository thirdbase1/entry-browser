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

def _paint(img, d: ImageDraw.ImageDraw, box: Box):
    tr = getattr(box, "transform", None)
    if tr and (tr[0] or tr[1] or tr[2] or tr[3] != 1.0):
        _paint_transformed(img, box)
        return
    ovf = box.style.get("overflow") if isinstance(box.style, dict) else None
    if ovf == "hidden" and box.children:
        # paint into clipped layer
        try:
            x0, y0 = max(0, int(box.x)), max(0, int(box.y))
            x1, y1 = int(box.x + box.w), int(box.y + box.h)
            if x1 > x0 and y1 > y0 and x1 <= img.width and y1 <= img.height:
                layer = img.crop((x0, y0, x1, y1))
                ld = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(layer)
                _paint_plain(layer, ld, box)
                img.paste(layer, (x0, y0))
                return
        except Exception:
            pass
    _paint_plain(img, d, box)

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

def _paint_plain(img, d: ImageDraw.ImageDraw, box: Box):
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
