# November 2 Report Evidence Review

## Scope

No investment threshold, grade, position sizing, or account-return definition
changes. Reporting additions are read-only. Quote optimization is limited to
the today-queue scope; standalone precision quotes retain their full provider
fallbacks.

## Evidence and Display

- Public Npay KRX snapshots supplement mock-only broker settings: four market
  investor totals, breadth, turnover and provider-dated margin debt. Values,
  units, market scope, timestamps and source links are checked independently.
  These are provider data, not a documented KRX API or verified sector flows.
  Market-wide buying is not asserted to cause semiconductor performance.
- Headline-supported safeguard events are retained in the existing owner-bound
  report-history JSONB payload for five observed KR sessions. Missing/partial
  calendars cannot delete durable evidence or authorize unverified display.
  This does not reconstruct articles that were never collected.
- FX comparisons admit the nearest completed five-minute bar within ten
  minutes on the same local date. Actual bar times and offsets are displayed.
  Future/incomplete bars and previous-day substitutions remain excluded.
  Futures alignment and underlying returns are unchanged.
- Account components re-express the existing total: US regular session,
  subsequent compounded increment, and Korea. Missing legs remain missing.
- Gate summaries expose the existing score components, next numerical
  boundaries and tactical-rebound shortfalls, without granting execution.
- Rotation exclusions state their data reason. Top/bottom lists are disjoint
  when fewer than six observations are eligible; score calculations are intact.

## Performance Verification

`tests/benchmark_today_quote_transport.py` runs three paired offline passes
against baseline `04d41218fbc802558f5e9811d7c25d3af8c31bfa`. Each pass resets quote
caches, uses identical synthetic compressed provider payloads, six US workers
and zero artificial network latency. Prices and KR snapshots must match exactly.

The fixture reduces large Yahoo HTML requests from 69 to 20, with 49 small
chart fallback requests. It does not claim 49 total network calls disappeared.
Required render-only KR requests are grouped into one batch instead of ten;
cached/non-consuming views must not prefetch unnecessary clusters.

Offline timing is not Cloud elapsed time. Live full-queue refreshes retain the
same account, options and provider chain, but external latency, shared provider
caches and timestamps cannot be frozen. Report repeated live observations
separately from deterministic fixture comparisons.

Final fixture run (seconds, three paired runs, local network disabled):

| Scenario | Before runs | After runs | Before mean | After mean |
| --- | --- | --- | --- | --- |
| US quote transport | .174159 / .159161 / .157278 | .113068 / .163074 / .153107 | .163533 | .143083 |
| KR render transport | .052531 / .049126 / .049058 | .035956 / .041139 / .037010 | .050238 | .038035 |

Cloud pre-deployment full-refresh observations: 94.136 / 65.943 / 63.839
seconds (mean 74.639). All three used 81 registered inputs, 12 automatic
candidates, 94 calculated rows, full money-flow refresh, and
`standard_refresh_not_fully_cold` cache policy. Yahoo HTML requests were
72 / 71 / 57; KR bulk requests were 3 / 3 / 3. This variability is why a
single before/after wall-time difference is insufficient proof of a speedup.

## Regression Coverage

Coverage includes mock exclusion, partial failures, date/unit validation, source
links, durable history across restarts and owner isolation, FX tie/completion
boundaries, account reconciliation, gate input omission, rotation invalid data,
thread scope restoration and bidirectional quote-cache policy isolation.

Final frozen-code suite: 6,066 passed plus 18 subtests in 337.57 seconds.
There were 77 existing dependency/date-parsing warnings, no test failures.
Compilation and whitespace checks passed. Independent reviews covered public
data/history, FX boundaries, and performance scoping; their two retention and
unused-prefetch findings were fixed and regression-tested before this run.

Cloud verification follows deployment. Private account reports and measurement
downloads stay outside git.
