"""entrybrowser.net — fetcher with its own UA, redirect following, and caching."""
from __future__ import annotations
import hashlib, os, gzip, zlib
try:
    import requests
except ImportError:
    requests = None

UA = "Mozilla/5.0 (X11; Linux x86_64) EntryBrowser/0.1 (+https://github.com/thirdbase1/entry-browser)"
CACHE_DIR = os.path.expanduser("~/.cache/entry-browser")

def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha256(url.encode()).hexdigest())

def fetch(url: str, timeout=15, use_cache=True) -> tuple[str, str, int]:
    """Return (body_text, final_url, status). Cache successful GETs on disk."""
    if not requests:
        raise RuntimeError("requests not installed; pip install requests")
    if use_cache and os.path.exists(_cache_path(url)):
        raw = open(_cache_path(url), "rb").read()
        if raw[:4] in (b"\x1f\x8b\x08\x00", b"\x1f\x8b"):
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace"), url, 200
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "text/html,*/*"}
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    body = resp.content
    if resp.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
        try: body = gzip.decompress(body)
        except Exception: pass
    if use_cache and resp.status_code == 200 and "no-store" not in resp.headers.get("Cache-Control",""):
        try: open(_cache_path(url), "wb").write(body)
        except Exception: pass
    text = body.decode(resp.encoding or "utf-8", "replace")
    return text, resp.url, resp.status_code
