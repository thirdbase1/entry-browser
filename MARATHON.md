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
