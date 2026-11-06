# Final decision safety/sizing extraction — 2026-11-07

## Scope

Started from clean main equal to origin/main at `c623569b` after fetch.
Code commit `fd0fe52e` pushed. No home/user work discarded.

Moved only the final safety/sizing orchestration from `calc_scores_and_decision`
into `stock_lab_core/decision_finalization.py::finalize_decision_sizing`.
The caller passes explicit inputs and the same policy callables, then receives
decision_outcome, dec, col, buy_amount and sizing_hint back into the same locals.
`build_decision_result(locals())` remains unchanged. Function: 480 -> 467 lines.

Order preserved: safety override, holding translation, non-core panic guard,
indicator-data error override/zero amount, final label/color, sizing hint.
No thresholds, Korean labels, rounding, ETF/core-DCA exceptions, provider calls,
TTL, caches or portfolio values changed. New module is directly imported and
registers its real loaded-source hash in existing precision provenance.
This is structural work; no application speedup claimed.

## Verification

Installed `.venv311/Scripts/python.exe` used.

| Check | Result |
|---|---|
| Before selected decision gate | 1,045 passed, 88.583s |
| Pre-edit full-output capture | 40 passed, 16.32s |
| Initial focused finalization/follow-up/priority/import checks | 215 passed, 30.48s |
| Final selected decision gate, including 87 new tests | 1,132 passed, 93.431s |
| Whitespace check | passed |

Immutable baseline is Git `c623569b`; no golden files regenerated. Twenty
existing representative scenarios, each with and without indicator-data error,
were captured before changing the caller. All forty outputs match after
extraction. Unrounded results are compared against the retained original
function, including frame nonmutation and policy call order.

Thirty-eight final-stage cases additionally cover RED, held/new positions,
individual/ETF/core-DCA, panic, sizing boundary 1%p, KR/US currencies, zero inputs,
None outcome and data-error precedence. Tests also verify failure propagation
without retries, exact original AST expressions, explicit call wiring and
loaded/stale module provenance. The prior AST suites reconstruct only this
extracted block; independent tests compare its complete body to the old code.

Private/ignored evidence:
- `cache/decision_finalization_before/` (40 synthetic result JSONs)
- `cache/refactor_checks/decision_6jrm0b8j/summary.json`
- `cache/refactor_checks/decision_kj1hs25m/summary.json`

## Deployment

Code pushed to main. Authenticated production reload and GOOGL precision
calculation completed at approximately 01:10 KST, without traceback. The displayed
technical judgement and execution-hold table rendered. Downloaded
`C:/Users/82amf/Downloads/precision_review_GOOGL (27).zip` includes the new helper:
loaded hash = disk hash = local hash
`d453639ee8802da2d64731a526b50f96552caaca5b7fd9a79c17226dafd5ce8b`.
Manifest reports `restart_required=false`, `stale_modules=[]`.
Screenshot: `C:/Users/82amf/Downloads/stock_lab_decision_finalization_20261107.jpg`.
Private exports remain outside Git; no holdings/watchlist values edited.
This is one live calculation/deployment smoke check, not same-input live parity.
This selected gate is not the entire repository suite, a backtest, or an
independent live-market data accuracy audit.

## Next bounded task

Extract only the SMC context assembly from `calc_scores_and_decision`, from
`smc_structure_labels = build_smc_structure_labels(...)` through `smc_insight`.
Keep structure/FVG/liquidity detection algorithms unchanged and preserve calls,
order, outputs and result locals. See HANDOFF.md for the single next task.
