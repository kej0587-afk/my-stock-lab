# Summary-worker and analyst wait diagnostics

2026-11-07 KST. Base: `f746134c`, initially clean and equal to origin/main.

## Bounded change

Added per-symbol timings for asset metadata, financial scoring, holdings lookup,
live-price alignment, leveraged review and benchmark lookup in summary workers.
The analyst callback now times the entire call, including outer-cache waiting.
Yahoo metadata separates lock acquisition, minimum-interval sleep and provider
callback time; analyst-context labels distinguish those calls from other readers.
FnGuide HTTP and analyst outer-cache events are also recorded.

No thresholds, labels, result calculations, provider order, TTL, mutex coverage,
backoff or concurrency changed. The diagnostic context never changes cache keys.
The callback tolerates the old metadata module during a rolling deployment.

## Verification

- Focused baseline: 160 passed (34.25s); final: 166 passed (37.90s).
- Immutable full-app AST comparison strips only the six timing scopes and the
  analyst callback wrapper. Provider results, sleep/cooldown policy, cache keys,
  callback identity and exception propagation retain their original behavior.
- Deterministic clock test distinguishes 4s lock wait from 3s provider time.
- Prices gate before/after initially: 265 passed / one identical pre-existing
  `test_investment_functions_are_unchanged` failure against the old decision AST.
  Final gate: same 265 passed / one known failure (45.16s).
  No golden reference regenerated; production result pending.

## Interpretation limits

Worker sums overlap; use active unions or phase wall times for elapsed time.
Generic per-symbol scopes include work and cache waits, not pure waiting alone.
The Yahoo provider counter counts fetch callbacks, not individual HTTP requests.
FnGuide request events count actual request attempts; responses can be non-2xx.
Outer-cache reuse can include concurrent waits, not only instant cache hits.
Reduced summary self time can be reclassification by the new nested timers.
A fresh deployment can invalidate decorated-function caches, so the first run
is not a controlled warm/cold A/B comparison or evidence of a speedup.

## Deployment

Code **`50283998` pushed**. One full production run, 2026-11-07
**12:01:23–12:02:49 KST**, ID **`0d35d5810c284faf924b437fb1a4f7f8`**,
same four accounts / 81 registered / 95 calculated / 12 flow candidates, full
flow refresh checked. Completed export and UI IDs match. Loaded/disk/local app
hashes match (`c1b7cf33c9fbca838933ace9d712686ffc317463eda1894db06f2749fd836b11`).

| Phase (wall seconds) | Previous full run | Current full run |
| --- | ---: | ---: |
| Today Check | 107.934 | 86.710 |
| Script including entry | 119.269 | 94.680 |
| Summary | 52.276 | 38.451 |
| Stock signals | 34.858 | 23.874 |
| Analyst enrichment | 9.038 | 1.896 |
| Flow refresh | 20.619 | 20.656 |

No controlled speedup claim: network, process and cache conditions differ;
instrumentation does not optimize provider work. Prices / indicators / external
active unions **53.219 / 22.099 / 22.108s**, overlapping. Zero instrumented errors.

| New scope | Calls | Concurrent sum seconds | Longest call seconds |
| --- | ---: | ---: | ---: |
| Summary live-price alignment | 95 | 32.015 | 1.920 |
| Summary leveraged review | 95 | 11.810 | 4.156 |
| Summary financial score | 95 | 5.413 | 1.304 |
| Summary holdings lookup | 95 | 0.378 | 0.043 |
| Summary benchmark lookup | 95 | 0.036 | 0.001 |
| Summary asset classification | 95 | 0.002 | <0.001 |
| Analyst callback including outer cache | 73 | 5.245 | 1.849 |

Summary self sum 69.766 -> 10.861s is partly reclassification by nested timers,
not measured waiting saved. The current scopes show where time is spent but
cannot by themselves distinguish cache waits from computation/provider work.

**Partial module deployment remains:** new per-symbol app timers exist, but
all `cache.analyst_snapshot` and `yahoo_metadata.*` events and new provider/lock
timers are absent. `get_analyst_snapshot` was called 73 times and its new cache
decorator emits a lookup even on hits, so absence is not proof of zero HTTP or
instant cache hits. The old news/metadata call path remains loaded. The report
fingerprint reports no stale modules but does not cover these helper modules.
Requested Cloud Reboot with this evidence. Do not infer the lock-wait portion
or change mutex/TTL/concurrency until the new reader executes after reboot.

Private evidence outside Git:
`C:/Users/82amf/Downloads/today_queue_0d35d5810c284faf924b437fb1a4f7f8.json`
and `stock_lab_summary_wait_20261107.png`.
JSON SHA-256: `b3bc46e3e4e83032baca0127e8226d6ba3f2bc8ecb4e5d1397d3fef977076fc9`.
