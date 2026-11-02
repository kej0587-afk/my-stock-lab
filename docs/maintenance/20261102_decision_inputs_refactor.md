# Decision Price And Technical Inputs

## Scope

Baseline: `01c5a522d75c59ce5a43c5e4dda5da1574c1cff9`.
`calc_scores_and_decision` shrinks from 501 to 480 lines. Only its price and
technical-input preparation moves to `stock_lab_core/decision_inputs.py`.

- `prepare_decision_price_inputs`: original close capture, live indicator
  preparation or copied precomputed frame, short-frame handling, current price,
  return windows and daily/live return selection.
- `prepare_decision_technical_inputs`: trend, MACD, RSI/MFI/%B, RS/slope,
  squeeze status and component scores. Provider-dependent callbacks remain
  explicit and keep their original order and count.
- Reuse the already selected last row for fallback close and the already read
  MACD values for the direction label. No network-call or caching optimization
  is claimed. No extra data lookup or cross-calculation cache is introduced.

## Preserved Contracts

No change to providers, source dates, return windows, live/prepared-frame
semantics, missing-value behavior, thresholds, scoring, policy precedence,
reason text, sizing, amounts, share calculations or screen rendering.
The original source closes are still read before live overlays. Prepared frames
are still deep-copied. Indicator failures still disable the live price and
reach the original data-error override. Source frames and their attributes
remain unchanged. Empty-frame and provider exceptions are not swallowed.

New-module source registration and both precision-build lists are updated so
an old in-memory helper is detectable after Cloud code changes.

## Verification

- Dedicated input suite: 86 tests; history lengths 1/2/14/20/21/60/61/120/121/260,
  live and prepared frames, failure flags, NaN, missing squeeze columns,
  MACD rise/fall/flat/NaN, provider failure and fresh/stale build metadata.
- Twenty full calculations compare every returned value to the retained
  baseline without rounding, including price, scores, decisions, amounts and
  sizing. Provider/scoring callback order and counts also match.
- AST checks compare the moved statements exactly, normalizing only the reused
  row/MACD reads. Restoring these two blocks yields the original full-function
  AST. Older extraction suites normalize this separately tested extraction;
  golden files are not regenerated.
- Targeted regression: 303 passed in 33.30 seconds.
- Actual Cloud before-state verified on GOOGL and 379800.KS. Their downloaded
  daily/weekly/monthly frames were replayed through both input implementations:
  six exact matches without external data calls. Review ZIPs containing account
  information remain outside the repository.

- Full regression: 5,826 passed, 18 subtests passed and 77 warnings in 280.71
  seconds. Compilation and whitespace checks also passed. No executable-code
  changes followed this run.
- Post-deployment browser checks are separate from deterministic parity;
  downloaded build metadata identifies the code actually used by Cloud.

## Limits

This is an input-boundary refactor, not an investment-performance backtest or
an end-to-end latency improvement. Live prices can change between browser
observations; exact numerical parity is established with fixed inputs, while
screen checks verify the deployed code, dates, execution restrictions and errors.
