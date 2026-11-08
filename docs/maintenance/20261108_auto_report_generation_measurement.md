# Full automatic report generation measurement

Scope: observation-only timing of the production generation button, based on
e56b95e0. No scores, gates, report content, providers, timeouts, worker limits,
cache TTLs or refresh policy are changed. Private reports stay in ignored cache/.

## Measurement boundary

- Dedicated `auto_market_report_generation` trace starts inside the generation
  branch and finishes after saving Markdown, before Streamlit's normal rerun.
  Prior completed measurements survive failure/rerun; output SHA256 prevents
  displaying a measurement for a different report.
- Exclusive main-thread wall stages separate price collection/alignment,
  flow snapshot, macro/official/investor evidence, RSS, article bodies, indicator
  calculations, history persistence and Markdown assembly. Worker time is
  propagated separately; cumulative parallel work is not added to wall time.
- Instrumented HTTP attempts and cache lookups/misses/reuses are distinct.
  Economic API, Google session RSS and public feed/body attempts are counted;
  other HTTP providers are not exhaustively instrumented. Existing Yahoo SDK
  download invocations are not a count of physical HTTP requests.
- App-entry work before the generation branch is reported separately. Browser
  paint, post-rerun rendering and diagnostic serialization/build hashing are
  outside the main measurement. Fallback generation paths are explicitly marked.
- No cache clear. Initial cache warmth unknown; source changes may invalidate
  source-keyed news caches once at deployment. This is not a cold/warm speedup
  comparison and does not claim an optimization.

## Local verification

- Focused collector/cache/performance contracts: 177 passed (26.96s).
- Additional exact app AST check against immutable e56b95e0 plus measurement
  tests and two older AST gates: 10 passed (14.73s). Only approved measurement
  statements/wrappers and moving rerun after trace completion are normalized.
  Existing decisions and all other app functions remain under their old contracts.
- Report gate: baseline 207 passed + existing theme-selection whole-app AST
  failure; final same 207/one failure (48.274s gate wall). No golden regeneration.
- Independent instrumentation review: no remaining actionable findings.
- Full decision gate: 1,367 passed, 142.873s, unchanged source hashes;
  `cache/refactor_checks/decision_ny78ipmy`. Production acceptance pending below.

## Production acceptance

Pending deployment and one complete authenticated generation with matching
output hash and loaded/disk source hashes. Do not use today's interrupted outer
`today_queue` record as the report's generation duration.
