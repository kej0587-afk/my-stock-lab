"""C-6/C-11 step 2 (2026-11-26, user decisions 3 and 4): no missing-signal estimate, account-scope check,
always-invest never overrides a safety block. Rows with a valid signal and no safety code are unchanged."""
import math

import pandas as pd

from stock_lab_core.monthly_rebalance import (ALWAYS_INVEST_SAFETY_CODES, UNKNOWN_SIGNAL_STATUS, build_rebalance_plan,
                                              compute_monthly_plan, prepare_rebalance_holdings)
from stock_lab_core.rebalance_multiplier import decision_signal_multiplier, legacy_label_multiplier


def _multiplier(tap, bucket, dip_level=0, decision=None):
    if isinstance(decision, dict) and str(decision.get("dec", "")).strip() == str(tap).strip():
        return decision_signal_multiplier(decision, bucket, dip_level=dip_level)
    return legacy_label_multiplier(tap, bucket, dip_level=dip_level)


def _holdings():
    return pd.DataFrame([
        {"티커": "QQQ", "자산명": "QQQ", "목표비중": 40, "bucket": "core", "asset_class": "us_etf_nasdaq", "현재가": 500.0,
         "매입가": 450.0, "보유량": 3, "is_etf": True, "운용대상": True},
        {"티커": "TQQQ", "자산명": "TQQQ", "목표비중": 10, "bucket": "leverage", "asset_class": "us_etf_nasdaq",
         "현재가": 60.0, "매입가": 80.0, "보유량": 5, "is_etf": True, "운용대상": True},
        {"티커": "SPY", "자산명": "SPY", "목표비중": 30, "bucket": "core", "asset_class": "us_etf_sp500",
         "현재가": 600.0, "매입가": 500.0, "보유량": 1, "is_etf": True, "운용대상": True},
        {"티커": "NVDA", "자산명": "NVDA", "목표비중": 20, "bucket": "swing", "asset_class": "us_stock",
         "현재가": 150.0, "매입가": 120.0, "보유량": 2, "is_etf": False, "운용대상": True},
    ])


SIGNALS = {"QQQ": "분할 매수", "TQQQ": "⚡레버리지 조건부 DCA", "SPY": "분할 매수", "NVDA": "🟢눌림 매수"}


def _plan(signals, *, always=(), decisions=None, redistribute=True, scope_valid=True):
    return compute_monthly_plan(_holdings(), total_invest=1_000_000, usdkrw=1400.0, signal_cache=signals,
                                signal_decisions=decisions or {}, always_invest_set=set(always),
                                redistribute_mode=redistribute, accumulated={}, signal_multiplier=_multiplier,
                                month="2026-11", signal_scope_valid=scope_valid, account_scope="scope-a")


def _rows(plan):
    return {r["ticker"]: r for r in plan["rows"]}


def test_valid_signals_keep_the_previous_plan():
    eligible = prepare_rebalance_holdings(_holdings())
    for redistribute in (True, False):
        before = build_rebalance_plan(eligible, 100.0, 1_000_000, 1400.0, SIGNALS, set(), redistribute, {}, _multiplier)
        plan = _plan(SIGNALS, redistribute=redistribute)
        assert [r["final_alloc"] for r in plan["rows"]] == [r["final_alloc"] for r in before]
        assert not plan["unknown"]


def test_missing_signal_is_unknown_not_estimated_and_not_redistributed():
    for missing in ("QQQ", "TQQQ", "NVDA"):
        for label in (None, "-", "", "계산 실패: timeout"):
            signals = dict(SIGNALS)
            if label is None:
                signals.pop(missing)
            else:
                signals[missing] = label
            for redistribute in (True, False):
                plan = _plan(signals, redistribute=redistribute)
                row = _rows(plan)[missing]
                assert row["signal_unknown"] and row["multiplier"] == 0.0 and row["final_alloc"] == 0.0
                assert row["rec_shares"] == 0 and row["status"] == UNKNOWN_SIGNAL_STATUS
                assert math.isnan(plan["alloc"][missing]) and plan["unknown"] == [missing]
                # The other rows get exactly what they would get if the unknown row were not planned at all.
                others = _holdings()[_holdings()["티커"] != missing]
                eligible = prepare_rebalance_holdings(others)
                expected = build_rebalance_plan(eligible, 100.0, 1_000_000, 1400.0, SIGNALS, set(), redistribute, {},
                                                _multiplier)
                got = {t: r["final_alloc"] for t, r in _rows(plan).items() if t != missing}
                assert got == {r["ticker"]: r["final_alloc"] for r in expected}


def test_signals_from_another_account_scope_are_all_unknown():
    plan = _plan(SIGNALS, scope_valid=False)
    assert plan["unknown"] == sorted(SIGNALS)
    assert all(r["final_alloc"] == 0.0 for r in plan["rows"])
    assert plan["account_scope"] == "scope-a"


def test_always_invest_still_overrides_ordinary_waits():
    signals = dict(SIGNALS, SPY="⏸️평단 위: 눌림 대기")
    plan = _plan(signals, always={"SPY"})
    assert _rows(plan)["SPY"]["multiplier"] == 1.0


def test_always_invest_never_overrides_safety_codes():
    for code in sorted(ALWAYS_INVEST_SAFETY_CODES):
        decision = {"decision_code": code, "dec": f"label {code}"}
        signals = dict(SIGNALS, SPY=decision["dec"])
        plan = _plan(signals, always={"SPY"}, decisions={"SPY": decision})
        row = _rows(plan)["SPY"]
        assert row["multiplier"] == decision_signal_multiplier(decision, "core"), code
        assert "항상투자 보류" in row["tap_disp"]


def test_always_invest_with_missing_signal_stays_unknown():
    signals = dict(SIGNALS)
    signals.pop("SPY")
    row = _rows(_plan(signals, always={"SPY"}))["SPY"]
    assert row["signal_unknown"] and row["final_alloc"] == 0.0
