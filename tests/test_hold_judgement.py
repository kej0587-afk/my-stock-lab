from copy import deepcopy

import pytest

from stock_lab_core.hold_judgement import HoldDecision, build_hold_decision


def test_dram_hold_classification_does_not_match_ram_substring():
    context = {"cur_p": 100, "dd": -0.05, "trend": "혼조세", "rs_label": "➖보통"}
    plain = build_hold_decision("DRAM", "Roundhill Memory ETF", True, 0, context, 100, True)
    leveraged = build_hold_decision("RAM", "RAM", True, 0, context, 100, True)
    assert plain.fundamental_score == 2
    assert leveraged.fundamental_score == 0


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


def test_hold_decision_fin_score_one_alone_is_not_emergency_exit():
    judgement = build_hold_decision(
        ticker="LOWQ",
        name="Low Quality",
        is_etf=False,
        fin_score=1,
        c={
            "cur_p": 100,
            "dd": -0.05,
            "trend": "혼조세",
            "rs_label": "➖보통",
            "rs_slope_label": "➡️RS횡보",
        },
        my_price=100,
        has_pos=True,
    )

    assert judgement.decision != HoldDecision.EMERGENCY_EXIT
    assert any("재무 1점" in reason for reason in judgement.reasons_caution)


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


def test_leveraged_etf_does_not_receive_core_etf_strong_hold_plan():
    judgement = build_hold_decision(
        ticker="SOXL",
        name="Direxion Daily Semiconductor Bull 3X Shares",
        is_etf=True,
        fin_score=0,
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

    assert judgement.decision != HoldDecision.STRONG_HOLD
    assert judgement.fundamental_score == 0
    assert "목표 비중까지 분할 매수 가능" not in judgement.action_plan


def test_hold_decision_ignores_nan_average_price():
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
        my_price=float("nan"),
        has_pos=True,
    )

    assert judgement.risk_score == 0


@pytest.mark.parametrize("label,slope,tech_score,decision,reason", [
    ("🚀강함", "", 2, HoldDecision.CONDITIONAL_HOLD, "가격 상대강도 우세"),
    ("🚀강함", "📉RS하락중", 1, HoldDecision.CONDITIONAL_HOLD, "기울기 하락 중"),
    ("🐢약함", "", -2, HoldDecision.WATCH, "가격 상대강도 열세"),
    ("🐢약함", "📈RS상승중", -1, HoldDecision.WATCH, "기울기 개선 중"),
])
def test_etf_and_rs_wording_only_changes_descriptions_not_scores(label, slope, tech_score, decision, reason):
    context = {"cur_p": 100, "dd": -0.05, "trend": "혼조세", "rs_label": label, "rs_slope_label": slope}
    original = deepcopy(context)
    result = build_hold_decision("CIBR", "First Trust Cybersecurity ETF", True, 0, context, 100, True)
    assert (result.fundamental_score, result.technical_score, result.risk_score, result.thesis_score) == (2, tech_score, 0, 0)
    assert result.score == 2 + tech_score and result.decision == decision
    assert result.action_plan == "현재 포지션 유지 가능"
    reasons = result.reasons_hold + result.reasons_caution
    assert "ETF: 개별기업 재무점수 대신 편입자산·상품구조 위험을 별도 확인" in reasons
    assert "부도 리스크 없음" not in " ".join(reasons)
    assert any(reason in item and "미확인" in item for item in reasons)
    assert context == original
