"""B-4/B-5/B-7 (2026-11-24): shadow tech review, leverage stage reader, shared precision post-processing."""
import ast
import copy
import pathlib

import pandas as pd
import pytest

from stock_lab_core.decision_behavior_groups import BEHAVIOR_GROUP_CODES
from stock_lab_core.leverage_stage import LEVERAGE_STAGE_BY_CODE, resolve_leverage_stage
from stock_lab_core.tech_review import (
    BLOCK, CAUTION, CONFIRM, DATA_CHECK, NEUTRAL, build_tech_review_shadow,
)
from stock_lab_core.tech_review_view import tech_review_rows

ROOT = pathlib.Path(__file__).resolve().parents[1]


def base(**kw):
    d = {"dec": "🔍관망: 타점 대기", "decision_code": "WATCH_WAIT_ENTRY", "decision_group": "wait",
         "cur_p": 110.0, "pct_b": 0.6, "rsi": 55.0, "ma20": 105.0, "ma50": 100.0, "vol_ratio": 1.0,
         "day_ret": 0.01, "history_days": 300, "data_state": "OK", "ext_structure": "Bullish",
         "pd_zone": "Neutral", "fvg_active": False, "fvg_type": "", "mtf_bias_label": "중립 확인",
         "buy_amt": 0.0, "sizing_hint": "-"}
    d.update(kw)
    return d


def test_missing_core_input_is_data_check_not_a_guess():
    out = build_tech_review_shadow(base(pct_b=float("nan")))
    assert out["verdict"] == DATA_CHECK
    assert any("%B" in text for _, _, text in out["reasons"])
    assert build_tech_review_shadow(None)["verdict"] == DATA_CHECK


def test_confirm_needs_several_supports_and_no_burden():
    d = base(mtf_bias_label="상위 시간대 우호", is_52w_breakout=True)
    assert build_tech_review_shadow(d)["verdict"] == CONFIRM
    assert build_tech_review_shadow(base())["verdict"] == NEUTRAL


def test_overheat_and_supply_overhead_are_caution():
    liq = {"ok": True, "status": "상단 매물 근접"}
    out = build_tech_review_shadow(base(pct_b=0.97, rsi=78), liquidity_profile=liq)
    assert out["verdict"] == CAUTION
    assert out["cautions"] >= 3


def test_broken_pattern_invalid_line_is_block_reason():
    pattern = {"name": "쌍바닥", "direction": "bullish", "status": "관찰", "invalid_price": 120.0,
               "formation_id": ("double", "bottom", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01"))}
    out = build_tech_review_shadow(base(), pattern_candidates=[pattern])
    assert out["verdict"] == BLOCK
    assert any(area == "형성기간" and "59일" in text for _, area, text in out["reasons"])


def test_shadow_never_changes_decision_gate_or_sizing():
    d = base(decision_code="LEVERAGED_DCA_CONDITIONAL", is_leveraged_or_inverse=True, buy_amt=300000.0)
    wf = {"판정분류": "⏳눌림대기", "게이트상태": "대기/관찰", "시장실행상태": "정상"}
    patterns = [{"name": "삼각수렴", "direction": "bullish", "status": "상방돌파"}]
    liq = {"ok": True, "status": "하단 유동성 우세"}
    snap = copy.deepcopy((d, wf, patterns, liq))
    model = tech_review_rows(d, wf, pattern_candidates=patterns, liquidity_profile=liq,
                             monthly_signal_decision={"decision_code": "LEVERAGED_DCA_CONDITIONAL"},
                             multiplier_fn=lambda *_: 0.5)
    assert (d, wf, patterns, liq) == snap
    assert model["leverage"]["stage"] == "L2"
    assert model["leverage"]["executable"] is False
    assert model["leverage"]["plan_gate_mismatch"] is True


def test_leverage_stage_covers_every_leveraged_code_and_reserves_l3():
    assert set(LEVERAGE_STAGE_BY_CODE) == set(BEHAVIOR_GROUP_CODES["LEVERAGED"])
    assert "L3" not in {stage for stage, _ in LEVERAGE_STAGE_BY_CODE.values()}
    assert resolve_leverage_stage({"decision_code": "ETF_DCA_OK"}) == {}
    held = resolve_leverage_stage({"decision_code": "HARD_BLOCK_OVERWEIGHT", "is_leveraged_or_inverse": True})
    assert held["stage"] == "L?" and held["executable"] is None and held["monthly_multiplier"] is None
    defended = resolve_leverage_stage({"decision_code": "LEVERAGED_RECOVERY_DCA_BLOCK"},
                                      market_state="레버리지 시장방어", monthly_multiplier=float("nan"))
    assert defended["market_defense"] is True and defended["monthly_multiplier"] is None


def _app_function(name):
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_precision_post_processing_helper_keeps_the_original_order():
    fn = _app_function("apply_precision_post_decision")
    calls = [ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    order = [c for c in calls if c in {"apply_precision_mtf_decision_guard",
                                       "apply_leveraged_precision_decision_override",
                                       "enforce_non_core_panic_scope_on_result"}]
    assert order == ["apply_precision_mtf_decision_guard", "apply_leveraged_precision_decision_override",
                     "enforce_non_core_panic_scope_on_result"]
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    assert source.count("apply_precision_post_decision(") == 3  # def + demo + precision
    assert "non_core_panic_scope=True, is_etf=is_etf" in source


def test_precision_page_shows_shadow_after_decision_roles():
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    roles = source.rfind('render_decision_roles(c, c.get("execution_workflow")')
    shadow = source.find("render_tech_review_shadow(")
    assert 0 < roles < shadow < roles + 800


@pytest.mark.parametrize("non_core", [False, True])
def test_precision_post_processing_matches_the_inline_chain(app_module, monkeypatch, non_core):
    log = []

    def step(name):
        def run(c, *args, **kwargs):
            log.append(name)
            return dict(c, **{name: True})
        return run

    for name in ("apply_precision_mtf_decision_guard", "apply_leveraged_precision_decision_override",
                 "enforce_non_core_panic_scope_on_result"):
        monkeypatch.setattr(app_module, name, step(name))
    out = app_module.apply_precision_post_decision({"core_dca_rate": 0}, {}, name="n", ticker="t", has_pos=False,
                                                   my_price=0.0, non_core_panic_scope=non_core, is_etf=False)
    expected = ["apply_precision_mtf_decision_guard", "apply_leveraged_precision_decision_override"]
    expected += ["enforce_non_core_panic_scope_on_result"] if non_core else []
    assert log == expected and all(out[name] for name in expected)
