# Theme stock display extraction — 2026-11-07

## Scope and preservation

Started on clean main equal to origin/main at `340fe067` after fetch. Code commit
`7f7e2e4a` is pushed. User/home baseline and existing private snapshots preserved.
Only the already classified/ordered stock table formatting was moved from
`render_image_theme_flow_section` into `prepare_theme_stock_display` in the
existing pure `theme_flow_view` module. Renderer: 489 -> 452 lines.

The helper retains currency/percent formatting, state badges, missing optional
column behavior, column/row order and original input. Classification, dedup,
rankings, charts, captions, selection/watchlist actions, providers, TTLs and
investment rules were not changed. The entire renderer AST matches the prior
version after normalizing only this block and its dataframe argument.

The app narrowly reloads this stateless formatting module only when the newly
introduced helper is absent from a retained module. Tests cover both fresh and
retained-old imports. No provider caches/session state are reloaded.

## Verification

Installed `.venv311/Scripts/python.exe` used; no golden files regenerated.

| Check | Before | After |
|---|---:|---:|
| Selected report gate | 180 passed, 7.694s | 180 passed, 7.240s |
| Flow UI/renderer/table tests | 19 passed, 27.13s | 40 passed, 40.40s |
| Pre-edit stock tables | 18 frozen | 18 exact matches |

The extra tests cover six fixture types across three incoming sort modes:
mixed KR/US, all-empty optional fields, minimal columns, nullable numerics,
empty table and reversed columns/rows. They check exact DataFrame and CSV,
nonmutation, renderer wiring and the import guard. Old group tests remain.
References: stock Git `340fe067`; group Git `612ab8c4`.

Ignored evidence: `cache/theme_stock_before.json`,
`cache/refactor_checks/report_u5_t2zfv/summary.json`, and
`cache/refactor_checks/report__8qpu20t/summary.json`.
These test durations are not app latency measurements. No speedup claimed.

## Deployment and UI

Code pushed to main. Authenticated production stock table was inspected before
push, then reloaded and the theme source analysis rerun after push. Production
showed 46/46 instruments, summary/chart and stock table without traceback.
KRW integer prices, USD two-decimal prices, percent columns and badges rendered.
This was a UI smoke check with changing live inputs, not exact live-value parity
or independent market-data accuracy verification. No account/watchlist edits.
Offline CSV equality is proven; browser CSV completion and helper runtime hash
were not collected. Private screenshot outside Git:
`C:/Users/82amf/Downloads/stock_lab_theme_stock_table_20261107.jpg`.

## Next bounded task

`calc_scores_and_decision` is now the largest top-level app function (480 lines).
Extract only its final safety/sizing orchestration, preserving all outputs and
locals required by result assembly. Exact scope and contracts are in HANDOFF.md.
