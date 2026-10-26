# EntryBrowser

A fast, lightweight, from-scratch web browser engine — no Chromium, no WebKit, no Gecko. Pure Python + Pillow, works out of the box.

```
pip install pillow requests
python -m entrybrowser render https://example.com page.png
```

## What it is

EntryBrowser is a real rendering engine built from first principles:

| Stage | Module | What it does |
|---|---|---|
| Network | `entrybrowser/net.py` | HTTP fetch, redirects, gzip, on-disk cache, custom UA |
| HTML | `entrybrowser/html.py` | WHATWG-style tokenizer + tree builder: void elements, RAWTEXT (script/style), implied html/head/body, auto-closing `<p>`/`<li>`/`<td>`, entities |
| CSS | `entrybrowser/css.py` | Tokenizer, parser, selector matching (element/class/id/descendant/child), specificity cascade, `!important`, inheritance, `style=""` attrs, UA stylesheet, colors (hex/rgb/hsla/named), lengths (px/pt/em/rem/%) |
| Layout | `entrybrowser/layout.py` | Block flow, inline runs with greedy word-wrap, real font metrics (DejaVu via Pillow), margins/padding/borders, text-align, flex-row (subset), image placeholders |
| Raster | `entrybrowser/render.py` | Backgrounds, rounded corners, borders, text painting → PNG |
| JS | `entrybrowser/js.py` | Optional: runs page scripts via dukpy if installed; degrades gracefully |

## Why

- **Fast**: no Chromium. A full pipeline pass on Wikipedia (7,367 DOM nodes) is ~500 ms on 2 cores; static pages < 30 ms.
- **Light**: ~1,300 lines of readable Python. One person can understand the whole engine.
- **Out of the box**: two pip deps, no native builds, no sandbox, no GPU.
- **Research**: built as an experimental platform for layout/text/agent-rendering experiments — every stage is inspectable and repl-able.

## CLI

```
python -m entrybrowser render <url|file> out.png [--width N]   # render to PNG
python -m entrybrowser text   <url|file>                       # extract readable text
python -m entrybrowser info   <url|file>                       # title, node/box counts, stage timings
```

## Python API

```python
from entrybrowser import Tab

tab = Tab(viewport_w=1280).load("https://example.com", is_url=True)
print(tab.stats())        # dom_nodes, boxes, timings per stage
tab.render_png("page.png")
print(tab.text())         # extracted readable text
```

## Known limits (v0.1, honest)

- No tables as grids, no floats, no absolute positioning, no CSS grid.
- No images fetched/painted (placeholder boxes only).
- No JS execution by default; with `dukpy`, scripts run but there is no DOM API yet.
- Selector matching is O(rules × nodes) per element — MDN-scale stylesheets take ~600 ms in CSS parse+match.
- Inline formatting: no italics fonts selection yet (bold works), no superscript.

## Tests

```
python -m pytest tests/ -q     # 16 contract tests, incl. live example.com
```

## License

MIT
