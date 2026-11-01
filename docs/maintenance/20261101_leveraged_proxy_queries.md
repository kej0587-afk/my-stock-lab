# Leveraged Proxy Query Scheduling

## Evidence And Scope

Previous completed production run: d8ffa692d2cc441f93419d740d97ccc9,
commit afe0bd6b, 95 calculated items. Today Queue elapsed 100.13s, entry wait
17.71s, total script elapsed 117.92s. Stock-signals elapsed 35.09s; display
quote resolution occupied 33.46s active wall across 133 calls. These calls
include cache lookups and are not a count of external requests.

The leveraged-product override inside stock signals also builds a cached
profile of 7-8 underlying/market/rate/currency proxies. Each proxy previously
loaded its display quote and 6mo history sequentially. These symbols/periods
are not necessarily in the summary's preloaded ticker/period set.

This patch extracts that row assembly into stock_lab_core/leveraged_watch.py
and overlaps independent proxy rows. No trading label, threshold, grade,
provider priority, history period, quote freshness TTL or persistence changes.
No authentication, account owner, financial record or database path changes.
The separate holdings/peer batch/display quote precedence is not changed.

## Boundaries

- At most two workers per profile, with two shared parallel-row permits
  across concurrent profiles. Each row keeps quote-before-history order.
  Existing provider locks, caches and fallback chains remain in use.
- Context is propagated using the existing submit_with_context helper.
  No worker writes Streamlit state or updates phase-progress messages.
- Futures are collected in input order. Full returned fields, formatting,
  unrounded returns, NaNs and history-error fallback match fixed 5a859433.
  Quote/formatting exceptions propagate; permits release on exceptions.
- Active session-local forced refresh retains the original serial caller
  thread, as does a single-row profile. The cached app wrapper still uses
  ttl=300/show_spinner=False; cache hits do not run providers. No new cache.
- The existing 300s profile cache is still independent of the 15s live-quote
  cache. This patch does not force profile recalculation on every manual
  quote refresh or claim to unify those snapshot dates.
- The new source registers its actual import-time hash. The metadata bridge
  includes it even if an older precision_build module's name list is cached;
  it never rewrites an older loaded hash to the current disk hash.

## Source Diagnostics

US realtime resolver, Yahoo overnight/chart/regular-close and yfinance
fallback durations now appear separately in the existing timing trace.
Yahoo request/response/error/timeout counters sit at the actual HTTP calls;
HTTP 429 has its own additional counter. A response counter means response
opened, not that a usable quote was accepted. Malformed data retains the
old fallback. Cached regular-close calls do not fabricate HTTP counts.

Provider bodies are AST-compared against fixed 5a859433 with only timing and
counter expressions removed. Choice conditions, ordering, timeouts, request
arguments, parsing and return values are unchanged. Diagnostics retain no
URLs, tickers, payloads, credentials or raw exception messages. Shared/global
Yahoo cooldown behavior and existing failure-result caching are unchanged.

## Verification

- Full suite: 5,218 passed, 1 skipped, 18 subtests passed in 256.52s.
  KRX session creation was stubbed for this offline run; account data and
  authenticated provider endpoints were not needed.
- Focused new tests: 132 passed. Includes baseline full-row parity, return
  windows, missing/invalid history, zero/invalid quote, context, shared cap,
  serial mode, permit cleanup, cache-hit/clear behavior, forced refresh,
  source provenance and transport counts/redaction.
- Existing quote/price/cache tests plus source diagnostics: 90 passed before
  the final cache/provenance tests were added.
- Existing summary/decision checks plus source diagnostics: 97 passed.
- Offline fake-provider benchmark: 8 rows, 8 quote + 8 history calls in both
  implementations, 20ms delay per call, three alternating-order runs.
  Median sequential 0.334s; two-slot 0.168s. Exact output equality asserted.
  This measures scheduling only, not production latency or fewer requests.
- Reproduce: python -m tests.benchmark_leveraged_watch.
- Independent review found no actionable regressions in app wiring, forced
  refresh/cache policy, source provenance or provider diagnostics.

Primary concurrency references:
https://docs.python.org/3/library/concurrent.futures.html
https://docs.python.org/3/library/contextvars.html

## Production Check

Immediately before deployment, complete measurement
1a83f47d66cb4ae09d49346cb1ce5806 on 5a859433 finished at
2026-11-01T12:18:18.321295+00:00: 96.33s Today Queue + 17.45s entry,
113.88s script total. It has the same 81 registered / 95 calculated / 12
auto-flow candidates and standard-refresh-not-fully-cold policy as d8ffa692.
Summary 46.53s; stock signals 31.27s; live quote active wall 29.13s.

Deployment 87d40eeb boots without an ImportError. A completed GOOGL review ZIP
confirms app entrypoint and prices loaded/disk hashes match the new source.
However, leveraged_watch has an unrecorded import hash, with a current disk
file. The missing registry entry does NOT prove an older implementation is
loaded. Keep the restart warning; do not invent a loaded hash from disk or
declare full module verification. A Cloud Reboot app was requested before
the final post-deployment measurement.

After the user confirmed Reboot app, a fresh completed GOOGL review ZIP on
79cbb66c (2026-11-01T12:34:22.990649+00:00) confirms restart_required=false,
with no stale modules. App entrypoint, prices, decision_priority and
leveraged_watch each have recorded import hashes matching both the current
disk file and this checkout's LF-normalized source. No runtime reload or
replacement of an unrecorded hash with a disk hash was used.

The complete post-reboot run, 999afd9de18d471bb3b1022c3d9f5067, finished
2026-11-01T12:37:59.437468+00:00 on 79cbb66c. It contains the same
81 registered / 95 calculated / 12 auto-flow candidates, full flow refresh
enabled, and standard_refresh_not_fully_cold metadata. The calculation and
full measurement both completed, with no recorded function errors or control
flow exits. The new helper ran five times and processed 38 proxy rows.

| Measurement | Before (s) | After Reboot (s) |
| --- | ---: | ---: |
| Today Queue elapsed | 96.33 | 94.72 |
| Before Today Queue entry | 17.45 | 17.77 |
| Script total including entry | 113.88 | 112.63 |
| Stock summary | 46.53 | 45.96 |
| Stock signals | 31.27 | 28.73 |
| Full flow refresh | 20.31 | 18.50 |
| Analyst enrichment | 5.49 | 9.93 |
| Display quote loader active wall | 29.13 | 27.80 |

The small total difference is NOT proof of a substantial end-to-end speedup.
Identical input counts and declared refresh policy do not imply identical
provider/cache contents, especially after reboot. Do not extrapolate the
single-profile synthetic 2x scheduling result to the whole app. One-minute
completion has not been achieved.

The new trace isolates the next price-loading bottleneck: Yahoo overnight
HTML, 73 function calls / 71 actual HTTP requests, 56.20s summed work,
25.32s active wall. Yahoo chart made 140 HTTP requests (19.05s work / 12.17s
active wall); regular-close made 3 HTTP requests. Requests/responses do not
prove a usable quote was accepted. No HTTP 429 or timeout event was recorded
in these instrumented transports; this is not a claim about all providers.
Provider/fallback precedence has not been altered to avoid that HTML work.
Loader calls, request counts, summed work and overlapping wall windows
remain distinct; none should be added together as user-visible latency.

## Remaining Work

The deployment/loaded-source check is complete. The next optimization target
is the measured overnight-HTML path and repeated main-thread entry work,
without changing quote precedence or weakening freshness checks. A single
before/after Cloud run is observational, not a controlled latency benchmark;
keep repeatable output-parity and bounded-load tests alongside future work.
