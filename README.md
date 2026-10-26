# EntryBrowser

A fast, lightweight, from-scratch web browser engine — no Chromium, no WebKit, no Gecko. Pure Python + Pillow + QuickJS, works out of the box. **v0.4.0**

## What's new in v0.4.0

Everything planned for v0.5.0–v0.8.0, shipped in one release:

- **Interactive window mode** — `entry-browser window <url>` opens a tkinter GUI shell: address bar, Back/Forward/Reload, status bar, and real click-to-navigate/click-to-interact via pixel hit-testing (spans carry their DOM node, so links are clickable; buttons/inputs are hit-testable widget boxes).
- **Form controls** — `<input>` (text/checkbox/radio), `<button>`, `<select>` (with dropdown arrow + selected option), `<textarea>` laid out with proper default sizes, painted as real widgets, sized to their labels, and exposed to JavaScript (`element.value`, `element.checked`, `element.disabled`, `focus()`/`blur()`/`click()`).
- **CSS Grid 2.0** — `grid-template` shorthand (both `'area' h … / tracks` and bare `rows / tracks` forms), `grid-template-areas` with named areas, `grid-area` placement, `minmax(a,b)`, `rem`/`min-content`/`max-content` tracks, auto-placement fallback, row spans. This is what real sites (Wikipedia's vector-2022) actually use — and it now lays out correctly.
- **CSS2.1 Appendix E paint order** — negative z-index → block backgrounds → floats → inline content → positioned z=0/auto → positive z-index.
- **Transforms** — `translate()`, `rotate()`, `scale()` parsed at layout, rasterized with alpha-composited offscreen layers.
- **Transitions/animations** — `Tab.animate(selector, prop, target, duration_ms, steps)` with smoothstep easing, per-frame relayout, optional PNG frame output.
- **Pseudo-classes** — `:hover`, `:focus`, `:active`, `:first-child`, `:last-child`, `:checked`, `:disabled` with `Tab.set_hover()`/`Tab.set_focus()` state APIs.
- **Event bubbling** — click events bubble to ancestor handlers; `element.click()` programmatically fires handlers.
- **`classList`** — `add`/`remove`/`toggle`/`contains` with automatic reflow.
- **letter-spacing** — parsed, applied to wrapping/width, and rendered per-glyph.
- **rowspan/colspan tables** — occupancy-grid table layout honoring spans, with row-height distribution.
- **Cookies + history + multi-tab** — `net.CookieJar` (Set-Cookie store, expiry, Cookie header), `Tab.goto()/back()/forward()` with session history, `Browser` class with tabs.
- **Downloads** — `Tab.download(url, path)` for http(s), data: URIs, with browser UA + cookies.
- **Devtools inspector** — `Tab.devtools()` dumps the box tree with computed styles, transforms, widget/image markers and stage timings.
- **Correctness fixes found by real-site profiling** — float-avoidance no longer shifts blocks past zero-width ghosts, `rem` units resolve, transparent backgrounds no longer paint black, zero-width tracks (`min-content`) size to content, off-canvas boxes clip safely. Full-page Wikipedia render dropped from 1.1 s to ~0.5 s while gaining all of the above.
- **53 contract tests** — grid areas/minmax, paint order, forms (layout+paint+JS), bubbling, spans tables, pseudo-classes, transforms, letter-spacing, animation, history, multi-tab, cookies, devtools, downloads, hit-testing.

## What's in the base engine (v2 → v0.3)

- **JavaScript execution** — page scripts run in QuickJS with a mini-DOM (`getElementById`, `querySelector`, `textContent`, `innerHTML`, `document.title`, `style`, `console`). DOM mutations flow straight into layout.
- **Real images + SVG** — fetched, decoded, cached, painted (relative URLs, data: URIs, parallel loading; SVG via cairosvg).
- **Full flexbox, floats + clear, absolute/fixed/relative + z-index, opacity, overflow clipping, box-sizing**.
- **Link styling** — blue + underline via the cascade; bold, italic, serif/mono, super/subscript all render with proper fonts.
- **@media queries** — min/max-width in px and em, media types (screen/print), `not` lists.
- **10–70× CSS** — rule indexing by rightmost selector key.

```
pip install pillow requests
python -m entrybrowser render https://example.com page.png
python -m entrybrowser window https://example.com
```

## What it is

EntryBrowser is a real rendering engine built from first principles:

| Stage | Module | What it does |
|---|---|---|
| Network | `entrybrowser/net.py` | HTTP fetch, redirects, gzip, on-disk cache, cookie jar, custom UA |
| HTML | `entrybrowser/html.py` | WHATWG-style tokenizer + tree builder: void elements, RAWTEXT (script/style), implied html/head/body, auto-closing `<p>`/`<li>`/`<td>`, entities |
| CSS | `entrybrowser/css.py` | Tokenizer, parser, selector matching (element/class/id/descendant/child + pseudo-classes), specificity cascade, `!important`, inheritance, `style=""` attrs, UA stylesheet, colors, lengths (px/pt/em/rem/%) |
| Layout | `entrybrowser/layout.py` | Block flow, inline runs with greedy word-wrap + per-word spans, full flexbox, CSS grid (areas/minmax/spans), floats, tables with rowspan/colspan, form widgets, transforms, absolute/fixed/relative |
| Raster | `entrybrowser/render.py` | CSS2.1 paint order, backgrounds, rounded corners, borders, widget chrome, transformed layers, text painting → PNG |
| JS | `entrybrowser/js.py` | QuickJS runtime: mini-DOM, value/checked/classList, event bubbling, timers, programmatic click |
| Shell | `entrybrowser/window.py` | tkinter GUI: address bar, nav buttons, pixel hit-testing, click-to-navigate |

## Why

- **Fast**: no Chromium. Full-pipeline Wikipedia (7,367 DOM nodes) ~0.5 s on 2 cores; static pages < 30 ms.
- **Light**: ~2,400 lines of readable Python. One person can understand the whole engine.
- **Out of the box**: two pip deps, no native builds, no sandbox, no GPU.
- **Research**: built as an experimental platform for layout/text/agent-rendering experiments — every stage is inspectable and repl-able.

## CLI

```
python -m entrybrowser render <url|file> out.png [--width N]   # render to PNG
python -m entrybrowser text   <url|file>                       # extract readable text
python -m entrybrowser info   <url|file>                       # title, node/box counts, stage timings
python -m entrybrowser window <url|file>                       # interactive GUI shell
```

## Python API

```python
from entrybrowser import Tab, Browser

tab = Tab(viewport_w=1280).load("https://example.com", is_url=True)
tab.render_png("page.png")
print(tab.text())          # extracted readable text
print(tab.devtools())      # box-tree inspector dump
tab.animate("#box", "width", 200, duration_ms=300, steps=10)
tab.set_hover("#menu")     # :hover state + relayout

br = Browser()
t1 = br.new_tab("https://example.com")
t1.back(); t1.forward()
```

## Benchmarks (1280px, live network included, 2-core box)

| Site | Time | DOM nodes |
|---|---|---|
| example.com | ~28 ms | 14 |
| MDN Web docs | ~70 ms | 1,714 |
| python.org (images) | ~260 ms | 1,855 |
| news.ycombinator.com | ~820 ms | 1,307 |
| Wikipedia full article | ~0.5 s | 7,367 |

## Tests

```
python -m pytest tests/ -q     # 53 contract tests, incl. live example.com
```

## License

MIT
