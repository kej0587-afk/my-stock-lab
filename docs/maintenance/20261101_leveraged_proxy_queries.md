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
the final post-deployment measurement. No Cloud speedup is claimed yet.

## Remaining Work

Production end-to-end improvement must be measured on a completed fresh
calculation with matching input counts/cache-policy metadata. A single
before/after Cloud run is observational, not a controlled latency benchmark.
Mixed loaded/disk sources must be resolved by app restart, not silent reload.
Next investigate the newly separated US provider waits and the main-thread
entry work before increasing concurrency or changing quote precedence.
