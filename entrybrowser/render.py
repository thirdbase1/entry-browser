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
    _paint(d, box)
    img.convert("RGB").save(out_path)
    return out_path

def content_height(box: Box) -> int:
    h = box.h
    for c in box.children:
        h = max(h, c.y + c.h)
    return int(h + 1)

def _paint(d: ImageDraw.ImageDraw, box: Box):
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
    if box.text_lines:
        st = box.style
        fam = st.get("font-family", "sans-serif")
        size = st.get("font-size", 16.0)
        bold = str(st.get("font-weight","normal")) in ("bold","bolder","700","800","900")
        color = st.get("color") or (0,0,0,255)
        path = _find_font(fam, bold)
        from PIL import ImageFont
        try:
            font = ImageFont.truetype(path, int(round(size)))
        except Exception:
            font = ImageFont.load_default()
        for text, tx, baseline in box.text_lines:
            d.text((tx, baseline), text, font=font, fill=tuple(color))
    for c in box.children:
        _paint(d, c)
