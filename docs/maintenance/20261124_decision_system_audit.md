# 투자판정 체계 전수 조사 (2026-11-24)

요청: 판정 기준·임계값을 바꾸기 전에 현재 GitHub 코드의 투자판정 시스템을 정확히 파악한다.
기준 커밋 `3ec1608d` (main, PR #31 병합 직후). **이번 작업에서 판정 코드·점수·임계값·라벨·게이트·사이징·TTL은 한 줄도 바꾸지 않았다.**
추가된 파일은 이 문서와 재현 스크립트 `scripts/decision_audit_cases.py`(읽기 전용) 뿐이다.

설계 의도(사용자 설명, 2026-11-24): **후보 품질 = 안전관리자**, **최종 투자판정 = 현장소장**. 두 판정이 따로 있는 것은
의도된 구조이므로 이 문서는 둘을 합치자고 제안하지 않는다. 대신 이후 추가된 R/R·SMC·유동성·돈흐름·RS·매크로·계좌 비중·
레버리지 조건이 지금 어느 역할에 들어가 있는지, 같은 지표가 여러 단계에서 쓰일 때 그것이 확인 절차인지 중복 가중인지를 본다.

## 0. 결론 먼저

1. **엔진 본체는 이미 역할별로 나뉘어 있다.** `calc_scores_and_decision`은 입력 준비 → 점수·후보등급(안전관리자) → 신호 플래그 →
   구조손상 → 우선순위 판정(가드) → 후속 판정(보유/신규) → 안전 하향·보유 번역·비코어 패닉 차단·데이터 오류 → 사이징 힌트의
   고정 순서로 돌고, 각 단계는 `stock_lab_core/decision_*.py`의 순수 함수다. 이 순서는 골든 스냅숏과 패리티 테스트로 고정돼 있다.
2. **문제는 엔진 밖이다.** 엔진이 낸 `dec/decision_code` 위에 화면마다 다른 후처리가 붙는다.
   Today·정밀관측소는 상위시간대 가드 → 레버리지 재판정 → 라벨 재작성 → 실행 게이트를 거치지만,
   **자산현황(포트폴리오) 표와 그 표를 읽는 월 적립 리밸런싱 계산기는 엔진 원라벨을 그대로 쓰고, 배율을 라벨 글자에서 다시 계산한다.**
3. 그래서 같은 고정 입력에서 화면별 결론이 갈리는 경로가 실제로 재현된다(§8). 대표 사례:
   - 레버리지 ETF: 자산현황 `⚡레버리지 DCA 조건부`(월적립 배율 0.5) ↔ Today·정밀 `⚡레버리지 회복 전: DCA 보류`(게이트 방어우선).
   - 코어 ETF -50%: 엔진 적립률 200% ↔ Today 게이트 방어우선 ↔ 월적립 배율 **0.5** (라벨의 "-50%"를 "50%"로 읽음).
   - 미국 대표지수 코어 + 퍼펙트스톰: 엔진 "100% 거치 적립" ↔ Today 후보등급 칸 "시장방어(매수금지)"·게이트 대기 ↔ 최종 체크 매크로 "차단".
   - 같은 정밀관측소 화면에 **보유판단 패널이 2개**(독립 모듈 `hold_judgement` + app.py `render_hold_or_cut_panel`) 있고 점수·임계값이 달라 결론이 다르다.
4. 화면 간 차이 중 상당수는 **의도된 역할 차이**(시점 스냅숏, 수동 현재가, 자유입력 미보유 경로, 최종 체크가 더 엄격한 것)다. 오류로 분류하지 않았다.
5. 권장 방향: 엔진의 판정 순서·임계값은 유지하고, **"엔진 결과 1개 + 공용 후처리 1개"를 모든 화면이 같이 쓰게 하는 것**이 첫 리팩토링 후보다.
   라벨 글자 파싱(그룹·배율·게이트 정규식)을 코드 기반으로 바꾸는 것은 그 다음이다. 둘 다 동작을 바꾸므로 사용자 결정이 먼저 필요하다(§10).

## 1. 투자판정 전체 구조도

```
[입력]  가격 OHLCV(1y) · 실시간가(+수동가) · 재무점수(fin_score 0~4) · 보유/평단/현재·목표비중 · 매크로(final_macro_risk, macro_penalty)
          │  RS/RS기울기(벤치 대비 20일·8주) · 섹터 벤치 · 예수금/파킹자산
          ▼
┌───────────────────────── calc_scores_and_decision (app.py:16501) ─────────────────────────┐
│ ① 입력 준비   decision_inputs.prepare_decision_price_inputs / prepare_decision_technical_inputs │
│ ② 점수        tech_total(RS·MFI·추세·MACD·SQZ) → classify_candidate_grade = 후보등급 [안전관리자] │
│               main_score(추세·MACD·RSI·거래량) + RS + MFI + RS기울기 − 매크로패널티 = adj_tech_score │
│               classify_safety_state(RED/YELLOW/GREEN), classify_macro_state(STORM/CAUTION/NORMAL/UNKNOWN) │
│ ③ 구조·위치   ATR R/R(build_rr_context) · 52주 돌파 · SMC(decision_smc) · 섹터 머니플로우(표시용) │
│ ④ 계좌        build_position_management_context: 비중차·매수금액·코어 DCA 적립률·레버리지 DCA 플래그 │
│ ⑤ 진입 신호   decision_signals.build_entry_signal_context (모멘텀/MA5·FVG 눌림/우량주 회복/구조/ETF 적립) │
│ ⑥ 구조손상    decision_engine.build_structure_damage_context (신규·보유별 위험 라벨, 투매 판정)    │
│ ⑦ 판정 선택   is_free → decision_policies.select_free_mode_decision (단일 사다리)              │
│               계좌경로 → decision_priority (가드→레버리지/코어→회복/낙폭→구조/예외) 첫 일치    │
│                        → 없으면 decision_followup (코어/과열/돌파/ETF적립 → 수익보유/보유/신규) │
│ ⑧ 최종 보정   decision_finalization: 안전 RED 하향 → 보유 번역 → 비코어 패닉 차단 → 데이터오류 │
│ ⑨ 사이징      buy_amount(목표비중 부족분) · core_dca_amt · sizing_hint(1/3 정찰, 40% 추가)     │
└───────────────────────────────────────────────────────────────────────────────────────────┘
          │ 결과 dict c (dec, decision_code, decision_group, grade, t_score, … , sizing_hint)
          ▼
[화면별 후처리]  Today(오늘점검)            정밀관측소                 자산현황/월적립          전광판 스윙표
  상위시간대 가드              ●                          ●                           ✕                       ✕
  레버리지 대시보드 라벨변환   ●                          (표시 함수 안에서)          ✕                       ✕
  레버리지 정밀 재판정         ●                          ●                           ✕                       ✕
  비코어 패닉 표시가드         ✕(엔진에서 이미)           ●                           ✕                       ✕
  build_decision_workflow      ● 후보등급칸·최종읽기     ●                           ✕                       ✕
  시장 가드·돈흐름·애널        ● prepare_execution_context ●                         ✕                       ✕
  실행 게이트                  ● execution_gate          ●                           ✕                       ✕
  최종 체크(13항목)            ✕                          ● build_pre_buy_final_checks ✕                     ✕
  실행 준비도                  안내 문구만               ● build_execution_readiness  ✕                      ✕
  보유판단(별도 점수)          ✕                          ● 2개 패널                  ✕                       ✕
  라벨 글자 → 배율             ✕                          ✕                           ● _rebcalc_signal_multiplier ✕
```

## 2. 파일·함수별 역할표

### 2.1 요청한 5단계 기준

| 단계 | 결정되는 것 | 파일·함수 | 사용하는 입력 |
| --- | --- | --- | --- |
| 1. 기업·자산 품질 | 재무점수 1~4(ETF 0), 후보등급 S/A/B/C/F·ETF 우수/양호/보통/관망, 안전상태 | app.py `calc_weighted_fin_total`·`get_final_fin_score`, `financial_score.estimate_kr_fin_score_from_naver_snapshot`; `decision_engine.score_technical_components`, `classify_candidate_grade`, `classify_safety_state` | 재무 판정표(S×3·A×2·B×1, 위험 개수), RS 라벨, MFI, 추세, MACD, SQZ |
| 2. 기술 타점·시장 구조 | 추세·MACD·RSI/MFI/%B, main/adj 점수, R/R, 52주 돌파, SMC/FVG/PD Zone, 신호 플래그, 구조손상, 상위시간대 편향 | `ta_engine.get_trend/get_macd_state`, `decision_inputs.*`, `decision_engine.score_main_entry/build_rr_context/build_structure_damage_context`, `decision_smc`, `decision_signals.*`, app.py `get_precision_mtf_bias`, `decision_engine.build_sideways_quality_state` | OHLCV·지표, 52주 고점, 거래량비, RS/RS기울기 |
| 3. 투자판정 | 신규매수·추매·보유·비중축소·손절점검·코어 DCA·레버리지 DCA·데이터확인 등 107개 코드 | `decision_policies.select_free_mode_decision/select_portfolio_guard_decision/select_new_entry_decision/select_holding_decision/select_profitable_holding_decision`, `decision_priority.*`, `decision_followup.*`, `decision_finalization.finalize_decision_sizing`, app.py `apply_precision_mtf_decision_guard`, `apply_leveraged_precision_decision_override`, `today_queue.apply_leveraged_dca_dashboard_override` | 2단계 결과 + 재무점수 + 보유/평단 + 비중 + 매크로 + 상품 구분 |
| 3'. 보유판단(별도) | 장기보유·조건부보유·모니터링·비중축소·손절 검토 | `hold_judgement.build_hold_decision`(+`render_hold_decision_panel`), app.py `render_hold_or_cut_panel` | 재무점수, 추세, RS, 고점대비, 평단대비, (한쪽만) 매크로·구조위험·재무방향 |
| 4. 실행 게이트 | 실행가능 / 대기·관찰 / 방어우선 / 데이터확인 / 관망 → 최종 체크 → 실행 준비도 | `execution_gate.build_execution_gate/apply_execution_gate_columns`, `decision_workflow.build_decision_workflow/attach_market_execution_context/partition_today_queue`, app.py `build_today_market_guard`, `execution_context.prepare_execution_context`, app.py `build_pre_buy_final_checks` + `final_check_rows`, `decision_governance.independent_check_summary`, `execution_readiness.build_execution_readiness` | 판정코드·라벨 글자, R/R, 데이터상태, 상위시간대, 시장 가드, 돈흐름, 가격 신선도, 최종체크 13항목 |
| 5. 포지션 사이징 | 목표·현재비중, 비중차, 매수금액, 코어 DCA 금액, 1차 정찰 금액, 월적립 배율 | app.py `get_effective_weights/get_effective_buy_amount/build_core_dca_context`, `decision_engine.classify_core_etf_dca_rate/build_core_dca_context_values/compute_sizing_hint`, `today_queue.build_today_queue_execution_snapshot`, app.py `render_entry_execution_plan`, `_rebcalc_signal_multiplier` + `monthly_rebalance.build_base_allocations` | 보유표(현재·목표비중, bucket), 평가총액, 예수금·파킹자산, 판정코드/라벨 |

### 2.2 화면별 소비자

| 화면 | 호출 위치 | 판정 입력 차이 | 후처리 |
| --- | --- | --- | --- |
| 오늘점검(Today) | app.py:20950 `_calc_summary_item` | 매크로·평가액·현금을 **실행 시점 스냅숏**으로 고정, `is_free=False` | 상위시간대(주/월만) → 레버리지 2단 → workflow → 시장가드·돈흐름 → 게이트 → `prepare_today_queue_display` 라벨 재작성 |
| 정밀관측소 | app.py:34643 | 매크로는 현재 전역값, **수동 현재가 허용**, 미보유 자유입력만 `is_free=True` | 상위시간대(일/주/월) → 레버리지 재판정 → 비코어 패닉 표시가드 → workflow·게이트 → 최종 체크 → 준비도 → 보유판단 2패널 |
| 공개 데모 정밀 | app.py:33251 | 위치 인자 호출, 매크로 전역 | 상위시간대 → 레버리지 재판정 → workflow |
| 자산현황(포트폴리오) | app.py:35497 | 매크로 전역, `_live_indicator_context` 없이 내부 계산 | **후처리 없음.** `기술적타점`=엔진 `dec` → `_ticker_signal_cache` → 월적립 계산기·인쇄 리포트 |
| 전광판 스윙 시스템표 | app.py:21331 `build_swing_system_df` | 위와 같음 | **후처리 없음** |
| 시황 | (판정 엔진 호출 없음) | — | 보유 영향 설명은 기존 결과를 읽기만 한다 (요청대로 별도 엔진 없음) |

## 3. 판정 우선순위 지도 (실제 실행 순서)

`calc_scores_and_decision`(app.py:16501)의 실제 순서. "→첫 일치"는 위에서부터 처음 맞는 규칙 하나만 쓴다는 뜻이다.

```
0  티커 정규화, 알려진 개별주면 is_etf=False 강제
1  가격 입력: 실시간가를 일봉에 붙여 지표 재계산(실패 시 indicator_data_issue 기록, 직전 이력으로 복원)
   cur_p = 실시간가(괴리 50% 미만일 때) 또는 마지막 종가; day_ret/live_gap_move/ret_1m·3m·6m
2  기술 입력: trend, MACD 상태, RSI/MFI/%B, RS 라벨(20일 ±3%), RS 기울기(8주·4주 동방향 ±3%), SQZ
3  점수: tech_total → 후보등급·safety_state / main_score → adj_tech_score(−macro_penalty) / macro_state
4  R/R(ATR14×2 손절, 내부→외부 고점, 없으면 +4ATR 투영), 52주 돌파, 섹터 머니플로우(표시), SMC
5  계좌: 비중·매수금액·코어 DCA 적립률·레버리지 DCA 대기/조건부·집중 ETF 상단·보유주 단기하락 대기
6  신호 플래그 → 구조손상 라벨(신규용/보유용) → 투매(capitulation) 판정
7  판정 선택
   7a is_free=True  → select_free_mode_decision (아래 F 사다리, 첫 일치)
   7b is_free=False → select_portfolio_priority_decision
        P1 가드      재무F(개별주 fin≤1) > 목표0%보유 > 비중초과 > 비중충족 > 코어+퍼펙트스톰 적립 > 퍼펙트스톰(≥4.5)
        P2 레버리지·코어  레버리지 일급락(≤-8%) > 레버리지 DCA 과열패스 > 레버리지 DCA 조건부
                     > 코어 -50% 최종투입 > 코어 -40% 현금투입 > 코어 -30% 폭락 적립 > 레버리지 -50% > 레버리지 -30%
        P3 회복·낙폭  우량주 회복후보 > 회복초입 > 회복관찰 > 비코어 -50%/-40%/-30% 원인점검 > 코어 -20% 하락 적립
        P4 구조·예외  (미보유)실시간급락 > (미보유)구조손상 > (보유)-20%+구조 > (보유)-20% > (미보유)-20%
                     > (보유)실시간급락 > (보유)구조손상 > 실시간가 예외반등 대기 > 예외승인 추매/진입
        → 모두 불일치면 select_portfolio_followup_decision
        Q1 코어 DCA 적립 > 신규ETF(이력 부족) > MFI≥85 하드차단 > 과열확장 > 대장주 MA5 > (개별주)%B≥0.95
           > ETF 큰 미달 적립 > ETF 적립 > 개별주 상승확인 2차 추매
        Q2 보유+평단 +2% 초과 → select_profitable_holding_decision (비중충족 > 과열 > 추가가능 > 보유유지)
        Q3 보유 → select_holding_decision (익절검토 > S급 눌림 추매 > 단기과열 > 낙폭과대 > S급 과매도
           > 보유주 단기하락 대기 > 집중ETF 상단 > A급 반등 > 정배열 눌림 > 평단이상 대기 > 평단이하 단계)
        Q4 미보유 → select_new_entry_decision (집중ETF 상단 > %B 0.85~0.95 > 52주 돌파 > S급 눌림 > 단기과열
           > 회복 3단계 > 낙폭과대 > 반전초입 > 대장주 > 역배열 낙폭 > 하락추세 > 역배열 > 중립 세부)
8  finalize_decision_sizing (항상 이 순서로 덮어씀)
   8a 안전관리자 RED + 미보유 + 공격적 신규코드 13개 → SAFETY_RED_NO_NEW_ENTRY
   8b 보유 중인데 신규진입 코드 11개 → HOLDING_* 번역 (예: NEW_ENTRY_LEADER → HOLDING_LEADER_ADD_REVIEW)
   8c 코어 DCA 비허용 대상의 패닉 투입 라벨 → 원인점검 라벨
   8d 지표 재계산 실패 → DATA_ERROR, 매수금액 0  (가장 마지막, 모든 것을 덮음)
   8e sizing_hint: 신규진입 코드면 목표비중 1/3, MA5 대기 4개 코드면 부족분 40%
9  build_decision_result: safety_state는 데이터 코드면 "DATA"로 표시
───────────── 엔진 밖 (화면별) ─────────────
10 apply_precision_mtf_decision_guard: 미보유 진입형 → 주/월봉 추세훼손이면 MTF_DAMAGE_NO_ADD, 과열이면 MTF_OVERHEAT_SCOUT_ONLY.
   보유 중이면 라벨 유지, sizing_hint에만 주의 문구
11 apply_leveraged_dca_dashboard_override(Today) / apply_leveraged_precision_decision_override(Today·정밀):
   레버리지 프로필 종목은 비중 코드(목표0·초과·충족)를 제외한 모든 판정을 레버리지 단계표로 다시 씀
12 enforce_non_core_panic_scope_on_result(정밀만): 캐시된 옛 패닉 라벨 정리
13 build_decision_workflow: 후보등급 칸(📌후보등급)·최종읽기·판정분류 재작성 (라벨 글자 기반)
14 attach_market_execution_context: 시장 가드 모드 → "시장방어: 신규매수 중단" 등
15 build_execution_gate (첫 일치):
   데이터/신규ETF 이력 > 상위시간대 자료부족 > 비중 문구 > 시장방어 > 상위시간대 경고 > 방어 정규식 > 하드차단
   > 시장정보 미확인 > 지표 결측 > 가격 신선도 > [대기 사유 누적: R/R<1, 투영목표, 하락패턴, 과열, 대기코드·문구, 돈흐름, 레버리지 조건부]
   > caution 그룹 → 대기 > buyish(또는 정밀확인) → R/R 없으면 데이터확인, 있으면 실행가능 > 그 외 관망
16 (정밀) build_pre_buy_final_checks: 13개 점검행, 차단 2개↑ 매수 금지 / 1개 대기, 게이트≠실행가능이면 실행 라벨 강등
17 (정밀) build_execution_readiness: 게이트 실행가능 AND 최종체크 execution_allowed AND 차단0 AND 핵심결측 없음일 때만 "정밀확인"
```

**덮어쓰기 우선순위 요약 (강한 것부터):** 데이터 오류(8d) > 비코어 패닉 차단(8c) > 보유 번역(8b) > 안전 RED(8a) > 우선순위 가드(P1~P4) > 후속 판정(Q1~Q4).
엔진 밖에서는 레버리지 재판정(11) > 상위시간대 가드(10) > 엔진 결과이며, 실행 단계에서는 최종 체크(16) > 게이트(15) > 시장 가드(14)
순으로 **더 엄격한 쪽이 이긴다**(`execution_readiness`가 "최종 거부가 표시에서 이긴다"를 보장). 게이트·최종체크는 판정 라벨을 바꾸지 않고
실행 가능 여부만 제한한다. 예외: Today 표의 `최종읽기` 칸은 게이트 결과 문구로 대체된다.

## 4. 판정코드·라벨·임계값

### 4.1 점수·등급 (실제 코드 값)

| 항목 | 규칙 | 위치 |
| --- | --- | --- |
| 재무점수(개별주) | 가중합 = S항목×3 + A×2 + B×1. 위험(🚨) 개수 ≥ 한도면 1점, 아니면 ≥45→4, ≥25→3, ≥5→2, 그 외 1. 범용 한도1·수주 한도2, 중간형 = 둘 평균 반올림(둘 다 1이면 1). 조회 실패 시 3점(`AUTO_FIN_FAIL_SCORE`), Naver 요약 대체는 1~3점 상한. ETF/ETN 0점 | app.py:5239, 3758; financial_score.py |
| RS 라벨 | 벤치 대비 20거래일 상대수익 >+3% 🚀강함(2점), <-3% 🐢약함(0), 그 외 ➖보통(1). 공통거래일·기준일 7일 차이·이력부족은 별도 라벨 | relative_strength.py:59, app.py:3766 |
| RS 기울기 | 8주(41행) 변화 >+3% 그리고 4주와 같은 방향 → +1 📈, < -3% → -1 📉, 그 외 0. 42행 미만 기울기부족 | app.py:15692 |
| tech_total | RS(2/1/0) + MFI(<30 +2, >80 -1) + 정배열 2 + MACD(골든 2, 상승중 1, 데드 -2) + SQZ 해제직후·MACD상승계 1 | decision_engine.py:745 |
| main_score | 추세(정배열 2, 혼조 1) + 골든크로스 2 + RSI(<35 2, <45 1) + 거래량(양봉·1.2배 +1 / -2%↓·1.5배 -1) | decision_engine.py:775 |
| adj_tech_score | main_score + RS점수 + MFI점수 + RS기울기(±1) − macro_penalty | app.py:16595 |
| macro_penalty | final_macro_risk ≥4 → 2, ≥2.5 → 1.5, ≥1.5 → 0.5, 그 외 0. Yahoo 일괄조회가 비면 final_macro_risk = max(1.5, 이벤트위험), penalty 0.5 | app.py:15581, 15536 |
| final_macro_risk | VIX>30·USDKRW>1400·10Y>4.7 각 +1, 10Y·유가·환율 1개월 ±0.5%↑/↓ 각 ±0.5, MOVE ≥120 +1.5 / ≥100 또는 결측 +0.5, + 이벤트 위험 | app.py:15515 |
| 후보등급(ETF) | tech_total <1 관망, <3 보통, <5 양호, 그 외 우수 | decision_engine.py:790 |
| 후보등급(개별주) | t_score = tech_total + fin_score. fin=1 → F(재무위험/처분). t<3 → fin≥3이면 C(기술부진 관망) 아니면 F(기술/재무 부진). <5 C, <7 B, <9 A, 그 외 S | 同 |
| 안전상태 | tech_total 결측·<1 RED, <3 YELLOW, 그 외 GREEN | decision_engine.py:823 |
| 매크로상태 | final_macro_risk 결측 UNKNOWN, ≥4.5 STORM, ≥1.5 CAUTION, 그 외 NORMAL | decision_engine.py:848 |

### 4.2 신호 플래그 (decision_signals.py, position context)

| 플래그 | 조건 (모두 AND) | 판정에 쓰이는 곳 |
| --- | --- | --- |
| 개별주 상승확인 추매 | 개별주·보유·목표>0·비중차≥2·평단대비 0~+5%·정배열/혼조·RS강함·MACD 상승·MFI<80·RSI<70·%B<1.0·거래량비<2.5·매크로<4.5 | STRENGTH_ADD_ON_OK |
| 선진입 | 정배열·RS강함·MACD 상승·MACD 상태 데드/관망·MFI<80·%B<0.85·RSI 50~65·adj≥4 | EARLY_ENTRY / EARLY_REVERSAL_ENTRY |
| 과열확장 / 대장주 정상돌파 | 개별주·fin=4·adj≥4·RS강함 + %B>1.02 / 0.95≤%B≤1.02 | OVERHEAT_EXTENSION_WAIT_MA5 / LEADER_MA5_* |
| 예외 진입 | 개별주·fin=4·정배열·RS강함·MACD 골든/상승중·adj≥4 + RS기울기 하락 아님 + (MA5 눌림: 저가≤MA5×1.01·현재가≤MA5×1.025·이격≥-2% 또는 강세 FVG 하단×0.995~상단×1.01) + MFI<82·%B<1.0·RSI<70·거래량비<2.5 | EXCEPTION_* / PREMARKET_REBOUND_* |
| 우량주 회복 기반 | 개별주·이력 충분·fin≥3·(고점대비≤-12% 또는 3M/6M≤0·결측 또는 정배열 아님)·MFI<82·RSI<72·%B<0.98·단일봉 급락 아님·매크로<4.5 | 아래 3단계 |
| 회복관찰 / 초입 / 후보 | 관찰: MA20×0.97 이상·MACD 회복·RS 약함 아님. 초입: MA20×0.99·MA50×0.98 이상·RS 회복·1M>-8%·당일>-4%. 후보: 초입 + RS강함·MA20·MA50 위·MA120×0.95 이상·1M≥-3% | QUALITY_RECOVERY_* |
| 구조손상(진입 위험) | 개별주·이력 충분 + (고점대비 ≤ 임계[극단모멘텀 -35%, 대장주 -20%, 그 외 -15%] 또는 MA50 하회(대장주 RS강함 예외) 또는 MA20×0.98 하회·RS강함 아님·반등중 아님 또는 단일봉 급락) | STRUCTURE/PRICE_DRAWDOWN/SINGLE_DAY_* |
| 단일봉 급락 / 실시간 급락 | 개별주·실시간 아님·당일≤-6%·거래량비≥1.2 / 개별주·실시간·갭≤-6% | 同, LIVE_GAP_SHOCK_* |
| 투매(자유입력만) | 고점대비≤-20%·극단모멘텀 아님·회복구간 아님 + (≤-30%, 정배열 아님, MA20×0.98·MA50×0.95 하회, 1M≤-8%, 당일≤-4%, %B≤0.35, RSI≤35, MFI≤25 중 하나) | CRISIS_PANIC_SELL_OFF |
| 깨끗한 대장주 | 개별주·adj≥4.5·RS강함·정배열·당일>-4%·고점대비>-15%·MA20×0.98 이상·구조손상 아님 | NEW_ENTRY_LEADER |
| ETF 적립 허용 | ETF·레버리지 아님·보유·목표>0·비중차≥3·(역배열이면 비중차≥10)·MFI<85·RSI<75·%B<1.03·매크로<4.5 | ETF_DCA_OK / ETF_LARGE_GAP_DCA_OK(≥10) |
| 집중 ETF 상단 | 비코어 집중 ETF + (고점대비>-3% 또는 %B≥0.95 또는 RSI≥68 또는 MA20 대비 +4%↑) | CONCENTRATED_ETF_UPPER_WAIT |
| 레버리지 DCA | 후보: ETF·레버리지·보유·목표>0·비중차>0. 과열대기: 고점대비>-10% 또는 %B≥0.85 또는 평단대비>-3% 또는 당일≥+8%. 조건부: 과열대기 아님·매크로<4.5·역배열 아님·(고점대비≤-10% 또는 평단대비≤-3% 또는 %B<0.75). 일급락: min(당일, 실시간갭)≤-8% | LEVERAGED_* |
| 보유주 단기하락 대기 | 보유·개별주·adj≥4·현재가≤평단·현재<목표비중·당일/실시간 ≤-2%·MA5 하회·고점대비>-10%·%B≥0.60 | HOLDING_PULLBACK_WAIT_CLOSE |
| 코어 DCA 적립률 | 코어 ETF·비중차>0·레버리지 아님. 매크로≥4.5: 미국 대표지수 100%, 극단과열 0%, 국내 코어 -20%·비과열 50% 아니면 25%, 기타 50%/25%. 평시: ≤-30% 200%, ≤-20% 150%, ≤-10% 또는 (RSI≤55·MFI<70·%B≤0.70) 100%, 극단과열(MFI≥85/RSI≥80/%B≥1.0) 25%, 상단과열(80/75/0.90) 25%, 역배열 25%, 그 외 50% | decision_engine.py:1550 |

### 4.3 판정코드 선택 표 (우선순위 순, 계좌경로)

| 단계 | 코드 (라벨) | 발동 조건 | 신규/보유 | ETF/개별주·코어·레버리지 | 매크로 | 재무 | 기술 | 비중 | 게이트(중립조건) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | HARD_BLOCK_FINANCIAL_F 🚨하드차단: 재무F급(처분) | 개별주 fin≤1 | 둘 다 | 개별주만 | — | ≤1 | — | — | 방어우선 |
| P1 | TARGET_ZERO_NO_ADD 🛑목표비중 0% | 보유·현재>0·목표≤0 | 보유 | 전체 | — | — | — | 목표0 | 방어우선 |
| P1 | HARD_BLOCK_OVERWEIGHT / HARD_BLOCK_TARGET_FILLED | 현재>목표 / 현재≥목표 (목표>0) | 둘 다 | 전체 | — | — | — | 초과/충족 | 방어우선 |
| P1 | CORE_STORM_DCA 🧱코어 방어: … | 코어 DCA 허용·매크로≥4.5 | 둘 다 | 코어 ETF | ≥4.5 | — | 과열은 적립률에 | 부족 | **Today에서 실행가능 불가** (§6.2) |
| P1 | MACRO_STORM_HOLDING_CAUTION 🛡️시장위험: 추매중단/보유점검 | 매크로≥4.5 (보유 여부 무관) | 둘 다 | 코어 DCA 제외 전체 | ≥4.5 | — | — | — | 방어우선 |
| P2 | LEVERAGED_DAILY_DROP_NO_ADD | 레버리지 일급락 ≤-8% | 둘 다 | 레버리지 | — | — | 당일 | — | 방어우선 |
| P2 | LEVERAGED_DCA_OVERHEAT_PASS / LEVERAGED_DCA_CONDITIONAL | 4.2 레버리지 DCA | 보유 | 레버리지 | <4.5(조건부) | — | 고점·%B·당일 | 부족 | 대기 / 대기 |
| P2 | PANIC_FINAL_DEPLOY / PANIC_CASH_DEPLOY / CORE_CRASH_DCA | 코어 DCA 허용 + 고점대비 ≤-50% / ≤-40% / ≤-30% | 둘 다 | 코어 ETF | — | — | 고점대비 | 부족 | 방어우선 / 방어우선 / 실행가능 |
| P2 | LEVERAGED_RECOVERY_DCA_BLOCK | 레버리지 고점대비 ≤-50% / ≤-30% | 둘 다 | 레버리지 | — | — | 고점대비 | — | 방어우선(-50%) / 관망(-30%, 그룹 neutral) |
| P3 | QUALITY_RECOVERY_CANDIDATE/SCOUT/WATCH | 4.2 회복 3단계 | 둘 다 | 개별주 | <4.5 | ≥3 | MA·RS·MACD | — | 실행가능/실행가능/대기 |
| P3 | STOCK_/NON_CORE_ETF_ PANIC/DRAWDOWN/CRISIS_CAUSE_CHECK | 고점대비 ≤-50/-40/-30% (코어 DCA 아님) | 둘 다 | 비코어 | — | — | 고점대비 | — | 방어우선 |
| P3 | CORE_DRAWDOWN_DCA | 코어 DCA·≤-20% | 둘 다 | 코어 | — | — | — | 부족 | 실행가능 |
| P4 | LIVE_GAP_SHOCK_WAIT / _HOLDING_CHECK | 실시간 급락 | 미보유/보유 | 개별주 | — | — | 갭≤-6% | — | 대기 / 방어우선 |
| P4 | STRUCTURE_DAMAGE·PRICE_DRAWDOWN·SINGLE_DAY_BREAKDOWN _NO_ENTRY / _HOLDING_CHECK | 구조손상 (사유별 라벨) | 미보유/보유 | 개별주 | — | — | 4.2 | — | 방어우선 |
| P4 | DRAWDOWN_20_HOLDING_STOP_CHECK / _CAUSE_CHECK / _NO_ENTRY | 고점대비 ≤-20% | 보유(+구조)/보유/미보유 | 전체 | — | — | — | — | 방어우선 |
| P4 | PREMARKET_REBOUND_(HOLDING_)WAIT, EXCEPTION_ADD_ON / EXCEPTION_ENTRY | 예외 진입 + 실시간가 사용 / 보유·평단×1.02 이하·비중 부족 / 미보유 | 각각 | 개별주 | — | =4 | 4.2 | 부족(추매) | 대기 / 실행가능 |
| Q1 | CORE_*_DCA (적립률 라벨) | 코어 DCA 허용 | 둘 다 | 코어 | 적립률 | — | 과열·고점 | 부족 | §6.2 |
| Q1 | NEW_ETF_* | ETF·이력<60 또는 MA50/120 없음 | 둘 다 | ETF | — | — | 85/80/1.00, 80/75/0.95, 눌림 | 부족/충족 | 대부분 대기 |
| Q1 | HARD_BLOCK_MFI_OVERHEAT | MFI≥85 | 둘 다 | 전체 | — | — | MFI | — | 대기(과열) |
| Q1 | OVERHEAT_EXTENSION_WAIT_MA5 / LEADER_MA5_PULLBACK_ENTRY | 4.2 돌파 | 둘 다 | 개별주 | — | =4 | %B | — | 대기 / 대기 |
| Q1 | HARD_BLOCK_BOLLINGER_UPPER ⏳볼린저 상단권 | 개별주 %B≥0.95 | 둘 다 | 개별주 | — | — | %B | — | 대기(과열) |
| Q1 | ETF_LARGE_GAP_DCA_OK / ETF_DCA_OK | 4.2 ETF 적립 | 보유 | 비레버리지 ETF | <4.5 | — | 과열 상한 | ≥10 / ≥3 | 실행가능 |
| Q1 | STRENGTH_ADD_ON_OK | 4.2 | 보유 | 개별주 | <4.5 | — | 4.2 | ≥2 | 실행가능 |
| Q2 | TARGET_FILLED_S_GRADE_WAIT / TARGET_FILLED_HOLD | 평단+2% 초과 보유·현재≥목표×0.97 (S/A급이면 앞쪽) | 보유 | 전체 | — | 등급 | — | 97% 충족 | 방어우선 |
| Q2 | S_GRADE_OVERHEAT_WAIT / OVERHEAT_WAIT | 비중차≥3·(MFI≥80 또는 RSI≥72 또는 %B≥0.90) | 보유 | 전체 | — | 등급 | 과열 | ≥3 | 대기 |
| Q2 | S_GRADE_ADD_ON_OK / A_GRADE_ADD_ON_REVIEW / ABOVE_COST_WAIT_PULLBACK | 비중차≥3·MFI<75·RSI<68·%B<0.88 + S급·RS강함·정배열·fin≥4·매크로<4.0(RS상승중)/<3.5 / A급·정배열 / 그 외 | 보유 | 전체 | <4.0·<3.5 | ≥4 | 과열·추세 | ≥3 | 실행가능 / 관망 / 대기 |
| Q2 | ABOVE_COST_HOLD | 그 외 | 보유 | 전체 | — | — | — | — | 대기 |
| Q3 | PROFIT_TAKE_REVIEW 🔔익절 타이밍 | 코어 ETF 아님·MFI≥80·%B>0.9·평단대비>+20% (실제로는 Q2가 먼저 잡아 도달 불가, §7 #9) | 보유 | 비코어 | — | — | 과열 | — | 대기 |
| Q3 | S_PULLBACK_ADD_ON | 정배열·RS강함·45<RSI≤58·0.45<%B<0.8 | 보유 | 전체 | — | — | 4개 | — | 실행가능 |
| Q3 | SHORT_OVERHEAT_NO_ADD | MFI≥80 | 보유 | 전체 | — | — | MFI | — | 대기 |
| Q3 | OVERSOLD_ADD_ON / FUND_OVERSOLD_REBALANCE_REVIEW | RSI≤30 (TDF·펀드는 리밸런싱 검토) | 보유 | 전체 | — | — | RSI | — | 실행가능 / 대기 |
| Q3 | S_GRADE_OVERSOLD_BUY | RS강함·MFI<35 | 보유 | 전체 | — | — | — | — | 실행가능 |
| Q3 | HOLDING_PULLBACK_WAIT_CLOSE / CONCENTRATED_ETF_UPPER_WAIT | 4.2 / 집중ETF 상단·adj≥4·평단 이하 | 보유 | 개별주 / 집중 ETF | — | — | 4.2 | — | 대기 |
| Q3 | A_GRADE_TECH_REBOUND 🎯A급: 기술적 반등 | adj≥4·평단 이하 | 보유 | 전체 | penalty | — | adj | — | 대기 (그룹 neutral) |
| Q3 | UPTREND_PULLBACK_DCA | 정배열·%B<0.8·RSI<60·평단 -3%~-15%·현재<목표 | 보유 | 전체 | — | — | 3개 | 부족 | 실행가능 |
| Q3 | ABOVE_COST_WAIT | 현재가>평단 | 보유 | 전체 | — | — | — | — | 대기 |
| Q3 | BELOW_COST_TARGET_FILLED / NEAR_COST_WAIT / COST_MINUS_3_7_DCA / COST_MINUS_7_15_CONDITIONAL_DCA | 평단 이하: 비중충족 / >-3% / -3~-7%·역배열 아님·MFI<80 / -7~-15%·fin≥3·매크로<4.5 | 보유 | 전체 | <4.5(-7~-15) | ≥3 | 추세·MFI | 충족/부족 | 방어우선 / 대기 / 실행가능 / 실행가능 |
| Q3 | COST_MINUS_15_TREND_RISK / COST_MINUS_15_CAUSE_CHECK / TREND_RISK_CAUSE_CHECK / HOLDING_DCA_CONDITION_MISS | 위 단계 미충족: -15%↓+역배열 / -15%↓ / 역배열 / 그 외 | 보유 | 전체 | — | — | — | — | 방어우선 ×3 / 대기 |
| Q4 | CONCENTRATED_ETF_UPPER_WAIT, NEAR_UPPER_WAIT(0.85≤%B<0.95), BREAKOUT_52W_ENTRY(돌파·RS강함·당일>0·MFI<80·%B<0.95), S_PULLBACK_ENTRY, SHORT_OVERHEAT_NO_ENTRY(MFI≥80), QUALITY_RECOVERY_*, OVERSOLD_NEW_ENTRY(RSI≤30), EARLY_REVERSAL_ENTRY, NEW_ENTRY_LEADER, OVERSOLD_DCA(역배열·adj≥5), DOWNTREND_NO_ENTRY(3M<0·역배열/혼조), REVERSE_TREND_NO_ENTRY | 기재 조건 | 미보유 | 전체 (돌파·대장주는 개별주) | 4.2 | 4.2 | 4.2 | — | 대기/실행가능/방어우선 (부록) |
| Q4 | QUALITY_PULLBACK_ENTRY / TREND_PULLBACK_EXPLORE | 정배열·RS강함·RSI 45~65·%B 0.35~0.75·MFI<75·매크로<3.5 + fin≥4 / 그 외 | 미보유 | 전체 | <3.5 | ≥4 | 5개 | — | 실행가능 |
| Q4 | UPTREND_PULLBACK_CONFIRM / S_UPTREND_WAIT_PULLBACK / A_UPTREND_SEARCH_ENTRY / SEARCH_NEW_ENTRY | 정배열·RS보통·RSI<55·%B<0.65 / S급·정배열 / A급·정배열 / 그 외 | 미보유 | 전체 | — | 등급 | — | — | 대기 |
| 8a | SAFETY_RED_NO_NEW_ENTRY 🧯안전관리자 RED | tech_total<1·미보유·공격적 신규코드 13개 | 미보유 | 전체 | — | — | tech_total | — | 방어우선 |
| 8b | HOLDING_* (11개) | 보유인데 신규진입 코드 | 보유 | 전체 | — | — | — | 잔여비중 문구 | 코드별 |
| 8d | DATA_ERROR ⚪데이터확인 | 실시간 지표 재계산 실패 | 둘 다 | 전체 | — | — | — | 매수금액 0 | 데이터확인 |
| 10 | MTF_DAMAGE_NO_ADD / MTF_OVERHEAT_SCOUT_ONLY | 미보유 진입형 + 주/월봉 추세훼손 / 상승 과열권 | 미보유 | 전체 | — | — | 주·월봉 | 30% 이하 정찰 | 방어우선 / 대기 |
| 11 | LEVERAGED_WATCH_NO_POSITION / TARGET_ZERO_ / TARGET_FILLED_DCA_EXCLUDED / DCA_OVERHEAT_PASS / RECOVERY_DCA_BLOCK / RECOVERY_DCA_CONDITIONAL | 레버리지 단계표: 미보유 / 목표0 / 충족 / 과열(RSI≥70·MFI≥80·%B≥0.92) / ×0·회복<3/6 / 후보·정찰 | 각각 | 레버리지 프로필 | — | — | 회복체크 6개 | 목표 | 대기·방어 |

자유입력(미보유) 사다리 F: 코어 DCA > 신규ETF > MFI≥85 > 과열확장 > 대장주 MA5 > %B≥0.95 > 회복 3단계 > 투매 > 실시간 급락 > 구조손상 >
레버리지 일급락 > 레버리지 DCA > 52주 돌파 > S급 눌림 > RSI≤30 > 선진입 > 대장주 > 역배열 낙폭 > 하락추세 > 역배열 > 관망.
**P1 가드(재무F·비중·퍼펙트스톰)가 없다.** 2026-11-24 사용자 결정으로 자유입력 경로는 미보유 종목에만 쓰인다.

> 정정(2026-11-24, [정책안](20261124_decision_policy_proposal.md)): 107개는 리터럴로 적힌 코드 수다. 변수로 만들어지는 코드 20개(신규 ETF 9, 비코어 패닉·급락·위기 원인점검 6, 평단 -15% 원인점검 등)를 더하면 실제 생성 코드는 127개다. 아래 '사전에만 있는 코드'에 이 20개를 넣었던 것은 오류이고, 사전 전용은 `HARD_BLOCK_MACRO_STORM`·`CRISIS_CORE_FOCUS` 둘이다.

107개 코드 전체의 기계적 속성(그룹 출처, 신규진입 사이징 대상, RED 하향 대상, 보유 번역, Today 차단/대기 집합, 중립 조건 게이트,
월적립 배율)은 **부록 A**에 있다. 사전에만 있고 현재 어떤 경로도 만들지 않는 코드: `HARD_BLOCK_MACRO_STORM`(🛑하드차단: 퍼펙트스톰(대피)),
`CRISIS_CORE_FOCUS`(🚨위기(-30%↓): 코어 집중). 판정 매뉴얼 탭(app.py:21858)은 미보유 종목에 "하드차단: 퍼펙트스톰"이 뜬다고 설명하지만
실제로는 보유 여부와 관계없이 `MACRO_STORM_HOLDING_CAUTION`이 나온다(사례 A2). 차단 효과는 같고 라벨만 다르다.

### 4.4 같은 개념의 기준이 여러 곳에 있는 경우 (과열 기준 예)

| 위치 | 과열로 보는 기준 | 결과 |
| --- | --- | --- |
| 엔진 공통 하드차단 | MFI ≥85 | HARD_BLOCK_MFI_OVERHEAT / EXTREME_OVERHEAT_NO_CHASE |
| 신규진입·보유 | MFI ≥80 | SHORT_OVERHEAT_* |
| 수익 보유 | MFI≥80 또는 RSI≥72 또는 %B≥0.90 (추가 허용은 <75/<68/<0.88) | S_GRADE_OVERHEAT_WAIT 등 |
| 코어 DCA 적립률 | 극단 85/80/1.00, 상단 80/75/0.90 | 적립률 25%/0% |
| 신규 ETF | 극단 85/80/1.00, 상단 80/75/0.95 | NEW_ETF_* |
| 집중 ETF | RSI≥68 또는 %B≥0.95 | 상단권 대기 |
| 최종 체크(정밀) | 차단 MFI≥85·RSI≥75·%B≥1.02, 주의 80/70/0.95 | 과열 행 |
| 횡보 품질 | 관찰 RSI70·MFI75·%B0.82, 강함 75/82/0.95 | 횡보/눌림 품질 행 |
| 레버리지 단계표 | RSI≥70·MFI≥80·%B≥0.92 | 과열패스 |
| 엔진 레버리지 DCA | %B≥0.85 (또는 고점대비>-10% 등) | 과열대기 |
| Today 대시보드 레버리지 변환 | %B≥0.95·당일≥12% | 과열패스 |

각 기준은 상품·목적별로 의도적으로 다를 수 있다. 다만 같은 상품에서 엔진·Today 변환·레버리지 단계표가 서로 다른 과열선을 쓰는 레버리지
경우는 화면 불일치의 직접 원인이 된다(§8 F2).

## 5. 신규진입 / 보유 / ETF / 개별주 / 코어 / 레버리지별 흐름

| 경로 | 엔진에서 실제로 지나는 단계 | 엔진 밖 | 사이징 |
| --- | --- | --- | --- |
| 개별주 미보유(계좌) | P1 재무F·퍼펙트스톰 → P3 회복·비코어 낙폭 → P4 실시간·구조·-20%·예외 → Q1 과열·돌파·%B → Q4 신규 사다리 → 8a RED | 상위시간대 재라벨, 게이트, (정밀) 최종체크 | 신규진입 7개 코드만 1/3 힌트 |
| 개별주 미보유(자유입력) | F 사다리 (가드 없음) → 8a RED | 정밀만: 게이트·최종체크에서 재무(fin<3 차단)·매크로(≥4.5 차단)가 다시 걸림 | 목표비중 0이면 "목표비중 먼저" 문구 |
| 개별주 보유 | P1 가드 → P3 → P4 보유 분기 → Q1 → 평단 +2% 초과면 Q2, 아니면 Q3 → 8b 보유 번역 | 상위시간대는 라벨 유지·힌트만, 게이트는 `상위 시간대 경고`면 방어 | MA5 대기 4개 코드에 부족분 40% 힌트 |
| 비코어 ETF | 개별주 전용 규칙(재무F·구조손상·돌파·%B 0.95 차단·단일봉)은 건너뜀. P3 비코어 낙폭, Q1 ETF 적립, 이력 부족이면 신규ETF | 같음 | ETF 적립은 비중차 기준 |
| 코어 ETF (bucket=core, 비중 부족) | `is_core_dca_allowed`가 거의 모든 단계보다 앞(P1 퍼펙트스톰, P2 -30/-40/-50%, P3 -20%, Q1) | Today: 패닉 코드 → 방어우선·"패닉진입대기", 퍼펙트스톰 → 후보등급 칸 "시장방어(매수금지)"·게이트 대기. 최종체크: 매크로≥4.5 차단, 고점대비≤-20%면 구조 행을 "주의"로 완화 | core_dca_amt = 매수금액×적립률, 재원 상한(개인모드: 예수금, -20%↓ 파킹자산 추가) |
| 레버리지/인버스 | 코어 DCA 제외(적립률 0). P2 일급락·DCA 과열/조건부·-50/-30%. `is_etf_accumulation_ok`에서 제외 | 프로필 종목은 단계표로 판정 전체 재작성(비중 코드 제외). 시장 가드 방어/비상이면 레버리지 시장방어 | 별도 레버리지 실행계획, 월적립은 라벨 글자 배율 |
| TDF/펀드 | RSI≤30일 때만 FUND_OVERSOLD_REBALANCE_REVIEW로 분기 | 대기 | — |

## 6. 투자판정과 실행 게이트의 관계

### 6.1 구조

- 판정(현장소장)은 `decision_code`/`dec`를 만든다. 게이트는 그 결과를 **바꾸지 않고** 실행 가능 여부를 5단계로 분류한다(`execution_gate.py` 모듈 설명 그대로).
- 게이트 입력은 코드 집합 + **라벨·실행메모·패턴 문구 정규식**이다(`_RE_DEFENSE_BLOCK`, `_RE_OVERHEAT_WAIT`, `_RE_GENERAL_WAIT` 등).
  그래서 판정 라벨 문구를 바꾸면 게이트 결과가 바뀔 수 있다. 라벨이 사실상 게이트 입력이다.
- 정밀관측소는 게이트 뒤에 최종 체크 13행과 `independent_check_summary`(같은 근거 중복 집계 제거)를 거치고, `build_execution_readiness`가
  게이트·최종체크 둘 다 통과할 때만 "정밀확인"으로 표시한다. **최종 체크가 게이트보다 엄격하며, 이것은 의도된 설계다**(20261120 framework reset).
- 보유판단 패널·레버리지 패널의 행동 문구는 `qualify_hold_action_plan`으로 "현재 매수 허가가 아님"이 앞에 붙는다. 이미 "보유 적합성 ≠ 오늘 매수 허가"를 지원한다.

### 6.2 코어 DCA 코드의 게이트 결과 (R/R 2.0·데이터 정상·시장 정상 고정 입력)

| 코드·라벨 | 엔진 그룹 | Today 후보등급 칸 | 최종읽기 | 게이트 |
| --- | --- | --- | --- | --- |
| CORE_STORM_DCA "🧱코어 방어: 미국지수 퍼펙트스톰 100% 거치 적립" | buyish | 🛡️시장방어(매수금지) | 🧱코어적립확인 | 대기/관찰 (주의 판정) |
| CORE_OVERHEAT_DCA "…과열 25% 정기적립" | caution | ✅ETF 양호 | 🧱코어적립확인 | 대기/관찰 (과열) |
| CORE_NEUTRAL_DCA / CORE_PULLBACK_DCA / CORE_DRAWDOWN_DCA | buyish | ✅ETF 양호 | 코어적립확인 / 정밀확인 | 실행가능 |
| PANIC_CASH_DEPLOY / PANIC_FINAL_DEPLOY | **caution**(라벨 "패닉"으로 추론) | 🛡️패닉진입대기(계획확인) | 🛡️패닉진입대기 | **방어우선** |

즉 코어 적립의 "속도"(적립률)는 엔진이 정하지만, 퍼펙트스톰 예외·과열 25%·패닉 투입은 Today/정밀에서 실행 가능으로 나오지 않는다.
월 적립 계산기는 같은 라벨에서 배율을 따로 읽으므로 실제로 돈을 배분하는 쪽은 또 다른 결론을 낸다(§8 C·D).

## 7. 요소별 역할 분류와 중복 사용

사용자 분류: ①후보 품질 ②최종 투자판정 ③최종판정을 덮어쓰는 위험·우선순위 ④실행 가능 여부만 제한하는 게이트 ⑤사이징 ⑥참고·설명.

| 요소 | 현재 들어가 있는 역할 | 중복 판단 |
| --- | --- | --- |
| 재무점수 | ① 후보등급(t_score 가산, fin=1 F) · ② 조건(fin=4 돌파·대장주·예외, ≥3 회복·평단 -7~-15%, ≥4 우량주 눌림·S급 추가) · ③ P1 재무F 하드차단 · ④ 최종체크 재무행(fin<3 차단) · 보유패널 2곳 가점 | 점수 합산은 1회(t_score)뿐이고 나머지는 필수조건. **의도된 확인 절차**. 단 보유패널 2곳이 서로 다른 가중치를 쓴다(아래 #3) |
| 기술점수 tech_total | ① 후보등급·안전상태 · ③ RED 하향(8a) | 안전관리자 역할에 정확히 일치. **YELLOW는 주석상 "소액/분할만"이지만 실행 코드가 없다**(Today 정렬 순위에만 쓰임) |
| main/adj 점수 | ② 진입 조건(adj≥4, ≥4.5, ≥5) | 현장소장 점수. RS·MFI가 tech_total과 adj 양쪽에 들어가지만 두 점수는 합산되지 않고 서로 다른 결정에 쓰여 **확인 절차**로 본다 |
| 추세·RS·MACD | ① tech_total · ② adj와 동시에 개별 필수조건(예: 깨끗한 대장주 = adj≥4.5 AND RS강함 AND 정배열) · 보유패널 | 같은 판정 안에서 점수 + 필수조건 이중 사용. 기준을 강하게 만드는 **의도된 확인**으로 보이나 가중 집중이므로 검증 대상 |
| RS 기울기 | ② adj ±1, 예외진입 금지(하락중), S급 추가 매크로 기준 완화(<4.0), 회복 RS 판정 · ⑥ SMC 해설 | 의도된 확인 |
| R/R | **엔진 판정 분기에는 쓰이지 않음.** ④ 게이트(<1 대기, 투영목표 대기, 없으면 데이터확인) · 최종체크(<1 차단, <1.5 주의) · 횡보 품질 · ⑤ 실행메모(<1.5 "소액 1차만") · 레버리지 정밀(2.0) | 역할이 깔끔하다: R/R은 실행 제한·사이징 요소 |
| SMC: FVG | ② 예외 진입 플래그(강세 FVG 눌림) | 판정 요소 |
| SMC: PD Zone | ④ Today 실행메모 대기(Premium·%B≥0.78) · 횡보 품질 상단권 | 게이트 요소 |
| SMC: 내/외부 구조·이벤트·유동성 청산·smc_action·insight | ⑥ 표시·해설·AI 프롬프트만 | 참고용 |
| 유동성 열지도(정밀) | ⑥ 표시 | 참고용 |
| 거래량비 | ② main_score, 단일봉 급락, 예외·추매 상한 · 횡보 품질 | 판정 요소 |
| 돈흐름(테마·섹터) | ④ 게이트(추격금지·회복확인 문구, 점수≤-10) · 시장 가드(확산률<35/50%, 가속<35%) · 섹터 머니플로우는 ⑥ | 게이트 요소. 판정 엔진에는 들어가지 않음 (원칙과 일치) |
| 매크로 final_macro_risk | ② adj 감점(0.5~2) · ② 조건(<4.5·<4.0·<3.5) · ③ P1 퍼펙트스톰 가드(≥4.5) · ⑤ 코어 적립률(≥4.5 예외표) · ④ 최종체크(≥4.5 차단, ≥2.5 주의) · ④ 시장 가드(≥4.5 +2, ≥3.5 +1) · 보유패널 하나(≥4.5 -2, ≥2.5 -1) | **가장 많이 겹친다.** ≥4.5에서 엔진 가드·최종체크·시장가드·보유패널이 모두 같은 방향으로 막아 결과는 일관되지만, 2.5~4.5 구간에서는 같은 판정 안에서 adj 감점과 `_fmr<3.5` 조건이 동시에 작동한다(예: QUALITY_PULLBACK_ENTRY). **중복 가중 후보 — 의도 확인 필요** |
| 시장 가드(지수 breadth) | ④ 게이트(시장방어/레버리지 시장방어/시장정보 확인) | 게이트 요소. 엔진 매크로와 다른 측정이며 역할 분리 원칙에 맞다 |
| 상위시간대(주/월봉) | ③ 미보유 진입형 재라벨 · ④ 게이트(경고=방어, 자료부족=데이터확인) · ⑤ 힌트(30% 이하) · 최종체크 행 | 미보유는 판정 덮어쓰기 + 게이트 두 번 (같은 결과). 보유는 게이트만 → 역할 혼재 |
| 계좌 비중 | ③ P1 목표0·초과·충족 · ② 비중차 조건(≥2, ≥3, ≥10) · ④ 게이트 비중 문구·최종체크 비중행 · ⑤ 매수금액 | 판정·게이트·사이징 모두에 있음. 비중 초과를 판정(P1)에서 막고 게이트에서 다시 막는 것은 **의도된 이중 안전장치** |
| 레버리지 조건 | ② P2 엔진 규칙 · ③ 레버리지 단계표 재판정(엔진 결과를 덮음) · ④ 게이트 문구·시장 가드 · ⑤ 별도 실행계획·월적립 배율 | **기준표 4종이 공존**(엔진, Today 변환, 단계표, 월적립 배율). 불일치 원인 |
| 고점대비 낙폭 | ② 구조손상·코어 적립률·패닉/위기 단계 · 최종체크 구조행 · 보유패널 2곳 | 판정 요소, 보유패널 가중 상이 |
| 평단대비 | ② 보유 사다리(-3/-7/-15%), 레버리지 단계(-12/-25/-35%) · 보유패널 2곳(-15% vs -10/-20%) · 최종체크(-7%) | 보유판단 기준이 3종 |

## 8. 중복·충돌 가능성이 있는 코드 (발견 목록)

분류: **[버그 의심]** 의도와 반대로 동작할 가능성이 높음 · **[충돌]** 두 규칙이 서로 다른 결론, 의도 확인 필요 · **[역할 차이]** 다른 질문에 답하는 정상 차이 · **[정리]** 동작 영향 없음, 유지보수 위험.

| # | 분류 | 내용 | 근거 |
| --- | --- | --- | --- |
| 1 | 버그 의심 | 월 적립 배율이 라벨 글자를 파싱한다. 코어 `💣코어 패닉(-50%↓): 최종투입`은 "50%"가 들어 있어 **0.5배**, `-40%` 현금투입도 기본값 0.5배. 엔진 적립률은 둘 다 2.0 | app.py:3832 `_rebcalc_signal_multiplier`, 사례 C |
| 2 | 버그 의심 | `🔔익절 타이밍 … (분할 매도 검토)`가 "분할"을 매수어로 읽혀 그룹 buyish, 월적립 배율 core/swing **1.0**. 데이터확인 라벨도 core 0.5배 | `classify_decision_signal`, 부록 A |
| 3 | 충돌 | 정밀관측소에 보유판단 패널 2개: `hold_judgement.build_hold_decision`(재무4 +4, 재무1 -2, 평단 -15% -3, 구조위험 -2, 매크로 없음, 레버리지 강력보유 금지)과 app.py `render_hold_or_cut_panel`(재무4 +2, 재무≤1 -4·하드손절, 평단 -10/-20%, 매크로 -1/-2, 재무방향 가점, 구조위험 없음, 하드손절에 역배열 필요) | 사례 B |
| 4 | 충돌 | 자산현황·전광판 스윙표는 엔진 원라벨을 그대로 표시. Today·정밀의 상위시간대 가드·레버리지 재판정·게이트가 빠져 있다. 월적립·인쇄 리포트가 이 원라벨을 읽는다 | app.py:35497, 21331, 사례 E·F2 |
| 5 | 충돌 | 미국 대표지수 코어의 "퍼펙트스톰 100% 거치 적립"(엔진·매뉴얼에 명시된 예외)이 Today 후보등급 칸에서는 "시장방어(매수금지)", 게이트 대기, 최종체크 매크로 차단으로 실행 불가. 월적립 배율은 1.0 | 사례 D, §6.2 |
| 6 | 충돌 | 코어 패닉 투입(-40/-50%)은 엔진 적립률 2.0, Today 게이트 방어우선, 월적립 0.5. -30% 코어 폭락은 Today 실행가능 → 낙폭이 깊을수록 실행이 더 막히는 비단조 구조. Today의 "패닉진입대기(계획확인)"는 의도된 표현으로 보이나 세 층의 결론이 다르다. 같은 행의 `실행메모`는 "분할 가능" | 사례 C |
| 7 | 충돌 | 레버리지 기준표 4종: 엔진(과열 %B≥0.85, 고점>-10%, 평단>-3%) / Today 변환(%B≥0.95, 당일≥12%) / 단계표(RSI70·MFI80·%B0.92, 평단 -12/-25/-35%, 회복 3/6) / 월적립 배율(-5/-10/-15%) | 사례 F2 |
| 8 | 충돌 | 매크로 결측 처리 3종: 엔진 NaN → UNKNOWN, 퍼펙트스톰 가드 미발동, `<4.5` 조건이 모두 거짓이라 ETF 적립·회복·추매 신호가 꺼짐 / `render_hold_or_cut_panel`은 결측을 0으로 보고 감점 없음 / Yahoo 일괄조회 실패 시 `get_macro_analysis`가 1.5 이상을 가정(penalty 0.5) | 사례 G, B3, app.py:15536 |
| 9 | 정리 | `select_holding_decision`의 PROFIT_TAKE_REVIEW는 평단 +20% 초과가 필요한데, 평단 +2% 초과 보유는 그 전에 `select_profitable_holding_decision`으로 가므로 **계좌경로에서 도달 불가**. 같은 조건의 `profit_take_signal`은 AI 프롬프트 표시에만 남아 있다 | decision_followup.py:132, 코드 분석 |
| 10 | 정리 | `_select_structure_and_exception_priority`의 마지막 `elif is_live_gap_shock:`·`elif is_structure_damage_entry_risk:`는 앞의 보유/미보유 분기가 모든 경우를 덮어 도달 불가 | decision_priority.py:281-293 |
| 11 | 정리 | 사전 전용 코드 2개(HARD_BLOCK_MACRO_STORM, CRISIS_CORE_FOCUS)와 매뉴얼의 "하드차단: 퍼펙트스톰" 설명 | §4.3 |
| 12 | 정리 | 107개 중 49개 코드가 `DECISION_GROUP_BY_CODE`에 없어 라벨 단어로 그룹을 추론. 예: LIVE_GAP_SHOCK_WAIT·`⚡레버리지 급락권: 회복조건 확인`은 neutral, `⏳과열: 눌림 대기`·`🆕신규ETF 보유: 눌림 대기`는 buyish. 그룹은 게이트 입력이다 | 부록 A, 사례 H |
| 13 | 정리 | 판정코드·문구 목록이 여러 파일에 복제: `TODAY_QUEUE_*_CODES`(today_queue.py)와 app.py:17618 실행계획의 같은 목록, 게이트·리포트·카드의 정규식, 패닉 코드 집합 4곳 | grep |
| 14 | 정리 | 안전상태 YELLOW는 정책 설명만 있고 실행 코드 없음 | decision_engine.py:823 |
| 15 | 역할 차이 | Today는 매크로·평가액·현금을 큐 계산 시점 스냅숏으로, 정밀은 현재 전역값으로 판정 | app.py:20950 vs 34643 |
| 16 | 역할 차이 | 정밀은 수동 현재가 입력을 허용 (출처 표시됨) | app.py:34632 |
| 17 | 역할 차이 | 미보유 자유입력은 가드 없는 자유 경로. 사용자 결정(2026-11-24)이며, 정밀 최종체크의 재무(fin<3)·매크로(≥4.5) 행이 실행을 다시 막는다 | 사례 A2 |
| 18 | 역할 차이 | 정밀 최종체크가 Today 게이트보다 엄격 (설계상 최종 거부 우선) | execution_readiness.py |
| 19 | 역할 차이 | 보유판단 패널은 "보유 적합성", 게이트는 "오늘 실행 가능성"이며 문구로 분리돼 있음 | decision_workflow.qualify_hold_action_plan |

## 9. 화면별 결과 불일치 — 고정 입력 사례

재현: `python -X utf8 scripts/decision_audit_cases.py` (코드 무수정. RS·벤치·레버리지 비교행·상위시간대 편향만 프로세스 안에서 고정값으로 대체).
가격은 `tests/fixtures_price.make_price_df`의 시드 고정 합성 데이터다. 실제 종목 시세가 아니므로 **숫자는 경로 확인용**이다.
"Today 게이트"는 `build_decision_workflow` 결과이며, 시장 가드·돈흐름을 붙이는 `prepare_execution_context` 단계는 포함하지 않았다(시장 정상 가정).

| 사례 | 고정 입력 | 화면별 결과 | 분류 |
| --- | --- | --- | --- |
| A2-1 | 미보유 개별주, 시드6 상승추세, RS강함, fin=1, 매크로 1.0, 목표 10% | Today(계좌): `🚨하드차단: 재무F급(처분)` 방어우선 / 정밀 자유입력: `🎯S급 눌림목: 탑승 찬스` 게이트 실행가능, 힌트 "1/3 정찰 330,000원" → 정밀 최종체크 재무행 차단 | 역할 차이(#17), 최종 단계에서 수렴 |
| A2-2 | 같은 입력, fin=4, 매크로 5.0 | Today: `🛡️시장위험: 추매중단/보유점검` 방어우선 / 자유입력: S급 눌림목 실행가능 → 최종체크 매크로 차단 | 역할 차이, 라벨은 매뉴얼과 다름(#11) |
| B | 보유 개별주 fin=1, 평단 100, 현재 106.62, 매크로 1.0 | 엔진·Today: `🚨하드차단: 재무F급(처분)` / 같은 정밀 화면의 패널1 `🚨 손절 검토`(-4점), 패널2 `❌ 손절 강력 검토`(-3점, 하드손절) | 충돌(#3) |
| B2 | 같은 c에 구조위험=True, fin=4, 매크로 5.0 | 패널1 `⚠️ 모니터링 강화` 2점(구조 -2 반영, 매크로 무시) / 패널2 `⚠️ 모니터링 강화` 1점(매크로 -2 반영, 구조 무시) | 충돌(#3): 결론은 같지만 근거가 반대 |
| B3 | 매크로 값 없음 | 패널2가 0으로 간주 → `✅ 조건부 보유` | 충돌(#8) |
| C | 코어 국내 ETF(069500), 목표 9%·현재 3%, 고점대비 -50.5% / -42.2% / -34.6% | 엔진: 최종투입 / 현금투입 / 폭락 200%, 적립률 모두 2.0, core_dca_amt 600,000원 · Today 게이트: 방어우선 / 방어우선 / 실행가능 · 월적립 배율: **0.5 / 0.5 / 2.0** | 버그 의심(#1), 충돌(#6) |
| D | 미국 대표지수 코어(VOO, us_etf_sp), 매크로 5.0 | 엔진: `🧱코어 방어: 미국지수 퍼펙트스톰 100% 거치 적립` 적립률 1.0 · Today: 후보등급 `🛡️시장방어(매수금지)`, 최종읽기 `🧱코어적립확인`, 게이트 대기 · 최종체크: 매크로 차단 · 월적립 1.0 | 충돌(#5) |
| E | 미보유 개별주 시드6, `S_PULLBACK_ENTRY`, 상위시간대 편향을 고정 | 자산현황 원라벨 `🎯S급 눌림목: 탑승 찬스` / Today·정밀: 경고 → `⚠️상위시간대 경고: 신규/추매 보류` 방어우선, 과열 → `🟡상위과열 눌림: 1차 정찰만` 대기. 보유 종목이면 라벨은 그대로이고 게이트만 방어우선 | 충돌(#4) |
| F2 | 레버리지(TQQQ) 보유, 시드2·꼬리충격 -10%, 평단 123.86, 현재 114.69, 고점대비 -23.8%, %B 0.06, 기초축 비교행 없음 | 자산현황: `⚡레버리지 DCA 조건부: 단계별 소액` → 월적립 배율 **0.5** / Today·정밀: 단계표 "관망 ×0, 회복 1/6" → `⚡레버리지 회복 전: DCA 보류` 게이트 방어우선, 배율 0.0 | 충돌(#4, #7) |
| G | 비코어 ETF 적립 조건 충족 입력, 매크로 1.0 / NaN / 5.0 | 적립 허용 True / **False(UNKNOWN)** / False(STORM); 퍼펙트스톰 가드 발동 False / **False** / True | 충돌(#8) |
| H | 그룹 맵에 없는 라벨 | `⚠️실시간 급락: 정규장 확인대기` neutral, `⚡레버리지 급락권: 회복조건 확인` neutral, `💣코어 패닉(-50%↓): 최종투입` caution, `🆕신규ETF 보유: 눌림 대기` buyish | 정리(#12) |

## 10. 유지 / 정리 / 추가 검토

### 10.1 현재 체계를 유지하는 것이 좋은 부분

- **안전관리자(후보등급·안전상태)와 현장소장(최종판정)의 분리.** 후보등급은 합산 점수, 최종판정은 상황별 우선순위 규칙으로 서로 다른 질문에 답한다.
- **엔진 내부 판정 순서와 모듈 분리**(inputs → signals → priority → followup → finalization). 순수 함수이고 골든·패리티 테스트가 있다.
- **판정과 실행의 분리**: 게이트·최종체크·준비도는 라벨을 바꾸지 않고 실행만 제한하며, 더 엄격한 쪽이 이긴다. 보유 문구에 "매수 허가 아님"을 붙인다.
- **R/R·돈흐름·시장 가드를 판정 엔진 밖(게이트)에 둔 것.** ROADMAP의 "실행·계좌 제한은 후보 문구가 해제하지 않는다" 원칙과 맞다.
- 비중 초과·목표0의 판정+게이트 이중 차단, 데이터 오류 최우선, 비코어 패닉 투입 차단.
- 결측을 0으로 보지 않는 최근 원칙(지표 결측 → 데이터확인, R/R 없음 → 데이터확인).

### 10.2 리팩토링(정리)이 필요한 부분 — 동작 보존 범위

1. **엔진 밖 후처리를 하나의 공용 함수로 묶는다.** 상위시간대 가드 → 레버리지 재판정 → 비코어 패닉 표시가드 → workflow/게이트를 한 함수로 만들고
   Today·정밀·데모가 그대로 쓰게 한다. 순서와 결과는 지금과 동일하게 유지(동등성 테스트). 이것만으로는 자산현황 결과가 바뀌지 않는다.
2. **판정 코드 사전 한곳 정리.** 코드 → (그룹, 신규진입 여부, 차단/대기 집합, 표시 라벨)을 한 표로 모으고, `TODAY_QUEUE_*`와 app.py:17618 복제,
   패닉 코드 집합 4곳을 그 표에서 읽게 한다. 그룹 맵 누락 49개는 현재 추론값 그대로 표에 고정해 동작을 바꾸지 않는다.
3. 도달 불가 분기(#9, #10)와 사전 전용 코드(#11)는 테스트로 도달 불가를 확인한 뒤 주석·문서로 표시한다(삭제는 별도 승인).
4. 두 보유판단 패널의 입력·가중치를 표로 나란히 보여 주는 문서/테스트를 먼저 만든다(통합은 아래 결정 후).

### 10.3 동작이 바뀌므로 사용자 결정이 먼저 필요한 부분

| 결정 항목 | 선택지 | 영향 |
| --- | --- | --- |
| 자산현황·월적립이 쓰는 판정 | (a) 지금처럼 엔진 원라벨 (b) Today와 같은 후처리 결과 | (b)면 레버리지·상위시간대 결과가 화면 간 일치, 월적립 배분이 바뀜 |
| 월적립 배율의 근거 | (a) 라벨 글자 (b) `decision_code`·`core_dca_rate` | (b)면 코어 패닉 0.5→2.0, 익절검토 1.0→0 등 배분 변경 |
| 보유판단 패널 2개 | 하나를 기준으로 하고 다른 하나를 설명용으로 둘지, 두 개를 유지할지 | 같은 화면 결론 일치 |
| 미국 대표지수 퍼펙트스톰 100% 적립 | 실행 가능해야 하는 예외인지, 표시만 하는 정보인지 | 게이트·최종체크 매크로 행에 예외를 둘지 결정 |
| 코어 패닉 -40/-50% | 계획 확인 후 실행(현재 Today 의도) 유지 / 적립률과 맞출지 | 게이트·월적립 일치 |
| 매크로 결측 | UNKNOWN을 차단·대기·정상 중 무엇으로 볼지 하나로 통일 | 엔진·보유패널·매크로 수집 실패 경로 |
| 레버리지 기준표 4종 | 단계표 하나를 기준으로 할지 | 레버리지 화면·배분 일치 |
| 매크로 이중 반영 (adj 감점 + `_fmr<3.5` 조건) | 의도된 이중 확인인지 | 임계값 검증 작업에서 함께 |

### 10.4 추가 검토가 필요한 부분

- 운영 데이터에서 위 충돌이 실제로 얼마나 자주 나는지(보유 레버리지·코어 ETF가 자산현황과 Today에서 다른 라벨인지). 이번 감사는 합성 고정 입력만 썼다.
- 시장 가드·돈흐름까지 붙인 Today 전체 경로(`prepare_execution_context`)의 고정 입력 대조. 이번에는 시장 정상 가정.
- 임계값 자체의 타당성(성과 검증)은 ROADMAP 5단계 "투자 기준 검증" 범위이며 이번 감사에서 평가하지 않았다.

## 11. 검증 기록

- 기준 커밋 `3ec1608d`. 저장소 이력이 얕은 복제라 `git fetch --unshallow` 후 실행(패리티 테스트가 과거 커밋 원문을 읽는다).
- `python -X utf8 scripts/check_refactor.py --scope decision` (Python 3.13, requirements-dev 설치 venv): **1,637 passed / 1 failed**,
  실패는 HANDOFF에 기록된 기존 실패 `test_extracted_policies_preserve_all_original_conditions_and_literals`와 동일. 코드 무변경이므로 전후 동일.
- 코드 목록: AST로 `_set_decision`/`build_decision_outcome`/`"decision_code"` 리터럴을 수집(107개) + 구조손상·코어 DCA·보유 번역 동적 코드.
- 운영 앱(Streamlit Cloud) 확인은 하지 않았다. 이번 변경은 문서와 읽기 전용 스크립트뿐이라 배포 동작에 영향이 없다.

## 부록 A. 판정코드 107개 기계 속성

열 설명: 분류출처 = `DECISION_GROUP_BY_CODE`에 있으면 "코드표", 없으면 라벨 단어로 추론. 신규진입 사이징 = `NEW_ENTRY_DECISION_CODES`(1/3 힌트).
RED 하향 = `AGGRESSIVE_NEW_ENTRY_CODES`. 보유 번역 = `HOLDING_ENTRY_DECISION_OVERRIDES`. Today 차단/대기 = `TODAY_QUEUE_EXECUTION_BLOCK/WAIT_CODES`,
방어신호 = `is_today_queue_defense_signal`. 중립 조건 게이트 = R/R 2.0, 지표 정상, 시장·패턴·돈흐름 없음에서 `build_decision_workflow` 결과.
월적립 배율 = `_rebcalc_signal_multiplier(라벨, bucket)`.

| 코드 | 표시 라벨(코드에 있는 문구) | 분류(group) | 분류출처 | 신규진입 사이징 | RED 하향 대상 | 보유 시 번역 | Today 차단/대기 집합 | 중립 조건 게이트 | 월적립 배율 core/swing/lev | 생성 위치 |
|---|---|---|---|:-:|:-:|:-:|---|---|---|---|
| `ABOVE_COST_HOLD` | ⏳평단이상: 보유 유지 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `ABOVE_COST_WAIT` | ⏳평단이상: 하락대기(보유) | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `ABOVE_COST_WAIT_PULLBACK` | ⏳평단이상: 추가 하락 대기 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `A_GRADE_ADD_ON_REVIEW` | 📈A급 비중여유: 소액 추가 검토 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_policies |
| `A_GRADE_TECH_REBOUND` | 🎯A급: 기술적 반등 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_policies |
| `A_UPTREND_SEARCH_ENTRY` | 🔍A급 정배열: 타점 탐색 중 | neutral | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 0.5/0.0/0.5 | decision_policies |
| `BAND_UPPER_WAIT` | ⚠️밴드상단: 눌림 대기 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `BELOW_COST_TARGET_FILLED` | ⏸️평단이하: 비중 충족(추매 보류) | caution | 라벨 단어 추론 |  |  |  |  | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `BREAKOUT_52W_ENTRY` | 🚀52주 신고가 돌파: 모멘텀 진입 검토 | buyish | 라벨 단어 추론 | ● | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `CONCENTRATED_ETF_UPPER_WAIT` | 🟡집중 ETF 상단권: 눌림대기 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `CORE_CRASH_DCA` | {…} 폭락: {…} | buyish | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome, decision_priority |
| `CORE_DRAWDOWN_DCA` | {…} 하락: {…} | buyish | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome, decision_priority |
| `CORE_NEUTRAL_DCA` | (동적 라벨) | buyish | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome |
| `CORE_OVERHEAT_DCA` | (동적 라벨) | caution | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome |
| `CORE_PULLBACK_DCA` | (동적 라벨) | buyish | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome |
| `CORE_STORM_DCA` | {…} 방어: {…} | buyish | 코드표 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_engine.build_core_dca_outcome, decision_policies |
| `COST_MINUS_3_7_DCA` | ✅평단 -3~-7%: 소액 분할매수 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `COST_MINUS_7_15_CONDITIONAL_DCA` | 🎯평단 -7~-15%: 조건부 분할매수 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `CRISIS_PANIC_SELL_OFF` | 🚨위기/패닉: 투매 포착 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.5/0.0/0.0 | decision_policies |
| `DATA_ERROR` | ⚪데이터확인: 실시간 지표 재계산 필요 | caution | 코드표 |  |  |  |  | 데이터확인 | 0.5/0.0/0.5 | decision_finalization |
| `DOWNTREND_NO_ENTRY` | ⚠️하락추세: 진입보류 | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `DRAWDOWN_20_HOLDING_CAUSE_CHECK` | ⚠️고점대비 -20%: 추매금지/원인점검 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_priority |
| `DRAWDOWN_20_HOLDING_STOP_CHECK` | ⚠️고점대비 -20%: 추매금지/손절기준 점검 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_priority |
| `DRAWDOWN_20_NO_ENTRY` | ⚠️고점대비 -20%: 신규진입 보류 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_priority |
| `EARLY_ENTRY` | 🟢선진입 가능 구간 | buyish | 라벨 단어 추론 |  | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `EARLY_REVERSAL_ENTRY` | 🟢선진입 가능: 반전 초입 | buyish | 라벨 단어 추론 |  | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `ETF_DCA_OK` | ✅ETF 목표비중 미달: 적립식 매수 가능 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_followup |
| `ETF_LARGE_GAP_DCA_OK` | ✅ETF 비중부족 큼: 소액 적립 허용 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_followup |
| `EXCEPTION_ADD_ON` | 🟣예외승인: 정찰대 추매(MA5/FVG) | buyish | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 1.0/1.0/1.5 | decision_priority |
| `EXCEPTION_ENTRY` | 🟣예외승인: 정찰대 진입(MA5/FVG) | buyish | 라벨 단어 추론 | ● | ● | ● |  | 대기/관찰 | 1.0/1.0/1.5 | decision_priority |
| `EXTREME_OVERHEAT_NO_CHASE` | 🚫극단과열: 추격금지 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `FUND_OVERSOLD_REBALANCE_REVIEW` | ⏳TDF/펀드 낙폭과대: 소액 리밸런싱 검토 | caution | 코드표 |  |  |  | 대기 | 대기/관찰 | 0.5/0.0/0.5 | decision_policies |
| `HARD_BLOCK_BOLLINGER_UPPER` | ⏳볼린저 상단 초과: 추격대기 ¦ ⏳볼린저 상단권: 추격대기 / 🚫하드차단: 볼린상단 이탈 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_followup |
| `HARD_BLOCK_FINANCIAL_F` | 🚨하드차단: 재무F급(처분) | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `HARD_BLOCK_MFI_OVERHEAT` | 🚫하드차단: MFI 극단 과열 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_followup |
| `HARD_BLOCK_OVERWEIGHT` | 🛑하드차단: 비중 초과 | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `HARD_BLOCK_TARGET_FILLED` | ⏸️하드차단: 비중 충족(관망) | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `HOLDING_BREAKOUT_TRAIL` | 🚀보유 신고가: 추격보다 추적 | caution | 코드표 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_EARLY_ADD_REVIEW` | 🟢보유 반전초입: 추가는 확인 | caution | 코드표 |  |  |  |  | 대기/관찰 | 1.0/1.0/1.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_EARLY_REVERSAL_ADD_REVIEW` | 🟢보유 반전초입: 추가는 확인 | caution | 코드표 |  |  |  |  | 대기/관찰 | 1.0/1.0/1.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_EXCEPTION_ADD_REVIEW` | 🟣보유주 예외승인: 정찰대 추가 | buyish | 코드표 |  |  |  |  | 대기/관찰 | 1.0/1.0/1.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_LEADER_ADD_REVIEW` | 📈보유대장주: 추가는 눌림 확인 | caution | 코드표 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_OVERSOLD_ADD_REVIEW` | 🔥보유 낙폭과대: 추가 검토 | buyish | 코드표 |  |  |  |  | 실행가능 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_PULLBACK_WAIT_CLOSE` | 🟡보유주 단기하락: 추매는 종가 확인 | caution | 코드표 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `HOLDING_QUALITY_PULLBACK_ADD_REVIEW` | 🎯우량 보유주 눌림: 추가 검토 | buyish | 코드표 |  |  |  |  | 실행가능 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_QUALITY_RECOVERY_CANDIDATE` | ✅보유주 회복 후보: 추가는 분할 | buyish | 코드표 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_QUALITY_RECOVERY_SCOUT` | 🟢보유주 회복초입: 추가는 소액 | buyish | 코드표 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_S_PULLBACK_ADD_REVIEW` | 🎯보유 S급 눌림: 추가 검토 | buyish | 코드표 |  |  |  |  | 실행가능 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLDING_TREND_PULLBACK_ADD_REVIEW` | 📈보유주 추세눌림: 소액 추가 검토 | caution | 코드표 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_engine.HOLDING_ENTRY_DECISION_OVERRIDES |
| `HOLD_WAIT_SIGNAL` | ⏳보유중(신호대기) | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `LEADER_MA5_FAST_PULLBACK_ENTRY` | 🔥불뿜는 대장주: 초단기 눌림(MA5) 진입 | buyish | 라벨 단어 추론 |  | ● |  | 대기 | 대기/관찰 | 1.0/1.0/1.5 | decision_policies |
| `LEADER_MA5_PULLBACK_ENTRY` | 🔥불뿜는 대장주: MA5 눌림 진입 | buyish | 라벨 단어 추론 |  | ● |  | 대기 | 대기/관찰 | 1.0/1.0/1.5 | decision_followup |
| `LEVERAGED_DAILY_DROP_NO_ADD` | ⚡레버리지 급락: 신규/추매 보류 / ⚡레버리지 급락: 추매금지/종가 확인 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.5/0.0/0.0 | decision_policies, decision_priority |
| `LEVERAGED_DCA_CONDITIONAL` | ⚡레버리지 DCA 조건부: 단계별 소액 | buyish | 코드표 |  |  |  | 대기 | 대기/관찰 | 0.5/0.0/0.5 | decision_engine, today_queue |
| `LEVERAGED_DCA_OVERHEAT_PASS` | ⚡레버리지 과열패스: DCA 대기 | caution | 코드표 |  |  |  | 대기 | 대기/관찰 | 0.25/0.25/0.0 | app, decision_engine, today_queue |
| `LEVERAGED_RECOVERY_DCA_BLOCK` | ⚡레버리지 급락권: 회복조건 확인 / ⚡레버리지 패닉권: DCA 보류 외 2 | neutral | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.5/0.0/0.5 | app, decision_priority, today_queue |
| `LEVERAGED_RECOVERY_DCA_CONDITIONAL` | (동적 라벨) | neutral | 라벨 단어 추론 |  |  |  | 대기 | 라벨 의존(본문 §6 표) | 라벨 % 의존 | app |
| `LEVERAGED_TARGET_FILLED_DCA_EXCLUDED` | ⚡레버리지 목표비중 충족: DCA 제외 | neutral | 라벨 단어 추론 |  |  |  |  | 방어우선 | 0.0/0.0/0.0 | app |
| `LEVERAGED_TARGET_ZERO_DCA_EXCLUDED` | ⚡레버리지 목표비중 없음: DCA 제외 | neutral | 라벨 단어 추론 |  |  |  |  | 방어우선 | 0.5/0.0/0.5 | app |
| `LEVERAGED_WATCH_NO_POSITION` | (동적 라벨) | neutral | 라벨 단어 추론 |  |  |  |  | 라벨 의존(본문 §6 표) | 라벨 % 의존 | app |
| `LIVE_GAP_SHOCK_HOLDING_CHECK` | ⚠️실시간 급락: 추매금지/정규장 확인 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_priority |
| `LIVE_GAP_SHOCK_WAIT` | ⚠️실시간 급락: 정규장 확인대기 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies, decision_priority |
| `MACRO_STORM_HOLDING_CAUTION` | 🛡️시장위험: 추매중단/보유점검 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `MTF_DAMAGE_NO_ADD` | ⚠️상위시간대 경고: 신규/추매 보류 | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.25/0.25/0.0 | app |
| `MTF_OVERHEAT_SCOUT_ONLY` | 🟡상위과열 눌림: 1차 정찰만 | buyish | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 0.25/0.25/0.0 | app |
| `NEAR_COST_WAIT` | ⏳평단근처: 추가 하락 대기 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `NEAR_UPPER_WAIT` | ⚠️상단부근: 눌림 대기 | caution | 라벨 단어 추론 |  |  |  | 차단 | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `NEW_ENTRY_LEADER` | 🆕신규진입: 대장주 포착 | buyish | 라벨 단어 추론 | ● | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `OVERHEAT_EXTENSION_WAIT_MA5` | ⚠️과열확장: 추격금지, MA5 대기 | caution | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 0.25/0.25/0.0 | decision_followup, decision_policies |
| `OVERHEAT_WAIT` | ⏳과열: 눌림 대기 | buyish | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `OVERSOLD_ADD_ON` | 🔥낙폭과대: 줍줍 찬스 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 0.5/0.0/0.5 | decision_policies |
| `OVERSOLD_DCA` | 🎯낙폭과대: 분할매수 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `OVERSOLD_NEW_ENTRY` | 🔥낙폭과대: 신규 진입 | buyish | 라벨 단어 추론 |  | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `PANIC_CASH_DEPLOY` | 💣코어 패닉(-40%↓): 현금 투입 / 💣패닉(-40%↓): 현금 투입 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.5/0.0/0.0 | decision_priority |
| `PANIC_FINAL_DEPLOY` | 💣코어 패닉(-50%↓): 최종투입 / 💣패닉(-50%↓): 최종투입 | caution | 라벨 단어 추론 |  |  |  | 방어신호 | 방어우선 | 0.5/0.0/0.0 | decision_priority |
| `PREMARKET_REBOUND_HOLDING_WAIT` | (동적 라벨) | neutral | 라벨 단어 추론 |  |  |  | 대기 | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_priority |
| `PREMARKET_REBOUND_WAIT` | (동적 라벨) | neutral | 라벨 단어 추론 |  |  |  | 대기 | 라벨 의존(본문 §6 표) | 라벨 % 의존 | decision_priority |
| `PRICE_DRAWDOWN_HOLDING_CHECK` | ⚠️가격위험: 추매금지/원인점검 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `PRICE_DRAWDOWN_NO_ENTRY` | ⚠️가격위험: 신규진입 보류 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `PROFIT_TAKE_REVIEW` | 🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토) | buyish | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 1.0/1.0/0.0 | decision_policies |
| `QUALITY_PULLBACK_ENTRY` | 🎯우량주 눌림 구간: 정찰 진입 적합 | buyish | 라벨 단어 추론 | ● | ● | ● |  | 대기/관찰 | 1.0/1.0/1.5 | decision_policies |
| `QUALITY_RECOVERY_CANDIDATE` | ✅우량주 회복 후보: 분할 검토 | buyish | 코드표 | ● | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies, decision_priority |
| `QUALITY_RECOVERY_SCOUT` | 🟢우량주 회복초입: 1차 정찰 | buyish | 코드표 | ● | ● | ● |  | 실행가능 | 1.0/1.0/1.5 | decision_policies, decision_priority |
| `QUALITY_RECOVERY_WATCH` | 🔎우량주 회복관찰: 바닥 확인 | neutral | 코드표 |  |  |  |  | 대기/관찰 | 0.5/0.0/0.5 | decision_policies, decision_priority |
| `REVERSE_TREND_NO_ENTRY` | 🚫역배열: 진입 보류 / 🚫진입보류: 역배열 대기 | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `SAFETY_RED_NO_NEW_ENTRY` | 🧯안전관리자 RED: 신규진입 보류 | caution | 코드표 |  |  |  | 방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine |
| `SEARCH_NEW_ENTRY` | 🔍대기: 신규 타점 탐색 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
| `SHORT_OVERHEAT_NO_ADD` | ⚠️단기과열: 추매 보류 | caution | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `SHORT_OVERHEAT_NO_ENTRY` | ⚠️단기과열: 진입 보류 | caution | 라벨 단어 추론 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `SINGLE_DAY_BREAKDOWN_HOLDING_CHECK` | ⚠️단기급락: 추매금지/종가확인 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `SINGLE_DAY_BREAKDOWN_NO_ENTRY` | ⚠️단기급락: 신규진입 보류 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `STRENGTH_ADD_ON_OK` | ✅상승확인: 2차 정찰 추매 가능 | buyish | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 1.0/1.0/1.5 | decision_followup |
| `STRUCTURE_DAMAGE_HOLDING_CHECK` | ⚠️구조훼손: 추매금지/손절기준 점검 / ⚠️추세훼손: 추매금지/손절기준 점검 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `STRUCTURE_DAMAGE_NO_ENTRY` | ⚠️구조훼손: 신규진입 보류 / ⚠️추세훼손: 신규진입 보류 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_engine.build_structure_damage_context |
| `S_GRADE_ADD_ON_OK` | ✅S급 비중여유: 분할 추가 가능 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `S_GRADE_OVERHEAT_WAIT` | ⏳S급 과열 구간: 식힌 뒤 추가 | neutral | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 0.25/0.25/0.0 | decision_policies |
| `S_GRADE_OVERSOLD_BUY` | 💎S급 과매도: 강한 분할추매 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `S_PULLBACK_ADD_ON` | 🎯S급 눌림목: 추매 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 0.5/0.0/0.5 | decision_policies |
| `S_PULLBACK_ENTRY` | 🎯S급 눌림목: 탑승 찬스 | buyish | 라벨 단어 추론 | ● | ● | ● |  | 실행가능 | 0.5/0.0/0.5 | decision_policies |
| `S_UPTREND_WAIT_PULLBACK` | 🔍S급 정배열: 눌림 구간 진입 대기 | buyish | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 1.0/1.0/1.5 | decision_policies |
| `TARGET_FILLED_HOLD` | ⏸️비중 충족: 보유 유지 | neutral | 라벨 단어 추론 |  |  |  |  | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `TARGET_FILLED_S_GRADE_WAIT` | ⏸️S급이나 비중 충족: 눌림 오면 재진입 | buyish | 라벨 단어 추론 |  |  |  |  | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `TARGET_ZERO_NO_ADD` | 🛑목표비중 0%: 추매금지/정리대상 | caution | 코드표 |  |  |  | 차단·방어신호 | 방어우선 | 0.0/0.0/0.0 | decision_policies |
| `TREND_PULLBACK_EXPLORE` | 📈추세 눌림 구간: 소액 탐색 가능 | buyish | 라벨 단어 추론 |  | ● | ● |  | 실행가능 | 0.5/0.0/0.5 | decision_policies |
| `UPTREND_PULLBACK_CONFIRM` | 🔍정배열 눌림: 신호 확인 후 접근 | buyish | 라벨 단어 추론 |  |  |  | 대기 | 대기/관찰 | 0.5/0.0/0.5 | decision_policies |
| `UPTREND_PULLBACK_DCA` | 📈정배열: -3% 이상 눌림 분할매수 | buyish | 라벨 단어 추론 |  |  |  |  | 실행가능 | 1.0/1.0/1.5 | decision_policies |
| `WATCH_WAIT_ENTRY` | 🔍관망: 타점 대기 | neutral | 라벨 단어 추론 |  |  |  |  | 대기/관찰 | 0.0/0.0/0.0 | decision_policies |
