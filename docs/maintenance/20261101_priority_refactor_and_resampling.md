# Priority Refactor And OHLCV Aggregation

## Scope

Two independently verified changes, based on commit 9ced3c66:

1. The largest function, calc_scores_and_decision, goes from 798 to 594 lines.
   Its 29 personal-mode priority branches (255 source lines) move to the pure
   select_portfolio_priority_decision helper. It receives 46 explicit keyword
   inputs and returns the first matching DecisionOutcome or None. The existing
   normal-entry fallback and post-selection safety/sizing pipeline remain in
   the app. The local _set_decision wrapper is still needed by that fallback.
2. Weekly/monthly OHLCV aggregation avoids per-group Python Volume callbacks
   only when an exactly equivalent native grouped sum is provable.

No trading label, threshold, grade, decision code/reason, provider, freshness
TTL, cache key, price basis, account owner, authentication or database path is
changed. No functionality is removed. No historical records are rewritten.
This does not combine candidate quality with entry timing or change either.

## Refactor Proof

The baseline is read from the fixed git revision, not regenerated snapshots.
AST comparison checks all moved conditions, literals and ordering. Re-inlining
the moved prefix reconstructs the entire original caller AST; the normal-entry
fallback is also compared separately. The existing golden JSON files are not
updated. Tests compare all unrounded output fields for the original 20 seeded
scenarios, plus direct priority cases and 300 deterministic combinations and
threshold neighbors. Inputs, including nested DCA context, remain unchanged.

The new helper has no DataFrame, Streamlit, network or persistence operations
at evaluation time. Existing pure guards/outcome builders are reused. A new
module avoids requiring a newly added symbol from an older cached policy
module. Source metadata includes its actual import-time hash even if the
metadata module's name list was previously cached. It never relabels an older
loaded hash as current disk code or reloads running modules.

## Exact Aggregation Fast Path

Only native NumPy int64/uint64 and integral finite float64 volumes are eligible.
NaNs remain missing. A conservative bound on every possible partial sum keeps
it within 2**53: max(abs(volume)) <= floor(2**53 / nonmissing_count).
Integer min/max are converted to Python ints before abs, avoiding signed/uint
overflow. Fractional, extreme, infinite, nullable, narrow, non-native, bool and
object volumes retain the old callback. No numeric coercion is introduced.

Groupers, sort order, weekly rules, monthly aliases/offset handling, index/name,
column order, OHLC aggregation, missing-OHLC row removal, exception behavior and
input immutability are preserved. min_count=1 retains all-missing volume as NA,
not fabricated zero. The original mixed callback aggregation drops source
attrs; the fast path does the same. Tests check exact frame equality, dtypes,
attrs and floating bit patterns, including signed zero.

Primary API reference (the pinned dependency remains pandas >=2.2,<3):
https://pandas.pydata.org/pandas-docs/version/2.2/reference/api/pandas.core.groupby.SeriesGroupBy.sum.html

## Measured Local Effect

Synthetic data only: 12 frames x 2 weekly/monthly resamples, 2,600 daily rows
per frame, five alternating-order repetitions; median seconds below. Output
equality is asserted before and after timing. pandas 2.3.3 / NumPy 1.26.4.

| Volume Case | Before | After | Exact Output |
| --- | ---: | ---: | --- |
| int64 | 0.729 | 0.309 | Yes |
| Integral float64 with missing values | 0.751 | 0.306 | Yes |
| Fractional fallback | 0.753 | 0.744 | Yes |

These are NOT Cloud end-to-end improvements or claims of a one-minute run.
Reproduce with python -m tests.benchmark_resample. No network or private
account data is used.

## Verification

- Full suite: 5,086 passed, 1 skipped, 18 subtests passed in 253.57s.
  KRX login/session creation was stubbed for this offline run; no production
  database writes or authenticated KRX requests are needed by the suite.
- Focused decision, source-build and resampling checks: 339 passed.
- Resampling parity also passes all 254 cases on pandas 2.2.3, installed into
  an isolated temporary target. The application environment remains pandas
  2.3.3; requirements and the virtual environment were not changed.
- The baseline decision/resampling source is fixed at 9ced3c66. Existing
  decision golden snapshots were not regenerated to accept the new code.

## Existing Runtime Evidence

The newest available completed local profile is measurement c7172bef...
(2026-10-31), elapsed 111.801s, 95 calculated items, standard refresh with
possibly warm provider/analyst caches. It predates this patch. Its sequential
top-level summary, flow-refresh and analyst-enrichment phases were 57.22s,
26.05s and 10.38s. Live quote loading occupied 29.96s active wall across 133
calls. Nested/concurrent function work totals are not additional elapsed time.
The older 240s sample is not a comparable before benchmark.

## Production Verification

One complete Today Queue run after deployment to 3insky.streamlit.app:
measurement d8ffa692d2cc441f93419d740d97ccc9, finished
2026-11-01T11:47:05.453283+00:00, base commit afe0bd6b.
The imported app entrypoint hash matches this patch's LF-normalized source.
The report build metadata has restart_required=false and no stale modules.
The run completed normally; no reboot or account-data mutation was needed.

Both this run and the Oct 31 sample contain 81 registered items, 95 calculated
items, 12 auto-flow candidates and the full flow-refresh option. Both declare
standard_refresh_not_fully_cold, with possible warm provider/analyst caches.
Different dates, provider latency and cache contents still prevent treating
this as a controlled before/after benchmark.

| Sequential Phase | Oct 31 Sample (s) | New Run (s) |
| --- | ---: | ---: |
| Today Queue elapsed | 111.80 | 100.13 |
| Before Today Queue entry | 5.59 | 17.71 |
| Script elapsed including entry | 117.55 | 117.92 |
| Stock summary | 57.22 | 53.06 |
| Full flow refresh | 26.05 | 20.20 |
| Analyst enrichment | 10.38 | 4.33 |

The user-visible total is effectively unchanged, not a demonstrated 11.7s
speedup. This is not a one-minute completion. The new run's prices category
occupies 66.61s active wall; the live-quote loader alone occupies 33.46s across
133 calls. Those calls include cache/scope lookups and are not a count of
outbound requests. The 731 price-frame calls likewise are not 731 network
requests. KR cluster snapshot calls now total only 0.545s across 36 calls;
KR fallback waiting is negligible in this run. Category active-wall windows
overlap and must not be added to total elapsed time.

Provider waits remain the main end-to-end target; pure policy extraction alone
cannot remove them. Avoid freshness/TTL changes merely to improve timings.
Ledger fragment isolation is another separate optimization: it must retain
authentication/owner checks and correct rerun scope, not just skip the app's
login entrypoint. Neither provider redesign nor fragment auth changes are
bundled here. The next largest function is render_print_report_v2 (685 lines),
which needs its own output characterization before extraction.
