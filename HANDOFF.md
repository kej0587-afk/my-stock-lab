# Stock Lab Work Handoff

## 2026-11-27 SOXL −20% 보완 연구 (보유기한·손절 민감도, 작업 중단 지점)

사용자 요청으로 토큰 절약을 위해 여기서 멈춤. [보완 보고서](docs/maintenance/20261127_short_term_soxl_drop_rebound.md),
스크립트 `scripts/research_drop_rebound.py`(앱 미사용, 연구 전용), 결과 JSON `/mnt/project-files/reports/short_term_study/`.
PR #108과 같은 SOXL 일봉(2010-03-11~2026-11-25)에 기준가 5종(20/60/252일 고점, 5일·1일 하락) × 보유 10/20/60일·무기한 ×
손절 없음/−10%/−20% × 비용 3단계를 재생. 결론: +10/+20 차이보다 손절·보유기한이 결과를 좌우(손절 −10%면 기대값 0 근처,
손절 없이 60일이면 +3~7%지만 최악 −63%). 2026-10-13 진입분은 11-25 기준 −73% 미청산. 앱·판정·장기·월적립·L3 변경 없음.
**다음 구체 단계:** 사용자 결정 (a) −20% 기준가 정의 (b) +10/+20/분할 청산 (c) 손절 폭 (d) 최대 보유기한 →
같은 스크립트로 TQQQ·국내외 개별주·일반 ETF 확장 → 단기 화면(진입·손절·익절·최대보유·보류 사유) 설계.

## 2026-11-27 DART 기업코드 재부팅 캐시

**이번에 끝낸 일:** #112 테스트 계약/운영 검증 기록까지 병합. DART 기업코드 준비를 분리하고,
기존 1일 수명 안의 정상 저장 목록을 재부팅 후 재사용하도록 보강했다. 공시·실적 기준과
운영 투자판정·월적립·L3는 그대로. 관련 139개, report 회귀 208개 통과.
[기록](docs/maintenance/20261127_dart_directory_cache.md).

**운영에서 확인한 일:** 차트/시안은 아래 최종 운영 확인과 동일. DART 변경은 배포 후 확인 예정.

**대기 사유:** 미국 장중 30초·공급 지연, 갤럭시 실기기, 새 연구 표본은 계속 대기.
전체 테스트 남은 16개 계약은 아직 미정리. 전체 backlog 완료 아님.

**다음 한 건:** DART 새 캐시의 재부팅 후 실제 출처·요청 수·연결 수를 확인하고,
모바일 시황 접근 거리/넓은 표를 점검한다. 동일조건 2~3회 평균이 없으면 전체 속도 개선율을 주장하지 않는다.

## 2026-11-27 최종 운영 확인 / 다음 한 건

**이번에 끝낸 일:** #108 연구 병합, #109 기존 차트 통합, #110 SOXL 2차 분봉 연구,
#111 SOXL 읽기 전용 관찰 시안·모바일 폭 수정까지 병합/배포.
1/5/30/60/120분·일/주/월 전환은 기존 분석 차트 한 곳에 통합했다.
120분 빈 화면의 연도 중복 category 축과 개장 기준 집계를 수정했다.
연구는 자료 품질 검사까지 완료했으나 검증 가능한 중첩 거래 0건으로 승률은 미확인이다.
운영 투자판정·월적립·L3에는 연구 규칙을 적용하지 않았다.

**운영에서 확인한 일:** 60→120→5→120, 120 선택 활성 + 캔들/거래량 각 1,500개.
원본 60분 5,055개 → 120분 2,892개(전체/표시 범위 구분).
일봉 복귀 시 패턴·추세선·매물대와 MA 5/20/120/240/1000 설정 복원.
계정 저장 후 재접속 복원 확인. SQL 직접 재조회는 하지 않았고 #107 실행 성공 기록과
이번 저장/복원을 대조했다. 412px 브라우저에서 가격 차트 폭 370px 확인(실제 갤럭시 아님).
SOXL 일곱 항목 시안에서 기준시각/진입/손절/익절/보류 사유가 보이고 기존 시장방어 유지.
실제 장 전 화면: 11/25 16:00 ET 참고 진입 32.02/손절 30.41/1R 33.63 USD,
채널 이탈·정규장 외·시장방어 보류. 현시점 매수 제안이나 새 -20% 연구 결과가 아니다.

**대기 사유:** 미국 정규장 전이어서 마지막 봉 가격·거래량 변화, 30초 갱신/원천 시세 지연 미확인.
갤럭시 첫 캔들/전환 시간은 실기기 미접근. 연구는 일봉/분봉 가격 불일치·결측과
당시 시장방어 유효기간 원본 부족. 새 독립 표본 0건, 자동 수집 서비스 미가동.
다른 PC 전용 파일은 확인 불가. 전체 backlog 완료라는 뜻이 아니다.

**검증:** decision 1,669 통과, 차트/시안 34 통과, 수정한 기존 계약 관련 74 통과.
전체 baseline 10,070 통과/207 실패/4 skip. 188개는 지원 pandas/numpy 재실행에서 통과,
남은 19개 중 오래된 계약 3개를 수정해 통과. 아직 16개는 과거 AST/출력 위치 계약 대조 필요.
[테스트 분류](docs/maintenance/20261127_test_baseline_audit.md),
[DART 측정](docs/maintenance/20261127_dart_cold_audit.md).

**다음 한 건:** DART 기업코드 cold 준비 10.546초를 기존 1일 캐시 의미를 유지한
재부팅 후 재사용으로 줄일 수 있는지 검증. 인증 오류를 가리거나 공시/재무 기준일을
늘리지 않고, 동일 입력 cold/warm 2~3회에서 연결 수·시간 한도 건수와 함께 비교한다.
이후 모바일 시황 접근/넓은 표 → 미연결 자료 → 실제 외부요청 병목 → 남은 16개 계약 정리.
장중/실기기/새 연구 표본 대기 때문에 위 다음 작업을 막지 않는다.
운영 허용·장기판정·월적립·L3 변경, 다른 종목 운영 신호, 유료 계약만 사용자 결정 대상.
아래 항목은 과거 경과이며 이 맨 위 기록이 우선한다.

## 2026-11-27 SOXL 관찰 시안 / DART cold 측정

**이번에 끝낸 일:** #108 연구, #109 통합 차트, #110 분봉 2차 연구 병합 완료.
SOXL 기존 1시간 계획을 일곱 항목 읽기 전용 요약으로 연결하고 중복 가격 표를 제거.
모바일 metric 2열 CSS가 정밀관측소의 큰 차트 열까지 좁히던 선택자를 제한.
새 -20%/+10·20% 연구는 운영 신호/승률로 연결하지 않았다.

**운영에서 확인한 일:** 통합 차트 120분 캔들·거래량/일봉·설정 복원은 #109에서 확인.
재부팅 후 첫 전체 계산 114.302초(101종목), 별도 첫 시황 122.100초.
DART 회사코드 준비 10.546초, 공시 수집 전체 23.423초, 한국 실제치 연결 14개 /
시간 한도 12개. 이번 시안과 모바일 CSS의 운영 화면은 배포 후 확인 예정.

**대기 사유:** 미국 정규장 전/갤럭시 실기기 미접근. 분봉 가격 대조와 과거 시장방어 기록 미확보,
독립 모의 표본 0건. 전체 tests baseline 10,070 통과/207 실패/4 skip(720.97초),
177개는 pandas 3 환경의 동일 read-only mask 오류. 운영 범위 pandas 2.3.3/numpy 1.26.4로
재검증해 177개 모두 통과(40.65초). 남은 30개는 별도 분류 중. 성공 기준 재생성 금지.

**다음 한 건:** 시안·모바일 운영 화면 확인 후 DART 회사코드 cold 준비와 시간 예산 처리 보강.
장기판정·월적립·L3/운영 신호·유료 계약은 변경하지 않는다.
[시안](docs/maintenance/20261127_soxl_observation_prototype.md).


## 2026-11-27 차트 운영 확인 및 SOXL 2차 자료 검증

**이번에 끝낸 일:** #108 연구 병합, #109 차트 통합 별도 병합(`d9cbac8a`).
2차 연구 규칙 사전 고정(`1acdeb00`), 1/5/60분 원자료·해시·재생 코드·품질 대조 보존.
332진입 중 16건 기간 중첩이나 12건 일봉/분봉 가격 불일치·4건 결측 포함으로 확정 성과 0건.
승률 0%가 아니라 미확인. [2차 기록](docs/maintenance/20261127_soxl_phase2_report.md).

**운영에서 확인한 일:** SOXL 60→120→5→120 전환, 가격 캔들 차트 1개,
120분 선택 상태 및 실제 캔들/거래량 각 1,500개, 일봉 레이어와 계정 MA 설정 재접속 복원.

**대기 사유:** 실제 갤럭시 기기 미접근, 미국 정규장 전이라 30초/원천 지연/마지막 봉 변화 대기.
당시 시장방어 유효기간 원본·가격 대조가 통과되는 분봉 자료 미확보. 독립 모의 표본 0건,
규칙은 고정했으나 자동 수집 서비스는 가동 안 함. 다른 PC 전용 자료는 확인 불가.

**다음 한 건:** SOXL 전용 읽기 전용 단기 관찰 시안과 재사용 구성 정리.
이후 DART cold 시간 측정, 모바일 2열 차트 폭, 남은 성능/현행 테스트 실패 순으로 진행.
운영 매수 허용·장기/월적립/L3·다른 종목 운영 신호·유료 계약은 사용자 결정 전 변경 금지.
아래 과거 미병합/운영 대기 기록은 이 항목으로 대체한다.

## 2026-11-27 기존 차트 통합 (최우선 인계)

**이번에 끝낸 일:** PR #108 범위 확인 후 연구 기록으로 병합(`b3a78694`). 별도 차트 브랜치에서
상단 빠른 차트 제거, 기존 분석 차트의 8개 봉 간격·MA 설정 통합, 연도 중복으로 비던 120분 축 수정,
거래소 개장 기준 집계와 전일 MA 겹침 수정. [상세](docs/maintenance/20261127_unified_analysis_chart.md).
연구 결과는 모의검증 후보이며 장기판정·월적립·L3는 변경하지 않았다.

**운영에서 확인한 일:** SOXL 60→120→5→120 순서에서 120 버튼 선택·자료 수신은 정상이나
가격·거래량이 비는 현상을 재현. SQL 적용·계정 복원은 PR #107 기록을 유지한다.

**대기 사유:** 수정본 운영 배포/화면 확인 진행 중. 미국 정규장 미개장으로 장중 마지막 봉 변화·
30초 재조회/원천 지연은 대기. 실제 갤럭시 기기에 접근하지 못해 기기 시간은 미측정.

**다음 한 건:** 기존 차트 통합 및 120분봉 운영 확인을 완료하고, 분봉 중첩 표본의 SOXL 2차 검증으로 이동.
이 아래 과거 '미병합/사용자 승인 대기' 지시는 대체한다. 후속 연구·시안·DART 측정은 승인됨.
운영 매수 허용·장기/월적립/L3 변경·다른 종목 운영 신호·유료 데이터 계약은 별도 사용자 결정.

## 2026-11-27 SOXL Research Handoff (read this first)

**확인한 중단 지점:** 원격 main `ad5f6f1f` / PR #107까지 반영, 시작 시 주 작업 트리 clean,
열린 PR 없음. PR #106 빠른 차트 구현, #107 SQL 적용·재접속 복원 검증은 완료 상태였다.
기존 11/13 SOXX 1시간봉 연구는 있지만 새 SOXL -20% 기준가/+10·+20% 비교 결과는 없었다.
다른 Claude 작업 트리의 월적립 `app.py` 수정과 11/16 임시 baseline 삭제 상태는 건드리지 않았다.

**이번에 끝낸 일:** [SOXL 비교 보고서](docs/maintenance/20261127_soxl_drawdown_report.md).
전일 종가/직전 20일 최고 종가 × 종가 확인/장중 도달 × +10/+20 목표 8개 안을
같은 진입 날짜·가격·금액으로 비교했다. 결과 수집 전 프로토콜 커밋 `5ada8a50`.
공개 일봉 4,205개(2010-03-11~2026-11-25), 신호·거래·일별 계좌곡선·해시·재실행 코드 보존.
전일 종가 -20%는 두 목표 모두 평균손익 음수. 20일 최고 종가 -20%는 평균 양수지만
기간별 불안정·갭 손실이 있어 운영 채택 근거로 단정하지 않는다. 장기판정·월적립·L3·앱 코드는 변경 없음.
새 연구 21개와 빠른 차트 9개 테스트 통과. SOXL 포함 선택 회귀는 기존 실패 1건을 수정 전 커밋에서 재현했다.
운영 14:22~14:24 KST: MA 복원·일봉/5분 표시 확인, 캐시 재조회 첫 차트 데이터 표시 약 3.9초(서버 0.11초).
연구 브랜치 `research/soxl-drawdown-paired-exits-20261127`; PR 검토용이며 main 병합·운영 재부팅은 하지 않는다.
[PR #108](https://github.com/kej0587-afk/my-stock-lab/pull/108) 생성·푸시 완료. 연구 커밋 `5ec914a5`, 사전 조건 `5ada8a50`.

**아직 확인하지 못한 일:** 다른 PC와 `/mnt/project-files/` 전용 자료는 확인 불가.
미국 정규장이 닫혀 있어 SOXL 장중 30초 마지막 봉 갱신·실제 시세 지연은 운영 확인 대기.
과거 분봉 순서, 당시 실제 체결, 독립 기간 외 성과, 과거 시장방어 통과 여부는 이번 일봉 연구로 검증하지 않았다.
SQL은 #107 적용 기록과 운영 설정 복원으로 확인했으며 이번에 DB DDL/RLS를 재조회·수정하지 않았다.

**다음 한 건:** 미국 정규장에 SOXL 30초 마지막 봉 갱신과 공급 시세 지연만 실측한다
(11/27 단축장 23:30 KST~11/28 03:00 KST). 단기매매 화면 반영·다른 상품 확대는 보고서 검토 후 사용자 결정.
아래 누적 작업 지시보다 이 인계가 우선한다.

Updated: 2026-11-27 KST. Read before large source files or edits.
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

[A-5/A-6 missing macro](docs/maintenance/20261125_a5_a6_macro_missing.md) (user-approved option A, 11-25): a failed
collection or any missing core input (10Y, VIX, USD/KRW, oil) gives macro risk NaN / UNKNOWN (no 1.5 / 0.5 assumption,
missing input no longer counted as 0); MOVE missing adds 0 and shows "MOVE 미확인". Incomplete results are never cached
(`_MacroIncomplete`). The engine runs the rules macro-neutral (risk 0 / penalty 0 internally, `macro_state` UNKNOWN,
reason "FMR 미확인"); `build_execution_gate` sends UNKNOWN to 데이터확인 "매크로 미확인 · … 데이터 누락" after all
defense checks, so 방어우선 stays. Diagnostics: `stock_lab_core/macro_status.py`, `macro_data_status`,
`macro_missing_components`, `last_complete_macro_at` (never reused in decisions). 30,278-state replay: only the expected
V2 changes (580 codes); normal-macro parity byte-identical. Core ETF DCA also stops on missing days (C-13).
Production: rebooted 2026-11-25 11:44 KST (includes A-4); header `매크로 지수: 0.5pt`, 5 indicator cells, 정밀관측소 GOOGL
11:45 KST unchanged (`실행 보류 · 상위 시간대 추세훼손`, no nan). A real missing-macro day was not observable; covered by tests.

### Previous: A-4

[A-4 PROFIT_TAKE_REVIEW](docs/maintenance/20261125_a4_profit_take_review.md) (user-approved 11-25): group buyish → caution,
monthly multiplier core/swing 1.0 → 0 (`rebalance_multiplier.POLICY_MULTIPLIER_BY_CODE`), leverage stays 0. The code is
unreachable in the current engine (profitable holdings never reach `select_holding_decision`), so parity replay is
byte-identical and decision gate is 1661 passed / 1 known failure. The 52 profit-condition states that get 1.0x under
other codes are recorded as C-12, not changed.

### Previous: decision policy v1 A/B stage

[Decision policy v1 A/B stage](docs/maintenance/20261124_decision_ab_stage.md) (user request 11-24, no result change):
A-1 perfect-storm manual wording matches the emitted label; A-2 hold panel says "매크로 미확인" when macro is missing
(score unchanged). B-1 `decision_behavior_groups.py` (127 codes → 9 groups); B-2 code-based group table +
`resolve_decision_group` (every emitted label keeps its old group); B-3 `rebalance_multiplier.py` (multiplier from
decision_code / core DCA stage, legacy parser only as fallback; signal rows carry `_ticker_signal_decision_cache`);
B-6 `decision_code_sets.py` (Today lists, core panic set, precision plan block/wait as explicit set differences);
B-7 `app.apply_precision_post_decision` (demo + precision; Today kept inline for per-stage error isolation);
B-5 `leverage_stage.py` (reads L0/LX/L1/L2 from the final decision, L3 reserved for C); B-4 `tech_review.py` +
`tech_review_view.py` shadow verdict shown in 정밀관측소 under the role table, never written back.
Changed files: app.py, stock_lab_core/{decision_engine,today_queue,monthly_rebalance,monthly_rebalance_view,
print_report_data}.py, the six new modules above + `rebalance_multiplier_table.py`, scripts/{policy_replay,check_refactor}.py,
tests (5 new files, 3 updated). Verification and parity results: doc §2.
Production: rebooted 2026-11-25 09:41 KST; 09:43 KST 정밀관측소 GOOGL shows the shadow panel (CAUTION, 6 reasons)
beside the unchanged decision (QUALITY_RECOVERY_WATCH, 방어우선).

### Previous: decision policy validation plan

[Decision policy validation plan](docs/maintenance/20261124_decision_policy_validation_plan.md) (user decisions 11-24
on the proposal, docs + read-only replay only): replayed the current engine/gate on history with
`scripts/policy_replay.py` (33 stocks 2015–2026 weekly = 17,902 rows; TQQQ/QLD/SOXL 2012–2026 × 5 cost levels = 10,875;
R/R counterfactual gate 5,878). Findings: executable rate is lowest in bull markets (1.9%); pivot R/R blocks leaders
(measured-move target: 16%→81% executable, 0.18R→0.68R) but EXCEPTION_ENTRY ("정찰" word → ⏳눌림대기) and LEADER_MA5_*
(wait list) stay 0% whatever the target; BREAKOUT_52W_ENTRY never fired; macro 2.5–4.5 downgrades come from the adj
penalty alone; leveraged ETFs never reach 실행가능 while the rebalance multiplier gives 0.5x in 2,904 states. A/B/C plan
with order, tests and replay method in §9. No rule changed. Decision gate 1637 passed / 1 known failure.

### Previous: decision policy proposal

[Decision policy proposal](docs/maintenance/20261124_decision_policy_proposal.md) (user request 11-24, docs only):
compared the early 관제탑 manual with Git history and current code, grouped all 127 emitted codes (107 literal + 20
variable-emitted; the audit's dictionary-only list is corrected) into 9 behavior groups, designed a technical-review
layer (CONFIRM/NEUTRAL/CAUTION/BLOCK/DATA_CHECK, forced structure blocks kept separate), traced upside features and
leverage rules to their commits, counted 11 macro touch points, and ended with 구현 오류 / 구조 정리 / 투자정책 결정
lists (I-1..I-16, D1–D13). Main upside bottleneck found: the R/R target (nearest pivot or projection = wait). Evidence:
`scripts/decision_policy_cases.py`. No score, threshold, code, permission or DCA change. Decision gate 1637 passed / 1
known failure.

### Previous: decision system audit

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

**Current (2026-11-27):** SOXL -20% paired-exit research is finished; see the four-part handoff at the top
and [report](docs/maintenance/20261127_soxl_drawdown_report.md). One next task: measure the remaining
SOXL live last-bar refresh/quote delay during a US regular session. Do not deploy the research rules.

### Historical work orders (superseded by the current handoff above)

**Current work order (user, 2026-11-26 21:18 KST; replaces the order below; status table §4):** errors and speed before new features.
(1) prod-check records up to date (done: status table v3). (2) incomplete results visible to the user: report made right after a reboot
before Today shows 0 companies → now labelled `오늘 점검 미계산` with counts for 확인 결과 0개 / 일부 조회 실패 / 공식값 없음 and a
warning above the 시황 view (PR after #82); BOK MPC '예정' fixed by PR #82 (collector `central_bank_results` BOK, main-page link →
통화정책방향 decision paragraph; live check on the home PC pending, bok.or.kr blocked from the cloud); still to check: KR export data
timeout, US filing time budget, classify the 33 known test failures by effect on report / decision / account amounts. (3) measure the
deployed version (Today 100 tickers 115 s, report 113 s before): first boot / same-condition rerun / plain refresh, time to first readable
summary and to completion, external requests, missing counts, decision/amount parity; fix the slowest stage first. (4) report and
observatory quality → needed refactoring → short-term trading. (5) Android/Google Play: review item only. Result format: one table
`문제 | 사용자에게 보이는 영향 | 수정 전후 수치 또는 화면 | 운영 확인 상태 | 남은 일`. Decision rules and monthly multipliers unchanged.

**Progress on the order above (updated after each unit, user 23:21 KST):** PR #82/#83 BOK result (prod 22:01 KST: 3.00%→3.25% in the
central-bank table, 오늘 달라진 점, calendar row), PR #84 미계산 labels (prod checked), PR #85 XKRX calendar race (first Today run had
0 '거래소 달력' rows) and 33 → 22 known failures (`docs/maintenance/20261126_known_test_failures.md`). Prod timings (condition A,
`20261126_prod_check_bok_today_gate_perf.md`): Today 87.8 / 75.3 s, report 125.0 / 63.7 s, refresh 26.4 s. Speed round 1
(`docs/maintenance/20261126_speed_round1.md`): KR history requests sliced from a wider window inside one calculation; EDGAR
accession documents kept for a day (PR #87). Re-measured 23:35 KST (PR #88 doc): KR history 384→328 requests, rerun SEC 94→61 requests / wait 43.9→26.6 s, decisions and amounts identical; first-run Today 108 s because Yahoo metadata lock wait 42.7 s appeared (serialized on purpose against 429; not changed). Assembly timing spans added (report_sections, compose_reading_report, post_close_brief, earnings_pipeline) to find the +12 s assembly growth. **Next:** re-measure condition A through the home-PC thread (ask the coordinator; do not merge
to main while it measures, Streamlit auto-redeploys), then the first-boot SEC wait (needs the user's policy choice: request spacing
or stored filings) and showing the quick summary before the full report.

**SEC 8/s trial A (user 2026-11-27 02:06 KST; doc `docs/maintenance/20261127_sec_rate_trial_a.md`):** app-wide limiter
`stock_lab_core/sec_rate.py` (≤8 SEC requests in any 1 s; 429 → pause all for Retry-After/600 s; second limit or >8 → legacy 5/s).
**Trial start 2026-11-27 02:30 KST, ends 2026-12-04 02:30 KST (code reverts automatically; no extension).** Compare 3 pairs of
first-after-reboot reports legacy (`sec_rate_mode = "legacy"` secret) vs A, median; reruns recorded separately. Adopt only if SEC
wait −30% with no more time-budget failures, or failures −30% with no more wait, and official count not lower; then set
`ADOPTED = True`. Otherwise legacy and stop. Afterwards: show the last completed report (with its time) first while a new one
builds; find the +12 s assembly growth from the `report_assembly` spans; Supabase filing store (B) only if reboot re-downloads dominate.
**A1 (A only, reboot 02:18 KST):** report 123.3 s, first summary 166.1 s, SEC wait 17.8 s / 146 requests, no access limit, official 23, time-limit failures 10 (all KR). Rerun 67.5 s, SEC 0 s / 32. **Result (3 pairs, 2026-11-27 09:12-10:25 KST, office PC, PR #92 `docs/maintenance/20261127_sec_rate_trial_a_pairs.md`):** medians legacy → A: SEC wait 44.4 → 26.7 s (−40%), time-limit failures 16 → 8 (US 0), official 21 → 23, report 121.2 → 119.7 s, first summary 164.6 → 155.4 s; no access limits. Both adoption rules met → **adopted, `ADOPTED = True`** (merged with PR #91). Secrets `sec_rate_mode` line removed by the user 10:15 KST. Total time barely moved: earnings collection waits for its 24 s budget; remaining failures are KR (DART).

**Last completed report first (user 02:06 KST; decided 06:28 KST: create Supabase `report_latest`, merge PR #91 only after the SEC
comparison; doc `docs/maintenance/20261127_last_report_first.md`):** `stock_lab_core/report_latest.py` stores each new complete report
per verified login + selected account set (`account_key` hash), restores it once per session even before Today runs, and keeps it
when a new report fails or is 미계산 (replaced only by the next complete one). SQL `docs/20261127_report_latest.sql` (RLS forced,
service_role only) applied 10:33 KST. **Merged (PR #91, main 2db1e580) and prod-checked 10:29-10:47 KST:** after reboot, the 오늘 점검 screen shows the last report caption 7.9 s after entering (first screen 8.5 s), before Today; 시황 view body 3.4 s; a 미계산 new report kept the old one; after Today a new report (148.7 s on screen) replaced it and updated the row. Not tested live: other user/account isolation (unit tests only). Prod check in the user's order: save one report → reboot → before Today the last report and
its time are visible (record time to visible), then new report completion time.

**Report quality round 1 (work-order step 4; doc `docs/maintenance/20261127_report_quality_round1.md`):** from the 10:46 KST prod
report and a 390 px check: index table now shown once (빠른 요약), 빠른 요약 lists the top-3 holdings' move (copied, no new numbers),
DART actuals read as 조/억원 (exact won in 상세 근거), 주요 기업과 사건 keeps 10 rows (body-confirmed first), rest in 상세 근거; phone-only
smaller title. **Merged PR #94, prod-checked 11:13 KST** (all four visible; 390 px title 440→62 px, holdings impact 7,070→4,410 px). Session order, 외국인 units and title/body labels were already right. Round 2: top-of-자산 현황 line '이번 달 월적립' (월계획액·누적 집행기록액·남은 계획액·오늘 추가 가능액, 미확인 never summed) and 2-per-row metric/macro cards on phones. Merged PR #95-#97, prod-checked 11:28/11:45 KST (monthly line at 591 px, was ~5,150 px; cause text names 기술적 타점계산, which fills the monthly signals). Next: 오늘 점검 → 시황 still ~2,400 px on phones, 34 wide tables.

**Staged refactoring (work-order step 4, after report quality; doc `docs/maintenance/20261127_refactor_report_sections_tables.md`):** #19 steps 3–6 moved the four remaining tables out of `report_evidence.report_sections` (452 → 245 lines) unchanged: `_background_candidate_lines`, `_economic_release_lines`, `_sector_why_lines`, `_watch_candidate_lines`. Base main `a349e4af`: check_refactor all 2 known failures / 2,495 pass both; full suite the same 22 known failures / 10,200 pass both; all 129 `report_sections` outputs recorded during the full suite identical (25 market_memo ones print the current minute, re-run in the same minute = identical); 10 synthetic inputs byte-identical. Tools: `scripts/report_sections_parity/`. Cloud clone is shallow: run `git fetch --unshallow origin` first or ~600 snapshot tests error. Prod-checked 12:07 KST report (reboot 11:55:58, office PC): the four blocks match the 11:13 KST pre-#98 report line by line apart from live data. Open question: both reports show no 관심 후보 table rows (pre-existing; check whether no non-held rows existed). Step 7 (same doc): 시장 스토리 fact lines → `_market_fact_lines` / `_story_cause_lines`, `report_sections` 245 → 168 lines, same checks all identical (base `51c084c5`); Merged PR #99, prod-checked 12:18 KST report (13 fact lines identical to the 12:07 report with numbers masked). Empty-looking 관심 후보 block: the table had moved to 포트폴리오 · 교체 검토; `additional_evidence` now adds "표는 위 '…' 구역에 있습니다." when only the explanation is left (PR #100, prod-checked 12:36 KST; also added to 지수·매크로 한눈에, 내 보유 종목 영향, 중앙은행 공식 결과, 시장 안전장치). **Data follow-up seen in that report (not caused by #100, cause not traced):** the KR filing actuals table (15 companies) was missing in the 12:07 and 12:36 reports but present at 12:18; the 12:36 report says DART live corp-code lookup failed and the stored list was used. Fixed display (doc `docs/maintenance/20261127_kr_filing_actuals_gap.md`): when Korean actuals are absent the block now states 미계산 / 일부 조회 실패 / 공식값 없음·미연결 / 확인 결과 0개 with reasons and counts from `pipeline.coverage.missing`; prod-checked 12:55/12:57 KST: first report after reboot 14 connected / 13 time budget / 2 absent of 29, second report 28 connected / 1 absent. **Open speed item:** first-report KR filing collection hits the 24 s budget for ~13 of 29 issuers (all of them when the DART corp-code live fetch also fails); options need measurement + user choice. app.py step 1 (doc `docs/maintenance/20261127_refactor_portfolio_asset_rows.md`): `build_portfolio_analysis_report` per-holding loop → `_portfolio_asset_rows` (411 → 340 lines); full suite / gate failure lists identical, 5 synthetic portfolios' full return values identical (`scripts/portfolio_analysis_parity.py`). Prod-checked 13:03 KST (risk 86/100, asset table, notes same; pre-value run may already have been new code). Step 2: risk-index components → `_portfolio_risk_components` (340 → 296 lines), same checks identical. Prod-checked 13:11 KST (identical). Step 3: risk notes → `_add_portfolio_risk_notes` (296 → 266 lines), same checks identical; prod baseline recorded before merge (13:12:39, old code) and after reboot 13:20 KST byte-identical (PR #104). Batch #98–#104 all prod-checked. **Rule from now on:** ask the office-PC thread to record the old-code values before merging (Streamlit redeploys on merge). **Next refactor step:** portfolio return metrics block of the same function, or another ROADMAP function. After refactoring: intraday charts/MAs (SOXL first) → short-term criteria.

**Follow-ups after errors/speed (user, 2026-11-26 21:28 KST), order: charts → short-term verification, in Streamlit:**
(a) intraday charts for KR/US stocks, ETFs, leveraged ETFs: 1/5/30/60/120-minute and daily bars; recent chart first on click, live
update of the last bar's price/volume during the session; measure first-chart and bar-switch time on SOXL; show realtime support,
delay and available history per market. (b) moving averages: user-entered periods incl. 5/20/120/240/1000, toggle each line, saved
settings; default computed on the chart's own bars; review daily MAs over intraday bars; show "데이터 부족" when history is short
(e.g. 1000-day). (c) short-term trading criteria (KR/US stocks, ETFs, leveraged ETFs; SOXL first): define the "−20%" reference price
first, replay +10% vs +20% exits on the same entries (win rate, avg P/L after costs, max loss, holding days). Long-term decisions,
monthly DCA and L3 stay. When errors/speed are done: one summary split into existing implementation / new development / needed price
data and cost for these three items.

**Quick chart (follow-ups (a)+(b), 2026-11-27; doc `docs/maintenance/20261127_quick_chart_ma.md`):** 정밀관측소 now opens with a
fragment chart (1/5/30/60/120-minute + daily, Yahoo regular session; 120m = two 60m bars per session; 30 s refresh of the in-progress
bar during the session; shows last bar, measured lag, received range, MA shortage). MAs: typed periods (default 5/20/120/240/1000),
per-line toggle, daily-MA overlay on intraday bars (through the previous close), "데이터 부족" when bars < period, saved per login in
Supabase `chart_preferences` (SQL `docs/20261127_chart_preferences.sql`, NOT applied yet; until then session-only with a caption).
Files: `stock_lab_core/{intraday_chart,intraday_chart_view,chart_preferences}.py`, app.py (7 lines), tests/test_intraday_chart.py.
SOXL server time (cloud, 3-run median): first 0.43 s, switches 0.20–0.25 s, cached 0.10–0.12 s; browser payload ~245 KB.
KR Yahoo 1m measured ~20 min behind (13:26 KST); Naver blocked from the cloud, KR realtime not connected. US live lag not measured yet.
**Merged PR #106 13:37 KST; table created 13:50 KST (user OK 13:49); prod-checked 13:51–13:58 KST (doc §7):** SOXL first chart 5.4 s wall
(server 0.40), switches 0.6–3.7 s; 005930 4.4 s, switches 0.4–0.9 s, lag 20–21 min (1m/5m); MA shortage line, daily overlay, save + reload restore OK.
**Next:** US-session SOXL live lag/refresh check, then follow-up (c) short-term criteria (define the −20% reference first).

**Work order after C-6/C-11 (2026-11-26 14:40 KST, full status table `/mnt/project-files/status/20261126_stock_lab_status_v3.md`):**
(1)–(3) C-8/C-9/C-12/C-13 **decided 2026-11-26 15:03 KST (C-8 one-tranche-per-day rule 15:13) and applied** (doc `docs/maintenance/20261126_c8_c9_c12_c13_apply.md`): C-12 monthly 0x for the 3 codes when the profit condition holds; C-9 screen text '100% = 1x of the ticker's normal monthly share'; C-13 macro missing/recovery log + monthly caption; C-8 crisis fund (time split 6, guard respect, 1 tranche per ticker per day, per-ticker fund + account cash check, candidate without a saved fund). Tables created 15:53 KST, PR #69/#70 rebooted 15:54, monthly panel and precision hold panels checked 15:56–16:00 KST. Supabase tables `crisis_fund_plans`/`crisis_fund_executions`/`macro_status_events` (SQL in `db_schema.get_crisis_macro_log_create_sql`). (4) C-7 hold panel: **comparison done 2026-11-26 (doc `docs/maintenance/20261126_c7_hold_panel_compare.md`), **user chose (c) 2026-11-26 and applied** (§8 of that doc): single verdict from hold_judgement, lower panel = evidence (fin trend, macro), '현재 보유분 관리' and '오늘 추가매수' shown separately (gate only), loss emergency exit needs MA 역배열 (445 states moved to 🚨/📉/⚠️, table §8.2; fin 0/1 boundary tests §8.3), fin ≤0 exit kept; verdict shown once (upper panel), lower panel evidence only (PR #72, rebooted 16:24, checked 16:27 KST). (5) C-10 YELLOW scout + D12b: **comparison done 2026-11-26 (doc `docs/maintenance/20261126_c10_d12b_yellow_leader_compare.md`), **user kept both as is (2026-11-26, comparison done · 현행 유지)**: YELLOW new entry stays 1/3 first scout, holding adds keep shortfall/monthly formula, leader overweight block stays. (6) long-term stock monthly execution rate: **analysis done 2026-11-26** (doc `docs/maintenance/20261126_long_term_stock_execution_rate.md`, mock account, C1 as is): planned stock-months executable at least once 14.6% (149/1,019), replay executable rate by amount 14.6%; months with no executable day mostly blocked first by stock timing (MTF trend damage 382, R/R/overheat/condition 448), market defense 39; timing-only full-month blocks 89. App records (16:43 KST): plans and executions tables empty. Monthly screen now uses the standard names (PR #74, rebooted 16:51, checked 16:52–16:53 KST) (월계획액 · 누적 집행기록액 · 남은 계획액 · 오늘 추가 가능액 · 현재 대기액 · 계획 초과 집행액 · 앱 기록 기준 실제 집행률; 0원 vs 미확인), `monthly_execution.standard_amounts`; gate and amounts unchanged. User 2026-11-26 17:10 KST: keep C1; 870 never-executable months replayed under 6 options (doc §5): single relaxations R/R 108, overheat 0, condition wait 153, MTF 80 months; all four together 635 months (73.0%), Δ 29,325,000 of 40,200,000 (72.9%); status 'analysis done · C1 kept'. Report overhaul started: earnings profit rows split into 영업이익/순이익/GAAP EPS/조정 EPS (unlabelled EPS separate), '오늘 달라진 점' always shown, closing section '마무리 · 보유 종목 영향과 다음 확인 사항' (doc `docs/maintenance/20261126_report_overhaul_earnings_closing.md`). PR #76 rebooted 17:29 KST; PR #78 (sector leader change, completed official results) merged 19:41. **Rebooted 20:33 KST (main e079af9e) and prod-checked 20:36–20:43 KST** (doc §6): profit rows (SK hynix/PANW/NVDA/INTC), sector-leader lines in '오늘 달라진 점' (KR 4, US 12), closing section (holdings rows copied from the portfolio table, 5 next items), monthly columns (남은 = 오늘 추가 가능액 + 현재 대기액 for all 7 rows). Not seen in prod: a '발표 완료' line (no official result on the 11-26 KR / 11-25 US sessions; BOK MPC 11-26 still 예정 in the report). Follow-up: PANW EPS from the net income sentence fixed by PR #80 (rebooted 20:56 KST, checked 21:03 report: GAAP EPS $0.57 and 조정 EPS $1.05 rows filled, doc §7). BOK MPC official result not collected yet: page structure recorded in `docs/maintenance/20261126_bok_mpc_source_structure.md` (latest decision via main-page link `통화정책방향 (date)` → P0000559 view `div.dbdata`; press list pages show "준비중"; meeting table decision cell empty on the day). Collector built (PR #82) and fixed against the live page (PR #83: main-page link query normalized, body heading skipped). **Prod-checked after reboot 21:56 KST (dd6835e5, PR #83–#85)** in `docs/maintenance/20261126_prod_check_bok_today_gate_perf.md`: BOK row in the central-bank table, '발표 완료' daily-change line, schedule row '공식 결과 확인' (3.00% → 3.25%); Today-not-calculated warning and report labels (PR #84); no '거래소 달력 조회불가' rows (PR #85); condition A run 1 Today 87.8 s / report 125.0 s, run 2 75.3 s / 63.7 s, refresh 26.4 s. Note: merging to main during a prod check auto-updates the app and cuts running work (21:31 and 21:52 reports lost). Speed round 1 (PR #87, e1193866) re-measured after 23:35 reboot (`docs/maintenance/20261126_perf_round1_remeasure.md`): Today 108.0 s (kr_history requests 384→328, slice_reuse 85, but a new 42.7 s Yahoo metadata lock wait), report 130.0 s; run 2 73.6 s / 72.2 s (SEC requests 94→61, sec_archive hit 33; assembly +12 s unexplained); refresh 13.7 s. Earnings line, 2 data-check rows, monthly 오늘 추가 가능액 distribution unchanged; decision codes identical between runs 1 and 2 (21:56 codes were not saved). (7) report: #7
earnings fields, #9 step 3, daily-reading follow-ups. (8) observatory/economic links (#10/#12/#13/#15) with a perf check.
(9) performance #18, Naver intraday comparison, cross-view fixed cases. (10) #19 next step, the 33 known test failures, B-8.
Date-bound: observe the 11-27 (Fri) US short session in a real report. Kept on hold: #6 preferred-share link (no official
source), AAPL release date (no dateline). Do not restart completed items (table marks prod-checked vs not).

**New follow-up after the list above: short-term trading decision redesign (user, 2026-11-26).** Background: the user bought
SOXL in small size after a big drop and sold at about +10–20% over their own cost a few times, while the app only showed
long-term / monthly / L3 hold or risk with no short-term entry or exit basis. Scope: KR/US stocks, normal ETFs, leveraged
ETFs; SOXL is the first case. Deliverables: existing-feature map (swing radar, flow/volume, precision pattern/supply/
position/scenario, entry/exit) without double counting and with candidate quality vs real entry kept apart; holding period
and trade types (crash rebound, uptrend pullback, volume breakout) per product group; a per-ticker view (state | entry zone
+ confirmation | stop/invalidation | take-profit/trailing | max holding | today's hold reason) with long-term and short-term
quantities/budget/exits kept separate; SOXL numbers as hypotheses ("−20%" basis undefined; "+10/+20%" = over own cost),
both exits on the same entry sample incl. misses: trades, win rate, avg P/L after costs, worst trade, strategy MDD, holding
days. First output: status table, design, replay comparison, and which existing blocks apply only to long-term DCA. Design
starts only after items (1)–(10); no rule change before the user's decision.


**C-1 policy (2026-11-25, user decision after the C-1/C-1b comparison):** apply one at a time, each with a replay diff
and regression tests: (1) EXCEPTION_ENTRY = executable 1/3 scout + trend exit — done (PR #40, prod checked 11-25 13:25 KST), `docs/maintenance/20261125_c1_step1_exception_trend_exit.md`;
(2) NEW_ENTRY_LEADER trend exit in 상승장 only (SPY/KOSPI 200DMA + 20-day slope; measured move rejected; 하락장 keeps current limits) — done (PR #41, prod checked 11-25 13:53 KST), `docs/maintenance/20261125_c1_step2_leader_uptrend_trend_exit.md`;
(3) C-1c: MTF 상승 과열 → 1/3 scout in 상승장 only, compare A current / B leader only / C exception only / D both; never relax
MTF 추세훼손. C-1c: user chose C (11-25) — 상승장 unheld EXCEPTION_ENTRY under MTF 정찰만 적합 stays a 1/3 scout (trend exit), shown as
"정찰 실행"; leader overheat not relaxed — done, `docs/maintenance/20261125_c1c_exception_mtf_overheat_scout.md`. C-1 group complete (PR #42, prod checked 11-25 14:41 KST). Kept as is: BREAKOUT_52W priority, LEADER_MA5 wait list (strategy cleanup candidate), normal pullback and
quality recovery R/R (pivot).

**C-3 leverage L3 policy (2026-11-25, user decision after the comparison):** D (both MA50) + recovery 4/6, L2 qualification
recorded per drawdown cycle (avg-cost −12/−25/−35% once), L3 = 1/3 of a pre-set leveraged DCA budget, max 3, capped by budget and
target shortfall minus this month's monthly plan; −50% panic latch released only by underlying 상승장 + both MA50 + 4/6 (never by
52-week-high roll-off). `stock_lab_core/leverage_l3_policy.py` + `app.build_leveraged_l3_read` (cycle rebuilt from 5y daily bars),
PR #46. Step 2 (user chose option A + approved Supabase): ≥ 20 completed trading days after the last *recorded* tranche; budget and
tranches stored in Supabase `leverage_dca_cycles` / `leverage_dca_tranches` (SQL: `db_schema.get_leverage_dca_create_sql()`;
tranches are insert-only audit rows, unique cycle_id + tranche_no). A tranche is consumed only by the user's "L3 n회차 실행 기록"
button in the precision panel, never by reruns or viewing. Executable needs budget, tranche left, cooldown, this month's monthly
plan (read from the monthly calculator's session value `_monthly_plan_alloc`; unknown → candidate) and amount ≤ shortfall − monthly.
Executable rows get `LEVERAGED_L3_RECOVERY_DCA` (buyish; gate reason "L3 회복 DCA n/3회차"); market defense, macro and data still
block at the gate. PR #47; Supabase tables created and prod checked 11-25 17:01 KST (SOXL panel: L3 대기, latch held, budget 미설정). Doc `docs/maintenance/20261125_c3_leverage_l3_policy.md`, replay `/mnt/project-files/reports/20261125_c3_l3_policy_replay.md`.

**C-3 closed (2026-11-25, user approved after the prod check):** 20-day spacing, manual tranche record, separate cycle/tranche
tables, 1/3 × max 3, budget/shortfall/monthly caps are the current policy. No extra condition for the early-bear latch release
(2000/2008/2022); managed by the caps and market defense, to be reviewed from real operating records.
**C-6/C-11 candidate (from C-3):** L3 executable currently needs `_monthly_plan_alloc`, which only exists after the monthly
calculator ran in this session this month. Keep that as a safety guard for now, but a screen visit should not be an investment
condition: in C-6/C-11 move the monthly allocation into a stored monthly snapshot (Supabase) or a shared calculation the
L3 read can call without the calculator screen.

**C-2 macro 2.5–4.5 comparison (2026-11-25, comparison only, no code change):** historical final_macro_risk rebuilt with the app
formula (Yahoo ^TNX/CL=F/USDKRW=X/^VIX/^MOVE + official FOMC/BLS/ECB/BOJ/KOSPI-expiry calendars), 144 tickers 2007–2026.
Current (A) = penalty-only (B): 0 gate differences; the separate <3.5/<4.0 conditions only rename 139 codes. The adj penalty
blocks 70/201 executable signals in the band; blocked ones were better in 상승장 but much worse in 하락장/risk episodes.
76% of band states come from calendar event points, not market stress. ≥4.5 guard: 0 executable in all variants.
Report `/mnt/project-files/reports/20261125_c2_macro_band_comparison.md`, scripts `reports/c2_study/`.
**C-2 closed (2026-11-25, user chose A = keep current):** follow-up split market vs event risk (D: market penalty + event
sizing; D': keep defence when market alone ≥2.5) with the real market guard, held add-on and KR previous-US-session macro.
D = D' everywhere; guard-applied band executables A 88 / C 131 / D 118, weighted R 0.12 / 0.14 / 0.09, 120-day bottom 10%
−16% / −22% / −18%; C/D move held codes and raise the core monthly multiplier ≈+0.6. Not adopted; B not applied either.
Macro score, penalty, separate conditions, event points and the ≥4.5 hard guard all stay. Report
`/mnt/project-files/reports/20261125_c2b_market_vs_event_risk.md`. Next: C-4/C-5 (chart pattern / tech-review layer),
comparison only, no decision/gate/sizing authority change.

**C-4/C-5 tech-review comparison (2026-11-25, comparison only, no code change):** point-in-time replay, 154 tickers
2007–2026 (282k states, pattern known_at check passed). Pattern: bullish "패턴유효: 정밀확인" adds 348 executables
(0.26R, mostly held add-on); bullish wait text blocks 340 (0.00R); bearish patterns block every stage incl. shape-only
(201, 0.25R). A 1,506/0.11R, B 1,498/0.05R, C 1,699/0.08R; A'' (bullish as now, bearish only in tech review) 1,707/0.13R,
best in every regime. Shadow: CAUTION does not separate outcomes (0.17R vs NEUTRAL 0.07R); BLOCK can never fire
(invalidated patterns are dropped before the shadow); liquidity "상단 매물 근접" is on ~90% because the first 'above' bin
straddles the close; a strict above-close read is the only element consistent in both halves. Recommended: C-4 A'',
C-5 authority A (display only), v2 display (dedupe clusters, strict liquidity, type-aware, L3 excluded). Waiting for
the user's choice. Report `/mnt/project-files/reports/20261125_c4_c5_tech_review_comparison.md`, scripts `reports/c45_study/`.

**C-4 implemented (2026-11-25, user decision A''+):** bullish pattern path unchanged; bearish patterns (shape,
close break, volume break) are tech-review context only; a close break with major structure damage (engine
structure_risk, or close < MA50 with bearish external structure) keeps the old 하락패턴 hold. Branch replay matches the
comparison: 1,686 stock executables, 0 gate mismatches. Core ETF holdings executable 278 → 1,008 (bearish shape/break
no longer blocks CORE_PULLBACK_DCA; monthly multiplier unchanged). Doc `docs/maintenance/20261125_c4_bearish_pattern_policy.md`.
Next: C-5 tech-review v2 display (no authority), then C-6/C-11.

**C-5 tech-review v2 (2026-11-25, user decision authority A):** display only, policy version `tech_review_v2_2026-11-25`
(`stock_lab_core/tech_review.py` build_tech_review_v2, `tech_review_view.py`). Deduped clusters, strict overhead supply (zones above
price only), formation period as reference, type-aware overheat (leader/exception scout: reference only), L3 tickers shown as
"레버리지 전용 정책 적용" with the C-3 rows. Never feeds codes, gates, sizing, monthly multipliers or sells; the record goes to the
review ZIP `signal_evidence.tech_review`. BLOCK stays practically unreachable by design (no condition added). Parity C-4 vs C-5:
41,391 rows × 40 columns identical. Doc `docs/maintenance/20261125_c5_tech_review_v2.md`. PR #54, prod checked 11-26 01:26–01:28 KST (GOOGL, TQQQ). C-4/C-5 closed. Next: C-6/C-11
(monthly DCA and cross-screen decision integration), wait for the user.

**C-6/C-11 comparison (2026-11-26, analysis and design only, no code change):** report
`/mnt/project-files/reports/20261126_c6_c11_monthly_dca_screen_integration.md`, scripts `reports/c611_study/`. Screens split into
engine-only (asset, monthly calculator, print, L3 monthly input) and post-processed+gate (Today, report, precision). Monthly plan reads
the raw engine code and never the gate: 30% (core ETF) to 63% (leverage) of planned states are 방어우선. Shared-structure B == A on
68,265 typed rows. Plan/executable split: with the full Today gate only 5.6% of core ETF plan is executable today and core
drawdown/crash DCA (150/200%) is 0% (all MTF trend damage); with timing reasons not blocking (C2) 62%. Implementation gaps: unscoped
`_ticker_signal_cache`, missing signal -> core 1.0 estimate, carryover/accum/done only in session, L3 needs `_monthly_plan_alloc`,
engine prefers global holdings over passed weights. Recommended L3 link: shared calc + confirmed monthly snapshot (C). Waiting for
the user's decisions; implement nothing before that.

**C-6/C-11 decisions + step 1 (2026-11-26):** user decided 09:14 KST (per-type monthly gate, core ETF MTF-damage exception D pending comparison, no missing-signal estimate, always-invest no override, DecisionRecord, Supabase confirmed plan, 5-stage order). Step 1 = `stock_lab_core/decision_record.py` + `compute_monthly_plan`; results unchanged (full suite failure set equal to main, 33). Doc `docs/maintenance/20261126_c6_step1_decision_record.md`. PR #57; prod rebooted 11:19 KST, asset/Today/monthly calculator/precision GOOGL checked 11:20–11:25 KST, no exceptions. Step 2 (account-scope stamp, explicit weights first, no missing-signal estimate, always-invest safety first): doc `docs/maintenance/20261126_c6_step2_monthly_safety.md`; replay differs only on MSFT/000660.KS (demo-table tickers). PR #59; prod rebooted 12:01 KST, calculator same allocation and scope-switch 미확인 checked 12:02–12:06 KST. Step 3 (four amounts, per-type monthly gate core ETF C2 / others C1, scout 1/3 cap, Supabase insert-only plan versions + execution log): doc `docs/maintenance/20261126_c6_step3_plan_execution_store.md`; PR #61; prod rebooted 12:17 KST, panel with table-missing warning checked 12:22–12:25 KST; tables need the SQL run once (user approval pending). D exception not active. Step 4 comparison (analysis only): doc `docs/maintenance/20261126_c6_step4_core_gate_compare.md`; base avg execution A 100% / B 18% / C 61% / D 98%; C blocks most DRAWDOWN/CRASH months, D opens them; D also opens CORE_STORM_DCA, so recommended scope excludes STORM/PANIC (C-8/C-9). User chose 12:59 KST: D for CORE_PULLBACK/NEUTRAL/OVERHEAT/DRAWDOWN/CRASH_DCA only (STORM/PANIC excluded, C-8/C-9). Final replay: base 98.0% (DRAWDOWN 97.8%, CRASH 92.2%), STORM unchanged, market defense 0 executed. D applied in `monthly_execution.core_dca_gate_without_mtf_damage` (gate recomputed without the damage label only; Today/precision gates unchanged). Step 5: L3 `current_month_monthly_plan_krw` reads confirmed plan − executed from Supabase (same account set, KST month); no confirmed plan → candidate. Doc `docs/maintenance/20261126_c6_step5_l3_confirmed_plan.md`. Full suite failure set equal to main (33). Supabase tables created 13:55 KST (RLS on, owner select/insert only); prod rebooted 13:56, checked 14:00–14:05 KST: storage read OK, core ETF rows with trend damage show the exception but stay blocked by market defense. Plan confirm / execution buttons not pressed (real records). Next: C-8/C-9 (STORM/PANIC), long-term stock execution-rate policy candidate.

**t_mult caution for C-6/C-11 (2026-11-25):** `scripts/policy_replay.py parity` writes a `t_mult` column computed from the
Today-chain decision (after the MTF guard and Today overlays). It is hypothetical. The app's monthly rebalance does not use
it: it reads the raw engine decision from `_ticker_signal_decision_cache` (calc_scores_and_decision, before the MTF guard).
C-1c changed `t_mult` on 177 parity rows (MTF_OVERHEAT core 0.25 → EXCEPTION 1.0) while the real rebalance multiplier did not
change. When C-6/C-11 link monthly DCA to the execution decision, do not read parity `t_mult` as the real multiplier;
recompute from the engine decision, or make an explicit, user-approved policy change first.

**Decision policy v1, after A/B (2026-11-24):** A-4 and A-5/A-6 done 11-25; next report to the user, then C (one item at a time). A-1/A-2 and B-1..B-7 are done with identical replay output
(`docs/maintenance/20261124_decision_ab_stage.md`). Next, one item at a time, each with a replay table (현행 / 대안 /
상승장 / 횡보장 / 하락장 / 실행가능 건수 / 차단·대기 감소량 / 평균 R / 손실 꼬리 / 골든·회귀 테스트) and the user's approval:
A-4 (PROFIT_TAKE_REVIEW buyish), A-5/A-6 (macro failure 1.5 assumption, missing macro = DATA_CHECK), then C-1/C-1b
(R/R by type: leader, 52w breakout, MA5/FVG exception, normal pullback, quality recovery; EXCEPTION_ENTRY 정찰, LEADER_MA5
wait list, BREAKOUT_52W shadowing together), C-3 (leverage L3 inside `leverage_stage.py`; severe market defense still
blocks leveraged crash DCA), C-2 (macro 2.5–4.5 only after rebuilding the historical macro series; keep the 4.5 guard).
Before C, reduce survivorship bias (point-in-time constituents or a wider sample). Parity check for any B-type change:
`scripts/policy_replay.py parity` on main and on the branch, all columns equal.

**Decision policy v1 (2026-11-24, superseded by the line above):** the user adopted the proposal direction (14 decisions, recorded in §1 of
`docs/maintenance/20261124_decision_policy_validation_plan.md`) and asked for staged work. Next: A-1/A-2 (display bugs),
then B-1..B-3 (behavior groups, frozen group table, code-based rebalance multiplier reproducing current values), each
with `scripts/policy_replay.py` output identical before/after. A-4..A-6 and every C item change results: show the replay
diff to the user and get approval one item at a time. Do not change R/R, macro, leverage, DCA or tech-review authority
before the C replay comparison. Cloud replay needs the Yahoo hosts allowed (added to the Default environment 11-24).

**Decision policy proposal (2026-11-24):** waiting for the user's review of
`docs/maintenance/20261124_decision_policy_proposal.md`. The user picks among its §10 decisions D1–D13 (R/R target
definition, macro responsibility split, missing-macro handling, single leverage stage table and crash-DCA vs defense
priority, asset/rebalance use of Today overlays, etc.); §12 lists implementation bugs that can be fixed without a policy
choice once the user approves. Do not change decision logic before that choice.

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
