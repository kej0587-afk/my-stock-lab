# Decision SMC context extraction — 2026-11-07

## Scope

Started clean/equal to origin/main at `11565166` after fetch. Existing home work
and retained baselines preserved. Extracted only SMC context assembly from
`calc_scores_and_decision` into `decision_smc.build_decision_smc_context`.
Explicit dependencies preserve original labels, structure events, liquidity,
FVG, premium/discount, action and insight. All ten original locals are restored
before the remaining decision pipeline and unchanged result assembly.

No detector, drawing, investment rule, threshold, amount, provider or TTL changes.
The helper registers its actual loaded-source hash in precision provenance.
Main function: 467 -> 463 lines. The value is isolating one responsibility, not
line-count reduction or measured speed improvement. Avoid continuing tiny
extractions solely to shorten this now mostly orchestration function.

## Verification

Installed `.venv311/Scripts/python.exe`; no golden files regenerated.

- Before decision gate: 1,132 passed, 93.962s (`decision_x72a4d3l`).
- Frozen before editing: 20 complete deterministic scenario outputs in ignored
  `cache/decision_smc_before.json`.
- Focused SMC/follow-up/priority/import tests: 174 passed, 30.20s.
- Final decision gate: 1,171 passed, 95.224s (`decision_erg4pcl8`; includes 39 new tests).

New contracts compare every unrounded result against original Git `11565166`,
exact dependency order, frame/attrs/levels nonmutation and the pre-edit capture.
Nine real-detector inputs include normal/up/down, NaNs, short/empty/single-row,
missing column and missing level cases. Seven injected dependency failures
verify identical exception propagation and no retry. Structural tests preserve
every original expression, explicit argument wiring and all ten output slots.
Two provenance cases cover loaded and stale source hashes.

The preceding finalization AST reference now restores only this SMC block before
its original comparison; the new independent test compares the complete current
function to `11565166` after normalizing just the SMC block. Older goldens remain.

## Deployment

Code commit `051ac66c` pushed. Authenticated production GOOGL calculation completed
at approximately 01:20 KST. The SMC detail panel displayed structure, liquidity,
FVG, PD and insight without traceback. Review export
`C:/Users/82amf/Downloads/precision_review_GOOGL (28).zip` confirms new helper
loaded hash = disk hash = local hash:
`a4a89437853071bbc76d60053b09e9377c07aeb2e0ee2e4f79a880209caa142d`.
Manifest: `restart_required=false`, `stale_modules=[]`.
Screenshot: `C:/Users/82amf/Downloads/stock_lab_smc_verification_20261107.jpg`.
This is a deployment/calculation smoke check, not a same-input live comparison.
No holdings/watchlist values edited. Private exports stay outside Git.
Selected regression coverage is not a full-suite, backtest or independent
market-data accuracy audit.

## Next bounded task

Measure one complete current-build Today Check run with its matching profile ID.
Separate wall time, self time, nested/parallel cumulative time, request counts and
cache state. Identify the dominant actionable bottleneck from that evidence.
Do not treat invocation counts as requests or these refactor test timings as
application speed gains; do not alter TTLs, investment rules or portfolio data.
