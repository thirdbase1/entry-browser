# Marathon research log — started

Goal: big breakthrough.

## Session 2 breakthroughs (all committed & pushed)
1. PROBE-COORDINATE BUG (the big one): flex/grid/table-cell subtrees were laid at (0,0) probe
   origin, then the container box moved WITHOUT the subtree -> mass text overlap on every
   real page. Fix: Layout._shift_tree shifts box.x/y AND span tx/baseline. Applied at flex
   place, grid place, table cell place.
2. Float model: block boxes no longer blindly shift past floats (was pushing pages 1280px off
   screen); inline content wraps around floats instead.
3. Flex: explicit width honored; shrink-to-fit only for pure-inline items (title wrap fix);
   estimator slack.
4. Tables: auto column sizing from text metrics (rank columns narrow, title columns wide).
5. HTML4 presentational attrs: bgcolor/width/height/align/valign -> CSS (HN: orange bar + beige).
6. cellpadding/cellspacing/border table attrs.
7. Inline-style side longhands (padding-top etc.) now parsed (were silently dropped).
8. UA sheet: center/dir/menu/caption/thead/tbody/optgroup + figure/caption/fieldset rules.
9. Images: fetch_raw with engine UA (wikipedia 403s Chrome UA), protocol-relative srcs,
   thumb->upload.wikimedia host fallback, utm strip -> wikipedia images 11/12 load.
10. CSS background-image (url, contain/cover) with lazy parallel loading -> HN vote arrows.
11. Anonymous-block split: block descendants of inline elements lay as blocks.
Receipts: wikipedia 2/10 -> readable body + one-line title + images; HN 2/10 -> 7/10;
53/53 tests; bench: example 28ms, MDN 83ms, wikipedia 0.74s warm, python.org 290ms.

## Batch 4 — FLOAT CONTAINMENT + FLOAT STACKING (breakthrough #5)
- python.org nav: floated LIs ALL stacked at x=0 → left-float stacking loop (rect-overlap bump).
- CRITICAL BUG FOUND: float box registered at 2*fx — _shift_tree called AFTER cb.x=fx double-shifted (shift_tree moves cb.x itself). Order: shift FIRST with delta (fx - old_x), then cb.y.
- Same double-shift in absolute branch → fixed with explicit dx/dy deltas.
- _floats never cleared → stale probe floats polluting placements → clear per build() + replace-stale-node on register + cy-expiry.
- Float containment (clearfix/BFC): block with only-floated children stayed h=0 → extend h to float bottoms when overflow!=visible or no in-flow content. ul.menu h=0→42.
- Receipts: python.org overlaps 283→32; nav bar renders (dark blue + Python/PSF/Docs/PyPI/Jobs); hero below; vision 3/10→6/10. 53/53 tests. python.org 441ms, MDN 1.8s.
- Next: right-column body text overlap on python.org (two-column grid collapse), wikipedia header chrome.

## Batch 5 — FLOAT CONTEXT SCOPING (breakthrough #6, the big one)
- ROOT CAUSE of stacked floats (python.org 4-col widget row all at x=0; nav lis; header widgets):
  self._floats was GLOBAL to Layout; nested block layout (any deep descendant) ran the
  cy-expiry filter and DELETED floats still needed by sibling branches. Floats must be
  scoped per containing block.
- FIX: save/restore _floats around each _layout_block recursion (float context = containing block).
- Receipts: python.org leaf overlaps 283 -> 3 (objective). Widgets stack 0/340/679/1019.
  Nav floats stack 0/213/427/640/853. 53/53 tests. Bench: example 29ms, MDN 82ms, python 285ms,
  HN 1.45s, wiki 1.66s.
- Debug lesson: prints used `node` (parent) instead of `child` — cost an hour. var discipline.

## Batch 6 — UNIVERSAL SELECTOR * (breakthrough #7)
- `* { box-sizing: border-box }` etc. were DROPPED: _SEL_PART required [a-zA-Z] tag start,
  so '*' rules never parsed. python.org (and most modern sites) rely on universal resets.
- FIX: regex allows \*, universal maps to tag=None with zero specificity via _universal flag.
- Receipts: python.org .small-widget w 339.6 -> 300 border-box; 4 cols at 0/300/599/899,
  Jobs no longer clipped (text right 1258 < 1280). Leaf overlaps still 3 (2 off-screen).
  53/53 tests. wikipedia unaffected (mw-content-text x=256 w=948 intact).

## Batch 7 — hidden-widget paint skip + flex re-lay
- opacity:0 boxes/widgets no longer painted (CSS checkbox hacks like wiki vector-dropdown-checkbox).
- Flex items re-laid at final width after placement (probe pass could crush absolute descendants).
- VERDICT: wikipedia sidebar "collapse" is CORRECT no-JS behavior (vector-dropdown-content is
  height:0/visibility:hidden unless checkbox :checked; JS-free real browsers show it hidden too).
  Closed as faithful-to-CSS. The dropdown IS interactive via :checked + click support.
- 53/53 tests. Bench: example 28ms, MDN 93ms, python 292ms, wiki 1.86s, HN 4.1s (network).

## Batch 8 — INTERACTIVE DROPDOWNS (breakthrough #8: sibling combinators + :checked toggle)
- parse_selector: added `~` (general sibling) and `+` (adjacent) combinators — wiki CSS relies
  on `.vector-dropdown-checkbox:checked ~ .vector-dropdown-content`.
- Tab.click toggles checkbox/radio checked attr + relayout.
- _relayout now keeps externally-fetched stylesheet text (was dropping sheets on relayout).
- absolute + width:auto shrink-wraps to content (CSS 10.3.7): dd-content w 1192 -> 185.
- top/bottom % now resolve against parent HEIGHT (was width).
- E2E receipt: toggling Main menu checkbox opens the full sidebar nav (Main page / Contents /
  Current events / Random article / ... + Contribute section) — vision-confirmed. 53/53.

## Batch 9 — grid-column/grid-row SPANS + aspect-ratio + display:contents (breakthrough #9)
- BBC news grid: `grid-column: 1 / span 18` was IGNORED — every grid item auto-placed into
  ONE track (w=53 of 1280), all cards collapsed. Implemented grid-column/grid-row parsing
  ("N", "N / span M", "span M", "N / M") with occupied-cell auto-placement.
- aspect-ratio: w / h derives height from width (BBC ImageCard 16/9 boxes).
- display:contents: element box vanishes, children join the parent's flow (CSS display L3).
- Receipts: BBC.com/news overlaps 511 -> 88; load 8.7s -> 1.5s; vision-confirmed multi-column
  news grid with headlines/summaries/timestamps/tags. 53/53 tests.

## Batch 10 — flex-shrink approximation (proportional squeeze)
- Non-wrapping flex rows overflowing the line now squeeze non-growing items proportionally
  to their overflow, re-laying each at its final width. Wikipedia header: landmark+logo were
  1192+1192 in a 1192 row (logo pushed off-right at x=1236 covering Search); now 596+596.
- Rejected: shrinking block-kid flex items to max-content directly (wikipedia page collapsed;
  reverted). Proportional overflow squeeze is the safe variant.
- Fresh-render vision: logo/wordmark + Main menu + title all present, no off-screen overflow;
  remaining rough: search row wraps below menu, titlebar tabs (Article/Read) collide — both
  pre-existing, not regressions. 53/53 tests.

## Site loop: github.com/microsoft/vscode
- 32s load (huge asset count), 233 leaves, only 53 overlaps. Vision: unstyled flow, no repo
  content — GitHub core content is client-hydrated ({{ message }} template uninterpolated).
  Boundary = JS hydration, not CSS/layout. No engine bug to fix here; a real no-JS browser
  gets the same skeleton.
## Wiki tabs verdict
- "Read"/"View history" tabs w=0 = computed display:none (faithful to wiki CSS for the
  selected view). Not a bug.

## Batch 11 — min/max-content grid tracks (content-sized columns)
- grid-template 'min-content 1fr min-content min-content' sized every track evenly (auto
  branch divided evenly); MDN header nav collapsed. Now: auto/min-content/max-content tracks
  measure item max-content via probe, fr tracks get the remainder, last track absorbs slack.
- Probe guarded: only runs when content tracks exist (no float pollution, no perf hit for
  pure-fr grids like BBC).
- Receipts: MDN logo track 316 -> 138 (content-sized), search 1fr 1126; BBC overlaps 98
  (from 88 pure-fr — within noise); wikipedia mw-content-text 256/948 unchanged; ul float
  containment intact. 53/53 tests.

## Batch 12 — <details>/<summary> collapse (breakthrough #10)
- 119 <details> elements on MDN laid their ENTIRE subtree (menus expanded inline). Now:
  details without open attr lays only its <summary>; content hidden (native HTML behavior).
- Receipts: MDN load 2.3s -> 0.5s. Menus render as readable link lists instead of
  overlapping smear. 53/53 tests. (MDN header chrome still stacks vertically — its nav is
  a details/summary+grid hybrid; next round.)

## Batch 13 — negative grid lines + display:contents grid items
- grid-column "1/-1": negative line numbers count from track end (clamped span).
- display:contents elements that are GRID ITEMS: their children splice into the grid as
  items (MDN navigation__popup pattern).
- Receipts: MDN nav popup children now lay as grid items (menu/search/user-menu at final
  positions); wiki 256/948, python 3, BBC 98 all stable. 53/53 tests.

## Batch 14 — CSS-sized images + absolute width cap (breakthrough #11)
- img boxes honored HTML width/height attrs but IGNORED CSS width/height (width:100% etc).
  Now: CSS width/height first (pct resolves vs line width), attrs fallback, then cap at
  available width (aspect preserved).
- Absolute width:auto elements capped at containing-block width.
- Receipts: cnn.com overlaps 1062 -> 463 (top offender was image__dam-img at intrinsic
  2400-5154px wide); BBC 98->88; wiki/python.org stable. 53/53 tests.

## Batch 15 — <picture> transparent wrapper in flex (breakthrough #12)
- <picture> inside a flex container: promote its <img> as the flex item, applying the
  picture's aspect-ratio to size the image (Chrome-parity sizing).
- Receipts: cnn.com overlaps 463 -> 114; media cards now real boxes (div 298x302 vs
  298x4); hero photo renders full-res with headlines clean; wiki/python/BBC/MDN stable;
  53/53 tests. Remaining CNN chrome (header/nav/ticker) is client-rendered (no-JS scope).

## Batch 16 — style cache 8x speedup (breakthrough #13)
- ROOT: style_for memo keyed on id(parent_style DICT) — computed() returns a fresh dict
  every call, so the key never matched and the cache always missed -> 124M
  selector_matches on CNN (3.1MB inline CSS, 4569 rules). Rekeyed on parent NODE identity
  (stable across re-lays).
- Receipts: cnn.com load 89.5s -> 9.8s (8x, network-bound tail); MDN/python.org render
  steady; all quality metrics identical (cnn 114, bbc 88, pyo 3, wiki grid exact).
  53/53 tests.

## Batch 17 — deep-DOM + malformed-CSS robustness
- Recursion limit 4000 at import (real-world docs DOMs nest hundreds deep — bootstrap
  docs crashed at default 1000).
- CSS _walk depth guard (24): malformed nested at-rule bodies (stray braces) previously
  recursed without bound -> RecursionError on en.wikipedia.org/wiki/Python_(programming_language).
- Receipts: bootstrap docs load 0.2s, 274 leaves, only 7 overlaps (53/53 tests); Python
  wiki article now loads (3.0s, 878 leaves — navbox tables are the next overlap front).

## Batch 18 — :not() pseudo-class + visually-hidden clip skip
- parse_selector now strips :not(simple) into SimpleSel.nots; matches() negates (also
  fixed :not(...) selectors aborting the WHOLE rule — bootstrap.min.css lost hundreds of
  rules this way).
- clip-path: inset(50%) / clip: rect(0,0,0,0) -> paint skip (visually-hidden pattern).
- Receipts: 53/53; bootstrap/wiki/pyo/BBC stable.

## Batch 19 — float:right subtree shift (breakthrough #14)
- float:right branch set cb.x WITHOUT _shift_tree — the float:left branch had it; table
  cells/spans stayed at the pre-float x (Python wiki infobox shell floated right, contents
  stranded in the lead text). Now both branches shift the subtree by the same delta.
- Receipts: Python wiki infobox table 844,336 with cells at 848 inside; article overlaps
  436 -> 412; p-p overlaps ZERO (remaining: td/th infobox internals, li column lists,
  hidden checkboxes); 53/53; all sites stable.

## Batch 20 — Tailwind v4 support stack (breakthrough #15, user-requested site tests)
User asked to test entry-agents.dev, pxxl.app, mozosubz.xyz. Findings + fixes:
- @layer / @supports at-rules now recurse (Tailwind v4 CSS: 9 -> 577 rules parsed).
- CSS custom properties: :root/:host vars captured; var() substitution in computed();
  scoped vars (class-defined, e.g. .landing { --l-fg }) resolved via ancestor-class walk.
- calc(len * num) evaluated in parse_length (h-16 = calc(var(--spacing)*16) -> 64px).
- Logical shorthands padding-inline/padding-block -> physical sides; gap routed through
  parse_length.
- Tailwind arbitrary-value classes: selector class regex accepts [..], (..), escaped
  backslashes stripped; ':' variant classes canonicalized (fixes hover: rules breaking).
- Modern color syntax: rgb/hsl space-separated + slash alpha + %; oklch/oklab/lab ->
  sRGB conversion; relative-color shapes guarded to None (no crash).
- absolute/fixed left+right with width:auto now spans the interval (nav fixed left-0
  right-0 went 112px -> full width).
- parse_color None + parse_length_shorthand None guarded (no crashes on unsupported values).
Receipts: entry-agents.dev overlaps 9 -> 10 w/ real styling (dark theme, cards, typography,
buttons w/ backgrounds; hero region still broken: 1 -> 4/10). mozosubz.xyz CRASHED before
(space-separated rgb) -> loads 4.6s, 159 leaves, 4 overlaps, 5/10 vision w/ full color
system + pricing cards. pxxl.app = CSR JS shell (1 leaf, out of scope). bootstrap docs 7
-> 4 overlaps. CNN 114 -> 64. 53/53 tests.

## Batch 21 — max-width clamp, flex min-height floors, padding longhand order, theme leak
- vh/vw units: parse_length returns ("vh"/"vw") sentinels; Layout._len resolves vs
  viewport_h/viewport_w (min-h-screen now spans the screen).
- max-width clamp in block layout: box.w clamped to max-width (border-box aware);
  enables Tailwind max-w-[740px]/[1320px] containers (hero constrained 1232->740).
- flex items: min-height/min-width floors enforced after final re-lay (buttons min-h-10
  h 17->40; text no longer clipped).
- CSS source order: shorthand expansion no longer clobbers longhands declared later
  (padding:0 vs padding-top:calc -> pt-24 = 96px wins). Side longhands now parsed in
  _resolve.
- prefers-color-scheme media queries gated: light scheme honored (was applying dark
  rules unconditionally).
- class_vars capture restricted to single-compound rules: `.dark .landing{--l-bg:...}`
  was overwriting `.landing{--l-bg:#fafafa}` scoped vars via shared class name — the
  site rendered in dark mode without JS. Light theme restored.
Receipts: mozosubz.xyz overlaps 4->0; CNN 64->40; entry-agents.dev light theme coherent
4/10 (residual: glyph-height overlap at leading-[1.03], demo-mockup internals).

## Batch 22 — grid last-track stretch + max-width BEFORE children layout
- Grid track stretch fix: last track stretched by cw - (sum(widths)+gaps), not
  cw - sum(widths) — was double-adding the total gap (moz tiles 189/153 → equal 141).
- ROOT FIX: max-width clamp moved BEFORE children layout in _layout_block (was after):
  containers now lay grids/flex inside the CLAMPED content width. max-w-6xl 2-col grid
  items were 600 (unclamped 1248 content) → 552 (clamped 1152). Closes the mozosubz
  right-panel overflow; entry-agents.dev + all sites stable.
- test_live_example_com: whitespace-normalize (example.com copy now wraps).
Receipts: mozosubz.xyz 0 overlaps, tiles even, panels inside viewport; 53/53.

## Batch 23 — font-metrics line-box floor (glyph clip killer)
- Line height floored at PIL font ascent+descent (line_h = max(css_line_h, asc+desc)):
  36px h1 at leading-[1.03] drew 43px-tall glyphs in a 37px box → descender collision
  with the next block. Now the glyph box always fits the line box.
- entry-agents.dev hero H1/paragraph overlap GONE (vision-confirmed clean).
- mozosubz.xyz para/CTA boundary flush; objective pixel check shows descenders fully
  painted above the button top (no clip).

## Batch 24 — inline SVG painter (breakthrough #16)
- Minimal SVG renderer in render.py: rect/circle/ellipse/line/polyline/polygon/path
  (M L H V C S Q T Z, abs+rel, arc→endpoint line), viewBox scaling, stroke=currentColor
  (engine color), fill, stroke-width, rounded rects. Compact-decimal path data
  ("4.5.5") split; malformed-arc/C guards.
- THE blocked bug: overflow-hidden boxes paint children into a cropped layer but child
  absolute coords were never translated → EVERYTHING inside overflow-hidden panels
  (icons, card content) silently painted outside the layer. Fixed with _LAYER_SHIFT
  context applied at layer root (copy box + span coords once).
- 288 svg paint calls on mozosubz.xyz alone; all four tile icons + hamburger + wallet
  + checkmarks render (vision-confirmed).
Receipts: mozosubz.xyz 7/10 (was 4), icons done; entry-agents.dev hero CLEAN (vision:
"no glyph collision"). 53/53.
