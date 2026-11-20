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
- Deployment verification is recorded below; both code commits are pushed and
  the final Cloud reboot/export are verified.

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

## Operating verification and discovered limitation

- Code `d9459894` pushed; Cloud owner menu reboot performed directly. App login
  succeeded through the existing Google account without credential entry.
- Actual completed GOOGL ZIP at 23:21 KST reports `restart_required=False`, no
  stale modules, and matching local/disk/loaded prices, overnight, signal-basis
  and input-contract hashes. Its price-input ID `954a9e6f4a09e2a7`, ATR
  `10.657137189592634`, `CRISIS_PANIC_SELL_OFF` and defense gate match the
  pre-change captured input/result. The input frames replay exactly.
- The new helper itself was missing from the precision manifest's module list.
  Follow-up `c1a11059` includes it; 184 focused export/build/input tests passed
  (25.22s). A final frozen gate and second actual Cloud reboot follow this fix.
- Actual selected quote is Yahoo overnight, observed **17:59:37 KST**; calculation
  was **23:21:53 KST** (pre-market). This over-five-hour-old selection is an
  existing provider-priority/freshness issue, now visible. This change deliberately
  preserves the selected value; it must NOT be described as a fresh live quote.
  Fixing this proven input issue supersedes domestic timestamp coverage as the
  single next task. All providers are not yet migrated.

- Follow-up frozen selected-all gate: **2,211 passed**, zero failures/errors/skips,
  226.721s, unchanged source hashes (`cache/refactor_checks/all_29vsd6tk`).
- Post-reboot Today full calculation: 95 unique rows, 105.2s wall screen time.
  The ZIP contains every new basis field; 50 rows have actual supplier observation
  times (44 Yahoo chart, six Yahoo overnight), 45 retain unknown provenance.
  Sessions: 42 pre-market, six overnight, one regular, 46 unknown. This is one
  actual run, not a matched speed benchmark; no speed improvement is claimed.
- In the same Today capture GOOGL used a 23:28:35 KST pre-market bar while
  SOXL/BITX still used roughly 17:59 KST overnight quotes. Code inspection confirms
  `_us_equity_after_hours_active` covers only 16:00–20:00 ET; pre-market falls into
  the overnight-first branch. The unchanged freshness window is 16 hours.
  This supports the next-task diagnosis without claiming different runtime
  quotes are identical inputs. The read-only ZIP click rerendered in 15.2s;
  it was not another full 95-stock calculation.

- Final actual GOOGL completed export at 23:31 KST is on `c1a11059`, with
  `restart_required=False` and no stale modules. All five quote/input helpers,
  including `quote_observation`, have identical loaded/disk/committed hashes.
  The selected Yahoo chart time is 23:31:07 KST, session regular, kind bar start.
  Source last date and ATR date are now Nov 20, 252 source rows: the supplier's
  in-progress daily row really is included and the new table explicitly flags
  possible incompleteness. This audit does not change that existing behavior.
- Captured final frames replay ID `e5bbc4a302f8ae5e` and ATR
  `10.214994158063616`; defense gate and `CRISIS_PANIC_SELL_OFF` remain. The source
  gained a new trading-day bar since the earlier 251-row capture, so this ATR is
  not a same-input before/after comparison. Frozen-input parity remains the
  relevant no-policy-change check.
- Final screenshot: ignored `cache/operating_20261120/quote_observation_live.jpg`.
  Final audits: `quote_observation_final_GOOGL.json` and
  `quote_observation_today_counts.json` in the same private folder. Board projection
  is regression-tested; no separate live board run was claimed in this task.

## Handoff

This bounded quote-evidence and partial-bar audit is complete and deployed.
The single next task is the proven stale overnight selection in pre-market;
see HANDOFF.md. Domestic provider timestamp coverage and completed-daily-bar
policy remain explicit limitations, not silently completed work.
