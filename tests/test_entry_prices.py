from copy import deepcopy
import math

import pytest

from stock_lab_core.entry_prices import build_entry_price_plan


def sample(**kwargs):
    return dict(cur_p=100, rr_stop=90, rr_target=120, atr=5, ma5=98, ma20=95, **kwargs)


@pytest.mark.parametrize("wait,first,tp", [(False, 100, 110), (True, 98, 106)])
def test_entry_and_one_r_share_basis(wait, first, tp):
    c = sample()
    before = deepcopy(c)
    plan = build_entry_price_plan(c, wait_for_pullback=wait)
    assert [entry[1] for entry in plan["entries"]] == [first, 95, 92.5]
    assert plan["exits"] == (tp, 120, 120)
    assert plan["rr"] == 2 and c == before


@pytest.mark.parametrize("key", ["cur_p", "rr_stop", "rr_target"])
@pytest.mark.parametrize("value", [None, 0, -1, math.nan, math.inf, -math.inf])
def test_missing_or_nonfinite_triplet_has_no_plan(key, value):
    c = sample()
    c[key] = value
    plan = build_entry_price_plan(c)
    assert not plan["valid"] and math.isnan(plan["rr"])
    assert "entries" not in plan and "exits" not in plan


@pytest.mark.parametrize("target,stop", [(100, 90), (99, 90), (120, 100), (120, 101)])
def test_invalid_triplet_has_no_plan(target, stop):
    c = sample()
    c.update(rr_target=target, rr_stop=stop)
    assert not build_entry_price_plan(c)["valid"]


def test_support_order_and_strict_gap_are_preserved():
    c = sample(fvg_top=97, fvg_bottom=96.9)
    plan = build_entry_price_plan(c, wait_for_pullback=True)
    assert plan["supports"] == [("MA5", 98.0), ("FVG 하단", 96.9), ("MA20", 95.0)]


def test_low_rr_uses_pullback_without_rounding_into_pass():
    c = sample()
    c["rr_target"] = 109.96
    plan = build_entry_price_plan(c, wait_for_pullback=True)
    assert plan["rr"] == pytest.approx(.996)
    assert plan["entries"][0] == ("MA5", 98)
    assert plan["exits"][0] == 106


def test_projection_and_risk_ladder_are_existing_references():
    c = sample(rr_target_is_projection=True, rr_tp1=108, rr_tp2=0, rr_tp3=125)
    c.update(ma5=None, ma20=0, atr=0)
    plan = build_entry_price_plan(c)
    assert [entry[1] for entry in plan["entries"]] == [100, 97.5, 92.5]
    c["atr"] = 5
    assert build_entry_price_plan(c)["exits"] == (108, 110, 125)
