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
