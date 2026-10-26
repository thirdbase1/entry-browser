"""entrybrowser.images — fetch + decode page images for the rasterizer."""
from __future__ import annotations
import io, os
from .net import fetch
from urllib.parse import urljoin

_decoded: dict[str, object] = {}

def get_image(src: str, base_url: str = "", timeout=10):
    """Return a PIL.Image for src (http/https/data/file), or None. Cached in-process."""
    if not src or src.lower().split("?")[0].endswith(".svg"):
        return None
    if src.startswith("data:"):
        import base64
        try:
            b64 = src.split(",", 1)[1]
            data = base64.b64decode(b64)
        except Exception:
            return None
    else:
        if not src.startswith("http") and base_url:
            src = urljoin(base_url, src)
        if not src.startswith("http"):
            # local file
            try:
                from PIL import Image
                return Image.open(src).convert("RGBA")
            except Exception:
                return None
        if src in _decoded:
            return _decoded[src]
        try:
            body, _, status = fetch(src, timeout=timeout)
            if status != 200:
                return None
            import requests as _r
            # fetch() decodes text — need raw bytes; refetch raw:
            import requests
            resp = requests.get(src, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"},
                                timeout=timeout)
            data = resp.content
        except Exception:
            return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        if src.startswith("http"):
            _decoded[src] = im
        return im
    except Exception:
        return None
