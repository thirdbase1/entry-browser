"""EntryBrowser — a fast, lightweight, out-of-the-box web browser engine.

Pipeline: net.fetch -> html.parse -> css (UA + page) -> layout -> render PNG.
CLI: entry-browser render <url|file> out.png [--width N]
     entry-browser text   <url|file>          (dump readable text)
     entry-browser info   <url|file>          (title, stats, timing)
"""
from __future__ import annotations
import time, os, sys

from .html import parse, parse_title, Node
from .css import Stylesheet, UA
from .layout import Layout
from .render import content_height
from .render import render
from . import net

class Tab:
    """One page load: everything the pipeline produces, with timings."""
    def __init__(self, viewport_w=800.0):
        self.url: str | None = None
        self.history: list[str] = []
        self._hist_pos: int = -1
        self.viewport_w = viewport_w
        self.timings: dict[str, float] = {}
    def load(self, source: str, is_url=True, css_text: str | None = None) -> "Tab":
        t0 = time.perf_counter()
        if source.startswith(("http://","https://")) or is_url:
            self.html_text, self.final_url, self.status = net.fetch(source)
        else:
            self.html_text = open(source, encoding="utf-8", errors="replace").read() if os.path.exists(source) else source
            self.final_url, self.status = source, 0
        self.timings["fetch"] = time.perf_counter() - t0
        t1 = time.perf_counter()
        self.doc = parse(self.html_text)
        self.title = parse_title(self.doc)
        self.timings["parse_html"] = time.perf_counter() - t1
        # collect page CSS
        # run scripts (JS mutates the tree; layout happens after, so mutations land)
        from .js import JSRuntime
        self.js = JSRuntime(self.doc)
        self.js.title = self.title
        self.js_logs: list[str] = []
        for script in self.doc.query_all("script"):
            code = script.text or ""
            src = script.attr("src")
            if src and src.startswith("http"):
                try:
                    code, _, _ = net.fetch(src)
                except Exception:
                    continue
            if code.strip():
                self.js.console_log = self.js_logs
                out = self.js.run(code)
                if out and out.startswith("[js error]"):
                    self.js_logs.append(out)
        if self.js.doc._mutated:
            t_after = self.doc.query_all("title")
            self.title = self.js.title or (t_after[0].text_content().strip() if t_after else self.title)
        t2 = time.perf_counter()
        css_bits = []
        if css_text: css_bits.append(css_text)
        for st in self.doc.query_all("style"):
            css_bits.append(st.text)
        for link in self.doc.query_all("link"):
            rel = (link.attr("rel") or "").lower()
            href = link.attr("href")
            if rel == "stylesheet" and href:
                url = href if href.startswith("http") else _abs(self.final_url, href)
                if url and url.startswith("http"):
                    try:
                        t, _, s = net.fetch(url)
                        if s == 200: css_bits.append(t)
                    except Exception:
                        pass
        self.stylesheet = Stylesheet.parse("\n".join(css_bits), viewport_w=self.viewport_w) if css_bits else None
        self.timings["parse_css"] = time.perf_counter() - t2
        t3 = time.perf_counter()
        self.layout = Layout(self.doc, self.stylesheet, viewport_w=self.viewport_w, base_url=self.final_url or "")
        self.root_box = self.layout.build()
        self.timings["layout"] = time.perf_counter() - t3
        t4 = time.perf_counter()
        self._load_images()
        self.timings["images"] = time.perf_counter() - t4
        return self
    def goto(self, url: str) -> "Tab":
        """Navigate to a URL, recording history."""
        html, final_url, status = net.fetch(url)
        self.url = final_url
        self.history = self.history[:self._hist_pos + 1]
        self.history.append(final_url)
        self._hist_pos = len(self.history) - 1
        self.load(html, is_url=True)
        return self

    def back(self) -> bool:
        if self._hist_pos > 0:
            self._hist_pos -= 1
            html, u, _ = net.fetch(self.history[self._hist_pos])
            self.url = u
            self.load(html, is_url=True)
            return True
        return False

    def forward(self) -> bool:
        if self._hist_pos < len(self.history) - 1:
            self._hist_pos += 1
            html, u, _ = net.fetch(self.history[self._hist_pos])
            self.url = u
            self.load(html, is_url=True)
            return True
        return False

    def set_hover(self, selector_or_id: str | None) -> None:
        """Mark :hover state on the matched node (clears previous). Relayouts."""
        for n in self.doc.walk():
            st = getattr(n, "_pseudo_state", None)
            if st:
                st["hover"] = False
        if selector_or_id:
            el_id = self.js._bridge.qs(selector_or_id) if not selector_or_id.startswith("#") else selector_or_id[1:]
            n = self.js._bridge._n(el_id)
            if n is not None:
                if n._pseudo_state is None:
                    n._pseudo_state = {}
                n._pseudo_state["hover"] = True
        self._relayout()

    def set_focus(self, selector_or_id: str | None) -> None:
        """Mark :focus state + focus ring. Relayouts."""
        for n in self.doc.walk():
            st = getattr(n, "_pseudo_state", None)
            if st:
                st["focus"] = False
        if selector_or_id:
            el_id = self.js._bridge.qs(selector_or_id) if not selector_or_id.startswith("#") else selector_or_id[1:]
            n = self.js._bridge._n(el_id)
            if n is not None:
                if n._pseudo_state is None:
                    n._pseudo_state = {}
                n._pseudo_state["focus"] = True
                if self.js is not None:
                    self.js.focused_id = el_id
        self._relayout()

    def animate(self, selector_or_id: str, prop: str, target,
                duration_ms: int = 300, steps: int = 10, out_prefix: str | None = None):
        """CSS-transition-style animation: interpolate a style property on an element
        over N steps, re-layouting each frame. Returns list of frame stats.
        If out_prefix given, each frame is rendered to <prefix>-<i>.png."""
        el_id = self.js._bridge.qs(selector_or_id) if not selector_or_id.startswith("#") else selector_or_id[1:]
        node = self.js._bridge._n(el_id)
        if node is None:
            return []
        def _num(v):
            try:
                return float(str(v).replace("px", "").strip())
            except (TypeError, ValueError):
                return None
        start = _num(node.attrs.get("style", "").split(prop + ":")[-1].split(";")[0]) if prop in node.attrs.get("style", "") else None
        if start is None:
            start = _num(self.layout.style_for(node, {}).get(prop)) if self.layout else None
        if start is None:
            start = 0.0
        unit = "px"
        frames = []
        step_dur = duration_ms / max(1, steps)
        for i in range(1, steps + 1):
            t01 = i / steps
            eased = t01 * t01 * (3 - 2 * t01)   # smoothstep easing
            val = start + (target - start) * eased
            cur = node.attrs.get("style", "")
            import re as _re
            if _re.search(rf"{prop}\s*:", cur):
                cur = _re.sub(rf"{prop}\s*:\s*[^;]+", f"{prop}:{val}{unit}", cur)
            else:
                cur = (cur.rstrip("; ") + f";{prop}:{val}{unit}").lstrip(";")
            node.attrs["style"] = cur
            self._relayout()
            info = {"step": i, prop: round(val, 2)}
            if out_prefix:
                from .render import content_height
                self.render_png(f"{out_prefix}-{i:03d}.png",
                                height=max(self.viewport_w and 0 or 0, content_height(self.root_box)))
                info["png"] = f"{out_prefix}-{i:03d}.png"
            frames.append(info)
        return frames

    def download(self, url: str, out_path: str) -> str:
        """Download a resource (image/link) to disk with browser UA + cookies."""
        import shutil, base64
        from .net import fetch as _fetch
        if url.startswith("data:"):
            header, _, payload = url.partition(",")
            out = base64.b64decode(payload) if "base64" in header else payload.encode()
            with open(out_path, "wb") as f:
                f.write(out)
            return out_path
        if url.startswith(("http://", "https://")):
            # binary-safe: use requests directly through net's session attributes
            try:
                import requests as _rq
                from .net import UA, JAR
                headers = {"User-Agent": UA}
                cj = JAR.header(url)
                if cj:
                    headers["Cookie"] = cj
                resp = _rq.get(url, headers=headers, timeout=30, stream=True)
                with open(out_path, "wb") as f:
                    for chunk in resp.iter_content(65536):
                        f.write(chunk)
                return out_path
            except ImportError:
                pass
        # local / data URI fallback: raw fetch text
        text, _, _ = _fetch(url, use_cache=False)
        with open(out_path, "w") as f:
            f.write(text)
        return out_path

    def devtools(self, max_depth: int = 12) -> str:
        """Dump the box tree with computed styles — devtools-style inspector output."""
        lines = []

        def walk(b, depth=0):
            if depth > max_depth:
                return
            nd = b.node
            tag = nd.tag if nd is not None else "?"
            ident = nd.attrs.get("id") or nd.attrs.get("class") or "" if nd is not None else ""
            pos = f"x={b.x:.0f} y={b.y:.0f} w={b.w:.0f} h={b.h:.0f}"
            extra = []
            if b.bg: extra.append("bg")
            if b.border: extra.append("border")
            if getattr(b, "is_widget", False): extra.append("widget")
            if getattr(b, "transform", None): extra.append(f"transform={b.transform}")
            if b.img: extra.append("image")
            lines.append("  " * depth + f"<{tag} {ident}> {pos} {' '.join(extra)}")
            for c in b.children:
                walk(c, depth + 1)

        walk(self.root_box)
        stats = self.stats()
        tm = stats.get("timings_ms", {})
        lines.append(f"--- {stats.get('dom_nodes')} nodes · {stats.get('boxes')} boxes · "
                     f"layout {tm.get('layout', 0):.0f} ms · parse {tm.get('parse_html', 0):.1f} ms ---")
        return "\n".join(lines)



    def click(self, selector_or_id: str) -> bool:
        """Dispatch click on an element (JS handler + onclick attr), then re-layout.
        Handlers on ancestors fire via bubbling. Returns True if the page mutated."""
        el_id = self.js._bridge.qs(selector_or_id) if not selector_or_id.startswith("#") else selector_or_id[1:]
        node = self.js._bridge._n(el_id)
        handled = self.js.fire_onclick_attr(el_id) or self.js.fire_event(el_id, "click")
        if not handled and node is not None:
            p = node.parent
            while p is not None:
                pid = self.js._bridge._id(p)
                if self.js.fire_onclick_attr(pid) or self.js.fire_event(pid, "click"):
                    handled = True
                    break
                p = p.parent
        if self.js.doc._mutated:
            self._relayout()
        return handled or self.js.doc._mutated
    def _relayout(self):
        """Re-run CSS + layout after JS DOM mutations."""
        from .css import Stylesheet
        t2 = time.perf_counter()
        css_bits = []
        for st in self.doc.query_all("style"):
            css_bits.append(st.text)
        self.stylesheet = Stylesheet.parse("\n".join(css_bits), viewport_w=self.viewport_w) if css_bits else None
        from .layout import Layout
        self.layout = Layout(self.doc, self.stylesheet, viewport_w=self.viewport_w, base_url=self.final_url or "")
        self.root_box = self.layout.build()
        self.timings["relayout"] = time.perf_counter() - t2
        t4 = time.perf_counter()
        self._load_images()
        self.timings["images"] = time.perf_counter() - t4
    def _load_images(self):
        from .images import get_image
        from concurrent.futures import ThreadPoolExecutor
        targets = []
        def walk(b):
            if b.node is not None and b.node.tag == "img" and b.w > 0:
                targets.append(b)
            for c in b.children:
                walk(c)
        walk(self.root_box)
        if not targets:
            return
        base = self.final_url or ""
        def load(b):
            im = get_image(b.node.attr("src"), base)
            if im is not None:
                b.img = (im, b.x, b.y, b.w, b.h)
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(load, targets))
    def render_png(self, out_path: str, height=None) -> str:
        t = time.perf_counter()
        h = height or max(600, content_height(self.root_box))
        render(self.root_box, int(self.viewport_w), int(h), out_path)
        self.timings["render"] = time.perf_counter() - t
        return out_path
    def text(self) -> str:
        out = []
        def walk(b):
            if b.spans:
                line, last = "", None
                for text, tx, baseline, *_ in b.spans:
                    if last is not None and abs(baseline - last) > 1:
                        out.append(line.strip()); line = ""
                    line += (" " if line and not line.endswith(" ") else "") + text
                    last = baseline
                if line.strip(): out.append(line.strip())
            for c in b.children:
                walk(c)
        walk(self.root_box)
        return "\n".join(out)
    def stats(self) -> dict:
        nodes = sum(1 for _ in self.doc.walk())
        boxes = sum(1 for _ in _walk_box(self.root_box))
        return {"title": self.title, "url": self.final_url, "status": self.status,
                "dom_nodes": nodes, "boxes": boxes,
                "content_height": content_height(self.root_box),
                "timings_ms": {k: round(float(v)*1000, 2) for k, v in self.timings.items() if isinstance(v,(int,float))}}

def _walk_box(b):
    yield b
    for c in b.children:
        yield from _walk_box(c)

def _abs(base: str, href: str) -> str | None:
    from urllib.parse import urljoin
    try: return urljoin(base, href)
    except Exception: return None

def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] in ("-h","--help"):
        print(__doc__); return 0
    cmd = argv[0]
    args = [a for a in argv[1:] if not a.startswith("--")]
    width = 800
    if "--width" in argv:
        width = int(argv[argv.index("--width")+1])
    if cmd in ("render","text","info") and args:
        src = args[0]
        tab = Tab(viewport_w=width).load(src, is_url=src.startswith("http"))
        if cmd == "render":
            out = args[1] if len(args) > 1 else "page.png"
            tab.render_png(out)
            print(out)
        elif cmd == "text":
            print(tab.text())
        else:
            import json
            print(json.dumps(tab.stats(), indent=1))
        return 0
    if cmd == "window" and args:
        from .window import run as run_window
        run_window(args[0], width=width)
        return 0
    print(__doc__)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())


class Browser:
    """Multi-tab browser with per-tab session history."""
    def __init__(self, viewport_w=800.0):
        self.viewport_w = viewport_w
        self.tabs: list[Tab] = []
        self.active: int = -1

    def new_tab(self, url: str | None = None, **kw) -> "Tab":
        t = Tab(viewport_w=self.viewport_w, **kw)
        self.tabs.append(t)
        self.active = len(self.tabs) - 1
        if url:
            t.goto(url)
        return t

    @property
    def current(self) -> "Tab | None":
        return self.tabs[self.active] if 0 <= self.active < len(self.tabs) else None

    def close_tab(self, i: int) -> None:
        if 0 <= i < len(self.tabs):
            self.tabs.pop(i)
            self.active = min(self.active, len(self.tabs) - 1)
