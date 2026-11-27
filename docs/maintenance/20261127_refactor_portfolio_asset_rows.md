# 분리: build_portfolio_analysis_report의 보유자산 행 계산 (2026-11-27)

ROADMAP 리팩토링 후보 표의 app.py 함수 중 첫 한 책임. 계좌 금액·비중·위험 계산과 표시 문구는 그대로다.

## 무엇을 옮겼나

- `app.build_portfolio_analysis_report`(411줄)의 보유자산별 반복문(전체·운용 비중, 목표비중 차이, 평가손익, 전략 표 행,
  가격 이력 로드와 기간수익률·연환산변동성·MDD, 가격 부족 메모)을 `_portfolio_asset_rows(active_df, total_asset, active_value,
  usdkrw, period, analysis_start_date, notes)`로 옮겼다. 반환: `asset_rows, strategy_rows, price_series`. 403줄이 됐다.
- 코드 줄은 그대로 옮겼다. 가격 부족 메모는 같은 `notes` 리스트에 같은 순서로 추가된다. `load_price_df`는 같은 모듈 전역을 부르므로
  테스트의 monkeypatch도 그대로 적용된다.
- 이 함수 본문을 과거 커밋과 비교하는 테스트는 없다(호출 테스트 2개 파일만 있음).

## 확인 (기준 main `e15570b7`, 두 트리 동시 실행)

| 확인 | main 원본 | 분리본 |
| --- | --- | --- |
| `check_refactor.py --scope all` | 2 실패 / 2,495 통과 | 같은 목록 |
| 전체 테스트 | 22 실패 / 10,202 통과 | 같은 목록 |
| 고정 합성 보유 5가지(9종목 혼합: 코어·스윙·레버리지·국내·이력 15일·조회 예외·이력 없음·대기자금 / 분석 시작일 지정 / 1종목 / 빈 표 / None) 전체 반환값(지표·자산표·메모·상관·곡선·리스크기여) | 기준 | 5건 정규화 JSON 동일 |
| pyflakes | 90개 | 같은 90개(줄 번호 제외) |

비교 도구: `scripts/portfolio_analysis_parity.py`.

운영 확인: (병합·재부팅 뒤 기록. 포트폴리오 분석 화면의 위험도·자산표·메모가 이전과 같은지)

## 다음 후보

같은 함수의 위험지수 구성(변동성·MDD·집중도·상관·레버리지·대기자금 점수와 판단근거)과 위험 메모 블록.
