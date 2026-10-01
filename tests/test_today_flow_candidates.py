from stock_lab_core.today_flow_candidates import (
    classify_flow_candidate_type,
    classify_money_flow_candidate_scope,
    classify_money_flow_radar_label,
)


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


def test_flow_candidate_excludes_weak_turn_without_recent_turn():
    row = {
        "상태": "약세 전환",
        "1주수익률": -0.02,
        "2주수익률": -0.05,
        "1개월수익률": -0.12,
        "가속도": -0.16,
        "단기가속도": -0.03,
        "가격수준": 0.58,
        "돈흐름점수": 2,
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


def test_radar_label_keeps_macro_gauges_out_of_candidates():
    row = {
        "구분": "매크로",
        "Ticker": "^VIX",
        "상태": "강세 가속",
        "스윙점수": 9,
        "가격수준": 0.42,
    }

    assert classify_money_flow_candidate_scope(row) == "매크로게이지"
    assert classify_money_flow_radar_label(row) == "📍 매크로게이지"


def test_radar_label_keeps_cashlike_assets_out_of_candidates():
    row = {
        "구분": "월배당 ETF",
        "섹터": "CD금리",
        "Ticker": "459580.KS",
        "상태": "관찰",
        "스윙점수": 8,
        "가격수준": 0.35,
    }

    assert classify_money_flow_candidate_scope(row) == "현금성게이지"
    assert classify_money_flow_radar_label(row) == "💵 현금성게이지"


def test_radar_label_uses_interest_candidate_not_entry_wording():
    row = {
        "구분": "ETF/섹터",
        "섹터": "반도체",
        "Ticker": "SOXX",
        "상태": "신규 유입",
        "스윙점수": 7,
        "가격수준": 0.62,
    }

    assert classify_money_flow_candidate_scope(row) == "후보"
    assert classify_money_flow_radar_label(row) == "👀 관심후보"


def test_radar_label_marks_high_price_as_watch_not_entry():
    row = {
        "구분": "ETF/섹터",
        "섹터": "반도체",
        "Ticker": "SOXX",
        "상태": "강세 가속",
        "스윙점수": 7,
        "가격수준": 0.91,
    }

    assert classify_money_flow_radar_label(row) == "⚠️ 고점관찰"
