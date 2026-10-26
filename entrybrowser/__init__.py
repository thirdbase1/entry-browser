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
        self.layout = Layout(self.doc, self.stylesheet, viewport_w=self.viewport_w)
        self.root_box = self.layout.build()
        self.timings["layout"] = time.perf_counter() - t3
        t4 = time.perf_counter()
        self._load_images()
        self.timings["images"] = time.perf_counter() - t4
        return self
    def click(self, selector_or_id: str) -> bool:
        """Dispatch click on an element (JS handler + onclick attr), then re-layout.
        Returns True if the page mutated."""
        el_id = self.js._bridge.qs(selector_or_id) if not selector_or_id.startswith("#") else selector_or_id[1:]
        handled = self.js.fire_onclick_attr(el_id) or self.js.fire_event(el_id, "click")
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
        self.layout = Layout(self.doc, self.stylesheet, viewport_w=self.viewport_w)
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
    print(__doc__)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
