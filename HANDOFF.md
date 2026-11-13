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

Latest bounded work (2026-11-13): **article evidence -> market-event reading ->
top report explanation**, base da1f26c2. User superseded the previous performance
next task with report quality. No investment rules, prices, gates, providers,
request budgets or TTLs changed. New `article_market_events.py` isolates short
attributed diplomacy/leadership events and editorial selection. Diplomacy keeps
the complete source sentence (including denial/conditional wording), never turns
the word "negotiation" into optimism. Generic CEO transitions are recognized
without issuer-specific stories; denied/historical/planned/demanded changes are
not treated as completed transitions. At most four body facts remain; existing
earnings/AI-risk priority is preserved. Same-market/session verified events can
survive a generic wrap; the three-row editorial table may reuse a wrap for distinct
events instead of silently dropping every fact after its first. Named-issuer
market recaps also retain explicit oil observations. Interpretation is separate
and does not assert production cuts, competitor benefits or causal price amounts.
Body parser cache revision v11 prevents reuse of v10 interpreted bodies; added
module is monitored by report build diagnostics. Saved old Markdown is unchanged:
generate a new report after deployment. No Cloud/UI acceptance claimed yet.

Verification: new synthetic regressions reproduced 11 failures before changes;
focused article/collection/summary/editorial/session/transport suite now 283 passed
(one pre-existing editorial-order assertion explicitly excluded after baseline
reproduction). Final decision gate 1367 passed with stable source hashes; report
gate 207 passed / same pre-existing theme AST failure as baseline. Evidence and
limitations are recorded in `docs/maintenance/20261113_article_market_events.md`.
Exactly one next task: inspect a newly generated Cloud report's top interpretation
and article-body diagnostics for this path; do not expand sources/indicators or
change investment thresholds. This is a bounded correction, not comprehensive
natural-language event coverage. Long ambiguous sentences remain unpromoted.

Latest bounded work: **official-bulletin independent retrieval overlap**, base
44e5ba9f. One Customs worker overlaps CPI on owner, only for exactly one eligible
row each; apply/persist order stays CPI -> exports -> manual fallback. Duplicate
rows stay serial. Providers/TTL/retries/guards/sources/scores unchanged. Fixed-label
collector/HTTP/cache/wait traces added; do not double-count bulletin_http against
report_http.economic_api. Focused158 pass, frozen18-mode full-output/request/store
parity, decision1367 pass140.489s, independent review clean. Report207pass/known
old theme AST failure; additional98pass/two pre-existing Mock __name__ failures
reproduced on baseline. **730d7871 pushed and verified in Cloud**, no reboot. Completed/normal run
e93556d34e58473ea2077ce7f637ebaa: all100 loaded/disk/local hashes match, no stale
modules, report SHA matches. Bulletin7.457->7.372s; macro21.098->21.107s;
full generation56.778->57.631s; separate app work22.973s, combined80.604s.
**No demonstrated speedup:** CPI already complete, so safe serial path ran.
Customs listing4.461s + dependent detail2.864s dominate; bothHTTP200/one attempt,
one export cache miss, no retry/cooldown. Concurrency remains a tested conditional
optimization, not an exercised Cloud benefit. Same95 rows/11categories/2percategory,
marketRSSon/watchRSSoff; price43lookup/26reuse/17miss and9KRrequests match baseline.
Bodies4cachehits vs old4misses: not a controlled identical-cache comparison.
All22 score/verdict/gate/flow columns match across deployment AND report generation;
three KR_CPI/KR_EXPORTS display rows unchanged. Private proof cache/bulletin_*;
visually checked complete screenshot; final update documentation only.
See [Bulletin overlap](docs/maintenance/20261108_official_bulletin_overlap.md).

Latest bounded work: **full automatic report timing accepted in Cloud**, based on
e56b95e0. Runtime6ac42e31/test-docs64f12040 loaded after user reboot. Measurement
**22bf0c2dc45b47538e96953665062f70**, completed/normal, no stale modules; all100
monitored source hashes match local LF content and exported Markdown hash matches.
Generation **56.778s**: macro/official21.098, prices15.816, assembly9.538,
history6.103, RSS1.959, article bodies1.198, calculations1.066. Pre-generation
app work adds23.290s = **80.068s** to saved report; browser paint/rerun excluded.
After reboot, Today calculated95 inputs first (not part of report time); prices
partly warm, RSS/body misses present, no cache clear. Same95 rows and all22
score/verdict/gate columns unchanged before/after generation. Older pre-reboot
export had stale-input data-confirmation gates and is not a valid parity baseline.
Dedicated trace survives rerun and is linked to report SHA256. Partial HTTP
coverage is documented; do not treat SDK calls or concurrent totals as HTTP/wall.
No provider/TTL/score changes. Local focused177, AST/timing15 and decision1367
passed; known report-gate whole-app AST failure remains. See
[measurement record](docs/maintenance/20261108_auto_report_generation_measurement.md).
Do not confuse the outer interrupted `today_queue` trace with this full report run.

Latest task: **market-wide leadership storyline**, base5f145fa3. US/KR paragraphs
separate actual uptrends from relative defense and rebounds; weak focus exposures
and alternative strength form a hypothesis, never capital-transfer/buy claims.
Existing dated news/body evidence, macro and price/volume proxies reused with no
new requests. Direct sector evidence precedes URL dedup; market-common news is
separate, after-close labels preserved, source text escaped. Detailed price/RS
tables collapsed but retained in exports. App, raw rotation, grades/gates/TTL/DB
unchanged. Focused213pass/one known editorial-order test deselected after base
reproduction. Report baseline207pass/one old theme AST failure42.660s; final207/
same failure47.210s. Independent findings fixed/closed,31review probes passed.
Decision1367pass138.179s, stable source hashes. **a910fcc3 plus UI followups
9a2c1d5c/0a4c980b pushed/accepted in authenticated Cloud**, no reboot. Followups
separate Markdown paragraphs and exclude incidental listing notices/evergreen
columns from this panel only; final40focused tests passed3.33s. Final report shows
US staples actual strength vs weak memory/chips, KR relative defense without an
actual uptrend alternative.10price/RS rows identical before/after. Three changed
module loaded/disk/local hashes match; restartfalse/stale[]. Same-session direct
sector/body evidence is still absent for4selected rows; common US/KR news is separate,
not a substitute for industry causes. Next-check questions remain explicit.
No full Today run/live portfolio-score comparison: app unchanged and regression
tests support score preservation. Final diagnostic is completed render_only, NOT
whole report-generation timing; no speedup claim. Private proof cache/leadership_*
and visually checked leadership_cloud.png. Final update is documentation only.
See [Leadership storyline](docs/maintenance/20261108_leadership_story.md).

Latest task: **generic selected-company prior-year cash-burden comparison**,
base08b2ac4e. Same downloaded8-K provides prior-year columns; no additional HTTP.
Shared calendar/scope/source guards; same10-Q basis and same8-K hash when recovered.
Raw8quarter, scores/gates, app.py, TTL/DB unchanged. Existing issuer reviews deduped.
DDOG company FCF/OCF/PPE/development comparison verified; NVDA prior productive
asset purchases1,894m release vs1,895m raw YTD difference stays held; latest cash
recovery unaffected. Do not assume rounding/override. UI separates market leadership,
company quality and cash sustainability; cash is not a universal market ranking.
Focused234pass15.83s; baseline decision1367pass134.934s. Independent review clean.
Final decision1367pass137.468s, stable sources. **134c64fc pushed/accepted in
authenticated Cloud after user reboot**. DDOG shows7-row same-quarter comparison,
cash interpretation and next checks; NVDA prior comparison remains held while latest
verified cash is preserved. Both downloaded comparisons match local/original-document
replay after JSON serialization; raw8quarter packets differ only in checked_at.
Four changed business-module loaded/disk/local hashes match; restartfalse/stale[].
Reboot cleared the session's full Today result. No live95-row score comparison or
full recalculation claimed this time: score preservation is supported by unchanged
app.py and fixed-input1367 regression tests. Initial sessions stalled before query;
Stop/reload and user reboot restored access, exact startup cause remains unproven.
Private proof cache/cash_yoy_cloud_{DDOG,NVDA,diagnostic,acceptance}.json and
cash_yoy_cloud.png; screenshot inspected. This final update is documentation only.
See [Cash YoY comparison](docs/maintenance/20261108_cash_yoy_comparison.md).

Latest task: **DDOG/NVDA held cash-flow reconciliation**, base `7dd38ffe`.
10-Q cash tables supply YTD only; existing different-filing hold is justified.
Shared explicit-query8-K99.1 parser independently verifies BOTH quarter and YTD
against held operands. No issuer/date constants, raw-packet/score/gate/TTL/DB changes.
DDOG software development cost is separate from PPE; company FCF distinguished
from simple OCF-minus-PPE. NVDA productive-assets scope stays broad. Export adds
source-bound `cash_recovery`; raw table/status preserved. Local original documents
and dynamic official discovery verified both. Focused208pass14.11s; baseline
decision1367pass133.454s; final1367pass132.291s, stable source hashes.
Independent review findings closed. **3bf84647 pushed/accepted in authenticated
Cloud**: both actual selected-company queries returned verified_release and source
links; explanations/downloads matched local validator. Raw8quarter packets unchanged
except checked_at, original holds preserved. Before13:59/after14:15ZIP95symbols ×
11score/grade/verdict/gate columns identical(1045values); not full recalculation.
App/view/recovery module loaded/disk/local hashes match; restartfalse/stale[].
Fresh session initially stalled in asset view; Stop/reload recovered, no Cloud reboot;
exact startup cause unproven. Current market context was absent in fresh session and
correctly held; no new automatic market report generated in this cash-only check.
Private evidence cache/cash_cloud_* plus cash_recovery_before/after.zip; screenshots
visually checked. Current update is docs-only; no further application changes.
See [SEC cash recovery](docs/maintenance/20261108_sec_cash_recovery.md).

Latest task: **selected-company market/sector context**, base `9f4451ed`.
Reuses account-scoped report snapshot, existing static sector proxies and validated
company financial readings. No implicit network collection, score/gate/TTL changes.
Dates must match the latest completed local exchange calendar session; old or
missing data do not become current facts. Same-session sector news remains article
claims. Raw financial packet preserved; export adds separate `market_review`.
Focused147pass57.74s; decision1367pass139.702s (before1367pass129.756s).
Report207pass/one pre-existing theme whole-app AST failure reproduced on base.
Independent review freshness finding fixed/closed; raw score baselines unchanged.
Application2b08d36a pushed/accepted in authenticated Cloud. DDOG/IGV and NVDA/SMH
show dated market/sector context, validated quarter facts, next checks and2related
article claims each; changing selection clears previous company display. Both
downloaded financial narratives exactly match unchanged local validator output;
raw8quarter packets preserved. Latest cash fields still held for different-filing
cumulative operands (not recovered). Before12:42/after13:02ZIP:95symbols and
11score/grade/verdict/gate columns identical(1045values), not full recalculation.
App/view/new reader loaded/disk/local normalized hashes match; restartfalse/stale[].
Old session stalled around deployment; new session recovered without user reboot,
exact cause unproven. Private proof cache/company_market_*; screenshot inspected.
Current update is docs-only; no further UI/network/performance changes.
See [Company market reading](docs/maintenance/20261108_company_market_reading.md).

Latest task: **full Today bottleneck measurement / unused daily MTF snapshot**,
basec2d9397e. Actual full Cloud95-symbol run `c0463d50817d4d8faa53ef2c400a2f28`
85.258s/script94.910s; prices54.923s, indicators19.029s, external22.189s active
unions(overlap). KR419misses/435lookups,389HTTP/30exact reuses; analysts70/73
warm. Not fully cold. Removed only unused daily MTF narrative in Today workers;
precision default, weekly/monthly guard, scores/TTL unchanged. Focused100pass;
20-case local MTF sequential.819337->.703249s, six-worker.870645->.747107s,
~14% substage reduction with exact guarded outputs; not Cloud/full speedup.
Review found no concrete scoped issue. Baseline decision1334pass; prices265pass/
one pre-existing DART whole-app AST mismatch. Final decision1367pass133.850s;
prices265pass/same pre-existing failure52.003s, stable sources. **d1d17690 pushed
and accepted in Cloud**. After full run `f3f000044b2f4119ab93d94a12a84e13`
12:31KST, same95symbols:79.759s/script89.212s; indicator builds380->285. KR
421/437misses,391HTTP/30reuses; analysts70/73warm. Prices53.189s, indicators
15.755s, external16.349s active(overlap). Observed5.499s reduction is not all
patch effect: flow refresh20.735->16.365s, stock signals21.534->22.403s.
Before/after11score/verdict/gate columns(1045values) identical; common columns
differ only calculation/analyst timestamps. App loaded/disk/local hashes match,
restart false/stale empty; no reboot. Initial old browser session stalled in
asset-page loading, fresh session recovered; cause unproven/outside Today timer.
Private evidence cache/perf_20261108_*. Application work complete, current
verification update is docs-only.
See [Today MTF performance](docs/maintenance/20261108_today_mtf_performance.md).

Latest task: **Amazon individual-company cash drivers**, basef59f7c41.
Selected AMZN connects source-bound Q32026 cash figures, gross/netcash distinction,
AWS/regional PP&E net additions(non-cash included), other investment cash and next
checks. No AWS-only cash split or all-AI assumption. Generic packet, scores/gates,
DB/TTL/default collection unchanged; download adds separate narrative. Baseline
decision1334pass103.788s; focused121pass8.17s. Fresh local SEC and original HTML
cash/segment rows verified. Decision1334pass106.863s; reviewer found unconditional
growth wording with missing prior, corrected to neutral current-period wording.
Final focused121pass7.61s; reviewer confirmed finding closed. Applicationedd125db
pushed/accepted in authenticated Cloud. Actual11:49KST AMZN query:8quarter packet
matches fresh local SEC except collection timestamp; full narrative matches local,
raw packet unchanged. Readable wrapped explanation/check tables, cash-vs-noncash
labels, source links and download verified. Before11:44/after11:49ZIP: same95tickers
and14score/grade/verdict/gate fields identical(1,330values); not whole-ZIP identity
or full recalculation. Diagnosticedd125db: new module and company view loaded/disk/
commit hashes match, restart false/stale empty, no reboot.11.012s render_only is
not full Today/SEC timing or a speed improvement. Private proof cache/amazon_*.
Dated2026Q3 narrative, not automatic new-quarter transcript/forecast generation.
See [Amazon individual cash](docs/maintenance/20261108_amazon_individual_cash.md).

Previous task: **Alphabet individual-company cash reading**, basec7d4a5fe.
Reuses verified Q3 recovery, same cash checks as Big Tech mode; generic packets,
scores/gates/DB/TTL/default market fetching unchanged. Selected GOOG/GOOGL shows
cash burden summary, source-dated driver table and next-check conditions. Separates
technical-infrastructure capex, TPU inventory working capital and2018EC fine cash
payment; no invented cause allocation/adjusted cash/price claim. Raw holds remain
in an expandable audit table; download adds a separate recovery/narrative object.
Baseline decision1334pass103.321s; final1334pass108.85s, stable sources. Focused
155pass8.43s and155pass8.15s after table-wrap-only correction; reviewer no concrete
scoped issue. Application7d9745fe plus UI4fc40f67 pushed/accepted in authenticated
Cloud. Actual11:26KST GOOGL query: full8quarter packet matches fresh local SEC
except collection timestamp; recovered2quarters and entire narrative match local.
Original packet cash holds preserved. Explanations initially clipped; final
wrapping tables visibly verified with source dates/links. Before11:21/after11:28
ZIP: same95tickers and14score/grade/verdict/gate fields identical(1,330values).
Not whole-ZIP identity/full recalculation. Diagnostic4fc40f67: loaded/disk/commit
hashes match3target modules, restart false/stale empty, no reboot. Final11.732s
diagnostic is render_only, not full Today/SEC timing or a speed improvement.
Private evidence cache/alphabet_individual_*; no account data committed. Source
commentary is reviewed2026Q3, not an automatic new-quarter transcript analysis.
See [Alphabet individual cash](docs/maintenance/20261108_alphabet_individual_cash.md).

Previous task: **Alphabet Q3 original-statement cash recovery**, base4f9dc9ab.
Direct2025/2026Q3 values in the2026 earnings exhibit reconcile to9mo-6mo10-Q
and2025 original release. Report-only exact-operand/issuer/period/status check;
no general parser/score/gate/DB/TTL changes. Big Tech comparison restores both
quarters with original-release/unaudited labels and separate recovery audit;
raw packets stay held. Individual-company generic reader remains unchanged.
CurrentOCF42290/cashPP&E51355 millionUSD,121.4% ratio,YoY+72.0pp; no AI-only or
price-cause claim. Baseline1334pass102.038s/final1334pass104.438s; targeted145pass
7.96s. Report207pass/one same historical theme-selection failure44.848s.
Reviewer found no concrete scoped issue; fresh local SEC and4original documents
verified. Applicationbc123b44 pushed/accepted in authenticated Cloud. Fresh10:40KST
3-company packets/comparison/recoveries match local live SEC. Exactly2quarters
restored; MSFT/AMZN rows/trends/readings unchanged. UI original-source links and
unaudited/recovery dates verified. Same95tickers and14score/grade/verdict/gate
fields identical(1,330 comparisons); no whole-ZIP/full-recalculation claim.
Diagnosticbc123b44 matches new module hashes, restart false/no stale modules;
no reboot. Private proof cache/alphabet_*.14.14s diagnostic is partial display,
not full Today or SEC timing. Startup/rerender delay remains; no speed claim.
See [Alphabet cash reconciliation](docs/maintenance/20261108_alphabet_cash_q3.md).

Latest task: **on-demand same-period Big Tech cash comparison**, base8736d90e.
Company mode compares held/watch MSFT/AMZN/Alphabet/META with exact calendar
quarters; cash definitions separated, no totals/rankings. YoY requires same
comparative filing; ratios need positive OCF. Fact/interpretation/next-check prose
does not assert AI-specific demand or explain current prices. No implicit market
fetches, score/gate/TTL/DB edits. Owner/selection-scoped6h display; explicit queries.
Baseline decision1334pass100.924s; final1334pass100.136s. Focused91pass6.78s.
Report207pass/one same historical theme-selection failure45.423s. Reviewer's two
period/prose findings fixed and tested. Live local MSFT/AMZN/GOOGL8quarter requests
succeeded: commonJul-Sep2026 versusJul-Sep2025. MSFT/AMZN cash burden increases;
Alphabet withheld due cross-filing cumulative subtraction. No substitution.
Application7f00c7cf and presentation fix5a7038f1 pushed/accepted in authenticated
Cloud. Actual10:22KST three-company8quarter packets and complete comparison equal
local live SEC data; final UI holds/commas/KST verified. Diagnostic5a7038f1 has
matching loaded/disk hashes, restart false/stale modules empty; no reboot.
Same95tickers and14score/grade/verdict/gate fields identical(1,330 comparisons),
not whole-ZIP identity or full recalculation. Evidence/screenshots ignored under
cache/bigtech_*. Startup/rerender delays remain;37.08s diagnostic is partial screen
execution, not full Today or SEC timing. No speed/full-suite claims.
See [Big Tech cash comparison](docs/maintenance/20261108_bigtech_cash_comparison.md).

Latest task: **market leadership reading and issuer questions**, base `cf84af2d`.
User clarified market rotation/semiconductor/Big Tech purpose, reprioritizing the
pending KR prose extension. Reuses existing rotation calculation once; adds actual
5/20-session returns, separates rising candidates from relative defense/rebounds,
deduplicates sector ETF votes and preserves KR/US dates. Promoted front section;
old audit tables collapsed, not deleted. Big Tech/supplier research questions link
to held/watch company review. No new requests, scores/gates/DB/TTL changes.
Decision before1334pass103.067s; final1334pass105.779s,stable source. Targeted155pass
8.07s. Review caught omitted KR technology focus; fixed/tested. Report's new section
has a narrow historical-digest adapter, no golden rewrite; final report207pass/one
same historical theme-selection failure41.830s. Application8eeed6db pushed and
accepted in authenticated Cloud. Diagnostic:matching commit/loaded hashes,
restart false/stale modules empty; no reboot. Fresh09:19KST report generation
f922ba27b64f/loaded639c2e2a02e0ac57 has one front section, distinct KR/US dated
2026-11-06,6 focus rows and deduplicated SOXX/SMH. XLP meets positive5/20/63+RS
conditions; falling relative winners remain defense; XHB negative63-day return
remains recovery. Same95tickers and14 core score/grade/verdict/gate fields identical
(1,330 comparisons), not whole-ZIP identity. Private proof cache/leadership_*.
No full Today timing or independently verified leadership prediction claim.
Company-specific segment/outlook metrics are still incomplete; the new questions
are research directions, not evidence that those business changes have occurred.
Actual MSFT selection shows investment/recovery question before explicit evidence
query. Company screen proof saved privately; no new SEC/cross-company query claim.
See [leadership reading](docs/maintenance/20261108_market_leadership_reading.md).

Latest task: **Korean selected-company imported DART fallback**, base `e3c75cc2`.
Explicit company query uses the existing owner-scoped stored evidence only when
live DART fails. Corporate/listing identity, ticker, original scope, hash and
seven-day collection expiry validated; source/age/cumulative/CFS-OFS/missing
periods shown. No DB writes, score/decision/parser/TTL changes. Baseline1334 pass
103.346s; final1334 pass105.735s, stable sources. Focused133 pass/one pre-existing
whole-app historical AST failure19.51s (old5cadb203 versus already-changed HEAD);
no golden changes. Bounded reviewer: no concrete findings. Local saved Samsung
bundle validated, one collected/two requested reports; actual-payload local
failure replay matches hash/all metrics/coverage with injected identity/store.
Application `07b34e61` pushed and verified in authenticated Cloud. Diagnostic
fcb7703e37eb4a1a8a55985b4c741b13 has matching commit, restart false, no stale
modules; new helper/store loaded hashes match disk. No reboot. Samsung live query
now succeeds; all7rows/packet fields except query timestamp equal pre-deployment
output. Same95tickers and14 score/grade/verdict/gate fields unchanged(1,330
comparisons). No whole-ZIP identity claim. Cloud failure/fallback was not induced;
fallback verified locally with real imported payload and injected read-only store,
plus synthetic HTTP/store/UI tests. No live fallback success claim. Private proof
under cache/company_kr_*. No full Today timing; startup/rerender delays remain.
See [KR imported evidence](docs/maintenance/20261108_company_kr_imported_evidence.md).

Latest task: **market-first report and selected-company deep dive**, base `8d53b10f`.
User superseded MSFT-only follow-up. Default report drops implicit MSFT SEC/IR
collection; market story/materials/index-macro precede holdings/calendar. Separate
Company view selects current held/watch stocks (ETFs excluded by existing asset
classifier); explicit one-company query, owner/ticker-isolated results, safe failure
and six-hour display freshness. US SEC8-quarter explanations/tables/source download;
KR existing annual/quarter provider with explicit source/failure/coverage limits.
MSFT Q4/IR extras retained only when selected. No score/decision/provider TTL/DB
edits. Generic guidance/consensus and KR8-quarter CAPEX remain unconnected.
Baseline decision1334 pass101.573s. Focused selection/reading/MSFT contracts151
pass5.98s; source-flow/MSFT/cash183 pass22.09s. Bounded review found no concrete
issue. Report207pass/one known theme-selection assertion48.736s. Live AMZN/NVDA
SEC8quarters verified; NVDA cross-filing cash interpretation explicitly held.
Final decision1334 passed108.758s,stable sources. Application `5d243918` pushed
and verified in authenticated Cloud. Fresh market report08:22KST/generation
008e550fc604 matches commit; market story/materials/index-macro precede holdings,
no MSFT sections, no stale-code warning/reboot. AMZN explicitly selected/queried:
8quarter packet,CIK,currency,status and all quarter records exactly match local
live SEC data. Download succeeded; NVDA selection hides previous AMZN result
without querying. Same95tickers and14 score/grade/verdict/gate fields unchanged
(1,330 comparisons), not whole-ZIP identity. Screenshots/report/ZIP/packets ignored
under cache/company_*. No live KR query or NVDA Cloud query claim (NVDA local
source and UI switch tested). Startup/rerenders still slow; no Today timing claim.
See [market/company split](docs/maintenance/20261108_market_company_split.md).

Latest task: **MSFT two withheld Q4 cash quarters**, base `64383d2b`.
Original annual/interim and earnings-release cash statements reconcile both
2025-06-30 and2026-06-30. The2026 exhibit directly reports both quarter values;
original2025 figures agree. Narrow report-only recovery requires exact live
companyfacts operands/status/filing metadata and reviewed date; any change holds
again. No generic guard/SEC parser/score/decision/TTL/database edits or extra calls.
Eight rows,zero held,four valid YoY pairs; latest43.0%→67.9% unchanged. Raw precision
evidence remains conservative pending the next display-only task. Targeted109
tests pass7.13s; independent review finds no concrete issue. Before decision1334
pass102.713s; final1334 pass105.460s,stable source. Report207 pass/one same
pre-existing theme-selection whole-app assertion45.924s. Live SEC2 requests200,
1.709s; cached0.000778s,not a Today/report benchmark. Private evidence ignored
under cache/msft_q4_*. Application `1314a530` pushed and verified in authenticated
Cloud. Fresh report07:39KST/generation951d071278fc matches commit; entire cash
section matches local live-SEC output exactly,8rows/0held/2reviewed/4YoYpairs,
direct exhibit links and unaudited notes visible. No stale warning/reboot.
Same95tickers,13 core score/grade/verdict/gate fields unchanged(1,235 comparisons).
Four saved gate-reason strings have different R/R values alongside live price/
enrichment refresh; this is NOT identical inputs or whole-ZIP parity. Fixed-input
decision gate passes. Startup/report loading is still slow; no Today speed claim.
See [Q4 reconciliation](docs/maintenance/20261108_msft_q4_recovery.md).

Latest task: **MSFT eight-quarter cash-burden report**, base `cab147bf`.
Existing SEC quarter parser/identity loader reused once outside rendering; public
six-hour success reuse. Same-period/USD/PP&E/provenance guards and same-filing YoY
pairs;8-row dated table, interpretation and next checks.2 cross-filing Q4 periods
held, never zero-filled. Existing scores/gates/provider TTLs unchanged. Fixed
briefing timestamp order so freshly collected data is not rejected as future.
Targeted204 tests pass; decision gate1334 pass101.937s. Narrow AST adapter retains
old baselines outside approved report statements. Report gate207 pass/one known
whole-app function-set failure before/after. Live SEC2 requests HTTP200,4.560s;
repeat0.000626s,no extra requests. Latest burden43.0% ->67.9%,3 valid YoY pairs,
2 withheld quarters. Application `21758193` pushed and accepted in authenticated
Cloud. Fresh report05:56KST/generationIDe83457ce3b52: entire cash section exactly
matches local live-SEC calculation, one visible block,8 rows,dates/filing links,
same3 valid comparisons and2 held quarters. Matching commit/no stale-code warning;
no reboot. Same95 tickers and14 core score/grade/verdict/gate fields identical
(1,330 comparisons). No whole-ZIP or auxiliary flow-scope identity claim.
Private screen/report/ZIP/acceptance evidence ignored under cache/msft_cash_*.
Separate briefing clock validated by replay; no second live generation/Today timing.
See [cash trend verification](docs/maintenance/20261108_msft_cash_trend.md).

Latest task: **MSFT evidence in automatic market reports**, base `5bdc22de`.
Bounded official packet collected once in report context; successful public-only
six-hour reuse. Visible report block connects demand, cash investment, company
outlook, holding exposure and next checks. Dates/scopes/forecast expiry guarded;
not today's price cause, no consensus imputation or scoring/decision changes.
Targeted75 tests pass; decision gate1334 pass (117.415s). Report gate207 pass/one
pre-existing whole-app AST assertion before/after, no new failure or golden reset.
Live issuer query13 metrics,5.694s; cached<0.001s, not full report/Today timing.
Application `1259b5f7` pushed and accepted in authenticated Cloud, fresh report
generationID9fbf13d5812c at03:31KST. Actual UI/Markdown: one MSFT block after core
interpretation, verified facts/outlook/links/holding exposure/next-check table.
Matching commit and no stale-code footer warning; no reboot. Same95 tickers and
14 core score/grade/verdict/gate fields unchanged (1,330 comparisons). Auxiliary
flow labels12 rows change from stock-history to radar scope after existing flow
snapshot collection; same timing, score differences only rounding(max4.76e-11).
Do not claim identical whole ZIPs or same flow scope. No Today timing benchmark.
Private screenshots/Markdown/ZIP/acceptance JSON ignored under cache/report_msft_*.
See [MSFT report integration](docs/maintenance/20261108_msft_report_evidence.md).

Latest task: **MSFT official segment/investment guidance evidence**, base `9390e4ce`.
New read-only precision expander, explicit homepage/release/call query (max3 URLs),
latest linked FY/quarter discovery and actual/forecast provenance. Distinguishes
recast reporting segments, overlapping Cloud/Azure indicators and company CAPEX
from cash PP&E. No score/DB/report/provider changes. Existing eight-quarter SEC
snapshot reused under owner/ticker/selection scope, exact periods/currency only.
New+quarter tests54 passed; stable decision gate1334 passed in101.466s, no source
changes/failures/skips. Application `30117c33` pushed and accepted on Cloud.
Authenticated MSFT IR query, three tabs,4 same-period SEC comparisons and JSON
download succeeded. All13 metric records match local parsing. Seven core CSVs
byte-identical before/after deployment and before/after SEC+IR queries. Matching
build, restart false, stale modules empty; no reboot. New modules are outside
the old monitor list, so actual UI/data were checked directly. Screenshot/JSON/
ZIP evidence ignored under cache/msft_ir_cloud_*. No full Today timing claim.
Actual official query succeeded locally with13 metrics; four SEC comparisons fall
within rounding ranges. Source wording/conditions fail closed, no old transcript
or consensus imputation. No LLM/DCF/report integration claimed. Private evidence
under ignored cache/msft_*; clean base/user work preserved.
See [MSFT business evidence](docs/maintenance/20261108_msft_business_evidence.md).

Latest task: **read-only SEC eight-quarter financial evidence**, base `68d617a4`.
User approved this financial-data phase, overriding pending report acceptance.
New precision expander compares income/cash investment/OCF/cash and derived FCF,
with explicit dates, source scope, missing/revision guards and review questions.
Manual query only, selected company plus up to four comparison tickers; owner/
ticker/selection-isolated session results, no score/DB/provider/cache changes.
Actual official SEC responses for MSFT/AMZN/GOOGL/META/NVDA/MU provide8 quarters
each; all latest raw fields present, derived FCF44/48 (four revision holds).
Cash investment distinguishes PP&E from productive assets including intangibles.
Focused105 tests pass; stable decision gate1334 passes in104.908s with no source
changes. First gate run also passed tests but correctly blocked source edits
during execution; not claimed accepted. Existing app functions AST-identical.
Published application commit `7c7ead8c`. Actual authenticated Cloud MSFT8-quarter
query, both tabs and JSON download verified; all records match local SEC output.
Seven core CSVs byte-identical before/after deployment AND before/after explicit
query. Completed ZIP: matching build, restart false, stale modules empty. No reboot
needed. New module is outside old monitor list; actual UI/JSON verified separately.
Private evidence under ignored cache/quarter_cloud_*; no personal data in Git.
Six-company Cloud/Today performance not tested; default app startup remains slow.
No LLM, consensus/segment guidance, debt maturity or valuation model implemented.
See [quarter evidence verification](docs/maintenance/20261108_sec_quarter_evidence.md).

Latest task: **report editorial/holiday status review**, base `ce13c311`.
User supplied00:48 report and two timing files, overriding the old next inventory.
Fixed weekend US live-disconnected wording using validated dated closes; no stale
futures fallback. Finance topic excludes sports-only bank-team stories. Added a
read-only source-bound editorial front section with holding links/check questions,
reordered explanation ahead of audit tables, retained evidence in exports and
collapsed more audit sections in UI. No trade/scoring/provider/cache/DB changes.
Final targeted190 tests pass. Report gate207 pass/1 pre-existing whole-app AST
theme-extraction assertion before and after; historical hashes unchanged with
explicit adapters for approved presentation changes. Not a clean full-suite claim.
Uploaded full Today run87.220s, initial script94.800s; render-only71.960s is a
different interrupted/rerun scope, not a comparable calculation benchmark.
Local reconstructed preview inspected; it is not a fresh operating report. Private
artifacts remain ignored. Publication is ready; Cloud acceptance remains pending.
See [report quality/timing audit](docs/maintenance/20261108_report_editorial_review.md).

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

**Investigate Customs listing -> detail transport connection reuse only.**

Actual Cloud bulletin cost7.372s is listing4.461 + dependent detail2.864, not CPI.
No duplicate request; CPI-complete guards correctly skip the new overlap path.
Evaluate a short-lived same-origin connection reuse without changing listing
selection, cookies/request semantics, parameters, retries/timeouts, failure
cooldowns, TTLs or data/score/gate output. Prove full fixed-input parity and actual
request counts, then compare natural-expiry cache-miss Cloud runs. Do not assume
handshake savings, parallelize dependent URLs, reuse a stale article ID, or change
freshness to claim a gain. See the latest bulletin record for baseline/options;
cache/bulletin_cloud.json is completed full generation, not a Today partial trace.
Browser tab38 holds the accepted report. No other performance scope in this task.

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
