# 남은 실패 테스트 분류와 큰 함수 정리 순서 (2026-11-27, 우선순위 5번 셋째 건)

최종 갱신: [남은 계약 정리·연구 재생 복구](20261127_remaining_contracts_complete.md).
`62f6c1a1`, Python3.11.9 전체 suite **10,382통과 / 0실패 / 1skip**, 756.25초.
subtest18통과, XML failures/errors0. skip은 기존 markdown_it 선택 의존성 미설치.
시작 시 남은11건(A10/E1) 전부 해결; 아래의 모든 실패 수와 다음 작업은 과거 기록이다.
현재 다음 한 건은 HANDOFF의 국내 가격 이력 실요청 계측. 운영 점수·판정·TTL 유지.

최신: [기업·시장 연결 계약](20261127_company_market_contract.md) 정리 후 **11실패(A10/E1)**.
기존 실패16개를 재실행해12통과/11실패(두 계약이 각각4/5상태로 확장). 새 전체 suite 수치 아님.
다음 한 건은 dart_evidence_view의 app 전체 AST 일치 검사. 아래12/13건은 과거 기록.

최신: [현금 비교 계약](20261127_cash_comparison_contract.md) 정리 후 **12실패(A11/E1)**.
기존 실패16개를 재실행하여7통과/12실패(교체1건이4상태로 확장). 새 전체 suite 수치가 아니다.
다음 한 건은 company_market_reading의 과거 app 전체 AST 일치 검사.

최신 재개: [B/C 정리·재집계](20261127_test_resume_bc.md). Python3.11 지원 환경 main339baf81에서
전체16실패(C 단독 실패/전체 통과), 해당16개 수정 후 재실행13실패(A12/E1).
아래19/17은 이전 실행 기록이며 최신 실패 수로 사용하지 않는다.

## 실행 조건
- 전체 suite: `main` ded72c8b(#122 병합 직후), python 3.12 venv + pandas 2.3.3 / numpy 1.26.4,
  `python -m pytest tests -q -p no:cacheprovider --tb=line -rf`.
- 결과 **10,310 통과 / 20 실패 / 1 skip, 608초**.
- 같은 20건을 오늘 작업 시작 시점 `a3e027a7`에서 다시 실행하니 19건 실패·1건 통과.
  - HANDOFF의 "남은 16건"은 이미 낡은 숫자였다. 시작 시점 기준선은 19건이다.
  - 새로 생긴 1건은 `test_report_energy_basis::test_collection_adds_daily_only_no_live_rotation_or_macro_changes`.
    #122의 관측실 FRED 조회가 네트워크 금지 테스트에 걸렸다.
  - 테스트에서 관측실 로더를 대체하고, 8개 지표가 모두 그 로더를 거치는지와 0으로 채우지 않는지를 확인하도록 고쳤다(통과).
- 이 문서는 분류만 한다. 남은 19건은 숨기거나 skip하지 않았다.

## 남은 19건 분류

| 분류 | 건수 | 테스트 | 실패 내용 | 정리 방향 |
|---|---:|---|---|---|
| A. 과거 커밋 app 함수 전체 AST·본문 해시 일치 | 12 | company_cash_comparison, company_market_reading, dart_evidence_view, guard_duplicate_inputs, leveraged_product_view, msft_ir_review, precision_narrative, sec_annual_review_view, sec_quarter_review, summary_wait_diagnostics, today_queue_view_refactor, today_quote_performance | `parse_holdings…` 등 app 함수 묶음의 AST 덤프나 sha가 기준 커밋과 다름 | 승인된 이후 기능 변경까지 막는 구조 비교. 각 테스트가 지키려던 함수(판정·점수·주문 금액)만 남기고, 그 함수의 입력→출력 golden으로 좁힌다. golden을 새 코드로 일괄 교체하지 않는다. |
| B. 리포트 섹션 위치·문구 | 3 | bok_report_calendar, report_evidence(front order), summary_ownership_restore(RAM 보유 표) | 과거 섹션 순서·표 줄 위치를 찾지 못함(`substring not found`, `'RAM(RAM) \|' in …`) | 통합 시황 개편(섹션 이동·표 위치 안내)과 대조해서, 실제 누락인지 위치 이동인지 하나씩 확인. 이동이면 새 위치 계약으로, 누락이면 코드 수정. |
| C. 네트워크 금지 테스트에 새 조회 경로 | 1 | market_observation_connected | `Connected observation tests are offline` (socket 연결 시도) | 어느 조회가 소켓을 여는지 찾아서 그 로더만 대체. #122 FRED 조회도 같은 경로를 탈 수 있다. |
| D. 데이터 판단 계약 | 2 | sec_cash_recovery(같은 머리글 충돌 표는 보류), sec_cash_recovery(review-only·수집 키) | 충돌 표에서 값이 None이어야 하는데 계산됨 / 수집 키 목록 달라짐 | 충돌 표 보류가 깨졌다면 잘못된 숫자를 만들 수 있으니 **먼저** 본다. |
| E. 고정 스냅샷 재생 | 1 | soxl_intraday_research::replay_frozen_snapshot | 재생 결과 sha 불일치 | 스냅샷 생성 이후 연구 규칙·입력 변경 여부 대조. 연구 전용이라 운영 영향 없음. |

## 정리 순서 (제안)
1. D(SEC 현금 회복 충돌 표 보류). 숫자를 지어낼 위험이 있는 유일한 묶음이다.
2. B(리포트 위치 3건). 사용자 화면 누락 여부와 직결된다.
3. C(오프라인 테스트 1건).
4. A(구조 해시 12건). 함수별 입출력 golden으로 바꾼다. 큰 함수 분리와 같이 진행한다.
5. E(연구 스냅샷 1건).

## 큰 함수 정리 순서 (오늘 점검·시황 실측과 같이 봄)
같은 조건 측정(→ [속도 기록](20261127_perf_same_condition_rounds.md))에서 누적 시간이 큰 경로부터 보면:
1. `_compute_summary_item`(오늘 점검 102회 · 누적 139~164초): 종목별 판정 묶음.
   가격 로드·지표·판정·표시 문구를 나누면 A 묶음 해시 테스트를 함수별 계약으로 옮기기 쉽다.
2. `build_today_market_guard`(약 280줄): 지역 점수·돈흐름·매크로·이벤트·포트폴리오 점수가 한 함수에 있다.
   6번 모의 비교에서 쓴 재현 게이트와 같은 단위(지역/돈흐름/매크로)로 나눌 수 있다.
3. 리포트 `collect_report_context`의 매크로·공시·수급 구간(47~55초): 공시 탐색 대기가 대부분이라
   함수 분리보다 대기 축소가 먼저다.
4. `render_entry_execution_plan`: 1번 작업에서 출처·금액 분리가 붙어 길어졌다. 계산과 표시를 나눈다.
각 단계는 기존 결과와 같은지(같은 입력 → 같은 행·금액)를 먼저 고정한 뒤 옮긴다. 판정 규칙은 바꾸지 않는다.

## D 정리 결과 (2026-11-27 19:0x KST)
- `test_conflicting_tables_with_same_header_are_held`: **실제 결함.** 설치된 lxml 5.4(libxml2)는 첫 `</html>` 뒤를 버린다.
  그래서 같은 머리글의 충돌 표가 뒤에 붙어 있으면 파서가 그 표를 보지 못했고, 앞 표 값으로 "확인"을 냈다.
  `parse_cash_release`는 이제 파싱된 표 수와 원문의 `<table` 수가 다르면 보류(None)한다. 숫자를 만드는 쪽이 아니라 보류하는 쪽이다.
- `test_recovery_is_review_only_and_default_market_collection_unchanged`: 7dd38ffe 시점 app 함수 전체 AST 비교라
  분류 A와 같은 낡은 계약이었다. 의도만 남겼다.
  - 원문 대조 로더(`collect_cash_release`)를 쓰는 app 함수는 `render_today_market_memo_panel`의 '기업 심층분석' 분기 하나뿐이다.
  - 리포트 수집 모듈은 `sec_cash_recovery`를 import하지 않는다.
- 검증: sec_cash_recovery 47개 통과. sec/company/cash 관련 1,037개 통과(남은 실패 4개는 분류 A).
  report 범위 208/0.
- 남은 실패: 17건(A 12, B 3, C 1, E 1). 다음은 B(리포트 위치 3건).
- 운영 화면: 리포트 경로는 바뀌지 않는다. 기업 심층분석에서 원문 대조 버튼을 눌러 보는 확인은 아직 하지 않았다.
