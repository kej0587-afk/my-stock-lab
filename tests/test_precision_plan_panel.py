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
