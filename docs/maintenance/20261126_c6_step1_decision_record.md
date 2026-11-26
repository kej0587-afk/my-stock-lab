# C-6/C-11 1단계: 공통 월적립 계산 + DecisionRecord (2026-11-26)

사용자 결정(2026-11-26 09:14 KST) 8항의 1단계. **결과는 바꾸지 않는 구조 정리**입니다.

## 바뀐 것
- `stock_lab_core/decision_record.py` (신규): 종목·계좌범위·입력시점별 공통 판정 레코드.
  candidate / engine(원판정) / post(MTF·레버리지·패턴 후처리) / market / gate / sizing / monthly / leverage_l3 /
  tech_review(표시 전용)를 구역별로 분리 보관. 캐시 키 = 계좌범위·보유상태·가격 기준일·매크로 기준일·정책 버전·출처.
  정밀관측소 수동 가격은 `precision_manual` 출처로 따로 저장되어 정상 레코드를 덮지 않음.
- 월적립 배율은 원판정(engine) 코드에서만 읽음(`engine_monthly_multiplier`). 후처리 코드·t_mult는 사용하지 않음.
- `compute_monthly_plan` (monthly_rebalance.py): 월적립 계산기와 L3가 같은 함수 결과를 사용. 기존
  `build_rebalance_plan` 결과와 동일(테스트로 고정).
- app.py: Today 요약·자산관리·정밀관측소가 계산 후 레코드를 `st.session_state["_decision_records"]`에 저장만 함.
  `_compute_summary_item` 반환값, 판정코드, 게이트, 사이징, 배율, L3 조건은 변경 없음. 저장 실패는 로그만 남김.

## 확인
- 신규 테스트 `tests/test_decision_record.py` 8건 통과(입력 불변, 수동가격 분리, 캐시 키, 계좌범위 불일치 시 미반환,
  원판정 배율, 월계획 = 기존 계산기 행).
- 전체 `pytest tests`: main 33 실패 / 브랜치 33 실패, 실패 목록 동일. `check_refactor --scope all`: main과 같은 2건.
- 고정 AST 테스트는 `tests/decision_record_ast_contract.py`로 레코드 저장 추가분만 제거한 뒤 기존 기준과 비교.

## 운영 확인
- 2026-11-26 11:19 KST 재부팅(PR #57 병합 후). 11:20–11:25 KST 확인, 모든 화면 예외 없음:
  - 자산 현황: 기술적 타점계산 실행 정상.
  - 오늘 점검: 관심/보유 종목 전체 계산 완료.
  - 월 적립 리밸런싱 계산기: 공통 함수 경유로 배분 계획·레버리지 현황 정상 표시. 배포 전 화면 숫자를 따로 저장하지 않아
    화면끼리의 전후 비교는 하지 않았고, 동일성은 `compute_monthly_plan == build_rebalance_plan` 테스트로 확인.
  - 정밀관측소 GOOGL: 실행 보류 · 상위 시간대 추세훼손, 기술검토 v2 CAUTION (C-5 운영 확인 때와 같음).
