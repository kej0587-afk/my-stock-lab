# Precision: three reviewed correctness fixes

Base: `768ceb5c`. Scope approved 2026-11-13 KST.

## Changes

- Recovery: unavailable RS labels no longer count as recovery. Missing/nonfinite
  underlying 1W or R/R cannot open leverage timing tranches; show unavailable
  inputs and zero proposed tranche weights. Known-input thresholds unchanged.
- Chart guide: a support/channel lower line above current price is a broken
  recovery reference, not a current pullback support. Geometry is unchanged.
- Structural 1R: use first planned entry plus (planned entry minus stop), capped
  by the existing target. The condition text uses that same entry. Existing
  targets, stops, entry selection, allocations and ATR projection rows unchanged.
  Actual fills/additional entries require risk recalculation; this is a plan.

No orders, holdings, target weights, market thresholds, scoring formulas,
provider/session inputs or channel construction rules changed.

## Verification

- New missing/channel regressions reproduced the defects before production edits.
- Baseline decision tests: 1367 passed (119.75s); wrapper correctly refused its
  evidence because regression tests were being added during that baseline run.
- Final decision gate: 1369 passed, no failures/errors/skips, wrapper PASS;
  133.897s. Evidence: ignored `cache/refactor_checks/decision_zkxg8xv3`.
- Focused precision/product/build coverage: 197 passed (23.66s).
- Immutable base comparison: 960 available-input timing combinations returned
  exactly identical complete outputs (four profile keys, held/unheld, R/R
  boundaries, positive/zero/negative underlying returns, recovery and heat).
- Historical broad AST contracts explicitly recognize only approved full-function
  fingerprints. Other edits are still exposed to old equality assertions; new
  behavior has independent regression tests. Historical baselines not regenerated.
- Local real Streamlit renderer: missing inputs show hold and zero tranches;
  broken lower line is a recovery reference; synthetic entry 97.50, stop 90.00
  produces first take-profit 105.00, with the same entry in its explanation.

These are test runtimes, not a claim of application speed improvement.
Code pushed: `70ad0493`. Cloud post-push verification at 14:09-14:10 KST:

- SOXL completed precision view: planned entry 61.69, stop 39.78, first
  take-profit 83.60. Its condition explicitly uses planned entry 61.69.
  Existing leverage market-defense execution hold is still present.
- NVDA completed precision view: broken channel lower 182.16 appears under
  recovery reference, not pullback support. Separate lower liquidity support
  remains visible. Existing higher-timeframe damage and buy block remain.
- Missing-input state was verified with synthetic local renderer inputs, not
  injected into production data. No account settings or positions changed.
- No Cloud reboot was required. Screenshots are private ignored cache files;
  account screenshots are not committed.

## Next Bounded Task

After deployment verification, review proposed SOXL strategy improvements
separately from these bugs. Do not change thresholds or adopt quarter-channel
signals without a distinct testable strategy specification and approval.
