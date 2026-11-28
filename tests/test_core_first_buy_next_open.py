import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from core_first_buy_next_open import anonymous_summary, evaluate_event, read_saved_events, paired_conventions


def data():
    days = pd.bdate_range("2024-01-02", periods=65)
    prices = pd.DataFrame({"Open": 100., "Close": 100., "Low": 90.}, index=days)
    return days, prices


def run(prices, days, gate, **kwargs):
    return evaluate_event(prices, days, days[0], gate, completed_through=days[-1],
                          gate_observed_through=days[-1], **kwargs)


def test_next_open_not_signal_close_and_common_end():
    days, prices = data()
    prices.loc[days[1], "Open"] = 110
    prices.loc[days[6], "Open"] = 80
    prices.loc[days[60], "Close"] = 120
    out = run(prices, days, days[5])
    assert out["A_return"] == pytest.approx(120/110-1)
    assert out["B_return"] == pytest.approx(120/80-1)
    assert out["end"] == days[60].date().isoformat()
    assert out["B_holding_sessions"] == 55


@pytest.mark.parametrize("gate_index", [None, 60, 62])
def test_never_open_or_after_horizon_is_cash(gate_index):
    days, prices = data()
    gate = None if gate_index is None else days[gate_index]
    out = run(prices, days, gate, cost_bps=10)
    assert out["status"] == "ok" and out["B_cash"]
    assert out["B_return"] == out["B_mdd"] == out["B_max_loss"] == 0
    assert out["A_return"] == pytest.approx(.999/1.001-1)


@pytest.mark.parametrize("idx,field,status", [(1,"Open","missing_entry_open"),
    (6,"Open","missing_entry_open"), (60,"Close","missing_end_close")])
def test_missing_not_skipped_or_filled(idx, field, status):
    days, prices = data()
    prices.loc[days[idx], field] = np.nan
    assert run(prices, days, days[5])["status"] == status


@pytest.mark.parametrize("field", ["Close", "Low"])
def test_missing_path_does_not_bias_terminal_return_cohort(field):
    days, prices = data()
    prices.loc[days[10], field] = np.nan
    result = run(prices, days, None)
    assert result["status"] == "ok" and result["A_return"] == 0
    assert result["A_path"] == "missing" and result["A_mdd"] is None
    assert result["A_max_loss"] is None


def test_missing_row_does_not_change_horizon():
    days, prices = data()
    assert run(prices.drop(days[1]), days, None)["status"] == "missing_entry_open"
    out = evaluate_event(prices, days, days[5], None, completed_through=days[-1])
    assert out["status"] == "incomplete_horizon"


def test_mdd_and_max_entry_loss_are_different():
    days, prices = data()
    prices.loc[days[2], "Close"] = 150
    out = run(prices, days, None)
    assert out["A_mdd"] == pytest.approx(100/150-1)
    assert out["A_max_loss"] == pytest.approx(-.1)


def test_explicit_holiday_schedule_is_respected():
    days, prices = data()
    sessions = days.delete(1)
    out = run(prices, sessions, None)
    assert out["A_entry"] == days[2].date().isoformat()
    assert out["end"] == days[61].date().isoformat()


def test_unknown_or_pre_signal_gate_rejected():
    days, prices = data()
    assert run(prices, days, days[0])["status"] == "invalid_event_date"
    with pytest.raises(ValueError):
        run(prices, days, None, cost_bps=-1)


def test_private_export_parser_and_public_summary(tmp_path):
    p = tmp_path / "private.md"
    p.write_text('| TEST | US | 2024-01-02 | 미개방(자료 끝까지) |  |  |  |  | 예 | 미확인 |\n', encoding="utf-8")
    saved = read_saved_events(p)
    assert saved[0]["gate"] is None
    days, prices = data()
    row = {**run(prices, days, None), "ticker": "PRIVATE", "kind": "ETF"}
    summary = anonymous_summary([row, {"kind":"stock", "status":"incomplete_horizon"}])
    assert summary["groups"]["ETF"]["cash_B"] == 1
    assert summary["groups"]["stock"]["endpoint_valid"] == 0
    assert "PRIVATE" not in str(summary)


def test_unknown_gate_history_not_treated_as_confirmed_cash():
    days, prices = data()
    result = evaluate_event(prices, days, days[0], None, completed_through=days[-1],
                            gate_observed_through=days[30])
    assert result["status"] == "unknown_gate_coverage"


@pytest.mark.parametrize("gate", ["2024-99-99", "unknown", ""])
def test_bad_gate_date_does_not_become_cash(tmp_path, gate):
    p = tmp_path / "bad.md"
    p.write_text(f'| TEST | US | 2024-01-02 | {gate} |  |  |  |  | 예 | 미확인 |\n', encoding="utf-8")
    with pytest.raises(ValueError):
        read_saved_events(p)


def test_risk_comparison_uses_paired_complete_paths():
    days, prices = data()
    prices.loc[days[2], "Low"] = np.nan
    row = {**run(prices, days, days[5]), "kind":"stock"}
    summary = anonymous_summary([row])["groups"]["stock"]
    assert summary["endpoint_valid"] == 1 and summary["risk_pairs"] == 0
    assert summary["A_mdd"]["count"] == summary["B_mdd"]["count"] == 0


def test_paired_conventions_use_same_input_and_exclude_short_endpoint():
    days, prices = data()
    prices.loc[days[1], "Open"] = 110
    prices.loc[days[2], "Open"] = 80
    row = {**run(prices, days, days[1]), "kind":"stock", "ticker":"TEST", "market":"US",
           "signal":days[0], "gate":days[1]}
    out = paired_conventions([row], {"TEST":prices}, {"US":days}, days[-1])
    assert out["stock"]["count"] == 1
    assert out["stock"]["median_pp"]["old"] == 0
    assert out["stock"]["median_pp"]["new"] == pytest.approx((100/110-100/80)*100)
    assert paired_conventions([row], {"TEST":prices}, {"US":days}, days[60]) == {}
