"""2026-11-27 SOXL reproduction: one effective target per plan, L0 vs 미설정 vs 조회 실패 kept apart.

The attached SOXL case showed 목표 8% in the entry plan's first row but 비중 0.0/0.0% and "목표비중 미설정" in the
leverage rows, and 회복 1/6 in the plan but 회복체크 미확인 in the leverage policy table.
"""

import ast
from pathlib import Path

import pytest

from stock_lab_core.execution_gate import GATE_DEFENSE
from stock_lab_core.tech_review_view import leverage_policy_rows

ROOT = Path(__file__).resolve().parents[1]


def _precision_calls():
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "calc_scores_and_decision":
            if node.args and len(node.args) >= 9 and getattr(node.args[8], "id", "") == "precision_decision_is_free":
                yield node


def test_precision_decision_reads_the_account_row_not_explicit_zero_weights():
    calls = list(_precision_calls())
    assert len(calls) == 1
    call = calls[0]
    # name..app_mode = 10 positional args; an 11th+ positional would be user_total_asset/curr_w/targ_w.
    assert len(call.args) == 10
    assert not {kw.arg for kw in call.keywords} & {"user_curr_w", "user_targ_w"}


class UI:
    def __init__(self):
        self.session_state = {"_app_final_macro_risk": 0.0}
        self.markdowns, self.frames = [], []

    def markdown(self, value, **kwargs):
        self.markdowns.append(value)

    def dataframe(self, value, **kwargs):
        self.frames.append(value)

    def info(self, value):
        self.markdowns.append(value)


def soxl_decision(**overrides):
    return {
        "cur_p": 35.82, "rr_stop": 14.61, "rr_target": 56.36, "rr_ratio": 0.97, "atr": 3.0,
        "ma5": 34.0, "ma20": 38.0, "ma50": 41.0, "buy_amt": 0.0, "current_w": 0.0, "target_w": 0.0,
        "dec": "⚡레버리지 미보유: 타점 관찰", "decision_code": "LEVERAGED_WATCH_NO_POSITION",
        "is_leveraged_or_inverse": True, "rsi": 40.0, "mfi": 35.8, "pct_b": 0.3,
        "execution_workflow": {"게이트상태": GATE_DEFENSE, "게이트근거": "레버리지 시장방어"},
        **overrides,
    }


@pytest.fixture
def plan_app(app_module, monkeypatch):
    ui = UI()
    seen = {}
    monkeypatch.setattr(app_module, "st", ui)
    monkeypatch.setattr(app_module, "get_target_weight_from_sheet", lambda *a: 8.0)
    monkeypatch.setattr(app_module, "get_sheet_current_weight", lambda *a: 0.0)
    monkeypatch.setitem(app_module.__dict__, "total_eval", 20_000_000.0)

    def state(name, ticker, c, has_pos, my_price):
        seen["state_target"] = c.get("target_w")
        return {"profile_key": "SOXL", "dca_stage": "미보유 관찰", "dca_multiple": "×0",
                "recovery_checks": [("MA20 위", False, ""), ("기초축 1W", False, "")],
                "recovery_passed": 1, "recovery_total": 6, "recovery_state": "방어 우선", "underlying_1w_avg": -7.2}

    monkeypatch.setattr(app_module, "build_leveraged_precision_state", state)
    monkeypatch.setattr(app_module, "build_sideways_quality_state", lambda *a, **k: {})
    return app_module, ui, seen


def test_entry_plan_passes_one_effective_target_to_the_leverage_rows(plan_app):
    app, ui, seen = plan_app
    decision = soxl_decision()
    plan = app.render_entry_execution_plan("SOXL", "SOXL", decision, has_pos=False, usdkrw=1400.0)
    assert seen["state_target"] == 8.0
    first = plan["rows"][0]
    assert first["단계"] == "목표까지 이론상 부족분"
    assert "목표 8.00%" in first["조건"] and "보유표 목표비중으로 보완" in first["조건"]
    lev = next(r for r in plan["rows"] if r["단계"] == "레버리지 조건")
    assert "비중 0.0/8.0%" in lev["조건"] and "회복 1/6" in lev["조건"]
    joined = " ".join(str(r["조건"]) for r in plan["rows"])
    assert "목표비중 미설정" not in joined
    assert "L0 미보유" in joined
    split = {r["구분"]: r["값"] for r in plan["amount_split"]}
    assert split["오늘 실행가능액"].startswith("0 · 오늘 신규·추가 실행 보류(레버리지 시장방어")
    assert split["실제 집행기록액"].startswith("미연결")
    assert decision["target_w"] == 0.0  # the input decision is never rewritten
    basis = plan["entry_basis"]
    assert [row["단계"] for row in basis][-2:] == ["최종 목표", "계획 무효·손절"]
    assert all(row["실행·수량"] == "보류 · 수량 미산출" for row in basis[:3])
    assert all("반올림 전" in row["기준선·산식"] for row in basis[:3])


def test_unset_target_still_reads_unset(plan_app, monkeypatch):
    app, ui, seen = plan_app
    monkeypatch.setattr(app, "get_target_weight_from_sheet", lambda *a: 0.0)
    plan = app.render_entry_execution_plan("SOXL", "SOXL", soxl_decision(), has_pos=False)
    assert seen["state_target"] == 0.0
    assert plan["rows"][0]["조건"] == "목표비중 미설정 · 배분금액/주수 미산출"


WF = {"게이트상태": GATE_DEFENSE, "시장실행상태": "시장방어"}


def test_l0_rows_observe_prices_and_mark_cycle_rules_not_applicable():
    obs = {"applicable": False, "reason": "L0 미보유: 보유 사이클 없음", "axis": "SOXX",
           "leveraged_above_ma50": False, "underlying_above_ma50": False, "underlying_date": "2026-11-25",
           "underlying_error": "", "recovery_passed": 1, "recovery_total": 6}
    rows = {r["항목"]: r["값"] for r in leverage_policy_rows({"leveraged_l3_observation": obs}, WF, None)}
    assert rows["회복체크"] == "1/6"
    assert rows["기초지수 MA50"].startswith("아래 (SOXX 2026-11-25")
    assert rows["레버리지 ETF MA50"] == "아래"
    for key in ("패닉 latch", "남은 회차", "20거래일 cooldown", "남은 예산", "L3 판독"):
        assert rows[key].startswith("해당 없음 · L0 미보유")


def test_l0_history_failure_is_reported_as_failure():
    obs = {"reason": "L0 미보유", "underlying_above_ma50": None, "underlying_error": "기초 가격 이력 조회 실패",
           "leveraged_above_ma50": None, "recovery_passed": 1, "recovery_total": 6}
    rows = {r["항목"]: r["값"] for r in leverage_policy_rows({"leveraged_l3_observation": obs}, WF, None)}
    assert rows["기초지수 MA50"] == "조회 실패 · 기초 가격 이력 조회 실패"
    assert rows["레버리지 ETF MA50"] == "미확인"


@pytest.mark.parametrize("note, expected", [("", "미설정"), ("레버리지 DCA 기록 조회 실패", "조회 실패 · 레버리지 DCA 기록 조회 실패")])
def test_held_budget_unset_vs_lookup_failure(note, expected):
    read = {"status": "L3 대기", "cycle": {"active": True, "tranches_used": 0}, "record": {},
            "last_bar": {"recovery_passed": 2}, "record_note": note}
    rows = {r["항목"]: r["값"] for r in leverage_policy_rows({"leveraged_l3": read}, WF, None)}
    assert rows["남은 예산"] == expected
    assert rows["회복체크"] == "2/6"
