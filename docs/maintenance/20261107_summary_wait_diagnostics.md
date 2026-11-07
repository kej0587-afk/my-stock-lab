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

Pending code push and one complete production Today Check with unchanged scope.
Private diagnostic exports and screenshots remain outside Git.
