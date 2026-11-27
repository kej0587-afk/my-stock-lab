# 기업 현금흐름 비교 계약 정리

## 원인과 변경 범위

- 시작 `e6ca8f30`, clean 작업 트리. fetch한 origin/main과 차이 없음.
- 수정 전 `tests/test_company_cash_comparison.py`: 25통과/1실패(3.82초).
  실패는 `app.py` 전체를 과거 `08b2ac4e`와 문자 단위로 비교하던 검사였다.
  이후 승인된 UI·조회·판정 입력 연결 변경까지 거부하므로 현금 비교의 회귀 근거가 되지 않는다.
- 이 한 검사를 직접 공시값/원문 복구/자료 부족/부적격 입력의 네 경우로 교체했다.
  실제 `render_company_deep_dive`를 선택 기업 조회 경로로 실행하며 외부 조회만 고정한다.
  분기자료·실적발표 각각1회, 다운로드 비교의 검증/보류 상태, 검토 전용·점수 제외,
  원자료 불변, 재무점수 map·오늘점검 표·서명 불변을 검사한다.
- 기존 `run_scenario`와 20개 시나리오를 재사용해 조회·표시 전후 **전체 판정 출력**을 비교한다.
  기존 absolute golden 검사는 별도로 유지한다. golden 재생성·실패 skip 없음.
- 판정 실행의 표시용 Yahoo 종목명 조회도 고정해 소켓 차단 상태에서 재현한다.
  운영 조회/캐시/TTL/점수/판정/금액 산식은 변경하지 않았다.

## 검증 범위

- Python3.11.9, 기존 설치 환경 사용.
- 수정한 파일29통과(20.90초).
- 현금 비교·현금 해석·기업 심층분석·SEC 복구·판정 전체 출력 회귀140통과(26.54초).
- `check_refactor --scope decision`: **1669통과/0실패/0skip**(162.589초),
  `cache/refactor_checks/decision_s3fgo382`. 기존 전체 출력 golden 포함, 기준값 갱신 없음.
- 기존 전체의 실패16개 재실행: **7통과/12실패**(50.96초). 교체1건이4상태로 확장되어19개다.
  실제 남은 실패는 A11/E1. 이번에 전체 suite를 다시 실행한 결과는 아니다.
- 증거는 ignored `cache/resume_20261127/cash_contract.xml/log`,
  `cash_remaining.xml/log`, `cash_decision_gate.log`에 보관한다.
- 테스트·문서만 변경하므로 이번에 운영 화면을 새로 열거나 재부팅하지 않았다.
  기존 #121 차트 하단 운영 확인 기록은 유지하며 새로운 운영 검증으로 주장하지 않는다.

## 다음 한 건

`tests/test_company_market_reading.py::test_app_adapter_restores_only_current_company_context_change`.
시장 맥락 연결이 점수·판정에 들어가지 않는 계약을 확인하고 과거 app 전체 AST 동일 요구를
해당 연결의 실제 입력/출력 검사로 좁힌다. 나머지 A와 연구 스냅샷 E는 이후 순서로 유지한다.
