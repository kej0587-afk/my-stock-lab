# #3 보유 종목 직접 검색 시 계좌 기준 판정 (2026-11-24)

## 결정

사용자가 2026-11-24 16:35 KST에 "보유면 계좌 기준 판정(권장)"을 선택했다.

## 배경

정밀 화면에서 직접 검색(자유입력)한 종목이 보유 종목이면, 가격·점수·비중이 같아도 판정이 오늘 점검과 달랐다.
예를 들어 379810(11-21 기록)은 자유입력 경로에서 `CRISIS_PANIC_SELL_OFF`, 계좌 경로와 오늘 점검에서는 `HARD_BLOCK_OVERWEIGHT`였다
([기록](20261121_cross_view_price_mode.md)).

## 변경

- `signal_basis.decision_uses_free_path(selection_is_free, has_position)`: 보유가 확인된 종목이면 자유입력으로 골라도 계좌 경로(False)를 쓴다.
  보유가 아니거나 확인되지 않으면 기존 자유입력 경로를 유지한다.
- `app.py` 정밀 화면: `calc_scores_and_decision`에 이 값을 넘기고, 근거 표의 '분석경로'도 실제로 쓴 경로를 기록한다('선택유형'은 free 그대로).
  평단선 표시도 같은 경로를 따른다(보유 종목이면 직접 검색이어도 평단선 표시).
- `calc_scores_and_decision`, 판정 함수, 점수, 가중치, 문턱값은 바꾸지 않았다. 미보유 종목의 자유입력 판정도 그대로다.

## 확인

- 새 테스트 2건(`tests/test_selection_price_evidence.py`): 보유·미보유·미확인 조합의 경로, 정밀 화면이 선택 유형이 아니라 판정 경로를 넘기는지.
- decision 게이트: main 1,637 통과 · 1 실패, 변경 후 1,637 통과 · 1 실패(`decision_zcesgseq`).
  실패 1건 `test_extracted_policies_preserve_all_original_conditions_and_literals`는 main에서도 같다.
- report 게이트 208 통과(`report_wj5h8x85`).
- 운영 확인: 아래에 기록.
