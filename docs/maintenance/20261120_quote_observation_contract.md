# Selected quote observation contract

Date: 2026-11-20 KST. Starting revision: `7ee2fc7d`; clean main, upstream 0/0.
This continues the latest handoff's input/session task, not historical news work.

## Change and boundaries

- Carry evidence on the exact selected scalar quote through the existing cache,
  request scope, display loader, Today input basis, board and precision exports.
  Numeric float behavior and price-input v1 identity are unchanged. A derived
  scalar loses supplier evidence; no global price-keyed side channel is used.
- Instrument existing Yahoo candle, metadata and overnight JSON paths. A candle
  timestamp is explicitly its bar start, not the time of the last trade. A session
  is shown only from a named supplier field or a matching supplied session interval.
  Absent/ambiguous intervals remain unknown. No new requests/providers/TTL changes.
- Manual inputs, wrong-symbol evidence and uninstrumented providers remain
  unknown. A separate reference quote is never substituted into a decision.
- The input table audits the source daily date against the selected quote's local
  market date. A same-day regular-session bar is potentially incomplete; an older
  source bar is not automatically certified as a completed close. This audit is
  observational: it does not remove rows or change indicators, scores or gates.
- Existing source ATR restoration and provisional overlay behavior are retained.
  Original vendor rows can still include a partial daily bar. A completed-session
  source policy remains a separate, evidence-backed step, not hidden in this patch.

## Verification

- Before edits: 84 focused input/basis/overnight/scope/cache tests passed (11.88s).
  An initial unittest discovery found zero pytest tests and is not counted.
- Initial integration: 69 tests passed (25.73s), including exact same-price
  indicator/ATR/identity parity, source date/session audit, and old-versus-new
  display loader numeric results/provider-call order.
- Historical AST guard uses a six-statement exact adapter for metadata transport;
  original baseline is retained. Separate behavioral comparisons use `7ee2fc7d`.
- Actual pre-change GOOGL Cloud export (22:58 KST) replayed exactly: input ID
  `954a9e6f4a09e2a7`, ATR `10.657137189592634`, source date 2026-11-19. Adding
  synthetic timestamp metadata for this parity test preserves all three. That
  synthetic timestamp is not evidence of an actual supplier observation.
- Final frozen selected-all gate: **2,210 passed**, zero failures/errors/skips,
  222.544s; source hashes unchanged during run. Evidence:
  `cache/refactor_checks/all_d4eezq90`. This is selected regression coverage, not
  the full repository suite, a speed benchmark, or investment validation.
- Deployment verification will be recorded below after push/reboot.

## Historical local cache conflict found during verification

The first selected-all run (`cache/refactor_checks/all_l210kr1f`) ran 2,210 tests:
2,201 passed, nine failed, no errors/skips (232.204s). All nine failures were the
optional untracked November 7 `decision_smc_before.json` and
`decision_finalization_before/` captures. The current-vs-historical-function exact
output/call-order checks passed before each old cached-file comparison failed.

An isolated untouched `7ee2fc7d` worktree with the same captures reproduced the
same nine failures (117 passed, nine failed, 21.95s). These captures predate the
already-approved November 20 ATR source-bar restoration; this patch did not change
ATR. Preserve rather than regenerate: 41 artifacts were moved to ignored
`cache/historical_baselines_20261107/`, with before/after SHA256 equality recorded
in `preservation.json`. No committed golden, old reference function, decision
expression or expected score was replaced. The final selected gate retains all
2,210 tests and exact historical-function comparisons.

Private captures remain under ignored `cache/operating_20261120/` and Downloads;
no account data or credentials are committed.
