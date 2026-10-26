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
    img.convert("RGB").save(out_path)
    return out_path

def content_height(box: Box) -> int:
    h = box.h
    for c in box.children:
        h = max(h, c.y + c.h)
    return int(h + 1)

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

def _paint_plain(img, d: ImageDraw.ImageDraw, box: Box):
    if box.bg and box.w > 0 and box.h > 0:
        col = tuple(box.bg) if len(box.bg) == 4 else (*box.bg, 255)
        try:
            op = float(box.style.get("opacity", 1) or 1)
            if op < 1: col = (*col[:3], int(col[3]*op))
        except (TypeError, ValueError):
            pass
        if box.radius and box.radius > 0:
            d.rounded_rectangle([box.x, box.y, box.x+box.w, box.y+box.h],
                                radius=box.radius, fill=col)
        else:
            d.rectangle([box.x, box.y, box.x+box.w, box.y+box.h], fill=col)
    if box.border and isinstance(box.border, dict) and box.border.get("width",0) > 0:
        bcol = box.border.get("color", (0,0,0,255))
        d.rectangle([box.x, box.y, box.x+box.w, box.y+box.h],
                    outline=tuple(bcol), width=int(box.border["width"]))
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
        for text, tx, baseline, fpath, size, color, underline, sup in box.spans:
            key = (fpath, int(round(size)))
            if key not in cache:
                try:
                    cache[key] = ImageFont.truetype(fpath, int(round(size)))
                except Exception:
                    cache[key] = ImageFont.load_default()
            font = cache[key]
            d.text((tx, baseline), text, font=font, fill=tuple(color if color else (0,0,0,255)))
            if underline:
                tw = font.getlength(text)
                ly = baseline + size * 0.18
                d.line([tx, ly, tx + tw, ly], fill=tuple(color if color else (0,0,0,255)), width=max(1, int(size/16)))
    if box.img:
        im, ix, iy, iw, ih = box.img
        try:
            img.paste(im.resize((max(1,int(iw)), max(1,int(ih)))), (int(ix), int(iy)), im.resize((max(1,int(iw)), max(1,int(ih)))))
        except ValueError:
            img.paste(im.resize((max(1,int(iw)), max(1,int(ih)))), (int(ix), int(iy)))
        d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img)  # re-bind after paste
    # paint children sorted by z-index (stable for equal/absent z)
    def _z(c):
        try:
            return int(float(c.style.get("z-index") or 0))
        except (TypeError, ValueError):
            return 0
    kids = sorted(box.children, key=_z)
    for c in kids:
        _paint(img, d, c)
