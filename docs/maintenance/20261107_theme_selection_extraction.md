# Theme selection UI extraction — 2026-11-07

Base: `9cd5f6a2`; clean working tree and upstream checked before editing.

## Change

Move only theme labels, selection widgets and the description/ETF chip into
`_render_image_theme_selection(themes)` in app.py. The renderer retains heading,
empty-theme handling, lazy-run guard, data loading and all calculation/display
paths. State keys, market/theme values, Korean text and provider policy are
unchanged. Keeping the helper in app.py avoids a new cross-module import contract.

## Verification

- Report gate: before 180 passed; after 208 passed, zero failures/errors/skips.
- Adjacent UI, source-flow and wait/history contracts: 186 passed.
- New 28 contracts compare immutable base UI events for both selected themes,
  all three market scopes, four metadata cases, empty themes/module availability
  and lazy-run behavior. Inlining only this helper makes all app functions AST
  identical to the base. Earlier immutable contracts normalize this exact
  extraction; golden values and baseline commits are unchanged.
- Test durations are not application performance measurements. No full Today
  Check rerun or claimed live speed improvement for this display-only extraction.

## Deployment

Commit/push and production smoke verification pending. No account data in Git.

## Next bounded task

Four-view integration review with the same tickers/date: Today Check, radar,
precision observatory and portfolio. Preserve investment rules; only fix proven
wiring errors, then finish closure regression/deployment checks.
