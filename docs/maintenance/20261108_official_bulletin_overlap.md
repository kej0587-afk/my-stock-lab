# Official-bulletin retrieval overlap

2026-11-08 KST; baseline `44e5ba9f`, clean main synchronized before editing.

## Change and preserved contracts

The accepted Cloud generation `22bf0c2dc45b47538e96953665062f70` spent
7.456865s in apply_official_bulletins, within 21.098s macro/official and
56.778s total generation. Independent public CPI and Customs requests were serial.

Prefetch Customs in one worker while CPI remains on the owner thread, only when
exactly one row of each requires retrieval. Apply and persist CPI, then exports,
then dated manual fallbacks on the owner. Duplicate/ineligible rows keep the old
serial path. Providers, request parameters, retries, timeouts, TTLs, failure
cooldowns, latest-period/pending guards, source/vintage metadata, scores and gates
are unchanged. Network completion order can differ; shared caches retain locks.

Added fixed-label request/cache/collector/wait timing. bulletin_http overlaps the
existing economic_api counter for CPI/listing: do NOT sum both as unique HTTP.
Customs detail retries are now separately counted. Worker context propagates the
trace; worker totals can overlap owner wall time. No URLs/credentials are recorded.

## Verification

- Before: focused provider/regression tests 135 passed (2.84s).
- After: focused plus frozen-baseline parity/thread tests 158 passed (3.60s).
- Original `44e5ba9f` implementation compared against final full outputs, request
  multisets, persisted last-success bytes and unmodified inputs in 18 modes:
  cold/warm, pending/unflagged/supplied/wrong basis, complete/duplicate/single
  providers, newer/same period/source date, failures/rejection/cooldown, expired
  manual data and restored success. Tests also verify owner apply order, overlap,
  trace propagation, warm zero HTTP and unchanged cache bound.
- Decision gate: 1,367 passed, 140.489s; stable source hashes, no golden changes.
- Report gate: 207 passed, existing whole-app theme AST failure (46.23s pytest).
- Additional scope: 98 passed, two existing calendar Mock tests fail because the
  prior component timer requires __name__. Both reproduced with the baseline
  bulletin implementation (2.60s). Not a bulletin regression; left out of scope.
- Independent bounded review: no actionable findings.

Local live serial probe (not a Cloud benchmark): 4.682s total, CPI3.294s plus
exports1.388s; five actual HTTP attempts, both cache misses. Public endpoints and
existing parsers worked; local timing must not be presented as a Cloud speedup.

## Deployment and production comparison

Runtime **730d7871** pushed and accepted without a reboot. Completed/normal run
**e93556d34e58473ea2077ce7f637ebaa**, generated 17:02 KST. All 100 monitored
loaded/disk/local LF source hashes match, stale list empty, restart false;
exported Markdown SHA256 matches the dedicated full-generation JSON.

Same settings: 95 Today rows, 11 categories, 2/category, market RSS on, stock RSS
off. Today was recalculated first (~84.8s, outside report timing). No cache clear.

| Wall-time boundary | Before (s) | After (s) |
| --- | ---: | ---: |
| apply_official_bulletins | 7.457 | 7.372 |
| macro/official stage | 21.098 | 21.107 |
| prices/alignment | 15.816 | 15.819 |
| closed indicators | 1.066 | 1.094 |
| RSS | 1.959 | 2.021 |
| article bodies | 1.198 | 0.287 |
| history/persistence | 6.103 | 7.245 |
| assembly | 9.538 | 10.058 |
| complete generation | 56.778 | 57.631 |
| separate pre-generation work | 23.290 | 22.973 |
| script start to saved report | 80.068 | 80.604 |

**No demonstrated production speedup.** CPI already met the current-period
complete guard, so no CPI HTTP was necessary and the serial branch correctly ran.
Customs exports used one cache miss: listing 4.461s, detail 2.864s, collection
7.368s. Both returned HTTP200, one attempt each, no connect retry/cooldown.
The 0.085s bulletin difference is ordinary observed variation, not evidence of
the concurrency improvement. Conditional overlap is verified on frozen inputs,
but was not exercised by this production input. Do not force redundant CPI
requests just to exercise it.

Price history counts match (43 lookup/26 reuse/17 misses, nine KR requests).
RSS counts match (16 misses/15 success/one unavailable), publisher feeds four
attempts, economic_api eight attempts. Article bodies were four cache hits after
vs four misses before. These are observational production runs, not an identical
cache-state or network-controlled benchmark. Existing economic_api includes the
Customs listing; add only the newly visible detail attempt when describing the
coverage, not all bulletin counters again. Browser paint/rerun remain excluded.

95 tickers x all 22 score/verdict/gate/flow columns match both across deployment
and across this report generation (2,090 cells per comparison). The three report
rows containing KR_CPI/KR_EXPORTS also match exactly. This preserves existing
data semantics; it does not certify unrelated economic observations as correct.

Private artifacts: cache/bulletin_cloud.json, bulletin_cloud.md, bulletin_input.zip,
bulletin_after.zip, bulletin_acceptance.json and visually inspected
bulletin_cloud_complete.png. The accepted older baseline remains untouched.

## One next bounded task

Investigate **Customs listing -> detail connection reuse** with the now measured
4.461s + 2.864s chain. Detail parameters depend on the listing result; there is no
same-run duplicate or safe parallelism between these two requests. Reusing a
short-lived same-origin transport may reduce handshakes, but needs its own proof;
no saving is promised. Preserve fresh listing selection, cookies/request semantics,
HTTP parameters/response guards, retries/timeouts, failure cooldown and TTLs.
Validate fixed-input full output/request/persistence parity first and then compare
cache-miss production runs after natural expiry. Do not shortcut source selection
with an old article ID, change cache freshness, or expand to unrelated stages.
