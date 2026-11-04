# Architecture Review and Incremental Refactoring

Baseline: `ef08d5e0`. Scope: report assembly and holdings display consistency.

## Working Rule

Do not postpone correctness review until all functions have been extracted.
For each bounded path: reproduce an inconsistency, capture unchanged outputs,
separate responsibilities, fix the proven defect, and test the whole path.
Moving code alone does not establish correctness or improve market-data latency.

## Current Paths

| Layer | Current owners | Contract to protect |
| --- | --- | --- |
| Collection | `app._collect_today_report_context`, `report_context.collect_report_context`, price/news/economic providers | Preserve source, observation timestamp, market, session, missing/failure state |
| Prepared evidence | `report_session`, `report_account`, `report_intraday`, `earnings_pipeline` | A single prepared input is reused; closed, live and extended prices stay separate |
| Investment policy | `app.calc_scores_and_decision`, execution workflow and final-check helpers | Preserve scores, thresholds, gate reasons and allocations during extraction |
| Presentation | `market_memo`, `report_evidence.report_sections`, tab renderers | No new fetches or policy changes while formatting; table, summary and export agree |

The repository has already separated many helpers. Remaining coupling matters
more than a percentage of lines moved. For example, several report helpers
import common conversion functions from `report_evidence`; these should eventually
move to a small lower-level module, with compatibility imports and tests.

## Completed in This Pass

- `report_sections`: 642 -> 483 lines. Holdings and calendar blocks have explicit
  owners (`report_account_section`, `report_calendar_section`).
- Section assembly no longer searches displayed Korean headings to determine
  block boundaries. Editing a heading must not break reordering.
- Removed a second holdings-filter pass. No new remote requests were introduced.
- Registered both extracted files in report build provenance, so a deployed old
  module cannot silently masquerade as the new renderer.
- Holdings live-price cells now use the same existing freshness/session validator
  as account totals and sector evidence. Missing timestamps, old observations,
  future timestamps and different-session values are not current prices.
- SOL semiconductor reference text also rejects an invalid SOXX live observation
  and uses explicitly labelled closed evidence instead.
- Corrected the asset-table `본전까지%` display: required rise is
  `max(0, breakeven/current - 1) * 100`. Invalid prices remain missing. The existing
  breakeven fee assumption, P/L, valuation, shares and weight logic are unchanged.
  The pure helper lives in `holdings_display`, avoiding a new required export from
  a potentially cached `portfolio` module during Cloud hot deployment.

## Verification Contracts

- Twelve full-report hashes captured from the previous implementation: preopen,
  Korean intraday, post-close, US premarket/intraday and weekend, with/without holdings.
  The fixture contains no stale live quote, so the extraction must be byte-identical.
- Same-day quote validity: fresh, exactly 15 minutes old, one second too old,
  morning stale, future, missing timestamp and wrong date; account and table agree.
- Recovery percentage: losses, gains, breakeven, fee-adjusted values and missing
  inputs; execute the real holdings builder and compare every other returned column.
- Broader report, earnings, news, portfolio and golden regression suites.

Validation run: 2,056 selected regression tests passed (4,413 unrelated tests
deselected); the final focused contract/display run passed 34 tests, including
two additional US-intraday output fixtures. Python compilation and diff whitespace
checks passed. These are correctness tests, not investment-performance backtests
or a live market-data speed benchmark.

## Live Inspection and Limits

Read-only Cloud inspection on 2026-11-04: asset overview and Today Check navigation.
Observed negative `본전까지%` values for loss positions; code confirmed the reversed
formula. Today Check was pending calculation in this new session, so zero pending
counts were not treated as a decision defect. Holdings and target weights were not
edited. This inspection is not a completed audit of every tab or a validation of
all live provider values.

Follow-up observations, not established calculation bugs: the narrow viewport
uses excessive space for the dashboard title; asset captions mention different
price-cache durations. Verify which caches each caption refers to before changing.

## Next Bounded Passes

1. Shared observation contract: compare Today Check, board, precision, report and
   CSV for one held KR ETF and one held US ETF using the same frozen input.
   Check source date, session, stale/missing state, base price and return sign.
2. Policy/display contract: compare candidate grade, execution gate, entry plan
   and final check. Extract the remaining score function (480 lines) and entry
   renderer (478 lines) one responsibility at a time. Do not collapse candidate
   quality into permission to buy.
3. Evidence/story contract: official earnings result versus outlook, actual
   versus consensus, same-market/session articles, factual versus attributed
   interpretation. Keep missing evidence explicit; do not fill gaps by inference.
4. Provider performance: measure actual remote requests separately from cached
   function invocations. Optimize duplicate calls within a calculation snapshot;
   do not extend TTLs or mix observation dates to manufacture a speed improvement.

Each pass needs a fixed-input before/after comparison, relevant missing-data and
session-boundary cases, and a live smoke check. Broader financial policy changes
remain a separate reviewed decision, not part of this refactor.
