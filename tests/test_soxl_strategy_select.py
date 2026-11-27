"""2026-11-27 request 4: three SOXL strategies stay separate; phase-2 win rate stays 미산출."""

import numpy as np
import pandas as pd

from stock_lab_core import soxl_strategy_select as ss


def daily(last):
    idx = pd.bdate_range(end="2026-11-25", periods=30)
    close = np.full(30, 40.0)
    close[-10] = 50.0
    close[-1] = last
    return pd.DataFrame({"Close": close, "Volume": np.r_[np.full(29, 100.0), 250.0]}, index=idx)


def test_drop_rebound_unmet_has_no_prices():
    s = ss.drop_rebound_status(daily(42.0), gate_text="방어우선 · 레버리지 시장방어")
    assert s["met"] is False and s["prices"] == []
    assert "직전 20일 최고 종가 $50.00" in s["summary"] and "−20% 기준선 $40.00" in s["summary"]
    assert "미충족" in s["summary"]


def test_drop_rebound_met_shows_research_prices_only():
    s = ss.drop_rebound_status(daily(39.0), gate_text="g")
    assert s["met"] is True
    names = [p["항목"] for p in s["prices"]]
    assert names == ["가정 진입 기준", "가정 손절", "가정 익절 +10%", "가정 익절 +20%", "최대 보유"]
    assert s["prices"][1]["가격"] == "$35.10"


def test_short_history_is_not_a_signal():
    s = ss.drop_rebound_status(daily(39.0).tail(10), gate_text="g")
    assert s["met"] is None and s["prices"] == []


def test_volume_candidate_reports_facts_without_a_rule():
    s = ss.volume_breakout_status(daily(42.0), gate_text="g")
    assert s["met"] is None and "2.50배" in s["summary"] and "미정" in s["next"]


def test_phase2_win_rate_stays_uncomputed():
    rows = {r["전략"]: r for r in ss.strategy_rows()}
    assert "순서 확정 0건" in rows[ss.DROP]["검증 단계"] and "2차 승률 미산출" in rows[ss.DROP]["검증 단계"]
    assert rows[ss.VOLUME]["검증 단계"] == "진입·청산 규칙 및 성과 검증 전"
    assert ss.DROP_PHASE2["confirmed"] == 0
