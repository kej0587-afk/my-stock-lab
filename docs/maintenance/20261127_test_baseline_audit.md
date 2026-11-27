# 현행 main 테스트 기준 점검

## 기준 실행

main e77b13bc (운영 코드는 d9cbac8a와 동일), UI 시안 적용 전 실행:
`python -m pytest tests -q --tb=short --junitxml=cache/pytest_main_20261127.xml`

10,070 pass / 207 fail / 4 skip, 720.97초. ignored cache의 과거 worktree를 수집하지
않도록 반드시 `tests` 경로를 지정한다. 검증 중 기존 사용자 worktree는 변경하지 않았다.

로컬 venv는 pandas 3.0.2/numpy 2.4.4로 requirements(pandas<3/numpy<2) 밖이었다.
환경 전체를 바꾸지 않고 cache 아래 pandas 2.3.3/numpy 1.26.4를 설치해 해당 실패만 재실행:

| 분류 | 건수 | 재확인 |
|---|---:|---|
| `closed_daily_frame`의 read-only array 예외 | 177 | 지원 버전에서 전부 통과(40.65초) |
| dtype/예외 등 나머지 중 지원 버전에서 통과 | 11 | 통과 |
| 계속 실패 | 19 | 아래 분류; 일괄 golden 갱신하지 않음 |

이는 전체 suite를 지원 버전으로 다시 실행한 결과가 아니라 **실패했던 207건의 재실행**이다.
yfinance 등 다른 환경 차이가 있으므로 전체 운영 환경 호환 완료라고 주장하지 않는다.

## 계속 실패한 19건

- 13건: 과거 커밋의 app 전체 AST/본문 해시와 일치 요구. 이후 승인된 기능 변경을
  함께 금지하는 오래된 구조 비교다. 기존 golden을 새 코드로 갈아끼우지 않고,
  각 보호 대상 계산/판정 계약으로 좁히는 후속 검토가 필요하다.
- 3건: BOK/리포트 순서·표 위치·RAM 보유 표의 과거 섹션 위치 요구. 실제 누락인지
  새 섹션 이동인지 각 출력 계약을 대조해야 한다. 이번에 성공 처리하지 않았다.
- 3건: 수급 저장의 `component` 계측 래퍼, Customs 외 MOTIR fallback 요청,
  연구 비용 widget 설정 보존. 코드를 읽어 현재 동작을 확인하고 이 세 테스트만 수정.

운영 함수/투자 임계값/출력 금액은 이 테스트 정리에서 변경하지 않는다.
decision 회귀 1,669개와 차트/관찰 34개는 별도로 통과했다.

## 재현 방법

`python -m pytest tests/test_soxl_short_observation.py tests/test_public_market_flow_history.py tests/test_customs_connect_retry.py -q`
실행: 74개 통과(22.22초). 이 묶음은 로컬 pandas 3 환경에서도 통과했다.
일반 전체 검증은 `python -m pytest tests -q`. 기존 실패를 감추는 xfail/skip 추가 없음.
남은 16건은 새 입력과 실제 표시를 대조한 뒤 하나씩 정리한다.
