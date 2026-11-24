# Stock Lab Work Handoff

Updated: 2026-11-24 KST. Read before large source files or edits.
This is the current work order. Historical next-task instructions are superseded.

## Resume Safely

1. Inspect `git status --short`, branch, recent commits and upstream after fetch.
   Preserve home/company edits; never reset or force-pull. Fast-forward only when compatible.
2. Read AGENTS.md, this file and the latest bounded record. Installed home Python:
   `.venv311/Scripts/python.exe`; another computer may use `venv/Scripts/python.exe`.
3. Private exports/captures are ignored under cache or Downloads and may be absent
   elsewhere. Never commit credentials, account quantities or private reports.
4. Commit/push and necessary owner reboot are already authorized. Do not request
   permission again. Ask for direct authentication only when an actual UI requires it.
5. Finish one bounded task, verify, then update this file with exactly one next task.
   Keep output compact; do not start another broad task when unable to finish it safely.

Repository: https://github.com/kej0587-afk/my-stock-lab.git, branch `main`.
Production: https://3insky.streamlit.app/.

## Big Picture

[ROADMAP](docs/maintenance/ROADMAP.md) defines the sequence and exit criteria:
**data identity/period/session → cross-view consistency → market/company/account
explanation → measured performance → bounded large-function extraction**.

Quality, timing and account/execution limits answer different questions. The report
explains their evidence; it must not implement another scoring/permission engine.
Many shared helpers already exist. This is continuation, not a rewrite. Missing
supplier fields are explicit limitations, not a reason to block all later stages.
No score thresholds, decision labels, TTLs or trading permissions may be changed
under a behavior-preserving task. Investment performance validation is separate.

## Latest Completed Task

[Decision system audit](docs/maintenance/20261124_decision_system_audit.md) (user request 11-24, read-only): traced
`calc_scores_and_decision` → quality / timing·structure / decision / gate / sizing, the priority map (P1–P4, Q1–Q4,
finalization), 107 codes with labels/groups/thresholds, screen overlays (Today, precision, asset page, rebalance), and
classified R/R, SMC, liquidity, flow, RS, macro, account weight and leverage into the six roles the user defined
(candidate grade vs final decision kept as intended separation). Fixed-input divergences reproduced by
`scripts/decision_audit_cases.py`. No logic, threshold, label, code, gate or sizing change. Decision gate 1637 passed /
1 known failure (same as main).

### Previous: daily market reading

[Daily market reading](docs/maintenance/20261124_daily_market_reading.md) (user request on report 62): the quick
summary's '시장 해석' was a condition-selected fixed sentence (two macro-burden names + SOXX/SMH·IGV 3M sign) in
`report_market_summary.market_summary`; daily index moves, news, flows and sectors never reached it. New
`report_daily_change.py` writes ① the day's biggest change (vs prior day, runs) ② reported background at its
confirmed level (title-only = not a cause; outlet count) ③ KOSPI flows/turns + sector leaders ④ remaining risk with
today's numbers and next checks; plus '오늘 달라진 점'. No repeat in 시장 스토리/핵심 해석. Scores/gates untouched.
Before/after on 11-18/20/23/24 public closes in the doc. Report gate 208/208; full suite 33 failures before and after (same list).

### Previous completed news dedup

[News dedup/classification](docs/maintenance/20261124_news_dedup_classification.md) (status #15):
article title keys drop wire-update marks ("(종합)", "(종합N보)", "[속보]") and unify ∼/~, so one
story's versions collapse; a bank quoted as forecaster (JP모건 "…AI 자본지출…") is classified by
the quoted topic unless the title is about its own results/dividends. Facts/links unchanged.
Report+news 1621 pass, related 318 pass, gate 208.

### Previous completed schedule split

[Schedule split](docs/maintenance/20261124_report_schedule_split.md) (status #16): the 7-day table
is now 이번 주 남은 일정 (today or later; multi-day events until `end_date`) → 이후 확정 일정·90일
→ 최근 지난 일정 · 결과 확인. Collection, states and wording unchanged. Bundle 1662; gate 208.

### Previous completed release fallback

[Release fallback](docs/maintenance/20261124_report_release_fallback.md), started at `af2a994a`.
물가·고용·소비·경기 was empty on 11-24 by design: the selection window is the last 3 sessions and
the latest publications were 11-10/11-13/11-16. When nothing falls inside the window, the section
now copies up to 6 dated (not future/pending/stale) rows newest first under "최근 3거래일 안 새 발표
없음 · 마지막으로 확인된 발표". Undated rows are not promoted; cells unchanged. Bundle 1883 pass; gate 208.

### Previous completed observatory values

[Observatory values](docs/maintenance/20261124_report_observatory_values.md) (status #10/#11 part),
started at `8d15a36a`. Country ETFs EWZ/INDA/VNM/EWJ (세계 시장과 국가 ETF) and SKEW/VVIX/OVX
(매크로 · 옵션 위험) now show completed-daily values from the same one-year Yahoo batch; 미연결 per
row when absent; kept out of alignment/live/rotation via `daily_only`. Only items with an actual
observation count as 본문 표시. Remaining 미연결: FRED/CNN/Cboe items, JPY=X, BTC-USD, Npay 005930,
local indices (each needs a new request in the report path; measure first).
Report bundle 1636 pass; earnings/SEC/DART/macro 690 pass / 6 known failures; gate 208.

### Previous completed earnings market pools

[Earnings market pools](docs/maintenance/20261124_earnings_market_pools.md) (status #5), started
at `90d0cd1c`. KR (DART) issuers shared one 3-worker pool with US issuers that sit in SEC's 0.2 s
fair-access wait, so KR work queued behind SEC. Now one 3-worker pool per market; the 24 s shared
budget, SEC rate lock, per-provider max 3 concurrent, retries, timeouts and TTLs are unchanged.
Production baseline (cold cache right after reboot, 78 issuers): 51 withheld by
`collection_time_budget`. Same PR: profit-row wording ("이 문장에 없음: …"; unlabelled + non-GAAP
figures read "조정(non-GAAP) 포함", e.g. INTC). Earnings bundle 714 pass / same 5 failures; gate 208.

### Previous completed earnings profit row

[Earnings profit row](docs/maintenance/20261124_earnings_profit_kind.md) (status #7), PR #4,
started at `b126db95`. NVDA's official release states "earnings per diluted share", which the
profit pattern missed (row showed 미연결); the pattern now accepts diluted-EPS wording with the
same money/forward/period/definition checks. `profit_kind` names the measures (영업이익/순이익/EPS)
and basis (GAAP/조정) the quoted sentence holds; the 이익·EPS row shows it, so PANW operating
income is no longer readable as EPS. Source sentences unchanged, nothing computed.
Report gate 208; earnings/SEC/DART bundle 710 pass / same 5 pre-existing failures.

### Previous completed report step 2

[Macro groups](docs/maintenance/20261124_report_macro_groups.md), PR #3 (`b126db95`): the reader
매크로 table is split by ticker into 금리 / 환율·달러 / 원자재 / 심리·변동성 (+기타 for unknown
tickers). Rows copied unchanged. Report gate 208 before/after.

### Previous completed report step 1

[Report reading order](docs/maintenance/20261124_report_reading_order.md), step 1 of the
2026-11-24 report-overhaul request, started at `36f7b425`. `compose_reading_report` now
reads quick summary (session basis, interpretation, index table, existing action line,
stale/recalculation warnings) → 지금 상태 3줄 → 지수 → US/KR (Korea first during a KR
session or after the KR close outside US hours) → 세계 시장과 국가 ETF (status only) →
매크로 → 물가·고용·소비·경기 (recent releases moved) → 관측실 지표 연결 상태 (every
macro_monitor item shown as 본문 표시/미연결) → themes, flow → 주요 기업과 사건 →
오늘의 판단 + account lines (moved from the top, unchanged text) → portfolio → schedule
→ appendix. Order/placement only; no calculations, scores, gates, collectors or TTLs.
Four tests that pinned the old order were updated to the new order without dropping any
checked value. Report gate 208 before/after. Full suite 9,879 pass / 32 fail; the 32 failures are the
identical set on base `f16e103` (old-commit app.py comparisons, date-dependent tests). Not yet generated in production.

### Previous completed DART task

[DART identity persistence](docs/maintenance/20261124_dart_identity_persistence.md),
started clean at `f16e103`. Cause reproduced: the bundled corporate list was
retrieved 2026-11-07 and expired 11-14 (7-day limit); no code saved live successes.
Nov21 report = connect_timeout x2 + expired bundled list → 31 KR issuers withheld.
Now a validated live list is saved to Supabase `dart_corporate_code_snapshots`
(shrink >10% refused, identical list not rewritten within 12h); on transport failure
the newest valid of {stored last success, bundled file} is used with origin/date/
age/valid-until shown and marked identity-only. Missing issuers in a dated list are
`dart_ticker_mapping_unavailable_in_snapshot`, no guessed mapping or filing request.
Retry count, timeouts, TTLs, 7-day limit and validation unchanged.
Related tests 273 pass (+17 new); 1 pre-existing failure identical before/after
(`test_existing_parser_and_app_functions_preserved` compares app.py to old `5cadb203`).
Report gate 208 before/after. SQL `docs/20261124_dart_corporate_codes.sql` prepared,
**not executed**; until it runs the store reports `schema_unavailable` and the old
behaviour remains. The DART connect failure cause itself could not be probed here
(sandbox proxy blocks opendart).
Production (owner-reported, 2026-11-24 ~12:00 KST): PR #1 merged as `60f8a298`, SQL
executed, app rebooted. Financial-input DART diagnostic: cause=ok, http200,
mapped_count4020, elapsed9.606s, persist_status=unchanged_recent (an earlier post-reboot
lookup had already saved the identical list); table has one row. Restore after a real
outage is covered only by fixed-input tests so far; not observed in production.

### Previous completed SEC task

[SEC release refusals](docs/maintenance/20261121_sec_release_refusals.md), started
clean at `a791d693`. Code **`2ac2d94b`** pushed, direct owner reboot and production
verification complete. MSFT year-less title recovers explicit FY2027Q1 from
realized body evidence; AAPL remains withheld for missing dateline, AMAT for
issuer-name mismatch (submissions suffix/state conflict; no guessed alias).
231 related tests, selected report208 before/after,14 exact accepted parser
outputs and9 exact collector outputs/request multisets. Same official bytes for3
issuers replayed. No score/TTL/provider/deadline/rate changes.
Live18 checks pass; report120.672s, discovery23.577s. Release parser21 calls:
accepted9, issuer6/quarter3/date2/title1 refusals. Added aggregate allowlisted
reason counters only, no raw exceptions/credentials. Fresh DART corporate lookup
failed with connect_timeout (2 existing attempts), leaving31 domestic connections
withheld; this separate availability issue is next, not a reason to relax checks.

### Previous completed profiling task

[Earnings discovery profiling](docs/maintenance/20261121_earnings_discovery_profile.md),
started clean at `05202ad1`. Code **`8604900a`** pushed; direct owner reboot and
two completed operating reports verified. Added setup/SEC rate wait/HTTP/body/parse/worker/join timings,
actual request identities and cache hit/miss counters, aggregate-only diagnostics.
Exact duplicate request identities **0 in both runs**; no response reuse added.
Coverage/provider/date/TTL/deadline/concurrency/scoring and financial outputs unchanged.
142 related tests passed, fixed cold/warm/failure/expiry replay **9 exact outputs**
and identical request argument multisets; selected report208 passed before/after.
First discovery23.486s = SEC setup0.133 + DART setup10.179 + worker join13.158 + other.
Repeat DART setup0.003s proves existing cache reuse, but discovery24.234s still fills
the collection budget with unique requests/SEC rate waits. Full reports116.109s and
78.992s have uncontrolled cache/network; not a measured code speedup.
SEC release validation refused9/15 then21/31; correctness of those refusals is next.

### Previous completed short-close task

[Report auxiliary short-session close](docs/maintenance/20261121_report_short_close.md),
started clean at `ce54e1eb`. Code **`10d216ab`** pushed; direct owner reboot and
completed operating report verification finished.
`regular_quote_observation` now uses the shared exchange calendar for latest and
previous completed sessions rather than fixed16:00. Normal grace/window,
quote validation, history repair, scores/labels/TTLs and extended hours unchanged.
Selected report **208 passes before/after** (`report_ps1ctilw`, `report_0oe6dzri`),
focused **137 passes**, original/new normal-session outputs **128 exact matches**.
Nov27 13:00 short close recovery is fixed-clock synthetic verification only.
Operating checks **13 passed**; normal Nov20 SOXL/GOOGL returns unchanged.
Today107.1s, report127.153s; prior report85.817s has uncontrolled cache/inputs/network.
No speedup or regression-cause claim. Next bounded task is measured filing discovery.

### Previous completed report audit

[Report repaired-close audit](docs/maintenance/20261121_report_repaired_close.md),
started clean at `6660a895`. Public report quote endpoint and completed operating
report confirm Nov20 SOXL close30.88/-31.83%, GOOGL265.29/-2.70%, matching prior
Today/precision. Post quotes are separate and not current during the weekend.

Fixed only the holdings report's misleading inactive-window "quote disconnected"
label; it now states holiday/closed and refers to dated closes. Active-window
missing/delayed warnings, numeric output, decisions and TTLs unchanged.
New/relevant 77 tests pass; selected report 208 passes before and after
(`report_jxn3q92o`, `report_gyh3u4_r`). No golden regeneration.
Code **`bc5d8d2e`** pushed; direct owner reboot, Today rerun and final operating
report verification complete. Report 82.366s before / 85.817s after with uncontrolled
cache/remote response; no speedup claim. 13 operating report checks and 10 public
quote/precision-source comparisons passed. Changes are report display only.

## Previous Completed Task

Completed after `bf7b385b`: [cross-view price/mode audit](docs/maintenance/20261121_cross_view_price_mode.md).
Code **`801cdf67`** pushed, owner reboot and production verification completed.

- Six representative US regular closes/afterhours observations and one KR ETF
  checked through public raw quotes and actual app loaders. SOXX is not in Today.
- Selection mode/held status are display evidence, not changed scoring inputs.
  Portfolio now compares saved Today/precision price/date/quote time/session/mode/ID.
- Fixed held KR ETF reproduces different existing free/held account-limit paths
  with equal price/quality/weight inputs. Do not unify policies without an explicit
  policy task. Matching price IDs alone do not prove all market/account inputs equal.
- 98 focused tests and final selected decision **1,638 passed / 152.724s**
  (`decision_iksxjci1`). Prices unchanged; selected prices **646 passed / 63.229s**.
  No golden regeneration, threshold/label/TTL/provider priority changes.
- Operating Today **95 rows / 105.0s**, no missing current prices, all source dates
  Nov20. Before 98.2s has uncontrolled cache state; no performance claim.
- Four completed precision captures (GOOGL, SOXL, KR ETF free/held) pass nine
  build/price/date/quote/workflow checks each. Portfolio UI comparison verified for
  SOXL and KR ETF; holding export prices also match for SOXL/KR ETF/BITX.

### Previous completed task

Current bounded work: [cross-view evidence and SOXL close repair](docs/maintenance/20261121_cross_view_soxl_close.md).
Started clean at `c895a19b`. The user reported SOXL 42.34 versus regular close 30.88
during the cross-view audit; the explicit price bug took priority over the former
no-provider-change restriction. Implementation/tests and production verification complete.

- `1a9989fb` passes existing calculated weights into precision's shared evidence.
  Three fixed cases preserve every existing workflow field and portfolio readiness;
  only two display fields are added. Original captures are not identical full inputs.
- Yahoo's Nov20 SOXL daily row has OHL/volume but null Close, while same-symbol
  regularMarketPrice=30.88 at 16:00:04 ET. Existing cleanup dropped the row; old
  regular-close fallback selected Nov19 45.30. The 42.34 quote had no provider/time
  evidence, so its actual supplier cannot be determined from the old ZIP.
- Repair only an existing missing US tail Close with matching symbol/calendar/date,
  close-time and OHL validation. Keep Adj Close unknown. Shared scalar/batch path;
  complete frames make no extra request. Prefer chart over untimed day fallback
  outside extended sessions. No TTL/score/formula/threshold/decision-label changes.
- Corrected data can change calculated results; this is an explicit input bug fix,
  not a claim that old wrong prices must yield identical output.
- Final selected prices: **646 passed / 60.359s**, `prices_eeb6nivt`.
  Final selected decision: **1,638 passed / 153.218s**, `decision_bqkmn9n1`.
  New/focused contracts: **75 passed / 26.26s**, including NaT/duplicate-column
  guards found in focused review. No golden regeneration.
- Local and production restore Nov20 Close30.88; separate post-session quote33.3694
  carries actual supplier timestamp/session. `49ab429d` pushed, owner reboot done,
  completed SOXL ZIP confirms loaded modules match disk and account weight fields connect.

### Previous completed display task

[2026-11-21 daily-return display basis](docs/maintenance/20261121_daily_return_basis.md),
based on `c759c585`. This is display evidence only, not a new return calculation.

- Source return now carries the actual previous/current row dates. No assumed
  previous trading day replaces a missing source row.
- Calendar/calculation time separates active partial bars from elapsed closes;
  elapsed close time still does not certify supplier finalization.
- Latest-price comparison identifies the actual last source Close. Supplier time
  and session remain unknown when the selected price carries no observation.
- Same evidence appears in precision input table, tactical/narrative displays and
  Today/dashboard detail columns. Existing return numbers, day_ret_label, scores,
  decision reasons, execution gates, price identity and cache TTLs remain unchanged.
- Report already separates completed/intraday values. Its computations/output were
  not rewritten or replaced with the decision engine's return.
- Two saved normal/intraday captures reproduce price, RSI, ATR, return, R/R and
  scenario date/price. Existing build_signal_basis fields are equal for the same
  frames/quote/clock; only three display fields are added.
- Baseline selected decision gate: **1,638 passed**, 153.437s,
  `cache/refactor_checks/decision_0r18f482`. Initial relevant tests: **140 passed**.
  New evidence tests: **19 passed**, 5.81s; final evidence/calendar/audit contracts
  **72 passed**, 11.82s. Final selected decision gate: **1,638 passed**, 151.881s,
  `cache/refactor_checks/decision_pmcv6zmr` (no failures/errors/skips/source drift).
  Code `35dd624d` pushed; owner reboot and precision operating verification completed.
- Ignored fixed-input record: `cache/operating_20261121/daily_return_basis_fixed.json`.
  No private ZIP/report goes into Git.

Previous [calendar fix](docs/maintenance/20261121_report_exchange_calendar.md)
aligned report equity sessions with exchange calendars while preserving separate
close buffers and legacy non-equity feed handling. It was deployed and verified
in `8c0caab5`; the record retains detailed tests and the operating report evidence.

The former 1,787-line handoff is preserved, unabridged, at
[HANDOFF_HISTORY_20261121.md](HANDOFF_HISTORY_20261121.md). It was copied before this
rewrite; its links retain their repository-root meaning. Read specific historical
records only as needed. Do not resume an older next task from that archive.

## Last Direct Production Verification

PR #7 (`96d45dc1`), report 2026-11-24 14:06 KST after Claude reboot: 물가·고용·소비·경기 shows
"최근 3거래일 안 새 발표 없음 · 마지막으로 확인된 발표" with 한국 수출 (11-16), PPI MoM/YoY (11-13),
CPI (11-10), newest first, cells unchanged. 다음 일정 order: 이번 주 남은 일정 (BOK MPC 11-26) →
이후 확정 일정 (Employment 12/04, FOMC 12/10 KST, CPI, PPI …) → 최근 지난 일정 (NVDA 11-17 … ).

PR #6 (`af2a994a`, observatory values), report 2026-11-24 13:56 KST after Claude reboot: EWZ 29.24,
INDA 52.14, VNM 16.71, EWJ 86.90 USD; SKEW 140.37, VVIX 117.36, OVX 49.19 pt; all dated
2026-11-20 → 2026-11-23, Yahoo Finance daily. 관측실 status marks exactly these 7 (plus existing
table items) as 본문 표시; PCR, JPY=X, BTC-USD, FRED/CNN items stay 미연결.

PR #5 (`8d15a36a`, market pools) after Claude reboot, cold cache, same 78 issuers, one run each:
`collection_time_budget` withheld 51 → 41 (KR 18 → 13); 정기보고서 확인 10 → 15; 공식 발표 확인
9 → 12. Single samples under live provider latency, not a controlled benchmark. Still withheld KR:
디아이, 삼성E&A, 케이씨, 원익홀딩스, 프로텍, 로보티즈, 나노신소재, 나무가, 코스맥스, 심텍,
케이씨텍, 효성중공업, 티엘비. Successes stay cached (existing TTLs), so later runs fill more.

PR #4 (`90d0cd1c`) after Claude reboot, report 2026-11-24 ~13:5x KST: NVDA FY2027Q3 이익·EPS row
shows "EPS (GAAP·조정)" with the $2.70/$2.68 diluted EPS sentence; PANW shows 영업이익 (GAAP).
Cold-cache earnings coverage in the same run: 78 checked, 51 `collection_time_budget` (baseline
for the market-pool change).

Report overhaul steps 1+2, code **`b126db95`** (PRs #2, #3), owner Reboot by Claude via
share.streamlit.io. Report generated 2026-11-24 13:24 KST (KR intraday, US closed).
Order seen: 빠른 요약 → 지금 상태 3줄 → 지수 → 한국 시황 → 미국 시황 (Korea first, correct for
KR session) → 세계 시장과 국가 ETF → 매크로 → 물가·고용·소비·경기 → 관측실 지표 연결 상태 →
테마 → 돈흐름 → 주요 기업과 사건 → 오늘의 판단 (open) → 포트폴리오 → 다음 일정. Quick summary
코스피 +7.08% / 코스닥 +4.70% equal 지금 상태 3줄. 매크로 shows 금리(^TNX, ^TYX) / 환율·달러 /
원자재(6) / 심리·변동성(^VIX, ^MOVE) then central-bank table. Observatory: 4 country ETFs 미연결;
VIX, DGS10, KRW=X, DX-Y.NYB, CL=F, HG=F, GC=F, indices 본문 표시. 물가·고용·소비·경기 selected no
recent release this run (fallback text shown) — check the selection window in a later task.
PR #4 (EPS row) not yet seen in production.

### Previous direct production verification

[SEC validation audit](docs/maintenance/20261121_sec_release_refusals.md), code
**`2ac2d94b`**, direct owner Reboot complete. Report
`3d4dd44113a04b259ac4d4c7bba38e0d` /120.672s, normal generation,18 checks pass.
Four loaded/disk/Git hashes and output/diagnostic hash agree; no stale modules.
MSFT FY2027Q1 /Oct28 official release visible in detailed evidence; AAPL date and
AMAT identity still withheld. SOXL Nov20 regular return-31.83% preserved.
Parser21 /accepted9 /refused12; reason histogram matches timing failures exactly.
Discovery23.577s, parsing0.850s. SEC68 unique get attempts; DART2 attempts /1
unique (existing retry), corporate connect_timeout leaves31 issuers unavailable.
Normal report completion is not complete provider coverage. No speedup claim:
cache/input/remote conditions differ from previous reports.
Private evidence `cache/sec_refusals_20261121/`: official body captures/hash
manifest, fixed replay/parity, report(47), matching auto_report JSON,18-check
audit and operating_msft.jpg. Browser on expanded company evidence table.

### Previous profiling verification

[Filing-discovery profiling](docs/maintenance/20261121_earnings_discovery_profile.md),
code **`8604900a`**, direct owner Reboot complete. Today95.1s; completed reports:

- First `4fa936799cd74701a0bf195894fc31f3` /116.109s; repeat
  `18f64f40ba704c5da03864baf9e5b1e0` /78.992s. Both12 checks pass, completed/normal,
  output hashes match, three loaded/disk/Git hashes match, no stale modules.
- Both collect74 issuers. SEC/DART get attempts51/31 then100/33; exact duplicate0.
  DART directory10.179s→0.003s; successful issuer cache16hits on repeat, but58misses:
  this is partial warmth, not an all-cache run. Failure TTL90s unchanged.
- Discovery23.486s→24.234s; SEC rate wait active wall5.649→14.940s.
  Parsing/selection cumulative0.575→1.269s. Worker join is waiting, not CPU work;
  do not sum overlapping worker/network/queue totals. No speculative reuse applied.
- SEC release parser validation exceptions9/15 then21/31 are caught by the existing
  collector. Do not call them confirmed bugs; audit original evidence next.
- Private evidence under ignored `cache/earnings_discovery_20261121/`: reports
  `(45).md`, `(46).md`, matching auto_report JSONs and operating_<ID> audits,
  `operating_profile.jpg`. Browser left on the completed79.0s report timing panel.

### Previous short-close verification

[Report auxiliary short-close verification](docs/maintenance/20261121_report_short_close.md),
code **`10d216ab`**, direct owner Reboot complete. Today **107.1s**; completed report
**127.153s**, ID `eb46a301838b450181a765803b4dbc68`, 17:17:45–17:19:52 KST.

- 13 operating checks pass: completed/normal, no degraded reasons, no stale modules,
  report output hash and three relevant loaded/disk/Git hashes match.
- SOXL -31.83%, GOOGL -2.70% retain Nov20 regular-close basis. Holdings inactive
  weekend label visibly correct; no post price promoted. Future short session is
  fixed-clock only. Same-input normal-session outputs match in 128 local cases.
- Exclusive stages: prices32.387s, macro/official47.742s, calculations1.260s,
  news1.954s, articles2.208s, persistence13.633s, assembly27.968s.
  Old report85.817s vs127.153s is uncontrolled; no causal speed claim.
- Filing discovery23.260s despite official HTTP76calls/active wall12.136s.
  Earlier discovery23.421s /142calls/21.474s is not a like-for-like request set.
  Two customs-body attempts failed; full normal mode does not certify every source.
- Ignore separate interrupted screen-rerender diagnostics for report timings.
  This completed report's diagnostic and Markdown hashes match. Browser download
  timeout was recovered via correct visible button, not a report regeneration.
- Private evidence: ignored `cache/operating_20261121/stock_lab_market_report (44).md`,
  `auto_report_eb46a301838b450181a765803b4dbc68.json`,
  `report_short_close_operating_audit.json`, `report_short_close_operating.jpg`.

### Previous report-close verification

[Report repaired-close verification](docs/maintenance/20261121_report_repaired_close.md),
code **`bc5d8d2e`**, owner Reboot completed. Today full run **85.7s** restored held
inputs, then final report **85.817s**, ID `d3a32b05ac864f60abbd3bcb41456af0`.

- completed/normal, no degraded reasons; base matches, restart_required=false,
  stale_modules=[]. Output Markdown hash matches the same diagnostic's output hash.
  Three relevant Cloud loaded/disk hashes match committed Git blobs (LF).
- SOXL -31.83% and GOOGL -2.70% remain Nov20 regular-close returns. Exact prices
  30.88/265.29 separately checked against public quote and completed precision CSVs.
  Earlier post33.3694/270.18 is not promoted to a current holiday observation.
- SOXL/BITX/IAU holdings rows visibly say holiday / no separate current quote /
  refer to dated close. Active-session missing/delayed paths remain tested.
- UI generation attempts without a completed file were excluded. Browser logs
  recorded WebSocket closures; server cause not established. Reconnected retry
  completed. Do not describe an interrupted attempt as an app computation result.
- Ignored `cache/operating_20261121`: report `(42).md` before / `(43).md` after,
  both `auto_report_<ID>.json` files, `report_close_operating_final.json`,
  `report_close_cross_view_audit.json`, `report_quote_probe.json`,
  `report_repaired_close_operating.jpg`. No private artifacts in Git.

### Previous cross-view verification

[Cross-view audit](docs/maintenance/20261121_cross_view_price_mode.md), code
**`801cdf67`**, owner Reboot completed directly, operating checks 12:56–13:29 KST.

- All four completed precision ZIPs match deployed commit, restart_required=false,
  stale_modules=[]. Today/precision share selected price, source date and price ID.
- SOXL source Close30.88 remains separate from selected Yahoo post quote33.3694,
  supplier bar time Nov21 09:59:59 KST. GOOGL Close265.29 / post270.18 similarly.
- KR ETF free and held selection share price23180, price ID, quality/technical score
  and weights. Free code CRISIS_PANIC_SELL_OFF versus held HARD_BLOCK_OVERWEIGHT;
  held code equals Today. Existing path difference is exposed, not rewritten.
- Portfolio analysis ran; actual SOXL/KR ETF selectors show matching saved prices,
  source dates, observation time/session and price ID in the new two-row table.
  KR provider time/session unknown remains unknown; no fabricated timestamps.
- Downloads Today `_20261121_1256.zip`, precision GOOGL `(37)`, SOXL `(2)`,
  379810 `(5)` free / `(6)` held. Private ignored `cross_view_operating_audit.json`
  and `cross_view_portfolio_{kr,soxl}.jpg` under `cache/operating_20261121`.

### Previous SOXL repair verification

[SOXL close repair](docs/maintenance/20261121_cross_view_soxl_close.md): code
**`49ab429d`**, direct owner Reboot completed, SOXL result at 2026-11-21 10:49 KST.

- base_commit matches, restart_required=false, stale_modules=[]; `prices` and
  `yahoo_daily_close` loaded/disk hashes match. Authenticated session recovered.
- Source CSV now includes Nov20 Close **30.88** (OHL 42.40/42.57/29.82 and volume
  533,762,471). Regular return -31.83% correctly compares Nov19→Nov20.
- Separate selected quote **33.3694**, Yahoo chart Nov21 **09:59:59 KST**, post.
  Screen and ZIP distinguish this observation from regular close; no claim of
  current active session or certified final afterhours close.
- Scenario/underlying axis displays $30.88. Shared workflow contains both existing
  calculated weight fields. Full Today/report was not rerun; no speedup claim.
- Prices changed, so grade changed with corrected input. Existing decision formula,
  thresholds and labels remain unchanged; fixed-input regression evidence above.
- ZIP attrs allowlist excludes daily_close_repair; proof uses actual source CSV,
  matching loaded modules and separate public raw probe, not invented export metadata.
- Private evidence: Downloads `precision_review_SOXL.zip` and `(1).zip`;
  ignored `cache/operating_20261121/soxl_close_operating.json` (7 checks passed),
  `soxl_missing_close_probe.json`, `soxl_close_operating.jpg`.

### Previous display verification

[Daily-return basis deployment](docs/maintenance/20261121_daily_return_basis.md):
code **`35dd624d`**, owner Cloud Reboot completed directly; authenticated session recovered.

- GOOGL completed capture at 2026-11-21 09:42 KST: base_commit matches,
  restart_required=false, stale_modules=[]. `signal_basis` loaded/disk hashes match.
- Precision table and expanded tactical panel display actual source Close
  Nov19 → Nov20, elapsed-close/supplier-finalization-unknown status, and separate
  selected quote timestamp Nov21 09:42:12 KST / afterhours session.
- Downloaded context and execution_workflow agree on all three new fields.
  Replaying the source dates and captured clock reproduces both date/status fields.
- Current quote/input ID differs from the pre-deploy capture. No like-for-like
  operating score equality is claimed. Numeric preservation uses the saved fixed
  inputs and selected regression gate above. The existing source-bar audit rejects
  this new quote-overlay capture by design; it was not weakened to force a pass.
- Today/dashboard detail columns are contract-checked; no new full Today run or
  report generation this turn. Cross-view evidence audit is the next task below.
- Private evidence: Downloads `precision_review_GOOGL (35).zip` before and `(36).zip`
  after; ignored `cache/operating_20261121/daily_return_basis_live.json` and
  `daily_return_basis_operating.jpg`. The captured tactical panel visibly confirms
  the tactical UI path, not merely a module fingerprint.

### Previous Report Verification

[Report calendar deployment](docs/maintenance/20261121_report_exchange_calendar.md):
code **`8c0caab5`**, owner Reboot completed after one Cloud internal-error retry.

- Auto report generated at 2026-11-21 09:08 KST: **55.337s**, completed/normal,
  measurement `38e7cbbeb5fb4abfa8a4a20bcf00b274`, no degraded reasons.
- Diagnostic base commit matches; restart_required=false, stale_modules=[].
  New clock, session, report evidence and market board loaded/disk hashes match.
- Downloaded Markdown SHA256 matches the diagnostic output SHA256.
- KR holiday, last confirmed close Nov20; US regular closed/afterhours, last
  confirmed close Nov20. Both calendar sources displayed (XKRX/XNYS).
- Full Today calculation was not rerun after reboot; this report explicitly states
  account/decision inputs are absent. No claim of a new account/grade comparison.
- Special/short-session boundaries are fixed-clock tests, not live time simulation.
  Caches were not cleared; 55.337s is an observation, not a speedup claim.

Ignored evidence: `cache/operating_20261121/stock_lab_market_report (41).md`,
`auto_report_38e7cbbeb5fb4abfa8a4a20bcf00b274.json`, `calendar_report_operating.jpg`,
`partial_bar_calendar_final.json`. Downloads originals remain intact.

Previous live full Today: 95 rows/106.065s, source `eb0af4a2`, measurement
`c4cd1b65cb224e08ae4aefaee052ed76`; see the Naver observation record, not this report run.
Fixed replay sources: Downloads `precision_review_379810.KS (4).zip` and
`precision_review_GOOGL (34).zip`. Their price input IDs and limits are in the
partial-bar audit. Keep these private files out of Git.

## Next Task Only

**Decision system audit (2026-11-24):** waiting for the user's review of
`docs/maintenance/20261124_decision_system_audit.md`; the user will choose the decision-overhaul direction from it.
Open user decisions are in its §10.3 (asset/rebalance using raw engine label vs Today overlays, label-text rebalance
multipliers, two hold panels, US storm 100% DCA vs gate, core panic -40/-50% gate, macro-missing handling, four
leveraged stage tables, macro double-count). Do not change decision logic before that choice. In a fresh cloud clone run
`git fetch --unshallow origin` before the decision gate (parity tests read old commits).

**Daily market reading (2026-11-24):** verified in production 17:57 KST (after 17:53 reboot, PR #30): 시장 해석 starts
with "코스피가 +6.32% 급등해 전 거래일 -3.31% 급락을 하루 만에 되돌렸습니다", '오늘 달라진 점' lists 4 index flips + "외국인(KOSPI)
순매도 7거래일 → 순매수 전환", and the story's macro warning is gone (doc section 6). Follow-ups: sector-leader change needs the prior day's sector ranking (not stored now); earnings/policy
"completed" items for '오늘 달라진 점'. Performance: two Today JSONs (83.9s completed; 135s interrupted by a Streamlit rerun,
1.1s active) are recorded in `docs/maintenance/20261124_performance_baseline.md`; exclude rerun-interrupted runs from comparisons.

**#5 follow-up: corrected 15:55 KST. The 15:47 report had 8 time-budget withholds (KR 0 / US 8), not 38; the 12 KR issuers withheld at 15:31 all show reported revenue/profit. Diagnostics: dart_accounts 15 hits / 13 misses, DART 54 requests, discovery 23.43s. The remaining US 8 are bounded by the SEC 0.2s fair-access spacing (117 requests in 24s). Next: confirm KR stays at 0 in one more normal report; reducing US withholds would need a cache-policy decision from the user (do not change budget/spacing).**
**#5 cold-start cause (16:07 KST report, first after reboot):** the DART corporate-code ZIP took 32.8s and ran before any issuer, so all 74 issuers (US too) were withheld. Fix: the DART directory setup now runs beside the US pool; only KR issuers wait for it (no budget/timeout/retry change). Verified 16:17 KST (first report after the 16:12 reboot): 16 withheld (KR 7 / US 9) vs 74 before; SEC used its 117-request cap. Open option for the user: use the stored official snapshot first on cold start (policy change).

#5 review (order is held-first; 24s shared budget; 2–4 cold DART calls per KR issuer; 10-min caches go cold between reports): `docs/maintenance/20261124_dart_budget_review.md`.
Other open decisions for the user (do not change without approval):
- #8 AMAT: user approved (15:58 KST) ignoring trailing EDGAR state tags ("/DE", "/NEW/"); the rest of the name must still match exactly. Done in [doc](docs/maintenance/20261124_sec_edgar_state_tag.md); verified 16:17 KST: the name now matches, and AMAT is held at the next check (explicit fiscal quarter unavailable). AAPL stays withheld (no publication dateline).
- #6 preferred share 009155: needs an official issuer link; no code-convention guess.
- #3: user chose (16:35 KST) the account path for a held ticker found by free input. Done: [doc](docs/maintenance/20261124_held_free_input_account_path.md); verified 16:46 KST: 379810 free input on precision now shows the same "실행 보류 · 목표비중/비중초과 우선" as Today (Today: hard block, weight 31.4% > 25%). Known pre-existing decision-gate failure on main: test_extracted_policies_preserve_all_original_conditions_and_literals.
- Remaining observatory 미연결 that need only Yahoo daily bars: 달러/엔 (JPY=X), 비트코인 (BTC-USD). Open design points: placement (FX row vs observatory table; the options table takes every non-country OBSERVATORY_DAILY item) and BTC 24h UTC bars vs equity closes. FRED/CNN/Cboe items need new providers and a performance check.
#19 bounded refactor, step 1 done: `report_sections` "기준일" block moved to `_basis_lines` (report gate 208/208 before and after, output byte-identical on 3 inputs): [doc](docs/maintenance/20261124_refactor_report_basis_lines.md). Step 2 done: "관측 축" table moved to `_observation_axis_lines` (gate 208/208 both). Next candidate: the "보도상 배경 후보" table. One responsibility at a time, report gate before/after.

Verified in production 2026-11-24 afternoon (first report after PR #10/#11): 키움증권 "이차전지…" is under 시장·업종;
PPI 2026-10 YoY row shows "6.6% Trading Economics · 대상월 2026-10" and the 컨센서스 연결 line names the row's month and
says the 2026-09 verified survey was not used. #12 (local indices: `docs/maintenance/20261124_report_local_indices.md`)
verified in production at 14:47 KST: 7 local index rows with local dates (11-24 bars correctly withheld before each close + 30 min; Nikkei 11-20 because 11-23 was a Japanese holiday); VN-Index 미연결.
#17: "상장사 자사주…" policy headline was tracked as an IPO plan; fixed (`docs/maintenance/20261124_report_listing_news_scope.md`). Continue #17 with other content checks. #14 verified in production at 14:57 KST. #17 content checks + same-body-sentence dedup (dedup verified 15:07; duplicate-check false positive fixed after that report): `docs/maintenance/20261124_report_content_checks.md`. #14: flow-history table now states its completed-day base date and that today's provisional flow is excluded (`docs/maintenance/20261124_report_kr_flow_history_note.md`).
Known pre-existing failures on main (not from these PRs): test_bok_report_calendar (reading report),
test_summary_ownership_restore RAM (looks under "## 내 보유 종목 영향"; table moved by the reading reorder),
test_company_market_reading app adapter, test_dart_evidence_view, SEC review tests.
Duplicate-check fix verified in production 15:17 KST (통과, 39 links). #18 condition A recorded twice (Today 78.8/114.8s, report 106.2/132.1s; >30% noise, so no speed claims below that): `docs/maintenance/20261124_performance_baseline.md`.

## Verification Discipline

- Use relevant existing contracts before/after edits:
  `.venv311/Scripts/python.exe -X utf8 scripts/check_refactor.py --scope decision`
  (or `report`, `prices`, `all`). Freeze sources while the gate runs.
- No golden regeneration to pass; old Nov-7 private baselines stay archived in
  `cache/historical_baselines_20261107/`, not restored over current caches.
- Compare remote requests/cache misses separately from calls; distinguish elapsed
  critical path from overlapping worker totals. Do not change TTLs to claim speedups.
- New offline audit command and exact limits: latest audit record above.
- Source architecture: [map](docs/20261104_architecture_refactor_map.md).
  Refactor procedure: [review](docs/maintenance/20261106_bounded_refactor_review.md).
