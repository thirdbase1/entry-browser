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

def _paint(img, d: ImageDraw.ImageDraw, box: Box):
    if box.bg and box.w > 0 and box.h > 0:
        col = tuple(box.bg) if len(box.bg) == 4 else (*box.bg, 255)
        if box.radius and box.radius > 0:
            d.rounded_rectangle([box.x, box.y, box.x+box.w, box.y+box.h],
                                radius=box.radius, fill=col)
        else:
            d.rectangle([box.x, box.y, box.x+box.w, box.y+box.h], fill=col)
    if box.border and isinstance(box.border, dict) and box.border.get("width",0) > 0:
        bcol = box.border.get("color", (0,0,0,255))
        d.rectangle([box.x, box.y, box.x+box.w, box.y+box.h],
                    outline=tuple(bcol), width=int(box.border["width"]))
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
        img.paste(im.resize((max(1,int(iw)), max(1,int(ih)))), (int(ix), int(iy)))
        d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img)  # re-bind after paste
    for c in box.children:
        _paint(img, d, c)
