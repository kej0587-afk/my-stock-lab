# 시황 개편 2단계: 매크로 표를 금리·환율·원자재·심리로 나누기

작성 2026-11-24 KST · 시작 `fa2494fb` · 근거: 2026-11-24 통합 시황 개편 요청서 B5~B8

## 범위

독자용 보고서 '매크로' 구역의 단일 표를 티커 기준으로 네 묶음으로 나눴다.
행은 기존 '지수·매크로 한눈에' 표에서 **그대로 복사**한다. 숫자, 단위, 비교 기준,
기준일, 출처, 점수, 게이트, 수집기, TTL은 바꾸지 않았다.

| 묶음 | 티커 |
| --- | --- |
| 금리 | ^TNX, ^TYX |
| 환율·달러 | USDKRW=X, DX-Y.NYB |
| 원자재 | CL=F, BZ=F, NG=F, GC=F, SI=F, HG=F |
| 심리·변동성 | ^VIX, ^MOVE |
| 기타 | 위 목록에 없는 행(새 지표가 추가돼도 사라지지 않게) |

중앙은행 공식 발표와 금리·에너지 재료는 기존처럼 표 아래에 둔다. 구역 제목('## 매크로')은
그대로라 부록 중복 제거(`MOVED_SECTIONS`)와 관측실 연결 상태 판정은 영향이 없다.

## 검증

- report 게이트: 수정 전 208건 통과(`report_vl1comgf`, main `fa2494fb` 작업 사본), 수정 후 208건 통과(`report_zrtlwe3l`).
- 보고서 관련 묶음(test_report_*, test_bok_report_calendar, test_market_memo*): 1608 통과·1 실패.
  실패는 기존과 같은 `test_bok_report_calendar::test_existing_reading_report_retains_bok_without_duplicates_or_input_changes`.
- 신규 테스트 `test_macro_rows_are_grouped_by_ticker_without_changing_cells`: 묶음 순서, 모든 행이
  한 번씩 그대로 남는지, 모르는 티커가 '기타'에 남는지 확인.
