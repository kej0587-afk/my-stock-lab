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
  `cache/refactor_checks/decision_ny78ipmy`. Production acceptance completed below.

## Production acceptance

Runtime **6ac42e31**, test/docs follow-up **64f12040**, accepted in authenticated
Cloud after the user's reboot. Previously stale modules no longer block generation.
On 2026-11-08 KST, measurement **22bf0c2dc45b47538e96953665062f70** completed via
the normal path, with no fallback reasons. Build 64f12040, `restart_required=False`,
zero stale modules. All 100 monitored sources match local files after CRLF/LF
normalization. Exported Markdown SHA256 matches the dedicated measurement.

The reboot cleared Today results, so a full Today calculation prepared 95 rows
before generation. Its duration is excluded from the report timer. Same 11 market
categories, two articles/category, market RSS on, watched-stock RSS off (disabled
limit 4). No cache clear; price cache partly warm, news/body misses observed below.
This is one measured workload, not a cold-cache benchmark or a before/after speedup.

| Exclusive generation stage | Seconds |
| --- | ---: |
| Macro / official disclosures / investor evidence | 21.098 |
| Prices / history / alignment | 15.816 |
| Markdown report assembly | 9.538 |
| History storage / context connection | 6.103 |
| News RSS / selection | 1.959 |
| Article body retrieval / interpretation | 1.198 |
| Closed-session indicator calculations | 1.066 |
| Preparation / cached flow snapshot | <0.001 |
| **Generation total** | **56.778** |

Stage sum differs from total by only 0.000007s. App-script work *before* entering
generation adds **23.290s**; script start through saved Markdown is **80.068s**.
Initial page navigation, prerequisite Today calculation, final rerun/browser paint
and diagnostic serialization are not a measured user-visible end-to-end latency.
The 56.8s number must not be presented as a sub-minute click-to-screen guarantee.

Largest measured generation stage is macro/official evidence (37.2%). Within it,
`apply_official_bulletins` takes **7.457s**, `load_economic_releases` **3.657s**,
`collect_report_earnings` **2.563s**, public-flow backfill **2.157s**. History update
alone takes **5.289s**. Price loading: 43 calls / 6.639s, including nine KR history
requests / 5.566s; one batch loader / 1.742s. These nested function times must not
be added to their parent stages. Google RSS cumulative work 5.844s versus active
wall 1.556s illustrates concurrency; it is not a 5.8s serial bottleneck.

### Requests and cache state

- Price history: 43 lookups, 26 reuses, 17 misses/successes; KR history nine unique
  requests/responses. Yahoo counts are **one batch + eight SDK download calls**,
  not nine proven HTTP requests. Other price transports lack exhaustive counts.
- Economic collector: eight instrumented HTTP attempts. Some official/news/other
  transports remain uninstrumented; no claim of total external-call coverage.
- Market RSS: 16 lookups/misses and 16 HTTP attempts, 15 successful-cache results,
  one unavailable/empty result. This does not establish an HTTP failure.
- Publisher feeds: four lookups/misses, four HTTP attempts, four successes.
- Article bodies: four lookups/misses, four HTTP attempts, four successes.
- RSS batch missed; incomplete batch not cached. TTL/failure cooldown unchanged.
  Total explicitly counted report HTTP attempts: 32, plus nine KR history requests.
  Never add SDK invocation counts to this partial HTTP count.

### Result preservation and evidence

Same-session generation input and output exports contain identical 95 tickers and
**all 22 score/verdict/grade/gate/flow-verdict columns match exactly** (2,090 cells).
The pre-reboot export is not a valid full parity baseline: all 95 rows then had
data-confirmation gates from stale inputs. After fresh calculation there are 80
defense, 14 watch and one data-confirmation gate; they remain unchanged by report
generation. Frozen-input decision regression above verifies code-level parity.

Private evidence (ignored, not in Git):
- `cache/report_generation_cloud.json`, matching `report_generation_cloud.md`.
- `cache/report_generation_input.zip`, `report_generation_after.zip`, and
  `report_generation_parity.json` (95 rows / 22 columns / zero changes).
- `cache/report_generation_cloud_complete.png`: full production timing panel.
- Older `report_generation_before.zip` and `report_generation_cloud_wait.png`
  retained as pre-reboot context only.

### Next bounded optimization

Reduce waiting inside **apply_official_bulletins** (7.457s measured). First split
CPI/export request and cache timing to identify the actual slow path, then apply
one safe exact-request reuse or independent-request concurrency improvement.
Current CPI and exports application is sequential; collect independently only
where existing eligibility guards permit, then apply results in the original
order. Preserve pending/current-period guards, vintage/source labels, fallback
and failure-cache semantics, timeouts, TTLs and report output on frozen inputs.
Compare like-for-like complete generation afterward; no projected saving claimed.
The separate 23.290s pre-generation work remains a later measured boundary to
investigate, not silently included in this bulletin optimization.
