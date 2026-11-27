"""Inverse semiconductor products must not inherit the long SOXL recovery axis."""
from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.decision_workflow import build_decision_workflow, attach_market_execution_context
from stock_lab_core.execution_gate import build_execution_gate, GATE_DEFENSE


@pytest.mark.parametrize("ticker,name", [
    ("SOXS", "Direxion Daily Semiconductor Bear 3X Shares"),
    ("soxs", "Direxion Daily Semiconductor 3X"),
    ("SOXS", "Direxion Daily Semiconductor Bull 3X Shares"),
    ("SOXS", ""),
    ("UNKNOWN", "Direxion Daily Semiconductor Bear 3X Shares"),
    ("UNKNOWN", "Direxion Semiconductor Inverse 3X"),
    ("UNKNOWN", "Direxion Semiconductor 인버스 3X"),
])
def test_inverse_cannot_borrow_long_profile(app_module, ticker, name):
    assert app_module.get_leveraged_etf_precision_profile(ticker, name) == ("", {})


@pytest.mark.parametrize("ticker,name,key", [
    ("SOXL", "", "SOXL"),
    ("soxl", "Direxion Daily Semiconductor Bull 3X Shares", "SOXL"),
    ("UNKNOWN", "Direxion Daily Semiconductor Bull 3X Shares", "SOXL"),
    ("UNKNOWN", "Direxion Daily Semiconductor 3X", "SOXL"),
    ("RAM", "", "RAM"), ("BITX", "", "BITX"), ("BITU", "", "BITX"),
    ("QLD", "", "QLD"), ("TQQQ", "", "TQQQ"),
    ("418660.KS", "", "NASDAQ100_2X_KR"),
])
def test_existing_long_profiles_keep_the_exact_profile(app_module, ticker, name, key):
    actual_key, profile = app_module.get_leveraged_etf_precision_profile(ticker, name)
    assert actual_key == key
    assert profile is app_module.LEVERAGED_ETF_PRECISION_PROFILES[key]


@pytest.mark.parametrize("held", [False, True])
def test_soxs_does_not_query_long_recovery_or_l3_and_keeps_market_defense(app_module, monkeypatch, held):
    def forbidden(*args, **kwargs):
        pytest.fail("SOXS must not evaluate the SOXL recovery axis or L3 through this profile")
    for name in ("build_leveraged_precision_watch_rows", "build_leveraged_l3_read",
                 "build_leveraged_l3_observation"):
        monkeypatch.setattr(app_module, name, forbidden)
    name = "Direxion Daily Semiconductor Bear 3X Shares"
    candidate = dict(grade="A", t_score=8, cur_p=100, rr_stop=90, rr_target=120,
                     rr_ratio=2, ma20=98, atr=5, target_w=5, current_w=1 if held else 0,
                     buy_amt=100, dec="신규진입: 대장주 포착", decision_code="NEW_ENTRY_LEADER",
                     decision_group="buyish", is_leveraged_or_inverse=True)
    before = deepcopy(candidate)
    assert app_module.build_leveraged_precision_state(name, "SOXS", candidate, held, 100) == {}
    result = app_module.apply_leveraged_precision_decision_override(candidate, name, "SOXS", held, 100)
    assert result == before == candidate
    row = build_decision_workflow(name, "SOXS", result, is_etf=True, has_pos=held,
                                 is_leveraged_product_fn=app_module.is_leveraged_or_inverse_product)
    guarded = attach_market_execution_context(pd.DataFrame([row]), {"us_stats": {"mode": "방어"}})
    assert guarded.iloc[0]["시장실행상태"] == "레버리지 시장방어"
    assert build_execution_gate(guarded.iloc[0].to_dict())["게이트상태"] == GATE_DEFENSE
