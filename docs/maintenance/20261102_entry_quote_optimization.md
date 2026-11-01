# Entry Initialization Timing

## Baseline And Scope

The verified 95-item repeated refresh 60d1fd4e717e4dbba37e347d8fbf796b
recorded 17.00s before Today Queue, 60.51s queue and 77.63s full script.
The first post-reboot calculation was 17.21s / 103.41s / 120.75s.
Neither profile attributed the pre-queue wait to individual entry tasks.

The first change adds a separate PerformanceTrace around the existing
initialization block: macro, events, settings, holdings, dividends, monthly
records, FX, holdings valuation and portfolio total. The same calls execute
in the same order and scope. UI, authentication, DB reads/writes, decisions,
source precedence, cache TTLs and price fallbacks are not changed.

Each Today attempt retains that same run's entry trace in entry_initialization
and the remaining uninstrumented before_today time in other_before_today_seconds.
The existing measurement ID and completed-vs-partial retention behavior remain
unchanged. The timing panel includes an entry-phase table for that report,
not the newest unrelated render's entry snapshot.

## Verification Before Measurement

- Entry business AST is identical to 7e67afba after removing timing wrappers.
- Live/demo stubs preserve calls, values and session-state keys/frames.
- Interrupted entry calls retain their exceptions and restore trace context.
- Timing panel includes the new table and retains the previous full result.
- Focused entry/performance tests: 26 passed in 23.23s.

## Optimization Boundary

The US batch quote loop and holdings display-price override are serial in
the baseline. Parallelizing them blindly can lose Streamlit session context,
change cooldown admission, or remove the independent display-source override.
No batch value is substituted for a display quote, and failed quote retries
are not memoized away. Further changes require the actual entry profile.

## Measured Entry Bottleneck

Completed production calculation a2010b7fa6f840d98cb87b3b7d697a93 on
236390c3 captured entry trace 453c1554f699454fa75fe0b49e9c2343:

| Metric | Seconds |
| --- | ---: |
| Before Today Queue | 17.935 |
| Instrumented entry initialization | 17.203 |
| Holdings prices and valuation | 16.406 |
| Batch quote lookup | 8.742 |
| Seven display-price overrides | 7.649 |
| Four saved-data reads combined | 0.755 |
| FX lookup | 0.0003 |

The seven US holdings triggered 14 realtime source-chain calls. HTML itself
accounted for 4.413s; the full source chains took 15.863s. Merely parallelizing
HTML would not address most of this wait. Today Queue was 86.689s and total
script about 104.7s; this run is a measurement baseline, not an optimization gain.

## Scoped Successful Source Reuse

The optimization keeps both the batch lookup and the independent display
override. Only successful, finite, positive _fetch_us_realtime_price results
are shared inside one holdings valuation. Existing single-price cache hits
still take precedence. Zero, invalid values and exceptions are not retained.
Provider bodies/order, manual overrides, KR lookups and portfolio arithmetic
remain unchanged; no worker threads are introduced.

The deadline is the existing 15s price TTL measured from provider-call start,
never renewed by a hit. Slow calls are not admitted. Every valuation starts
with an empty ContextVar scope; nesting, errors and explicit cache clearing
restore/invalidate it. The clear generation also prevents late publication
into this local memo after a refresh.

A scoped quote must NOT start a new global cache lifetime. result_cache's
explicit UncachedValue crosses both Streamlit cache layers as an internal
exception, then unwraps at the public decorator boundary. Only source values
obtained through a scoped hit take this path. Ordinary success/failure caches
and TTLs are unchanged. An older loaded cache module disables the new scope
instead of accepting a value whose original age would be lost.

Related entry, source-body parity, quote/cache priority, invalidation, concurrent
scope isolation and bypass tests: 134 passed in 36.96s. No scoring thresholds,
grades, decision wording, account records, authentication or DB writes changed.

## Production Result

Completed post-change calculation 0f148cd910ca4e9788c9986b223939e4 on
292ffcd6 captured entry trace ebcd78c56e844d41b5da007742277cef.
Both this run and a2010b7f used 81 registered / 94 calculated / 12 auto-flow
candidates, full-flow refresh and the same declared standard-refresh policy.
The previous day's 95-item profiles are not the before/after pair for this
change; no candidate count was reduced by the optimization.

| Metric | Before a2010b7f | After 0f148cd9 |
| --- | ---: | ---: |
| Before Today Queue (s) | 17.935 | 9.894 |
| Holdings prices and valuation (s) | 16.406 | 8.697 |
| Batch lookup (s) | 8.742 | 8.684 |
| Seven display overrides (s) | 7.649 | 0.0017 |
| Entry overnight HTTP requests | 14 | 7 |
| Entry chart HTTP requests | 16 | 8 |
| Scoped success / hit counts | not available | 7 / 7 |
| Today Queue elapsed (s) | 86.689 | 86.318 |
| Full script elapsed (s) | 104.711 | 96.312 |

The source-chain wrapper still ran 14 times after the change; seven were
actual successful chains and seven were local reuse hits. This distinction
is why wrapper counts alone are not request counts. The unchanged batch
latency and removed display wait match the intended optimization boundary.
These are separate live observations, not a controlled network-latency A/B
benchmark or a guarantee of the same gain on every render.

Both traces were completed, had full-calculation flags, and had no measured
failures. The post-change app source hash matched local LF-normalized source;
reported stale_modules was empty. Actual us_quote_scope.hit events verify
the new code path independently of source records. No extra Cloud reboot
was needed for this verification.

A news-module import KeyError was observed once during deployment. A normal
browser reload subsequently started successfully and the above calculation
completed. Its import-loader root cause was not proven, and no error masking
or news-module changes were added.

Final full suite: 5342 passed, 1 skipped, 18 subtests passed in 287.10s.
Programmatic checks confirmed matching input counts/cache policy, completed
queue and entry traces, seven genuine reuse hits, no measured failures and
the matching app source hash. Only documentation changed after this suite.

Saved UI proof: entry-scope-production.png in the 2026-11-02 visualization
directory. The diagnostic now shows all entry stages beside that exact
measurement's total; older reused reports retain their own entry snapshot.

Remaining measured work includes multi-timeframe packs (94 calls, 19.38s
active wall), current-price display (25.12s active wall) and history loading
(20.34s active wall). These overlap and must not be summed. The measured full
workflow remains above one minute; this change addresses entry duplication,
not all calculation bottlenecks.

Implementation reference: https://docs.python.org/3/library/contextvars.html
