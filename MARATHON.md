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
