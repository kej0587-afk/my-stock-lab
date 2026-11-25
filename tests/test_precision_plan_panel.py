"""Display-only regressions for held-position plans and ETF narratives."""

from copy import deepcopy

import pytest

from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, GATE_WATCH_ONLY,
)
from stock_lab_core.decision_engine import build_core_dca_context_values
from stock_lab_core.decision_workflow import build_decision_workflow


class RecordingUI:
    def __init__(self):
        self.session_state = {"_app_final_macro_risk": 0.0}
        self.markdowns = []
        self.frames = []
        self.messages = []

    def markdown(self, value, **kwargs):
        self.markdowns.append(value)

    def dataframe(self, value, **kwargs):
        self.frames.append(value)

    def info(self, value):
        self.messages.append(value)


@pytest.fixture
def display_app(app_module, monkeypatch):
    ui = RecordingUI()
    monkeypatch.setattr(app_module, "st", ui)
    monkeypatch.setattr(app_module, "get_target_weight_from_sheet", lambda *args: 0)
    monkeypatch.setattr(app_module, "get_sheet_current_weight", lambda *args: 0)
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *args: {})
    monkeypatch.setattr(app_module, "build_sideways_quality_state", lambda *args, **kwargs: {})
    monkeypatch.setattr(app_module, "get_valuation_headline_for_final_check",
                        lambda *args, **kwargs: ("ETF 별도판단", "", None))
    return app_module, ui


def held_decision(**overrides):
    return {
        "cur_p": 100.0, "rr_stop": 90.0, "rr_target": 120.0, "rr_ratio": 2.0,
        "atr": 5.0, "ma5": 98.0, "ma20": 95.0, "buy_amt": 0.0,
        "current_w": 6.0, "target_w": 5.0,
        "dec": "비중초과", "decision_code": "HARD_BLOCK_OVERWEIGHT",
        "rsi": 55.0, "mfi": 55.0, "pct_b": 0.5,
        "execution_workflow": {
            "유형": "ETF", "게이트상태": GATE_DEFENSE,
            "게이트근거": "목표비중/비중초과 우선",
        },
        **overrides,
    }


@pytest.mark.parametrize("gate", [GATE_DEFENSE, GATE_WAIT, GATE_DATA_CHECK, GATE_WATCH_ONLY, ""])
@pytest.mark.parametrize("has_pos", [True, False])
def test_restricted_headline_precedes_raw_plan_and_preserves_payload(display_app, gate, has_pos):
    app, ui = display_app
    decision = held_decision(
        buy_amt=140000, current_w=1.0,
        execution_workflow={"게이트상태": gate, "게이트근거": "목표비중/비중초과 우선"},
    )
    before = deepcopy(decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=has_pos)
    html = ui.markdowns[-1]
    assert "<span class='highlight'>실행 보류</span>" in html
    assert html.index("실행 보류") < html.index("분할 진입 가능")
    assert "조건 해소 후 참고할 원계획 등급: 분할 진입 가능 (실행 허용 아님)" in html
    assert "1차 정찰 후 눌림에서 추가하는 구간" not in html
    assert plan["status"] == "분할 진입 가능"
    assert plan["status_note"] == "현재 앱 신호 기준으로 1차 정찰 후 눌림에서 추가하는 구간입니다."
    assert plan["rows"] == ui.frames[-1].to_dict("records")
    assert (plan["current_price"], plan["stop"], plan["target"], plan["rr_now"]) == (100, 90, 120, "2.00")
    assert plan["rows"][1]["금액/수량"] == "$40 / 0.40주"
    assert decision == before


def test_plan_explains_ratio_invalidation_and_weight_without_changing_numbers(display_app):
    app, ui = display_app
    decision = held_decision()
    before = deepcopy(decision)
    app.render_entry_execution_plan("Test", "TEST", decision, has_pos=True)
    html = ui.markdowns[-1]
    assert "승률이 아닙니다" in html
    assert "신규·추가매수 계획의 무효선" in html
    assert "보유분 전량매도 권고" in html
    assert "비중 항목 통과" in html and "매수 근거가 아닙니다" in html
    assert decision == before


def test_executable_headline_and_plan_numbers_are_unchanged(display_app):
    app, ui = display_app
    decision = held_decision(buy_amt=140000, current_w=1.0,
                             execution_workflow={"게이트상태": GATE_EXECUTABLE},
                             chart_final_check={"execution_allowed": True, "block_count": 0, "core_missing_ids": []})
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=True)
    assert "<span class='highlight'>분할 진입 가능</span>" in ui.markdowns[-1]
    assert plan["status_note"] in ui.markdowns[-1]
    assert "실행 보류" not in ui.markdowns[-1]
    assert [row["가격"] for row in plan["rows"]] == ["$100.00", "$100.00", "$95.00", "$92.50", "$110.00", "$120.00", "$90.00"]
    assert plan["rows"] == ui.frames[-1].to_dict("records")


@pytest.mark.parametrize("has_pos", [False, True])
def test_pullback_entry_and_first_profit_share_risk_basis(display_app, has_pos):
    app, ui = display_app
    decision = held_decision(cur_p=64.29, rr_stop=38.2, rr_target=108.6,
                             rr_ratio=1.7, atr=13.045, ma5=60.86, ma20=57.77,
                             dec="눌림 대기", decision_code="S_UPTREND_WAIT_PULLBACK", current_w=0,
                             buy_amt=140000)
    before = deepcopy(decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=has_pos)
    entry = next(row for row in plan["rows"] if row["단계"].startswith(("1차 진입", "추가 1차")))
    first = next(row for row in plan["rows"] if row["단계"] == "1차 익절")
    price = float(entry["가격"].replace("$", "").replace(",", ""))
    assert price < decision["cur_p"]
    assert first["가격"] == f"${min(108.6, price + (price - 38.2)):.2f}"
    assert "1차 계획 진입가" in first["조건"]
    assert plan["rows"] == ui.frames[-1].to_dict("records")
    assert decision == before


@pytest.mark.parametrize("rr", [.996, .9999, 1.0, 1.004, 1.496, 1.5, 2.0])
@pytest.mark.parametrize("wait", [False, True])
def test_queue_precision_same_price_and_unrounded_boundaries(display_app, rr, wait):
    from stock_lab_core.today_queue import build_today_queue_execution_snapshot
    from stock_lab_core.formatters import format_rr_ratio
    app, ui = display_app
    decision = held_decision(
        rr_target=100 + 10 * rr, rr_ratio=99, buy_amt=140000, current_w=1,
        decision_code="S_UPTREND_WAIT_PULLBACK" if wait else "NEW_ENTRY_LEADER",
        dec="눌림 대기" if wait else "신규진입",
        execution_workflow={"게이트상태": GATE_WAIT, "게이트근거": "기존 대기"},
    )
    original = deepcopy(decision)
    queue = build_today_queue_execution_snapshot("Test", "TEST", decision, has_pos=True)
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=True)
    first = next(row for row in plan["rows"] if row["단계"].startswith("추가 1차"))
    assert first["가격"] == queue["1차기준"] == ("$98.00" if wait or rr < 1 else "$100.00")
    assert plan["rr_now"] == queue["R/R"] == format_rr_ratio(queue["RR값"])
    if rr < 1:
        assert plan["status"] == "현재가 보류 / 눌림 대기"
    if not wait:
        assert first["단계"] == ("추가 1차 (30%)" if rr < 1.5 else "추가 1차 (40%)")
    assert plan["display_status"] == "실행 보류"
    assert "1차 1." not in ui.markdowns[-1]
    assert "<details><summary>배분 기준·계획 주의사항</summary>" in ui.markdowns[-1]
    assert decision == original


@pytest.mark.parametrize("allow_current,expected", [(True, "$100.00"), (False, "$98.00")])
def test_dedicated_leverage_timing_is_not_replaced_by_ordinary_rr_policy(display_app, monkeypatch, allow_current, expected):
    app, _ = display_app
    monkeypatch.setattr(app, "build_leveraged_precision_state", lambda *args: {"profile_key": "SOXL"})
    monkeypatch.setattr(app, "build_leveraged_dca_timing_state", lambda *args: {
        "status": "기존 레버리지 조건", "allow_current": allow_current,
        "tranche_weights": [.25, .35, .40],
    })
    c = held_decision(rr_target=109, rr_ratio=.9, decision_code="LEVERAGED_RECOVERY_DCA_CONDITIONAL",
                      dec="조건부", current_w=1, buy_amt=140000)
    plan = app.render_entry_execution_plan("SOXL", "SOXL", c, has_pos=True)
    first = next(row for row in plan["rows"] if row["단계"].startswith("추가 1차"))
    assert first["가격"] == expected
    assert first["단계"] == "추가 1차 (25%)"
    assert plan["display_status"] == "실행 보류"


def test_held_nasdaq_overweight_keeps_final_check_and_zero_amounts(display_app):
    app, ui = display_app
    decision = held_decision()
    plan = app.render_entry_execution_plan("나스닥", "379810.KS", decision, has_pos=True)
    rows, summary = app.build_pre_buy_final_checks("나스닥", "379810.KS", True, decision, 0, True, 95)
    assert "<span class='highlight'>실행 보류</span>" in ui.markdowns[-1]
    assert "목표비중/비중초과 우선" in ui.markdowns[-1]
    assert plan["status"] == "분할 진입 가능"
    assert all(row["금액/수량"] == "-" for row in plan["rows"][:4])
    assert summary["block_count"] == 2 and summary["final_label"] == "매수 금지"
    assert next(row for row in rows if row["점검항목"] == "재무/상품")["상태"] == "통과"


@pytest.mark.parametrize("ticker", ["379810.KS", "379800.KS", "418660.KS", "CIBR", "SOXL",
                                  "0167A0.KS", "BITX", "0025N0.KS", "MAGS", "RAM", "GOOGL"])
def test_held_final_check_and_plan_keep_defensive_gate(display_app, ticker):
    app, ui = display_app
    decision = held_decision()
    before = deepcopy(decision)
    _, final = app.build_pre_buy_final_checks(ticker, ticker, ticker != "GOOGL", decision, 4, True, 95)
    assert final["execution_allowed"] is False
    decision["chart_final_check"] = final
    plan = app.render_entry_execution_plan(ticker, ticker, decision, has_pos=True)
    assert plan["display_status"] == "실행 보류"
    assert plan["execution_gate"] != GATE_EXECUTABLE
    assert (plan["current_price"], plan["target"], plan["stop"]) == (100, 120, 90)
    assert plan["rows"] == ui.frames[-1].to_dict("records")
    assert {k: v for k, v in decision.items() if k != "chart_final_check"} == before


@pytest.mark.parametrize("cash,expected", [(0, "-"), (100_000, "100,000원 / 1000.00주")])
def test_core_plan_keeps_cash_capped_amount_instead_of_target_gap(display_app, cash, expected):
    app, _ = display_app
    dca = build_core_dca_context_values(
        mode="개인모드", rate=1, label="기존 적립률", buy_amount=1_000_000,
        current_dd=-0.1, cash_available=cash, reserve_available=0,
    )
    decision = held_decision(
        bucket="core", current_w=1, target_w=5, buy_amt=1_000_000,
        dec="코어 적립", decision_code="CORE_ETF_DCA_BUY", **dca,
    )
    before = deepcopy(decision)
    plan = app.render_entry_execution_plan("나스닥", "379810.KS", decision, has_pos=True)
    installment = next(row for row in plan["rows"] if row["단계"] == "이번 회차 적립 기준")
    assert installment["금액/수량"] == expected
    assert installment["조건"].startswith("실행 보류 · 목표비중/비중초과 우선")
    if cash == 0:
        assert all(row["금액/수량"] == "-" for row in plan["rows"][1:5])
    assert plan["rows"][0]["금액/수량"].startswith("1,000,000원")
    assert decision == before


@pytest.mark.parametrize("target", [95, 100])
def test_precision_plan_and_final_check_reject_old_positive_rr(display_app, target):
    app, ui = display_app
    decision = held_decision(rr_target=target, rr_ratio=2, current_w=1,
                             decision_code="NEW_ENTRY_LEADER", dec="신규진입: 대장주 포착")
    decision["execution_workflow"] = build_decision_workflow("Test", "TEST", decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision)
    assert plan["status"] == "unavailable"
    assert "목표가" in ui.messages[-1]
    checks, summary = app.build_pre_buy_final_checks("Test", "TEST", True, decision, 0, False, 0)
    assert next(row for row in checks if row["점검항목"] == "손익비")["상태"] != "통과"
    assert summary["final_label"] in {"대기", "매수 금지"}
    narrative = app.build_precision_narrative("Test", "TEST", decision, 0, False, 0, is_etf=True)
    assert "R/R 비율</b>: <b>2.00" not in narrative


@pytest.mark.parametrize("ticker,metadata,kwargs,exempt", [
    ("379810.KS", {}, {}, True),
    ("UNKNOWN", {"is_etf": True}, {}, True),
    ("UNKNOWN", {"is_etf": "false"}, {}, False),
    ("UNKNOWN", {"execution_workflow": {"유형": "ETF"}}, {}, True),
    ("UNKNOWN", {"asset_class": "us_etf_nasdaq"}, {}, True),
    ("UNKNOWN", {}, {"is_etf": True}, True),
    ("UNKNOWN", {"is_etf": True}, {"is_etf": False}, False),
    ("379810.KS", {"execution_workflow": {"유형": "개별주"}}, {}, False),
    ("MSFT", {}, {}, False),
])
def test_narrative_finance_uses_product_metadata_not_zero_score(display_app, ticker, metadata, kwargs, exempt):
    app, _ = display_app
    decision = held_decision(execution_workflow={})
    decision.update(metadata)
    before = deepcopy(decision)
    html = app.build_precision_narrative("Test", ticker, decision, 0, True, 95, **kwargs)
    assert ("재무 해당없음(ETF/ETN 등)" in html) is exempt
    assert ("재무 🚨위험(0/4)" in html) is not exempt
    assert decision == before


def test_stock_financial_quality_label_is_unchanged(display_app):
    app, _ = display_app
    html = app.build_precision_narrative("Microsoft", "MSFT", held_decision(execution_workflow={}), 4, True, 95)
    assert "재무 💎완성형 우량(4/4)" in html


def test_ram_recovery_exception_does_not_soften_multiple_independent_blocks(display_app, monkeypatch):
    app, _ = display_app
    monkeypatch.setattr(app, "build_leveraged_precision_state", lambda *args: {
        "profile_key": "RAM", "dca_stage": "회복 후보", "dca_multiple": "×1", "recovery_passed": 4,
    })
    monkeypatch.setattr(app, "build_leveraged_dca_timing_state", lambda *args: {
        "status": "1차 소액만", "entry1_verdict": "조건부",
    })
    decision = held_decision(structure_risk=True, mfi=85)
    _, summary = app.build_pre_buy_final_checks("RAM", "RAM", True, decision, 0, True, 95)
    assert summary["block_count"] == 4
    assert summary["final_label"] == "매수 금지"
    assert not summary["execution_allowed"]
    assert summary["action"] == "목표비중/비중초과 우선"


def test_exception_entry_plan_is_one_third_scout_with_trend_exit(display_app):
    """C-1 step 1: EXCEPTION_ENTRY plans only the 1/3 scout tranche and a trailing exit."""
    app, ui = display_app
    decision = held_decision(dec="🟣예외승인: 정찰대 진입(MA5/FVG)", decision_code="EXCEPTION_ENTRY",
                             rr_target=115.0, rr_ratio=1.5, buy_amt=140000, current_w=0, target_w=10,
                             execution_workflow={"게이트상태": GATE_EXECUTABLE},
                             chart_final_check={"execution_allowed": True, "block_count": 0, "core_missing_ids": []})
    before = deepcopy(decision)
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=False)
    assert plan["status"] == "1/3 정찰 · 추세추적"
    stages = [row["단계"] for row in plan["rows"]]
    assert stages == ["총 추가 필요", "1차 진입 (33%)", "2차 추가", "3차 예비", "추세추적 정리", "초기 손절"]
    first = plan["rows"][1]
    assert first["가격"] == "$100.00" and first["금액/수량"] == "$33 / 0.33주"
    assert plan["rows"][2]["금액/수량"] == plan["rows"][3]["금액/수량"] == "-"
    assert plan["rows"][-1]["가격"] == "$90.00"
    assert decision == before


def test_exception_entry_plan_for_held_position_is_unchanged(display_app):
    app, ui = display_app
    decision = held_decision(dec="🟣예외승인: 정찰대 진입(MA5/FVG)", decision_code="EXCEPTION_ENTRY",
                             rr_target=115.0, rr_ratio=1.5, buy_amt=140000, current_w=1.0, target_w=10,
                             execution_workflow={"게이트상태": GATE_EXECUTABLE},
                             chart_final_check={"execution_allowed": True, "block_count": 0, "core_missing_ids": []})
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=True)
    assert plan["status"] != "1/3 정찰 · 추세추적"
    assert not any(row["단계"] == "추세추적 정리" for row in plan["rows"])


@pytest.mark.parametrize("regime, trend", [("상승", True), ("횡보", False), ("하락", False), ("미확인", False)])
def test_leader_plan_uses_trend_exit_only_in_uptrend(display_app, regime, trend):
    """C-1 step 2: NEW_ENTRY_LEADER keeps its tranches; only the exit rows change, and only in 상승장."""
    app, ui = display_app
    decision = held_decision(dec="🔥신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER", market_regime=regime,
                             rr_target=120.0, rr_ratio=2.0, buy_amt=140000, current_w=0, target_w=10,
                             execution_workflow={"게이트상태": GATE_EXECUTABLE},
                             chart_final_check={"execution_allowed": True, "block_count": 0, "core_missing_ids": []})
    plan = app.render_entry_execution_plan("Test", "TEST", decision, has_pos=False)
    stages = [row["단계"] for row in plan["rows"]]
    assert stages[1] == "1차 진입 (40%)"
    assert ("추세추적 정리" in stages) is trend
    assert ("1차 익절" in stages) is (not trend)
    if trend:
        assert plan["rows"][-1]["금액/수량"] == "진입분 전량"
