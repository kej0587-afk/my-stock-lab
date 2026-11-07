# Financial input provenance audit — 2026-11-07

Base: clean `main`, `009b74c4`, equal to upstream after fetch. No user edits
discarded. Private exports, provider responses and credentials remain outside Git.

## Findings

| Observed group | Cause established from saved records/code | Current handling |
| --- | --- | --- |
| 12 absent auto calculations | 11 automatic Today inputs have no financial-score DB row; one has only a manual score. Today reads stored scores and deliberately does not run financial APIs. | Preserve temporary/manual scores; expose the distinction and allow read-only provider review. |
| 4 simplified domestic inputs | Old `naver_fallback` records with DART extraction zero, no calculation/statement dates. Original DART errors were discarded, so the historical transport/auth/parse cause cannot be reconstructed. | Current live DART returns annual 2023–2025 and single quarters through 2026 Q2 for all four. Do not overwrite saved/manual scores. |
| 4 failed US inputs | Saved FMP HTTP 402 plus SEC fewer than two parsed annual records. Local current FMP requests reproduce HTTP 402 for all four. | No subscription upgrade or fabricated estimates. Expose permissions vs SEC format/period coverage separately. |

All 20 saved inputs lack recorded statement and computation dates. A recent price,
news item or API cache refresh cannot establish that the stored financial score
contains the latest earnings. Local SEC User-Agent is absent; this does **not**
establish production configuration is absent. Current SEC fetches were not run
with invented contact credentials. The parser supports US-GAAP 10-K/10-Q only;
foreign-issuer 20-F/6-K coverage needs a separate bounded implementation.

## Latest release versus available statement

Samsung's [official Q3 release](https://news.samsung.com/global/samsung-electronics-announces-third-quarter-2026-results)
is dated October 29. On November 7, direct DART CFS calls returned status 013
for 2026 Q3 for the four sampled domestic failures, while 2025 annual and 2026
half-year requests returned status 000. Full application extraction likewise
ended at Q2. Thus **latest announced earnings are not fully reflected**; a
successful API fetch must not be labelled latest-announcement complete.

The [DART statement guide](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020)
distinguishes annual/quarter reports, cumulative amounts and XBRL account IDs.
[SEC's API guide](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
includes 20-F/6-K and IFRS, beyond this application's current parser coverage.
[Nebius's filed 20-F](https://www.sec.gov/Archives/edgar/data/1513845/000110465926052948/nbis-20251231x20f.htm)
is an example of a real report excluded by the current form filter; it is not
proof of support or of automatically comparable quarterly periods.

## Bounded repairs

- DART provider errors retain safe status/category messages instead of becoming
  empty data and repeated historical requests. Status 013 still tries OFS.
  Credential-bearing request URLs and raw provider error bodies are not echoed.
- Production review exposed corporate-code mapping failure, unlike local success.
  Empty mapping now uses the existing result-cache 60s failure cooldown instead
  of 30-minute success retention. Explicit read-only refresh clears this mapping;
  successful mapping TTL remains 30 minutes. A recovery contract verifies an
  empty response can recover to the actual ZIP mapping on explicit refresh.
- A demonstrated OCF miss: the Korean label “영업활동으로 인한 순현금흐름” did not
  match the existing keywords. Only when the original result is missing, use
  the exact CF account `ifrs-full_CashFlowsFromUsedInOperatingActivities`.
  Keep existing matches, zero values, amount-column order and all score rules.
  Live public filing `20260320000859` reproduced missing -> KRW 3,510,392,442,000
  for 2025 OCF. No earnings-release estimate was substituted.
- SEC insufficient-history results now expose namespace/form coverage. They do
  not accept unsupported forms as valid statements or change accepted results.
- Precision's financial-evidence expander gets a read-only refresh and tables:
  stored period, provider period, check time, source, missing facts and currency.
  It clears only the selected financial request keys, runs only on explicit
  button action, and never calls scoring, DB writes or derived-view invalidation.
  Existing recalculation remains a separate explicit action.

Existing saved grades/decisions, manual overrides, thresholds and judgement
wording are unchanged. A future explicit financial-score recalculation can
legitimately differ when newly recovered OCF is used; this is an input repair,
not an exact-parity change to every future provider result.

## Verification and deployment

- Before: focused financial contracts 148 passed (16.77s); decision gate 1,327
  passed (101.896s), evidence `cache/refactor_checks/decision_f34ngpg0`.
- After: focused financial contracts 163 passed (18.17s), including failure
  redaction, one-request terminal errors, OFS fallback, exact OCF total/zero,
  foreign-form diagnosis and refresh-without-score/DB-write tests.
- Initial decision recheck: 1,326 passed, one broad historical AST freeze failed
  because new financial helpers were intentionally added. Its original Git
  baseline and every decision/flow body remain frozen. Exempted only the two
  added financial helpers and five repaired provider/extractor functions, which
  have direct financial contracts; no golden files were regenerated.
- Final decision gate: 1,327 passed, zero failures/errors/skips (101.185s),
  `cache/refactor_checks/decision_5l_tifla`. No decision golden files changed.
- Initial production code `85eb8c1a` and selected/result ticker were confirmed by
  completed precision ZIP; saved financial score/source retained. Its 101 monitored
  sources reported no stale module/restart, but the new financial-review module is
  not in that legacy monitored-source list; do not claim its hash was in the ZIP.
  The new review button and its real failure result were also verified visually.
- No latency improvement claimed. No full Today rerun or all-provider/all-stock
  latest-release completeness claim; this task is financial evidence repair.

Private local evidence: Downloads `stock_lab_review_export_20261107_1549.zip`,
`stock_lab_backup_20261107_1631.zip`; ignored `cache/financial_live_audit.json`,
`cache/financial_live_parsed.json`, `cache/financial_ocf_after.json`, and financial
test logs. The authenticated backup was downloaded read-only; no account data
was edited. The 11 automatic-input origins were corroborated in master export.

## One next task

Audit and implement **SEC foreign-issuer annual statement support** separately,
starting with 20-F and actual namespace/unit/date provenance. Use fixed public
fixtures, preserve existing 10-K/10-Q outputs and saved grades; do not infer
quarterly statements from 6-K labels or broaden to an IFRS rewrite in one step.
