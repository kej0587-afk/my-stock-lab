from stock_lab_core.today_flow_candidates import classify_flow_candidate_type


def test_flow_candidate_keeps_hot_rebound_from_crash_state():
    row = {
        "상태": "급락 경보",
        "1주수익률": 0.09,
        "2주수익률": 0.12,
        "1개월수익률": -0.02,
        "가속도": 0.08,
        "단기가속도": 0.05,
        "가격수준": 0.72,
        "돈흐름점수": 12,
    }

    assert classify_flow_candidate_type(row) == "회복추적"


def test_flow_candidate_still_excludes_crash_without_recent_turn():
    row = {
        "상태": "급락 경보",
        "1주수익률": -0.04,
        "2주수익률": -0.08,
        "1개월수익률": -0.15,
        "가속도": -0.20,
        "단기가속도": -0.05,
        "가격수준": 0.42,
        "돈흐름점수": -8,
    }

    assert classify_flow_candidate_type(row) == "제외"


def test_flow_candidate_marks_high_price_as_high_watch():
    row = {
        "상태": "강세 가속",
        "1개월수익률": 0.18,
        "3개월수익률": 0.42,
        "가속도": 0.16,
        "가격수준": 0.95,
        "돈흐름점수": 25,
    }

    assert classify_flow_candidate_type(row) == "고점주의"
