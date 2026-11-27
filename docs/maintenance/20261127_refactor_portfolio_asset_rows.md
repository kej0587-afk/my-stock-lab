# 분리: build_portfolio_analysis_report의 보유자산 행 계산 (2026-11-27)

ROADMAP 리팩토링 후보 표의 app.py 함수 중 첫 한 책임. 계좌 금액·비중·위험 계산과 표시 문구는 그대로다.

## 무엇을 옮겼나

- `app.build_portfolio_analysis_report`(411줄)의 보유자산별 반복문(전체·운용 비중, 목표비중 차이, 평가손익, 전략 표 행,
  가격 이력 로드와 기간수익률·연환산변동성·MDD, 가격 부족 메모)을 `_portfolio_asset_rows(active_df, total_asset, active_value,
  usdkrw, period, analysis_start_date, notes)`로 옮겼다. 반환: `asset_rows, strategy_rows, price_series`. 340줄이 됐다.
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

운영 확인(PR #102, 회사 PC, 분석 기간 1y): 13:00:15 KST 실행값과 13:01:50 재부팅(main `1e71b0af`) 뒤 13:03:17 실행값 비교. 위험지수·등급('공격/위험 86/100'), 변동성·MDD·상위3·대기자금, 결론 줄 문자 그대로 같음. 자산별 표 14열·6행, 순서·티커·버킷·목표비중·MDD·데이터 같음, 비중·수익률·변동성만 한국 장중 1분 시세 변동만큼 차이(비중 ≤0.005%p). 위험 메모 4행 같음(Sharpe −0.65→−0.64, 시세 변동). 주의: 13:00 실행은 #102 병합(12:58) 뒤라 이전 코드였는지 확정할 수 없다. 이전 코드와의 동등성 근거는 위 합성 계좌 비교다.

## 2단계: 위험지수 구성 (2026-11-27)

- 위험지수 0~100, 등급·색, 6개 영역 점수(변동성·MDD·집중도·상관관계·레버리지·대기자금)와 판단근거 계산을
  `_portfolio_risk_components(portfolio_vol, portfolio_mdd, top1_weight, top3_weight, hhi, avg_corr, leverage_summary, reserve_summary,
  reserve_target_weight)`로 그대로 옮겼다. 반환: `risk_index, risk_grade, risk_color, risk_components, reserve_gap, leverage_component`.
  `build_portfolio_analysis_report` 340 → 296줄. 점수 계수·상한·문구 변경 없음.
- 확인(기준 main `1e71b0af`, 두 트리 동시): check_refactor all 2 실패 / 2,495 통과 같은 목록, 전체 테스트 22 실패 / 10,202 통과 같은 목록,
  합성 계좌 5건 전체 반환값 동일(위험지수 80.31 포함), pyflakes 같은 90개.
- 운영 확인(PR #103, 회사 PC): 13:09:33 KST 값(1e71b0a 세션, #103 병합 13:08 뒤라 이전 코드 확정 불가)과 13:09:58 재부팅(main `ea090516`) 뒤
  13:11 값 비교. 위험도 '공격/위험 86/100', 결론 4줄, 위험 구성 6행(집중도 25.0·MDD 21.1·변동성 18.0·레버리지 15.9·상관 6.2·대기자금 0.0)과
  판단근거, 위험 메모 4행, 10년 작전 적합도 5행 모두 글자까지 같음.

## 3단계: 위험 메모 (2026-11-27)

- 집중도·변동성·낙폭·상관·레버리지·대기자금·Sharpe·CVaR·리스크기여도 기준 메모를 `_add_portfolio_risk_notes(notes, …)`로 그대로 옮겼다
  (같은 `notes`에 같은 순서로 추가). `build_portfolio_analysis_report` 296 → 266줄. 기준값·문구 변경 없음.
- 확인(기준 main `ea090516`, 두 트리 동시): check_refactor all 2 실패 / 2,495 통과 같은 목록, 전체 테스트 22 실패 / 10,202 통과 같은 목록,
  합성 계좌 5건 전체 반환값 동일(메모: 가격 데이터·레버리지·위험대비수익 / 집중도·변동성·낙폭·방어력·위험대비수익 포함), pyflakes 같은 90개.
- 운영 확인: 병합 전 기준값(13:12:39 KST, main `ea090516`, 1y): 위험 메모 4행(집중도 2·레버리지·위험대비수익 Sharpe −0.64). 13:19:04 KST 재부팅(main `7eaa5b9c`) 뒤 13:20 실행값과 표 원자료(arrow, 1,864바이트)를 대조해 바이트까지 일치(4행·순서 같음). 병합 전 이전 코드 기준이라 이번 단계는 운영에서도 이전 코드와 같음이 확인됐다.

## 다음 후보

이 함수는 266줄로, 남은 부분은 데이터 범위 집계·포트폴리오 수익률 지표 계산·결과 묶음이다. 다음은 수익률 지표 계산(포트폴리오 곡선·VaR·벤치마크) 또는
ROADMAP 표의 다른 함수(`render_entry_execution_plan`, `render_image_theme_flow_section`).
