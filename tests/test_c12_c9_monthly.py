"""C-12 (profit-take condition -> monthly 0x for 3 codes) and C-9 (perfect-storm share note), 2026-11-26."""
from stock_lab_core.monthly_rebalance import apply_monthly_signal_safety
from stock_lab_core.rebalance_multiplier import (PROFIT_TAKE_EXCLUDE_CODES, PROFIT_TAKE_EXCLUSION_TEXT,
                                                 core_storm_share_note, decision_signal_multiplier,
                                                 profit_take_exclusion)


def _d(code, signal=True, asset="us_stock", **kw):
    return {"decision_code": code, "dec": "x", "profit_take_signal": signal, "asset_class": asset, **kw}


def test_three_codes_with_profit_condition_get_zero():
    for code in PROFIT_TAKE_EXCLUDE_CODES:
        d = _d(code)
        assert profit_take_exclusion(d)
        for bucket in ("core", "swing", "leverage"):
            assert decision_signal_multiplier(d, bucket) == 0.0


def test_without_profit_condition_or_other_code_or_etf_unchanged():
    assert not profit_take_exclusion(_d("LEADER_MA5_PULLBACK_ENTRY", signal=False))
    assert not profit_take_exclusion(_d("OVERHEAT_WAIT"))
    assert not profit_take_exclusion(_d("LEADER_MA5_PULLBACK_ENTRY", asset="us_etf_other"))
    assert not profit_take_exclusion(_d("LEADER_MA5_PULLBACK_ENTRY", asset="kr_etf"))
    assert profit_take_exclusion(_d("HOLDING_QUALITY_RECOVERY_SCOUT", asset="kr_stock"))
    assert not profit_take_exclusion(None) and not profit_take_exclusion("LEADER_MA5_PULLBACK_ENTRY")


def _row(ticker="AAA", mult=1.0):
    return {"ticker": ticker, "tap_raw": "🔥불뿜는 대장주: MA5 눌림 진입", "tap_disp": "x", "bucket": "swing",
            "dip_level": 0, "base_alloc": 100.0, "multiplier": mult, "eff_alloc": 100.0 * mult}


def test_calculator_row_excluded_with_reason_even_when_always_invest():
    d = _d("LEADER_MA5_PULLBACK_ENTRY")
    for always in (set(), {"AAA"}):
        rows = [_row()]
        apply_monthly_signal_safety(rows, always, lambda *a, **k: 1.0, {"AAA": d})
        assert rows[0]["multiplier"] == 0.0 and rows[0]["eff_alloc"] == 0.0
        assert rows[0]["profit_take_excluded"] is True
        assert PROFIT_TAKE_EXCLUSION_TEXT in rows[0]["tap_disp"]
        assert PROFIT_TAKE_EXCLUSION_TEXT == "익절 검토 조건 충족으로 이번 적립 제외"


def test_calculator_row_untouched_without_condition():
    rows = [_row()]
    apply_monthly_signal_safety(rows, set(), lambda *a, **k: 1.0, {"AAA": _d("LEADER_MA5_PULLBACK_ENTRY", signal=False)})
    assert rows[0]["multiplier"] == 1.0 and "profit_take_excluded" not in rows[0]


def test_storm_note_says_what_100_percent_means():
    note = core_storm_share_note({"decision_code": "CORE_STORM_DCA", "core_dca_rate": 1.0})
    assert "퍼펙트스톰 100%" in note and "평소 월적립 몫의 1배" in note and "위기자금" in note
    assert "25%" in core_storm_share_note({"decision_code": "CORE_STORM_DCA", "core_dca_rate": 0.25})
    assert core_storm_share_note({"decision_code": "CORE_CRASH_DCA", "core_dca_rate": 2.0}) == ""
    assert core_storm_share_note({"decision_code": "CORE_STORM_DCA", "core_dca_rate": 0}) == ""
    assert core_storm_share_note(None) == ""
