# 운영 확인: 금통위 공식 결과(PR #82·#83), 오늘 점검 미계산 표시(PR #84), 거래소 달력(PR #85), 속도 조건 A (2026-11-26)

모든 시각은 KST. 확인한 컴퓨터: 사용자 집 컴퓨터(Claude 앱 브라우저). 계좌 금액은 기록하지 않습니다.
진단 JSON은 브라우저에서 읽어 요약만 옮겼고 파일로 저장하거나 Git에 넣지 않았습니다.

## 1. 금통위 수집기 로컬 실행 (PR #82 → #83)
- `main` b71c6f7b(PR #82) 21:21 실행: BOK `status missing`, `reason official_statement_link_unavailable`.
  - 원인 1: 한국은행 메인의 `통화정책방향 (2026.11.26)` 링크 두 개가 같은 nttId=11067084인데 쿼리에 `searchCnd`, `depth`, `programType`, `relate` 등이 붙어
    `nttId=N&menuNo=200690` 정확 일치 검사에서 거부됨.
  - 원인 2: 그 다음 `policy_decision_unrecognized`. `div.dbdata` 본문이 제목 `통화정책방향`으로 시작해 첫 `□` 앞 조각을 첫 문단으로 잡음.
- PR #83: 링크를 `view.do?nttId=N&menuNo=200690`로 정규화(다른 메뉴·호스트, 서로 다른 nttId 두 개는 계속 거부), 앞의 제목 문단은 건너뜀. 테스트 2개 추가.
  수정 후 로컬 실행: `official`, 3.0 → 3.25, `hike`, `decision_date 2026-11-26`, source nttId=11067084.
- 테스트: `test_central_bank_results.py` + `test_bok_report_calendar.py` 56 passed / 1 failed
  (`test_existing_reading_report_retains_bok_without_duplicates_or_input_changes`, 수정 전 main에서도 로컬에서 같은 실패). `check_refactor.py --scope report` 208 passed.
- 병합: 사용자 승인(21:46) 후 사용자가 직접 병합(자동 실행 안전장치가 Claude의 병합 클릭을 막음), `main` 7ae98021.

## 2. 재부팅 경과
- 21:26 재부팅(b71c6f7b): 시황 생성이 결과 없이 끝남. 21:48:55 재부팅(7ae98021): 21:52:27 시작한 시황 생성이 끊김.
  앱 로그 12:53:47 UTC "Pulling code changes from Github… Updated app!" — main에 PR #85가 병합되자 Streamlit Cloud가 자동 갱신하며 진행 중 실행을 끊음.
  21:31 실패도 PR #84 병합 시점과 겹침. 코드 버그가 아니라 **측정·확인 중 main 병합이 실행을 끊는 운영 조건**입니다.
- 21:56:15 재부팅(`main` dd6835e5, PR #83·#84·#85 포함) — 아래 3·4절의 기준 회차.
- 22:09:28 재부팅(같은 커밋) — 5절(오늘 점검 미계산 상태의 시황) 확인용.

## 3. 화면 확인 (21:56 재부팅분)
- **오늘 점검 미계산 경고(PR #84)**: 재부팅 직후 '✅ 오늘 점검 → 브리핑 보기: 시황'에서 21:57:29 노란 경고
  "오늘 점검이 아직 계산되지 않았습니다. 지금 생성하면 보유 종목 영향과 기업 실적 점검이 빠진 시장 전용 리포트가 됩니다. …" 확인(21:50:21 재부팅분에서도 같음).
  주의: 새 브라우저 세션(새로고침)에서는 저장된 오늘 점검 결과(22:05)가 복원되어 경고가 나오지 않습니다. 미계산 상태는 재부팅 직후에만 재현됩니다.
- **금통위 세 곳(22:01 생성 시황)**:
  - 중앙은행 공식 발표 표 첫 줄: `한국은행 금통위 | 인상 · 기준금리 3.00% → 3.25% | 2026-11-26 · 시각 미제공 | 한국은행 통화정책방향 결정문 확인 · Bank of Korea`(링크 nttId=11067084).
  - 빠른 요약 '오늘 달라진 점': "한국은행 금통위 기준금리 결정 발표 완료: 인상 · 기준금리 3.00% → 3.25%(2026-11-26 · 시각 미제공, 공식 결정문)".
  - 다음 일정 표 금통위 11-26 행: "공식 결과 확인 · Bank of Korea MPC · 결과 인상 · 기준금리 3.00% → 3.25% (공식 결정 근거)".
  - 운영 서버에서 한국은행 접속 정상(request_failed/http_ 사유 없음).
- **실적 연결 상태 첫 줄**: 1회차(22:01) "공식 발표 확인 20개 · 일부 조회 실패 24개(시간초과·한도·오류, 다시 생성 시 재조회) · 공식값 없음 19개";
  2회차(22:06) "공식 발표 확인 23개 · 공식값 없음 31개"(조회 실패 줄 없음). 점검 기업 78개.
- **한국 수출(KR_EXPORTS)**: "한국 수출 2026-10 전년비 · 발표 2026-11-16 (시각 미제공) Korea Customs Service (monthly final bulletin)" 93.9%,
  "컨센서스 미연결 · 이전 대비 +9.90%p", 이전 84.0%. 해석: 증가 지속·증가율 확대, 예상치 미연결로 서프라이즈 판단 보류.
- **거래소 달력(PR #85)**: 1회차 오늘 점검 100행(검토용 통합 CSV를 브라우저에서 읽음)에 "거래소 달력" 문구 0건. 데이터확인 행은 2개
  (0227L0.KS 신규 ETF 49일 이력, BRK.B 일봉 이력 조회 실패 · Yahoo 조회 제한).

## 4. 속도 조건 A (21:56:15 재부팅, 코드 dd6835e5, 한국 장 마감 후·미국 휴장일)
| 회차 | 작업 | 버튼 | 첫 결과 | 완료 | 앱 표시 |
|---|---|---|---|---|---|
| 1 | 오늘 점검 | 21:57:35.7 | 21:59:05.8 | 21:59:07.4 | 화면 처리 완료 · 87.8초 (측정 87.80초, 12:57:38→12:59:06 UTC) |
| 1 | 시황 생성 | 21:59:17.2 | 22:01:56.0 | 22:02:03.3 | 자동 시황 생성 125.0초 (12:59:30→13:01:35 UTC), 화면 처리 완료 · 22.0초 |
| 2 | 오늘 점검 | 22:04:26.6 | — | 22:05:43.7 | 화면 처리 완료 · 75.3초 (13:04:27→13:05:42 UTC) |
| 2 | 시황 생성 | 22:05:54.1 | 22:07:28.0 | 22:07:34.8 | 자동 시황 생성 63.7초 (13:06:06→13:07:10 UTC), 화면 처리 완료 · 19.3초 |
| — | 새로고침만 | 22:07:52.4 | — | 22:08:18.8 | 26.4초(첫 화면 '자산 현황' 표시·실행 종료까지, 계산 없음) |
- "직전 실행"은 화면 재표시 기록이라 위 계산 시간과 다릅니다(예: 1회차 시황 뒤 "interrupted · 135.0초 · briefing_render").
- 2회차 오늘 점검 직전에 CSV 다운로드 버튼을 눌러 재표시가 한 번 돌았습니다(측정에는 영향 없음, 기록만).
- 1회차 오늘 점검 앞 21:48 재부팅분(7ae98021): 101.6초. 로그에 "Yahoo metadata rate limited; pausing requests for 180s".

### 오늘 점검 진단 요약 (calculated 100행, 등록 87, 자동 돈흐름 후보 12)
- 1회차 단계: today_queue_render 87.8, summary 44.1, stock_signals 24.2, flow_refresh 19.4, flow_theme_prices 12.2, rs_price_history_3mo 9.6,
  flow_etf_prices 7.2, analyst_enrichment 6.5, price_history_10y 5.5, flow_context 5.0.
  분류 활성 시간(초): prices 58.1, external_data 26.7, indicators 20.8, decision 12.9 (작업 누적: prices 214.0, external 48.8, indicators 44.1, decision 21.0).
  상위 함수(누적): _compute_summary_item 132.5(100회), kr_history_http 98.4(384회), load_price_df 84.7(688), get_money_flow_ohlc 57.4(508),
  build_precision_multi_timeframe_pack 41.7(99), load_display_live_price 28.7, load_latest_price 28.7.
  카운터: kr_history_scope.lookup 413 · unique 384 · miss 384 · default_start 279 · explicit_start 134 · repeat/reuse 29, kr_history.request/response 384,
  yfinance_history.batch 6 · download 25, yahoo_chart.request 72 · response 66 · error 6.
- 2회차 단계: today_queue_render 75.3, summary 44.3, stock_signals 28.1, rs_price_history_3mo 9.0, flow_refresh 8.7, flow_context 5.8, flow_theme_prices 5.6.
  분류 활성: prices 53.1, indicators 18.4, decision 11.7, external_data 10.2. 상위: _compute_summary_item 125.6, build_precision_multi_timeframe_pack 36.9,
  load_display_live_price 26.7, load_price_frames_batch 25.2, _fetch_us_realtime_price 22.1. kr_history.* 요청 0(재사용), yahoo_chart.request 77 · error 8.
- 차이(87.8 → 75.3초)는 flow_refresh 19.4→8.7, flow_theme_prices 12.2→5.6, kr_history 384→0 요청 등 캐시 재사용에서 옵니다. 같은 프로세스의 두 번째 실행이므로 개선으로 보지 않습니다.

### 시황 생성 진단 요약
- 1회차 단계(중첩 없음, 초): macro_official 58.4, prices 26.9, assembly 18.9, persistence 15.0, articles 2.4, news 2.1, calculations 1.3.
  상위: earnings_discovery.worker 140.1(78), report_context 80.8, earnings_discovery.sec_rate_wait 54.7(107), earnings_official.request 51.7(154),
  earnings_discovery.http_get.dart 34.1(48), collect_report_earnings 25.9, earnings_filing_discovery 24.0, update_report_history 13.8.
  카운터: earnings_discovery.http.sec 107 · dart 48, workers 78, sec_release accepted 17 · issuer_mismatch 7 · fiscal_quarter_unavailable 5;
  bulletin_cache.exports miss 1 → listing/detail 각 1회; yfinance_history.batch 2 · download 9. degraded 없음.
- 2회차 단계: macro_official 23.9, prices 18.0, assembly 15.2, persistence 2.9, news 2.1. 상위: earnings_discovery.worker 80.9, sec_rate_wait 43.9(94),
  report_context 42.4, earnings_official.request 35.1(124). 캐시 적중: issuer_accounts 33 hit / 45 miss, dart_company 16 hit, bulletin exports reuse.
- 가장 긴 구간은 두 회차 모두 macro_official(실적 공시 탐색 포함)이고, 그 안에서 SEC 요청 간격 대기(sec_rate_wait)가 큽니다.

## 5. 오늘 점검 미계산 상태의 시황 (22:09:28 재부팅, 22:11 생성)
- 실적 연결 상태 첫 줄: "실적 점검 상태: 오늘 점검 미계산 · 보유·관심 종목 실적은 연결하지 않았습니다(확인 결과 0개가 아님). 오늘 점검 계산 후 다시 생성하면 연결됩니다."
- 마무리 절: "오늘 점검 미계산 · 보유 종목 영향 확인 불가(영향 없음이 아님). 오늘 점검 계산 후 다시 생성해 주세요."
- 조건 A를 깨지 않도록 측정 회차와 다른 재부팅에서 확인했습니다.
