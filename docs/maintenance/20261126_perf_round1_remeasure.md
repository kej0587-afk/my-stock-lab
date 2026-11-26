# 속도 1차 개선(PR #87) 재측정, 조건 A (2026-11-26)

비교 기준: 같은 날 21:56 회차(`20261126_prod_check_bok_today_gate_perf.md` 4절, 코드 dd6835e5).
이번 회차: `main` e1193866(PR #87: 국내 가격 이력 넓은 구간 1회 요청 후 잘라 쓰기, SEC 접수번호 문서 하루 보관). 시각 KST, 계좌 금액 미기록.
진단 JSON은 브라우저에서 읽어 요약만 옮김(파일 저장·Git 없음). 측정 중 main 병합 없음(앱 로그 확인은 하지 않음).

**시간대 차이 주의:** 기준 회차는 21:56, 이번은 23:35(둘 다 한국 장 마감 후·미국 추수감사절 휴장일). 원격 응답(Yahoo 제한 등)이 달라질 수 있어
총 시간 차이는 단계·카운터와 함께 봐야 합니다.

## 1. 시간
| 회차 | 작업 | 버튼 | 첫 결과 | 완료 | 앱 표시 | 21:56 회차 |
|---|---|---|---|---|---|---|
| 1 | 오늘 점검 | 23:36:47.1 | 23:38:36.4 | 23:38:37.9 | 108.0초 (14:36:48→14:38:36 UTC) | 87.8초 |
| 1 | 시황 생성 | 23:39:15.6 | 23:42:04.2 | 23:42:13.8 | 자동 시황 생성 130.0초 (14:39:31→14:41:41 UTC), 화면 27.1초 | 125.0초 |
| 2 | 오늘 점검 | 23:43:09.7 | — | 23:44:26.9 | 73.6초 (14:43:12→14:44:26 UTC) | 75.3초 |
| 2 | 시황 생성 | 23:44:39.5 | 23:46:29.5 | 23:46:39.7 | 72.2초 (14:44:55→14:46:07 UTC), 화면 27.1초 | 63.7초 |
| — | 새로고침만 | 23:47:08.0 | — | 23:47:21.7 | 13.7초 | 26.4초 |
- 1회차 오늘 점검이 끝난 뒤 시황 버튼까지 38초가 걸렸습니다(첫 클릭이 화면 재표시와 겹쳐 다시 누름). 기준 회차는 10초.

## 2. 오늘 점검 (100행, 등록 87, 자동 후보 12)
- 1회차 단계: summary 53.5(기준 44.1), stock_signals 24.5(24.2), flow_refresh 20.2(19.4), **rs_price_history_3mo 18.9(9.6)**, flow_theme_prices 13.0(12.2),
  **analyst_enrichment 10.3(6.5)**, flow_etf_prices 7.2(7.2), price_history_10y 5.7(5.5), flow_context 5.1(5.0).
- 분류 활성: prices 59.4(58.1), external_data 40.2(26.7), indicators 20.2(20.8), decision 13.9(12.9).
- 상위 함수: _compute_summary_item 137.6(132.5), kr_history_http 82.2/328회(98.4/384), load_price_df 69.5/726(84.7/688), get_money_flow_ohlc 58.5,
  **lookup_yfinance_info 51.6(60회), yahoo_metadata_lock_wait[info] 42.7(28회), get_analyst_snapshot 38.8(79회)** — 기준 회차 상위 10에 없던 Yahoo 메타데이터 대기.
- 카운터: **kr_history.request 328(384)**, kr_history_scope.lookup 413 · unique 328(384) · miss 328 · slice_reuse 85 · reuse 85(29) · default_start 279 · explicit_start 134;
  yfinance_history.batch 6 · download 25; yahoo_chart.request 89 · response 81 · error 8.
- 해석: PR #87로 국내 이력 HTTP 요청이 56건(14.6%) 줄고 kr_history_http 누적 16초 감소. 대신 Yahoo 메타데이터(애널리스트·종목정보) 잠금 대기가
  42.7초 생겨 external_data가 13.5초 늘었고 총 시간은 108.0초로 늘었습니다. 이 차이는 PR #87이 바꾼 경로가 아니라 원격 제한 쪽으로 보입니다(확정 아님).
- 2회차: 73.6초(75.3), summary 38.2, stock_signals 21.6, rs 9.4, flow_refresh 7.0. kr_history 요청 0, yahoo_chart.request 87 · error 6.

## 3. 시황 생성
- 1회차 단계: macro_official 49.0(58.4), prices 30.5(26.9), assembly 28.8(18.9), persistence 15.9(15.0), news 2.4, articles 2.3, calc 1.2.
  상위: earnings_discovery.worker 139.1(140.1), report_context 80.8, **earnings_discovery.sec_rate_wait 55.2/107회(54.7/107)**, earnings_official.request 50.7,
  http_get.dart 34.4(47회), collect_report_earnings 26.2, update_report_history 14.1. **http.sec 107(107)**, sec_archive.hit 없음(재부팅 직후라 비어 있음).
- 2회차 단계: macro_official 18.1(23.9), prices 21.3(18.0), **assembly 27.3(15.2)**, persistence 3.9(2.9).
  상위: earnings_discovery.worker 61.8(80.9), report_context 38.6(42.4), earnings_official.request 33.6/92회(35.1/124), **sec_rate_wait 26.6/61회(43.9/94)**.
  **http.sec 61(94), earnings_discovery.cache.sec_archive.hit 33**, issuer_accounts hit 33 / miss 45, bulletin exports reuse.
- 해석: SEC 문서 보관으로 두 번째 생성의 SEC 요청이 94→61건, 대기 43.9→26.6초 줄었습니다. 2회차 총 시간이 63.7→72.2초로 늘어난 것은 assembly(+12.1초)
  때문이며, assembly는 PR #87 범위 밖입니다. 원인은 이번 기록으로 확정하지 못했습니다.

## 4. 결과 일치
- 실적 첫 줄: 1회차 "공식 발표 확인 20개 · 일부 조회 실패 24개 · 공식값 없음 19개", 2회차 "공식 발표 확인 23개 · 공식값 없음 31개" — 21:56 회차와 같은 숫자.
- 데이터확인 행: 1·2회차 모두 2개(0227L0.KS, BRK.B) — 21:56 회차와 같음.
- 판정 코드: 1회차와 2회차 100행이 모두 같음(차이 0건). 1회차 분포: STOCK_PANIC_CAUSE_CHECK 25, STOCK_CRISIS_CAUSE_CHECK 9, STOCK_DRAWDOWN_CAUSE_CHECK 9,
  STRUCTURE_DAMAGE_NO_ENTRY 8, QUALITY_RECOVERY_CANDIDATE 6, NON_CORE_ETF_PANIC_CAUSE_CHECK 5, MTF_OVERHEAT_SCOUT_ONLY 5, PRICE_DRAWDOWN_NO_ENTRY 4, 그 밖 29.
  **21:56 회차의 판정 코드는 저장해 두지 않아 행 단위 비교는 못 했습니다.** 이번 회차부터 코드 목록을 로컬(저장소 밖)에 보관했습니다.
- 오늘 추가 가능액(월적립 표, 오늘 점검 재계산 후 23:50): 7종목 중 5개 `0원 · 차단`(방어우선 시장방어 3, 상위 시간대 추세훼손+다른 차단 2), 2개 `0원 · 이번 달 계획 0원`.
  20:42 확인과 같은 분포입니다. 21:56 회차에는 이 표를 보지 않았습니다.
  주의: 새로고침한 새 세션에서 오늘 점검을 다시 계산하기 전에는 5개가 `미확인 · 게이트 미확인`으로 나옵니다(저장된 결과 복원만으로는 게이트를 확인하지 않음).
