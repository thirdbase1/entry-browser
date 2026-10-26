# EntryBrowser

A fast, lightweight, from-scratch web browser engine — no Chromium, no WebKit, no Gecko. Pure Python + Pillow + QuickJS, works out of the box. **v0.3.0**

## What's new in v0.3.0

- **Full flexbox** — row/column, wrap, gap, justify-content (start/center/end/space-between), align-items, flex-grow distribution.
- **CSS Grid** — `grid-template-columns` with `repeat(N, 1fr)`, px and auto tracks, gap, source-order placement.
- **Floats** — left/right floats with text wrap-around, block-level float avoidance, and `clear`.
- **Positioning** — `absolute` (top/left/right/bottom incl. %), `fixed`, and `relative` offsets; `z-index` paint ordering; `opacity`; `overflow: hidden` clipping; `box-sizing: border-box`.
- **SVG rendering** — inline SVG images decoded via cairosvg and painted (data: URIs verified).
- **JS events + timers** — `addEventListener`, `onclick` attributes, `Tab.click(selector)` with automatic re-layout, `setTimeout`/`setInterval` dispatch.
- **List markers** — disc bullets and ordered numbering painted per `list-style-type`.
- **Style cache** — per-node computed-style memoization across the layout pass.
- **33 contract tests** — flex, grid, float+clear, absolute positioning, click-reflow, timers, SVG, border-box, overflow clipping.

## What's new in v2

- **JavaScript execution** — page scripts run in QuickJS with a mini-DOM (`getElementById`, `querySelector`, `textContent`, `innerHTML`, `document.title`, `style.color/background-color`, `console`). DOM mutations flow straight into layout.
- **Real images** — fetched, decoded, cached, painted into the page (relative URLs, data: URIs, parallel loading).
- **Link styling** — blue + underline via the cascade; bold, italic, serif/mono, superscript/subscript all render with proper fonts.
- **Table grids** — table/tr/td/th render as bordered grids with header rows.
- **@media queries** — min/max-width in px and em, media types (screen/print), `not` lists. Desktop/mobile CSS switching works.
- **10–70× faster CSS** — rule indexing by rightmost selector key. MDN page: 614 ms → 8.8 ms CSS parse+match; full Wikipedia article renders in ~0.7 s including images.

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

## Benchmarks (1280px, live network included, 2-core box)

| Site | Time | DOM nodes |
|---|---|---|
| example.com | 27 ms | 14 |
| MDN Web docs | 72 ms | 1,714 |
| python.org (images) | 250 ms | 1,855 |
| news.ycombinator.com | 820 ms | 1,307 |
| Wikipedia full article | 1.1 s | 7,367 |

## Known limits (v0.3, honest)

- Complex multi-column magazine layouts (heavy float+abs compositions, e.g. Wikipedia sidebars) can overlap.
- JS: no event bubbling model, no DOM event objects, timers fire manually via `run_timers()`.
- Wikimedia image hosts rate-limit some fetches (429) — host-side, not engine-side.

## Tests

```
python -m pytest tests/ -q     # 16 contract tests, incl. live example.com
```

## License

MIT
