# A-4 PROFIT_TAKE_REVIEW 분류·월적립 배율 정정 (2026-11-25)

## 결론

- `PROFIT_TAKE_REVIEW`("🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토)")는 **현재 엔진에서 도달할 수 없는 코드**다.
  그래서 분류나 배율을 고쳐도 지금 나오는 판정·게이트·매수금액·월적립 금액은 하나도 바뀌지 않는다(실제 재생 차이 0).
- 문제는 코드 표에만 있다. 라벨의 "분할" 때문에 판정분류가 `buyish`이고, 월적립 배율도 core 1.0 / swing 1.0(매수 방향)이다.
- 권장: 판정분류를 `caution`(보유관리)으로, 월적립 배율을 core·swing 0.0으로 고친다. 지금 결과는 그대로이고,
  나중에 이 경로가 열려도 익절 신호가 매수로 읽히지 않는다.
- 별도로 발견: 같은 익절 조건에 해당하는 실제 보유 상태 중 일부가 지금 월적립 1.0배(추가매수 방향) 판정을 받는다(§4).
  이것은 A-4 범위가 아니라 C 후보로 따로 적었다.

## 1. 어디서 쓰이나

| 위치 | 사용 |
| --- | --- |
| `decision_policies.select_holding_decision` 첫 분기 | 유일한 생성 위치. 조건: 코어 ETF 아님 + MFI ≥ 80 + %B > 0.9 + 평단 대비 +20% 초과 |
| `decision_engine.DECISION_GROUP_BY_CODE` | `buyish` (B-2에서 옛 라벨 추론값 그대로 고정) |
| `rebalance_multiplier_table.MULTIPLIER_BY_CODE` | core 1.0 / swing 1.0 / leverage 0.0 (옛 라벨 파서와 같은 값) |
| `decision_behavior_groups` | 5. 보유 유지·비중·익절 (표시용) |
| `today_queue` 실행메모 | 라벨에 "익절"이 있으면 다른 조건이 없을 때 "익절/추적" |
| 정밀관측소 · 자산현황 | 라벨을 그대로 표시, 자산현황 월적립 계산은 위 배율 사용 |
| 판정 매뉴얼 표 | "익절 타이밍" 행으로 설명 |

같은 조건을 쓰는 별도 표시값 `profit_take_signal`(결과 dict)은 판정과 무관하게 계산되고, AI 해석 프롬프트의 "익절 시그널" 한 줄에만 쓰인다.

## 2. 왜 도달할 수 없나 (4번 질문)

`select_portfolio_followup_decision`에서 보유 종목은 현재가 > 평단 × 1.02이면 `select_profitable_holding_decision`으로 가고,
그렇지 않을 때만 `select_holding_decision`으로 간다. 그런데 `PROFIT_TAKE_REVIEW`는 `select_holding_decision` 안에서
평단 대비 +20% 초과를 요구한다. 두 조건은 같은 현재가·평단으로 계산되므로 동시에 참일 수 없다.

재생 확인: 33개 종목 2015~2026, 5거래일 간격, 평단 대비 +25% / +50% / +100% 보유 가정에서 익절 조건이 참인 상태 473개 × 3 = 1,419건.
`PROFIT_TAKE_REVIEW`는 0건이었다.

## 3. 현재 값과 수정안 (2·3·5번 질문)

도달 불가라 실제 상태에서는 비교할 수 없어서, 시뮬레이션으로 경로를 강제로 열었다(엔진을 임시로 바꿔 실행, 저장소에는 넣지 않음).
열리면 147건이 바뀐다. 지금은 S_GRADE_OVERHEAT_WAIT 78건, OVERHEAT_WAIT 69건을 받는 상태다.

| 항목 | 실제 현재 (경로 닫힘) | 열렸을 때·현행 표 | 열렸을 때·안 1 (분류만) | 열렸을 때·안 2 (분류+배율) |
| --- | --- | --- | --- | --- |
| 판정코드 | S급 과열 대기 78 / 과열 대기 69 | PROFIT_TAKE_REVIEW 147 | 같음 | 같음 |
| 엔진 판정분류 | neutral 78 / buyish 69 | buyish 147 | caution 147 | caution 147 |
| Today 판정분류 | buyish 96 / caution 30 / neutral 21 | buyish 123 / caution 24 | caution 147 | caution 147 |
| 최종읽기 | 눌림대기 141 / 돌파대기 6 | 같음 | 같음 | 같음 |
| 실행게이트 | 대기/관찰 138 / 방어우선 9 / 실행가능 0 | 같음 | 같음 | 같음 |
| 월적립 배율 core / swing | 0.25 / 0.25 | **1.0 / 1.0** | **1.0 / 1.0** | 0.0 / 0.0 |
| 사이징 안내(MA5 1차 추가) | 78건 | 0건 | 0건 | 0건 |
| buy_amt(목표비중 부족분) | 147건 > 0 | 같음 | 같음 | 같음 |

- 실행게이트는 세 경우 모두 같다. 게이트는 판정분류보다 R/R·과열 문구로 먼저 대기를 건다(대표 근거: "R/R 목표가가 투영상단 · 과열/추격금지").
- `buy_amt`는 목표비중 부족분 계산값이고 매수 허용이 아니다. 허용 여부는 게이트가 정한다.
- 현행 표 그대로 경로가 열리면 오히려 월적립 배율이 0.25 → 1.0으로 올라간다. 이것이 "익절 신호가 매수로 읽히는" 실제 위험이다.

## 4. 보유 시나리오에서 바뀌는지 (6번 질문)

- 수정안 1·2 모두 **현재 운영 결과는 바뀌지 않는다**. 코드가 생성되지 않으므로 월적립 금액·매수 허용·게이트 차이 0.
- 참고(별도 C 후보): 같은 익절 조건 상태 473개 중 52개(LEADER_MA5_PULLBACK_ENTRY 35, HOLDING_QUALITY_RECOVERY_CANDIDATE 16,
  HOLDING_QUALITY_RECOVERY_SCOUT 1)는 지금 월적립 1.0배를 받고, 그중 1개(000270.KS 2019-11-22)는 게이트가 실행가능이다.
  MFI ≥ 80·%B > 0.9·수익 20% 이상인데 추가매수 방향으로 읽히는 경우라 C-6(월적립 배율) 또는 익절 경로 재설계에서 다룰 항목이다.
  이번 A-4에서는 손대지 않는다.

## 5. 테스트 영향 (7번 질문)

수정안 2를 임시로 적용해 decision 게이트를 돌렸다(되돌림): 1657 passed / 3 failed.
- 기존 실패 1건(`test_extracted_policies_preserve_all_original_conditions_and_literals`) 그대로.
- 새 실패 2건은 B단계 고정 테스트가 의도대로 변화를 잡은 것: `test_every_emitted_label_keeps_its_old_group`,
  `test_every_known_label_gives_the_old_multiplier`. 승인되면 이 두 테스트에 PROFIT_TAKE_REVIEW 한 건만 문서화된 예외로 넣고,
  새 값을 확인하는 테스트를 추가한다.
- 골든 스냅샷·회귀 테스트는 영향 없음(이 코드를 쓰는 테스트 없음). 재생 parity도 차이 0이 예상된다(병합 전 다시 확인).

## 6. 결정할 것

1. 안 2 (권장): 판정분류 caution + 월적립 배율 core·swing 0.0.
2. 안 1: 판정분류만 caution, 배율은 1.0 유지(경로가 열리면 매수 방향 배율이 남음).
3. 보류: 코드 표 그대로 두고, 익절 경로 재설계(C)에서 함께 정한다.

경로 자체를 여는 것(수익 중 과열 보유 종목에 익절 검토를 실제로 띄우는 것)은 판정이 바뀌는 정책 변경이라 이번 선택지에 넣지 않았다.

## 7. 사용자 결정과 반영 (2026-11-25)

사용자 결정: 안 2. 분류와 미래 경로 안전성을 바로잡는 구현 오류 수정으로 처리한다.

- `decision_engine.DECISION_GROUP_BY_CODE["PROFIT_TAKE_REVIEW"]` = `caution`
- 행동그룹: 5. 보유 유지·비중·익절 (B-1 표 그대로)
- 월적립 배율: `rebalance_multiplier.POLICY_MULTIPLIER_BY_CODE`에서 core 0 / swing 0 / leverage 0(기존 값 유지).
  라벨 문구와 관계없이 코드로 적용한다.
- 고정 테스트 두 개에 이 코드만 승인된 예외로 넣고(`APPROVED_CHANGES`, `POLICY_MULTIPLIER_BY_CODE`), 새 값을 확인하는 테스트를 추가했다.
- §4의 "익절 조건인데 다른 코드로 1.0배를 받는 52개 시점"은 이번 수정에 넣지 않았다. C-12로 검증 계획에 기록했다.

검증:
- decision 게이트: 1661 passed / 1 failed (기존 실패 `test_extracted_policies_preserve_all_original_conditions_and_literals`).
- parity 재생(41,391행, 2015~2026, 10거래일 간격): 변경 전 main 결과와 바이트 단위로 같다(도달 불가 코드라 예상대로 차이 0).
