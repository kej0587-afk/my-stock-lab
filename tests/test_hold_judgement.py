from stock_lab_core.hold_judgement import HoldDecision, build_hold_decision


def test_hold_decision_strong_hold_for_profitable_quality_stock():
    judgement = build_hold_decision(
        ticker="MSFT",
        name="Microsoft",
        is_etf=False,
        fin_score=4,
        c={
            "cur_p": 130,
            "dd": -0.05,
            "trend": "🚀정배열(상승)",
            "rs_label": "🚀강함",
            "rs_slope_label": "📈RS상승중",
        },
        my_price=100,
        has_pos=True,
    )

    assert judgement.decision == HoldDecision.STRONG_HOLD
    assert judgement.score >= 6
    assert "장기 보유 유효" in judgement.action_plan


def test_hold_decision_emergency_exit_for_damaged_low_quality_stock():
    judgement = build_hold_decision(
        ticker="BAD",
        name="Bad Stock",
        is_etf=False,
        fin_score=1,
        c={
            "cur_p": 70,
            "dd": -0.35,
            "trend": "🌊역배열(하락)",
            "rs_label": "🐢약함",
            "rs_slope_label": "📉RS하락중",
            "structure_risk": True,
        },
        my_price=100,
        has_pos=True,
    )

    assert judgement.decision == HoldDecision.EMERGENCY_EXIT
    assert judgement.reasons_exit


def test_hold_decision_etf_gets_fundamental_floor():
    judgement = build_hold_decision(
        ticker="VOO",
        name="S&P500",
        is_etf=True,
        fin_score=0,
        c={
            "cur_p": 100,
            "dd": -0.08,
            "trend": "혼조세",
            "rs_label": "➖보통",
            "rs_slope_label": "➡️RS횡보",
        },
        my_price=100,
        has_pos=True,
    )

    assert judgement.fundamental_score == 2
    assert any("ETF" in reason for reason in judgement.reasons_hold)
