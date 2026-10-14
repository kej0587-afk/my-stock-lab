# Cloud Timing Follow-up

## Production Evidence

The user's Cloud screenshot reports these elapsed times, in seconds:

| Top-level observed step | Seconds |
| --- | ---: |
| Today Queue body | 239.881 |
| Before entering Today Queue | 0.6 |
| Flow collection/analysis | 61.532 |
| All-symbol summary (85 symbols) | 34.586 |
| Analyst enrichment | 17.411 |
| Outside those three top-level steps | 126.352 |

The last figure is subtraction of non-overlapping top-level elapsed times.
Do NOT subtract nested 1y/10y/RS phases again or add concurrent function totals.
The remaining 126.352s includes possible network queries and calculations,
not necessarily browser layout or CPU rendering. Startup was not the dominant
component in this run. This screenshot does not identify that remainder's
exact function.

Concurrent work totals: prices/waits 160.793s, indicators/patterns 40.981s,
external data/flow 41.229s, decision/assembly 9.530s. These are not elapsed
phase shares and should not be divided into a wall-time pie chart.

## Source Findings and Changes

The flow-candidate and detail paths repeatedly build sector-internal snapshots.
Their existing session cache has a 90s TTL; the whole run lasted 240s. Re-fetch
after expiration is a plausible contributor, not yet a measured attribution.
TTL and freshness semantics were NOT changed to mask the delay.

KR constituent quotes use a bulk request, then serial realtime/basic Naver
fallbacks for missing fields. Those calls previously escaped detailed timing.
The fallbacks now use up to four workers, with a process-wide four-slot guard
also limiting simultaneous sessions. Each ticker still uses realtime before
basic, the same zero/missing handling and merge rules, original output order,
the same 45s batch cache, and the same exception behavior. No provider, score,
decision text, auth, persistence or feature was changed.

New timing coverage includes watch/candidate preparation, market guard,
flow-shortlist construction and attachment, briefing, export generation,
signal validation, candidate tools, full flow detail, KR/US cluster builders,
and KR quote loading and its fallback wait. The root's exclusive time is
reported as unclassified render/post-processing, not automatically CPU time.
Function/phase totals can overlap; repeated phase calls are aggregated.

The timing panel can download the complete report as JSON. Reports contain
only generic function names, counts and timings, not holdings or credentials.
Downloads use `on_click="ignore"` to avoid another app calculation.

Unrestricted pykrx parallelization was deliberately deferred. Read-only source
review found shared authentication/session and singleton initialization risks;
FDR-only concurrency would need a coordinated provider guard and more tests.

## Verification

- Controlled 12 missing quotes, realtime/basic each delayed 20ms:
  serial 0.492s, bounded parallel 0.131s, exactly equal output.
- Public six-stock KR quote probe: 0.561s serial, 0.379s bounded path, exactly
  equal six-quote results. This is a local provider check, not a Cloud benchmark;
  network variability and bulk-hit behavior prevent a speed claim from it.
- Tests cover provider order, partial/zero/empty payloads, identical merge and
  insertion order, shared cap across simultaneous batches, cache hits, worker
  trace propagation, exceptions, and unchanged 45s cache/clear contract.
- Full suite: 896 passed, one existing pykrx deprecation warning (42.02s).

No Cloud deployment was performed. The before screenshot is production
evidence; all after timings here are local/controlled. One-minute end-to-end
performance has NOT been demonstrated. After deploying all changed files
together and restarting, compare the expanded phase report/diagnostic JSON
against the 239.881s baseline before choosing the next optimization.
