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
- Independent instrumentation review: no remaining runtime findings. Review of
  the AST adapter found masking gaps; the adapter now rejects side-effecting
  discarded arguments, import aliases, context bindings and duplicate contexts.
  Final timing/AST/old-gate probes: 15 passed (17.67s), including five negative
  mutations. Immutable reference commits and golden files were not changed.
- Full decision gate: 1,367 passed, 142.873s, unchanged source hashes;
  `cache/refactor_checks/decision_ny78ipmy`. Production acceptance pending below.

## Production acceptance

Runtime commit **6ac42e31** pushed. Authenticated Cloud reached the report panel
after deployment but displayed a loaded-code/disk mismatch and disabled automatic
generation. Reload did not fix it. Cloud My apps redirected to GitHub login;
current app viewer menu offers Print/Record only, not Reboot. User reboot request
is pending. No full-generation time, HTTP count or bottleneck is claimed yet.

Pre-deployment 95-row export is preserved privately at
`cache/report_generation_before.zip`; UI blocker screenshot is
`cache/report_generation_cloud_wait.png`. After reboot, use the dedicated
`auto_report_<id>.json` download and matching Markdown, verify completed/normal
path and loaded/disk hashes, and compare the 95-row stored scores/verdicts.
Do not use the outer interrupted `today_queue` record as generation duration.
