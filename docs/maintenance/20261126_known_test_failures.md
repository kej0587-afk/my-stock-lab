# 기존 테스트 실패 33건 영향도 분류 (2026-11-26)

사용자 작업 순서 2번: "실제 시황·판정·계좌 금액에 영향을 주는 것부터". 각 실패를 직접 실행해 원인을 확인했습니다.

## 1. 실제 판정에 영향 → 수정함 (11건 해소)
| 테스트 | 원인 | 사용자 영향 | 조치 |
|---|---|---|---|
| `test_fresh_quote_summary.py` 11건 | ① 테스트가 app 함수만 떼어 실행하면서 `selection_basis`를 넣지 않아 NameError(테스트 문제) ② 그 뒤에 드러난 **실제 버그**: 오늘 점검의 병렬 작업이 재부팅 직후 한국 거래소 달력(XKRX)을 동시에 처음 만들면 `ValueError(Length of values …)`가 나서 "거래소 달력 조회불가" → 가격신선도 `unknown` → 게이트가 **데이터확인**으로 막음 | 재부팅 직후 첫 오늘 점검에서 한국 종목 일부가 "데이터확인 · 거래소 달력 조회불가"로 보일 수 있음(두 번째 계산부터 정상) | `report_eventstudy._exchange_schedule`을 잠금으로 직렬화, 동시 호출 회귀 테스트 추가. 테스트 하네스에 `selection_basis` 추가. 11건 모두 통과(원래의 완전 일치 비교 그대로) |

## 2. 시황 표시 문구·배치가 바뀐 뒤 갱신되지 않은 테스트 (판정·금액 영향 없음)
| 테스트 | 원인 |
|---|---|
| `test_bok_report_calendar` (상세 근거 끝 문단) | 보고서 뒤쪽 순서가 바뀌어 원본 문단이 상세 근거 끝에 있지 않음 |
| `test_report_evidence` ('원자료' 단어) | 자동점검 표에 "공급 원자료 기준" 문구 추가 |
| `test_summary_ownership_restore` (RAM 행 위치) | 보유 표가 '내 보유 종목 영향' 밖(포트폴리오 구역)으로 이동. RAM 행 자체는 "데이터부족, 현재비중·일간 기여 미연결"로 정상 표시 확인 |
| `test_precision_narrative` (해시) | 정밀관측 서술 문구 변경 |
| `test_soxl_short_observation` | 판정은 같고, 화면 위젯 기본값(`short_evidence_v1_SOXL_cost`)이 세션에 남는 것만 다름 |
| `test_customs_connect_retry` (요청 3→5회) | 한국 수출 자료에 산업통상부(motir.go.kr) 보조 경로가 나중에 추가됨. 시간 초과 점검(속도 측정)과 함께 볼 항목 |

## 3. app.py 함수 고정 스냅숏 (승인된 변경 뒤 미갱신, 영향 없음) — 13건
`test_company_cash_comparison`, `test_company_market_reading`, `test_dart_evidence_view`, `test_guard_duplicate_inputs`,
`test_leveraged_product_view`, `test_msft_ir_review`, `test_sec_annual_review_view`, `test_sec_quarter_review`,
`test_summary_wait_diagnostics`, `test_today_queue_view_refactor`, `test_today_quote_performance`,
`test_public_market_flow_history`(app 안 호출 위치 탐색 StopIteration), `test_sec_cash_recovery::…default_market_collection_unchanged`.
app.py 함수 본문을 특정 커밋과 통째로 비교하는 테스트라, 이후 승인된 A~C 단계·월적립 변경으로 달라진 것입니다.

## 4. 테스트 구성·환경 문제 (영향 없음) — 3건
| 테스트 | 원인 |
|---|---|
| `test_sec_cash_recovery::test_conflicting_tables_with_same_header_are_held` | 테스트가 HTML 문서 두 개를 이어 붙였는데 lxml이 두 번째 문서를 버림. 같은 문서 안에 충돌 표를 넣으면 코드는 정상적으로 보류(None) 확인 |
| `test_decision_refactor_parity` (AST 해시) | `decision_policies.py`는 10-14 이후 변경 없음. Python 버전별 `ast.dump` 형식 차이로 보임 |
| `test_market_observation_connected` | 실제 네트워크가 필요한 테스트(오프라인 환경에서 의도적으로 실패) |

## 남은 일
- 2·3절 테스트는 기대값 갱신 또는 비교 범위 축소로 정리(동작 변경 없음). 4절은 테스트 수정.
- 전체 테스트 기준: 33건 → 22건(1절 11건 해소).
