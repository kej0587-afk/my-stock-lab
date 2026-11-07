# Stock Lab Work Handoff

Updated: 2026-11-08 KST. Read before inspecting large source files or editing.
Check Git first; this document is not evidence that another computer has no newer edits.

## Resume Safely

1. Run `git status --short`, `git branch --show-current`, `git log -6 --oneline`
   and inspect upstream after `git fetch origin`. Preserve uncommitted/divergent work;
   never reset or force-pull it. Use `pull --ff-only` only on clean, compatible history.
2. Read AGENTS.md, this file and the latest linked measurement record below.
3. Use the installed environment. Home verification used
   `.venv311/Scripts/python.exe`; the other computer used `venv/Scripts/python.exe`.
4. Private exports/screenshots are outside Git and may not exist on another computer.
   Do not commit account data or secrets. Request login only if the UI needs it.

Repository: `https://github.com/kej0587-afk/my-stock-lab.git`, branch `main`.
Production: `https://3insky.streamlit.app/`.

## Current State

Latest task: **flow scope production acceptance completed after user reboot**,
deployed `9e393fe6` (application change `c96dfaa5`). Fresh authenticated precision
session verifies both new columns in UI and completed ZIP for121600.KQ standalone
and radar-backed paths. Scope/group correctly distinguish stock-history observation
from radar swing selection. Both exports: restart false, stale modules empty,
loaded/disk flow_connection hashes equal. Every old connection-table field matches
its respective saved baseline; all ten OHLCV comparisons pass. Same-session seven
core CSVs are byte-identical across flow refresh. Against older same-route exports,
six of seven core CSVs per route match byte-for-byte; final_check differs only in
macro detail1.4 ->0.5, matching exported context.macro_risk, with status still pass.
Do not claim old/new input identity or a complete final_check byte match. No code,
score, cache or policy changes this task. Prior regression gate not rerun for docs.
Private evidence: `cache/flow_scope_reboot_*`; no private files in publication.
The planned bounded refactor and this pending display acceptance are now closed;
this does not mean all large functions or provider/data limitations are resolved.
See [scope acceptance](docs/maintenance/20261107_flow_reference_scope.md).

Latest task: **flow scope production acceptance attempted**, deployed `c96dfaa5`.
Fresh authenticated tab completed standalone121600.KQ at2026-11-07T14:58:21Z.
The ZIP confirms new disk commit but old `stock_lab_core.flow_connection` in memory:
restart_required true, that single monitored stale module, and both new columns
absent. UI also explicitly requests Reboot app. User was asked to reboot based on
this evidence; production acceptance remains pending, not a new code regression.
Seven core CSVs and all five OHLCV CSVs match the preserved same-mode standalone
export byte-for-byte. No code/score/cache changes or new speed claim. Private
evidence: `cache/flow_scope_cloud_{standalone.zip,acceptance.json,stale.png}`.
See [scope diagnosis and acceptance](docs/maintenance/20261107_flow_reference_scope.md).

Latest task: **flow reference scope diagnosis/display clarification**, base `3ec0137c`.
Four saved cases have identical common returns, volume growth, flow score, dates
and timing; all20 exported OHLCV files match byte-for-byte. Actual verdict-helper
replay reproduces8/8 labels, and changing only candidate group reproduces4/4 radar
labels. Standalone context omits radar candidate selection; radar assigns swing/
recovery groups. Missing extra fields are the explicit compact-column projection,
not changed/zero metrics. No numeric/selection/scoring bug demonstrated by these cases.
Added only two display columns to `flow_connection_rows`: evaluation scope and
candidate group. Existing verdicts, gates, input rows, source choice, score and I/O
are unchanged. Focused156 before/163 after passed (19.65s). Decision gate1,334
passed, zero failures/errors/skips/source changes,101.453s
(`cache/refactor_checks/decision_sf6xc782`). No golden regeneration. Publication
contains helper/tests/docs; production display acceptance is still pending.
Private replay/history evidence is ignored under `cache/kr_flow_*`.
See [scope diagnosis](docs/maintenance/20261107_flow_reference_scope.md).

Latest task: **four KR sector-RS production acceptance**, deployed `b06916f8`.
Fresh in-app tab restored control. Four completed precision exports before and
after the existing flow-summary refresh (21:57 KST) confirm mappings/provenance,
2026-11-06 RS dates and exact local RS matches:121600/305540 +33.567044%,
006280/143860 +11.670106%,092730/228790 +22.822404%,003490/140710 -1.176051%.
Sector fields remain identical. Seven core CSVs per ticker (financial inputs,
candidate grade, main decision, final check, execution readiness, entry plan,
workflow display) are byte-identical:28/28 pass. Same free-ticker mode, explicit
listing suffixes; no registered/free-mode equivalence or new Today95-row claim.
Build matches; monitored stale modules empty/restart false. No code/score/TTL change.
Full execution workflow differs in flow references after summary refresh:
source changes from stock-history reuse to radar, with reference labels changing
from observation to swing/recovery. Root cause not yet determined; core decisions
are unchanged. This is the next bounded investigation, not silently dismissed.
Private evidence is ignored under `cache/kr_rs_*`; docs-only publication, no reboot.
See [four-case Cloud acceptance](docs/maintenance/20261107_sector_rs_cloud_acceptance.md).

Latest task: **SEC annual evidence production acceptance**, deployed `ed5539b3`.
Fresh tab in the selected in-app browser recovered authenticated access; old-tab
binding still failed. No reboot/login/permission changes required. Actual NBIS
SEC query, annual tables, source expander and JSON download succeeded on Cloud.
Query time2026-11-07T12:46:46.261046+00:00; CIK0001513845;2023–2025 USD periods.
All parsed annual records exactly match the local official-source result.
Before/after completed ZIPs have byte-identical financial inputs, candidate grade,
main decision, final check, execution readiness, entry plan and workflow display.
Build matches deployed commit; monitored stale modules empty/restart false. New
SEC helper is outside that monitor list, so actual UI/data verified separately.
No runtime fix or score/DB write. Docs-only verification; previous tests not rerun.
Private ZIPs/JSON/screenshot remain ignored under `cache/nbis_cloud_*`.
See [Cloud acceptance record](docs/maintenance/20261107_sec_annual_cloud_acceptance.md).

Latest task: **read-only SEC20-F precision panel**, base `5c83e217`.
User authorized proceeding with code/test work while browser control is blocked.
Added11 UI lines plus a separate evidence view: explicit ticker/CIK-verified SEC
request, latest3 annual periods, continuing/discontinued cash-flow columns,
balance/missing-data tables, field provenance and JSON download. Owner/ticker-scoped
reruns make no panel request; failed refresh clears old display and sanitizes errors.
Existing score/provider/cache/DB paths and all top-level app functions are unchanged.
Automatic20-F scoring remains unsupported; the panel supplies review evidence only.
Focused tests46 before/57 after; final combined99 passed (16.97s), including11
UI/isolation contracts. Actual local official company list and companyfacts both
HTTP200 through the panel loader; NBIS2023–2025 recovered, scoring eligibility false.
Decision gate:1,327 passed, zero failures/errors/skips/source changes,105.532s
(`cache/refactor_checks/decision_wl3rgaq6`). Publication scope: UI/helper/tests/docs only.
Cloud access/configuration and saved-result parity are unverified; no reboot request
is justified by the browser-control error alone. Four sector-RS checks remain open.
See [SEC annual panel verification](docs/maintenance/20261107_sec_annual_review_ui.md).

Latest task: **NBIS official annual evidence reader**, base `febb067e`.
User completed local SEC identity setup. Verified presence/format without exposing
the value; one actual companyfacts request succeeded (HTTP200,1,568,737bytes).
Committed public fixture contains83 unchanged official USD facts for2023–2025;
full raw payload/secret remain ignored. Added isolated offline20-F/20-F/A annual
review reader, with explicit CIK/currency/as-of, per-field provenance, missing-data
and business-scope flags. Continuing/discontinued cash flows remain separate.
No quarters/latest-earnings claim, scores, DB writes, provider routing or app imports.
Existing app and10-K/10-Q parser unchanged; NBIS runtime failure is not yet fixed.
Focused tests57 before/88 after (13.66s). Decision gate:1,327 passed, zero failures,
errors/skips/source changes,101.773s (`cache/refactor_checks/decision_ir07t9cm`).
All83 fixture rows match the actual payload; full source latest3 annuals exactly
match fixture output. Local source access is resolved; Cloud access/UI unverified.
Publication scope: isolated module/tests/docs; publishing changes no app behavior
and needs no reboot. No production UI verification is claimed for this module.
See [official annual evidence verification](docs/maintenance/20261107_sec_20f_annual_review.md).

Latest task: **four missing KR sector-RS mappings**, base `d9900090`.
User explicitly allowed moving past blocked SEC work. Audited the four
`벤치확인 필요` rows from the preserved95-row export: all lacked explicit mappings,
not intentional exclusions. Added four mappings and dated source/proxy notes:
121600->305540,006280->143860,092730->228790,003490->140710 (KR suffixes preserved).
No existing mapping or executable app/core code changed. Market RS used in scoring,
financial grades, thresholds and judgement labels remain unchanged. Sector evidence
for these four intentionally changes from missing to a computable comparison.
Actual local production price-loader calls for all eight stock/ETF histories
yielded61 common sessions, matching2026-11-06 dates,20-session RS on Close/Close.
Focused sector/RS tests:57 before,62 after. Decision gate:1,327 passed, zero failures,
errors/skips/source mutations,103.707s (`cache/refactor_checks/decision_x0_pflhf`). See
[mapping verification](docs/maintenance/20261107_sector_rs_four_gaps.md) for gate
results and data-source limits. Operating Cloud UI/cache refresh remains unverified.
SEC20-F was deferred at this point; the subsequent isolated-reader task above
resolves local acquisition/parsing only, not runtime integration.

Latest task: **NBIS official fixture acquisition**, base `554cafd1`.
Direct official original20-F download returned HTTP403 (2026-11-07 11:03:32 UTC).
No retry with rotated/spoofed identities; no financial fixture obtained. Research
access still reads the official filing text, which is not a raw companyfacts or
iXBRL fixture. Local `sec_user_agent` absence was checked without printing secrets;
user setup requested. Absence is not proven to be the cause of403, and setting it
does not guarantee transport recovery. Official issuer IR supplied earnings-release
links, not a verified20-F payload in the inspected pages.
New acceptance finding: the2026-05-22 20-F/A adds Exhibit97.1 only; it does not
replace financial disclosures in the2026-04-30 original. Latest filing alone must
not erase prior valid financial facts. Parser implementation remains pending a
legitimate source fixture; no runtime/score/DB changes. See
[fixture acquisition record](docs/maintenance/20261107_nbis_fixture_acquisition.md).

Latest task: **one US financial failure diagnosis (NBIS)**, base `8bdc407e`.
Saved evidence confirms FMP402 and a resolved SEC CIK followed by insufficient
parsed annual records. Official NBIS 2025 20-F contains US-GAAP multi-year
statements. Current SEC parser excludes 20-F twice: form allowlist and 10-K-only
annual anchor. A synthetic form-isolation probe reproduced 0 annual records for
20-F, still0 with allowlist-only relaxation, and3 for identical 10-K control.
The wrapper also hard-codes annual report labels to10-K. This is confirmed parser
coverage loss, not proof of absent company statements. Live companyfacts payload
could not be fetched through the research tool; no latest Cloud transport recovery
or exact NBIS fact/tag coverage claim. Existing SEC/review tests: **57 passed**,
16.47s. No app/provider/score changes, DB writes or recalculation; docs only.
See [NBIS bounded diagnosis](docs/maintenance/20261107_nbis_financial_failure_diagnosis.md).

Latest task: **authenticated production DART import roundtrip**, deployed base
`142e749a`. User reported table setup complete; actual production INSERT,
duplicate rejection/recovery and exact-scope SELECT all succeeded through the UI.
Uploaded the unchanged recent collector JSON, verified corporate/listing identity,
and reloaded its half-year data plus explicit Q3 no-data status from private storage.
Before/after completed precision exports match selected/result ticker. Financial
inputs, candidate grade, main decision and final check are identical; execution
workflow differs only in calculation time. Build matches `142e749a`, monitored
stale modules are empty and restart is not required. No runtime changes or score
recalculation. Private exports/screenshots remain ignored. Production path verified
for one authenticated owner/company/scope, not all users/providers or RLS denial.
See [production roundtrip record](docs/maintenance/20261107_dart_evidence_live_roundtrip.md).

Latest task: **precision DART file preview/import UI**, base `5cadb203`.
Connected the non-ETF Korean-stock financial-evidence expander to strict preview,
explicit corporate/listing identity verification, private import and exact-scope
stored-evidence lookup. Preview alone does not write or fetch; normal reruns reuse
owner/ticker-scoped state. Identity expires after at most10minutes; partial/expired/
mismatched files cannot be saved. Demo is preview-only. Missing schema displays
setup guidance and the prepared SQL download; migrations never run in the app.
Existing app function ASTs match the baseline exactly; scores/decisions unchanged.
Standalone Streamlit AppTest: **14 passed**, including button lifecycle, account
switch, schema missing, duplicate import and raw-uploader rendering.
Combined UI/store/collector/financial tests: **145 passed**, 17.47s. Fixed-source
decision gate: **1,327 passed**, 100.663s; no skips/changes/golden regeneration,
evidence `cache/refactor_checks/decision_w6u3nx3x`. Code and docs ready for publication.
At implementation time live setup/roundtrip were unconfirmed; the subsequent
production verification above closes that acceptance step. No schema execution
was performed by the agent.
See [precision evidence UI verification](docs/maintenance/20261107_dart_evidence_precision_ui.md).

Latest task: **private immutable DART evidence storage adapter**, base `9054d62b`.
Added owner-bound INSERT/SELECT with exact duplicate verification, payload validation,
and an indexed scope hash so another report period cannot satisfy the same lookup.
Prepared `docs/20261107_dart_evidence.sql`: one new private table/index/policy,
SELECT/INSERT-only server access. **SQL has not been executed; no live DB access.**
Focused storage/collector/financial tests: **131 passed** (15.01s), using actual
PostgREST builders with mock HTTP transport. SQL syntax: 10 statements parsed;
not a live RLS/DB integration test. Existing runtime and decision files unchanged.
Fixed-source decision gate: **1,327 passed**, 100.682s, no skips/source changes;
evidence `cache/refactor_checks/decision_9gnax73k`. No golden files regenerated.
The adapter is not wired into the UI yet; publication does not require a reboot.
See [DART evidence storage verification](docs/maintenance/20261107_dart_evidence_storage.md)
for shared-project migration impact, semantics and remaining limits.

Latest task: **local DART collector and version-1 evidence validator**, base
`db70567e`. Added a standalone bounded collector, strict JSON validator and CLI;
no app import, score calculation, DB write or Cloud UI change. Existing runtime
files and golden baselines remain untouched. Output stays under ignored local
cache, with exclusive creation so prior successful files cannot be overwritten.
Focused bridge/corporate/review/refresh tests: **129 passed** (14.15s).
Final fixed-source decision gate: **1,327 passed**, 100.825s; evidence
`cache/refactor_checks/decision_jz5id7nk`. No tests skipped or golden regeneration.
Actual local official fetch: one company, half-year success, Q3 CFS/OFS no-data;
1 report / 223 rows / 3 statement requests / 1.191s statement time. The lack of Q3
is explicit, not filled with estimates. Final offline validation passed.
This step does not repair Cloud transport or enable importing evidence into the UI.
Publication includes only isolated local tooling/tests/docs; no restart required.
See [collector implementation and verification](docs/maintenance/20261107_dart_evidence_collector.md)
for commands, private evidence location, semantics and remaining boundaries.

Latest task: **read-only DART evidence bridge design**, base `8cda6db8`.
Selected local raw collection -> authenticated file preview/import -> a dedicated
owner-scoped table in the existing Supabase project -> precision evidence review.
Defined provenance, expiry, partial-data handling, immutable imports and strict
separation from saved grades. Existing report/account tables cannot be reused.
This is a documentation-only design: no collector, table, schedule or upload UI
has been implemented, and Cloud financial transport remains unavailable.
Verified against current parser/review/auth/storage contracts and official DART
and Supabase documentation; no runtime or production validation claim.
Documentation checks: local links resolve, exactly one Next Task Only section,
and whitespace check passes. Documentation-only publication; production code stays
unchanged, so no app restart is required for this task.
See [DART evidence bridge design](docs/maintenance/20261107_dart_evidence_bridge_design.md).

Latest task: **Cloud DART corporate-code connection diagnosis/recovery**, base
`ee6a789e`. Diagnostic build `2f79bc3c` proved production connect timeout at
8.021s, no HTTP/API response or payload. Local official API returns 4,013 public
mappings in 2.638s. Added safe transport diagnostics and a dated official public-ID
snapshot fallback for transient transport failures only. No API keys, account
data, private tickers/weights or financial statements are in the snapshot.
Snapshot requires an official refresh after 7 days; it does not fix live network
access or provide latest earnings. Existing cache TTLs and all saved scores,
thresholds and decision text remain unchanged. No golden regeneration.
Final focused tests **66 passed**, decision gate **1,327 passed** (101.628s),
`cache/refactor_checks/decision_k9w2y2li`. Code `1b612377` pushed and verified in
production. Completed precision ZIP confirms matching selected/result ticker,
unchanged saved score/source, no stale entry among monitored modules and no
restart requirement. UI confirms `official_snapshot`, 4,013 mappings, as-of and
expiry; selected corporate code now resolves. **The subsequent financial API also
fails transport, so live DART financial retrieval remains unavailable in Cloud.**
No end-to-end live-connection or latest-earnings recovery claim. The bundled map
expires 2026-11-14 17:07:49 KST (subject to ordinary 30-minute map caching).
Private evidence: `cache/dart_cloud_connect_timeout.jpg`,
`cache/dart_cloud_snapshot_recovery.jpg`, Downloads
`precision_review_329180.KS (2).zip`. No API keys or private exports committed.
See [Cloud DART connection record](docs/maintenance/20261107_dart_cloud_connection.md)
for safe diagnostics, public snapshot maintenance and remaining network limits.

Latest task: **financial-input provenance audit and bounded repair**, base
`009b74c4`. Audited all 12 missing-auto/manual inputs and 8 stored failed/simplified
inputs against the authenticated read-only backup. Eleven lack a DB score row,
one is manual-only; four KR failures are old Naver summaries, four US failures
record FMP HTTP 402 plus insufficient parsed SEC annual data. Current KR providers
return through Q2 2026, not every latest earnings announcement; FMP 402 reproduced.
Fixed DART error loss/repeated requests and one proven OCF account-name omission.
Precision now offers explicit read-only provider refresh/comparison; no saved
score, judgement threshold/text, manual override or account data was changed.
Before/after decision gates **1,327 passed**, final 101.185s, evidence
`cache/refactor_checks/decision_5l_tifla`; focused financial tests **163 passed**.
Historical broad AST guard now excludes only these covered financial repairs;
decision/flow bodies and original Git baselines remain frozen. No golden updates.
Deployment: `85eb8c1a` pushed; production read-only review rendered and complete
precision ZIP confirmed the selected/result ticker and unchanged saved score.
Cloud exposed a corporate-code lookup failure, unlike local DART success.
Follow-up shortens empty-map caching to the existing 60s failure cooldown,
retains 30-minute successful-map TTL, and clears the map on explicit review.
The comparison metadata is now vertical to avoid clipped failure reasons.
Follow-up `ba0b243c` pushed and verified in production: completed review ZIP has
matching selected/result ticker, retained saved score/source, no stale module in
the monitored list, no restart required. Vertical comparison table renders.
**DART corporate-code mapping still fails in Cloud after explicit cache clearing.**
Do not claim provider recovery or newest actuals are complete. Local DART succeeds;
the current map loader suppresses its response/transport details, so the precise
Cloud cause is unproven. Next work is only that production failure (below).
See [financial audit](docs/maintenance/20261107_financial_input_audit.md) for exact
provider findings, latest-release limits, private evidence and preservation scope.

Latest task: **final optimization/refactor closure**, base `d459f693`.
Initial combined gate: 1,774 passed / one previously recorded structural-test
failure. AST diff contains only the approved SMC/finalization extractions;
updated the older test to reuse their existing AST adapter, keeping all frozen
baseline commits and real helper-body/call/output tests. Focused verification:
41 passed. Final combined gate **1,775 passed**, zero failures/errors/skips,
171.623s; all524 source/test/fixture hashes unchanged during the run. Evidence:
`cache/refactor_checks/all_n4m86e0j/summary.json`. No production code or investment rules
changed. Preserved 15:53 production export matches all102 current app/core source
hashes (LF-normalized), no stale modules; later commits changed only docs.
See [closure record](docs/maintenance/20261107_refactor_closure.md) for counts,
data freshness limitations and evidence boundaries. This closure record and the
test adapter are committed/pushed together. **The bounded optimization/refactor
sequence is complete; no further speculative extraction is scheduled.**

Latest task: **four-view integration checkpoint**, base `ffa04ee9`.
No demonstrated wiring defect; production code/rules unchanged. Live Today
completed ~78.2s (displayed, not controlled A/B); 95 rows/32 flow candidates.
Held KR ETF and registered US stock match across ten Today/precision fields
on the 2026-11-06 session. Radar reuses the same 15:48 snapshot. Portfolio after
precision retains 10/10 scoped signals with price dates and the reviewed ETF's
final restriction. Free exploration uses a distinct existing policy; switching
to registered mode resolves the apparent raw-code difference. Completed ZIPs
confirm `ffa04ee9`, no stale modules/restart requirement. Focused tests199 +
frozen-input tests55 pass; private ten-holding replay has zero mismatches.
See [four-view integration](docs/maintenance/20261107_four_view_integration.md)
for evidence, source freshness limits and the unsuccessful grid CSV download.

Latest bounded change: **theme selection/description UI extraction**, base `9cd5f6a2`.
Only `_render_image_theme_selection` was introduced in app.py; widget keys,
labels, order, metadata HTML, empty-theme guard and lazy data-loading sequence
are unchanged. Report gate before **180 passed**, after **208 passed**;
adjacent contracts **186 passed**. Immutable baseline AST and 28 new UI event
contracts pass; no golden regeneration or investment-rule changes. No runtime
speedup is claimed. Code `6cae5e7e` pushed. Production reopened successfully; theme/metadata/ETF
chip and market selection (all -> overseas -> all) verified, lazy state remains
waiting. No runtime source fingerprint was collected for this UI-only check.
See [theme selection extraction](docs/maintenance/20261107_theme_selection_extraction.md).

Current bounded change: single-row source-flow normalization, base`125748fc`.
`build_source_flow_context` uses the existing scalar rules directly, avoiding
repeated one-row DataFrame/apply work. Generic multi-row path and all investment
rules remain unchanged. Full-row/null/order/history parity:156 tests passed;
adjacent summary/observatory/AST contracts:32 passed. Decision gate before1171 /
after1327 passed, zero failures/errors/skips. Code and record pushed together;
**`d5dc6c02` pushed and production verified**: full run
`d7330531d2d046b98cf29e2878ee7c3b` (14:34–14:35 KST),95 rows,**83.929s**,
script92.993s, zero instrumented errors. Loaded/disk/local app hashes match;
no reboot needed. Previous95.186s is not a controlled A/B: analyst70 cache reuses
vs0 before (phase8.900 ->1.862s). Prices still54.497s active; no claim that all
11.257s improvement comes from this patch. Current verification is docs-only.
Fixed20-case residual median **.426508s -> .321040s (-24.73%)**, source-flow mean
**.251149s -> .144432s**; complete output hash unchanged, zero replay network.
Final four-worker median.332098s also matches the original complete outputs.
This is local partial computation, not a Cloud/full-check speedup. See
[single-row normalization](docs/maintenance/20261107_source_flow_row_fastpath.md).

Latest completed task: **fixed-input residual summary profile**, base`5953ce37`.
Production app/core unchanged; added `scripts/profile_summary_local.py` only.
20 existing seeded scenarios, five repeats: sequential median**0.427s**,
four-worker**0.449s**. Full rows match across instrumentation/repeats/workers;
frames unchanged, zero replay network attempts. Related tests**29 passed**.
Source-flow metrics/normalization dominates local remaining work (**59.46%**),
pattern detection32.72%, workflow2.25%. One-row DataFrame normalization is a
bounded improvement candidate. Parallel summed self time inflates substantially
without equivalent CPU/wall growth; do not treat Cloud42.481s as removable CPU.
This is not a live speedup; last full Cloud result95.186s remains the reference.
No production reboot needed. See
[fixed-input profile](docs/maintenance/20261107_summary_fixed_input_profile.md).

Current task: **`50283998` pushed**, summary-worker/analyst wait instrumentation
based on `f746134c`. Focused tests 166 passed; prices gate 265 passed / one same
pre-existing decision AST failure. Decisions, calls, cache policy and concurrency
unchanged. Full Cloud run `0d35d5810c284faf924b437fb1a4f7f8` (12:01–12:02 KST):
95 rows, **86.710s**, script 94.680s, zero instrumented errors. Previous 107.934s
is not a controlled A/B speed comparison. Analyst phase **1.896s**; 73 callbacks
sum 5.245s. Summary live alignment sum32.015s, leverage review11.810s,
financial score5.413s; parallel sums, not exclusive waiting/wall time.
**After user Reboot, new reader verified:** full run
`03869fcad7d54ba5a1de6d614dc3d7c4`, build `019b9950`, 12:42–12:43 KST.
95 rows **95.186s**, script101.073s; analyst phase8.900s. All73 analyst lookups
were misses (70success/3unavailable). Analyst Yahoo lock-wait sum20.210s,
throttle1.237s, provider7.558s; FnGuide4 HTTP calls sum5.645s. These overlap,
not additive wall time or guaranteed savings. Global serialization is unchanged.
Prices remain largest active union55.496s. Remaining summary self sum42.481s
is unclassified elapsed time, not established CPU/wait. No instrumented errors;
loaded/disk/local app hashes match and new events prove reader execution.
No further reboot required. Documentation-only verification this turn.
See [wait diagnostics](docs/maintenance/20261107_summary_wait_diagnostics.md).

Latest change: **`a25bd5ff` pushed**, exact **6mo leveraged-watch batching**, based on `b82d1b61`.
One summary scope shares successful frames, avoids overlapping batch duplicates,
and retains KR/missing/forced-refresh/original precision paths. No rules changed.
Focused contracts 205 passed plus final batch contracts 44 passed. Prices gate
remains 265 passed / one pre-existing AST failure. Local measured path 7.567s ->
2.437s, actual Yahoo chart HTTP 23 -> 23; not a controlled Cloud speedup.
**After user Reboot, new path verified** in full Cloud run
`6f1101e4f03b4f929275cce41dcfeb6e` (11:26–11:27 KST), build `42e80cb1`:
95 rows, **107.934s** / script 119.269s, zero instrumented errors.
Four 6mo batches, 13 shared hits, 36 batch-frame hits, two original KR fallbacks;
new quote/history/batch timers present. New path union 12.250s. Prior 90.206s
run used the old module; the latest full run is slower, not a proven speedup.
Analyst phase 2.212s -> 9.038s, stock signals 25.054s -> 34.858s; conditions differ.
KR scope still reuses 30 requests (416 -> 386 HTTP). All cache/rule settings kept.
UI/export ID and local/loaded app hashes match; no further reboot needed. See
[watch-history record](docs/maintenance/20261107_leveraged_history_batch.md).

Earlier measurement: **KR provider-cache expiry run**, 2026-11-07 09:37–09:39 KST,
ID `2f717dae89a341ba8e3c2f08676d4bcd`, build `5b5d81f6`. About 48 minutes elapsed
since the last visible calculation; no preliminary price/flow reload. Same
95-row calculation/settings. **91.089s** Today Check / **94.807s** script.
Actual duplicate reuse confirmed: 427 provider-cache lookups = 13 existing-cache
hits + 414 reader calls; **414 = 384 HTTP requests + 30 new-scope reuses**.
30 bypass events preserve cache age. No instrumented errors. Provider misses
96.96%; financial caches can still be warm, so not a fully cold app benchmark.
Price / indicator / external-data active unions: **56.841 / 19.137 / 28.666s**
(overlapping). Prices still dominate; leveraged watch rows cover 17.129s active
union (five builds, 38 rows), a bounded next I/O target. No code/rule changes.
See [expiry measurement](docs/maintenance/20261107_kr_history_expired_measurement.md).

Latest code: **`661431f9`**, exact KR daily-history request reuse, pushed and
verified executing in production (`kr_history_scope.enabled_v1=1`, 277 lookups).
Only identical resolved provider/date/count requests share successful copied
frames in one run. Existing TTL/failure/refresh and decision rules unchanged.
Fixed-response requests 8 -> 5; actual local Naver duplicate requests 3 -> 1
(1.125 -> 0.352s), with all 244-row frames exactly equal. All non-wrapper app
functions match immutable `24244c3e`; decision golden checks pass.
Focused tests 77 passed. Prices gate retains the same pre-existing structural
AST-freeze failure before/after (259 / 265 passed); no golden rebasing.

Adjacent full production runs: **89.438 -> 70.245s**, same 95-row count/settings,
but provider caches were warmer afterward and new-scope reuse was **zero**.
Do not attribute the 19.193s reduction or 416 -> 277 KR requests to this change.
Before had one recovered overseas fallback ConnectTimeout; after none.
No reboot required, no account changes. See the exact IDs, cache limitations,
request proof and private evidence in the
[request reuse record](docs/maintenance/20261107_kr_history_request_reuse.md).

Previous task: **production Today Check bottleneck measurement**, on build
`bd65d26b`, measurement `e36d58ac51f7463b9d86820aa3c4f8f9` (2026-11-07
04:05:46–04:07:24 KST). Complete 95-row calculation: 98.540s wall, 101.682s
including entry/bookkeeping. Standard refresh, not fully cold; unchanged scope.
Price / indicator / external-data active unions: 66.016 / 20.936 / 23.361s;
these overlap and must not be summed. KR history made 414 HTTP requests, with
30.074s active union; the number of avoidable duplicates is not yet established.
Analyst enrichment (1.800s) and KR cluster snapshots (0.524s) are not the current
dominant bottleneck. Completed export/UI ID and local build matched; tracked
report modules were not stale. Documentation-only task, no reboot needed.
See [full measurement and limits](docs/maintenance/20261107_today_bottleneck_measurement.md).

Latest bounded refactor: **`051ac66c`**, pushed from clean/equal `11565166`.
Extracted only SMC context assembly into
`stock_lab_core/decision_smc.py::build_decision_smc_context`.
All ten original locals and seven dependency calls retain their order; result
assembly, detector algorithms, charts, thresholds, labels and amounts unchanged.
`calc_scores_and_decision`: 467 -> 463 lines; no measured speedup claimed.
The purpose is responsibility isolation, not merely reducing line count.

Verification: decision gate **1,132 passed before** (93.962s), **1,171 passed after**
(95.224s, 39 new tests). Focused SMC/follow-up/priority/import tests: 174 passed.
Twenty pre-edit full results match; exact unrounded outputs, dependency order,
nonmutation, failure propagation and loaded/stale provenance verified.
No golden files regenerated; immutable reference Git `11565166`.

Post-push GOOGL precision calculation, SMC detail display and review ZIP passed.
New helper loaded/disk/local hashes match; no stale modules/restart required.
No account/watchlist edits. Private UI/ZIP evidence is linked in the record below.

Latest record: [Single-row source-flow normalization](docs/maintenance/20261107_source_flow_row_fastpath.md).

## Preserved History

- `042c0bef`: idempotent ETF exemption writes prevent clearing saved signals on
  precision visits. Decision gate 1045 passed; Cloud retained all 10 connected
  results after the visit. See the connection review below for exact evidence.
- `ff2e8490`: exact-parity MFI window optimization. Selected all gate 1453 passed;
  fixed-input indicator benchmark improved 26.9%. Cloud repeat times were noisy
  (roughly 70s), first-load time did not improve; no sub-minute guarantee.
  Full timing/cache/deployment limits are in the MFI record below.
- Home baseline branch `codex/home-baseline-20261106-29d90955` remains local.
  No user edits were discarded. Private exports/screenshots stay outside Git.

## Next Task Only

**On the next request, refresh the Today financial-input completeness inventory.**

The current bounded refactor/display verification is finished; do not start another
extraction by default. Use one completed Today export to distinguish saved scores,
official review evidence and missing latest-release dates, comparing with the old
95-instrument inventory without assuming the universe is unchanged. Report actual
remaining gaps; do not change scores, automate20-F scoring or fabricate dates.
Cloud live DART financial transport and SEC interim/IFRS support remain unresolved.
Private exports stay outside Git. This next inventory is not an unfinished part
of the accepted two-column display change.

## Evidence and Remaining Limits

- Latest: [Single-row source-flow normalization](docs/maintenance/20261107_source_flow_row_fastpath.md).
- Latest: [Fixed-input summary profile](docs/maintenance/20261107_summary_fixed_input_profile.md).
- Latest: [Summary/analyst wait diagnostics](docs/maintenance/20261107_summary_wait_diagnostics.md).
- Latest: [Watch history batching](docs/maintenance/20261107_leveraged_history_batch.md).
- Latest: [KR cache expiry measurement](docs/maintenance/20261107_kr_history_expired_measurement.md).
- Previous: [Exact KR request reuse](docs/maintenance/20261107_kr_history_request_reuse.md).
- Previous: [Today Check bottleneck measurement](docs/maintenance/20261107_today_bottleneck_measurement.md).
- Previous: [SMC context extraction](docs/maintenance/20261107_decision_smc_extraction.md).
- Previous: [Decision finalization extraction](docs/maintenance/20261107_decision_finalization_extraction.md).
- Previous: [Theme stock display extraction](docs/maintenance/20261107_theme_stock_display_extraction.md).
- Previous: [Theme group display extraction](docs/maintenance/20261107_theme_group_display_extraction.md).
- Connection: [Held-view connection review](docs/maintenance/20261107_held_view_connection_review.md).
- Performance: [MFI window optimization and measurements](docs/maintenance/20261106_mfi_window_review.md).
- Previous: [Yahoo chart connection measurements](docs/maintenance/20261106_yahoo_chart_connection_review.md).
- Workflow: [Bounded refactor review](docs/maintenance/20261106_bounded_refactor_review.md).
- Previous timing IDs are in the MFI record. Connection evidence is in the held-view
  review; latest refactor verification is in the theme extraction record.
  Full JSON/ZIP/screenshots remain outside Git.
- The preceding connection optimization improved its quote segment but not full
  runtime (64.779s -> 66.336s on a different 96-row input). Do not blend those old
  measurements with today's 95-row runs or claim a sub-minute guarantee.
- Broader refactoring and investment-rule redesign remain separate future tasks.
