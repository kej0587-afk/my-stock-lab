import pandas as pd

from stock_lab_core.decision_workflow import attach_market_execution_context, build_decision_workflow, partition_today_queue
from stock_lab_core.execution_gate import apply_execution_gate_columns
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT


def _candidate(**overrides):
    return {
        "grade": "✅A급 (분할 매수)", "t_score": 8,
        "dec": "🔍A급 정배열: 타점 탐색 중", "decision_code": "A_UPTREND_SEARCH_ENTRY",
        "decision_group": "watch", "cur_p": 100, "rr_stop": 90, "rr_target": 120,
        "rr_ratio": 2.0, "ma20": 98, "atr": 5, **overrides,
    }


def test_candidate_quality_survives_timing_wait_and_position_defense():
    waiting = build_decision_workflow("Palo Alto Networks", "PANW", _candidate())
    blocked = build_decision_workflow("Palo Alto Networks", "PANW", _candidate(
        dec="비중 초과: 추매금지", decision_code="HARD_BLOCK_OVERWEIGHT", decision_group="caution",
    ))
    assert waiting["후보품질"] == blocked["후보품질"] == "✅A급 (분할 매수)"
    assert waiting["후보점수"] == blocked["후보점수"] == 8
    assert waiting["🔥기술적 타점"] == "🔍A급 정배열: 타점 탐색 중"
    assert waiting["게이트상태"] == GATE_WAIT
    assert blocked["게이트상태"] == GATE_DEFENSE


def test_partition_is_exhaustive_disjoint_and_gate_matches_execution():
    frame = pd.DataFrame({"게이트상태": [GATE_EXECUTABLE, GATE_WAIT, GATE_DEFENSE, GATE_DATA_CHECK, "관망"]}, index=[1, 3, 5, 7, 9])
    reason = pd.Series(["일반", "관심/눌림대기", "비중초과 방어", "데이터확인", "일반"], index=frame.index)
    masks = partition_today_queue(frame, reason)
    assert pd.DataFrame(masks).sum(axis=1).eq(1).all()
    assert masks["execution"].equals(frame["게이트상태"].eq(GATE_EXECUTABLE))
    assert masks["wait"].loc[3]
    assert masks["overweight"].loc[5]


def test_regional_leverage_guard_and_mtf_damage_share_defensive_routing():
    row = build_decision_workflow("SOXL", "SOXL", _candidate(
        dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER", decision_group="buyish",
    ), is_etf=True)
    frame = attach_market_execution_context(pd.DataFrame([row]), {"us_stats": {"mode": "방어"}})
    frame = apply_execution_gate_columns(frame)
    masks = partition_today_queue(frame, pd.Series(["일반"]))
    assert frame.iloc[0]["게이트상태"] == GATE_DEFENSE
    assert masks["market_defense"].iloc[0]
    mtf = build_decision_workflow("Test", "TEST", _candidate(
        dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER", decision_group="buyish",
        mtf_bias_label="상위 시간대 경고",
    ), has_pos=True)
    assert mtf["게이트상태"] == GATE_DEFENSE
