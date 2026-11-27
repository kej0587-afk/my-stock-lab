"""Synthetic path tests; no network and no production-policy edits."""

from dataclasses import replace
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from soxl_drawdown_engine import (
    DEFAULT, entry_ledger, equity_curve, run_study, simulate_trade, summarize, validate_prices,
)


def bars(rows):
    frame = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], dtype=float,
                         index=pd.bdate_range("2024-01-01", periods=len(rows)))
    frame["Dividends"] = 0.
    frame["Stock Splits"] = 0.
    return frame


def test_previous_reference_excludes_signal_close_and_fill_is_next_open():
    frame = bars([(100, 100, 100, 100), (100, 110, 70, 79), (75, 90, 74, 85)])
    entries, _ = entry_ledger(frame, "previous_close", "close_confirmed")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["reference_price"] == 100 and entry["trigger"] == 80
    assert entry["signal_date"] == "2024-01-02"
    assert entry["entry_date"] == "2024-01-03" and entry["entry_raw"] == 75


def test_20_day_reference_is_shifted_has_full_warmup_and_not_all_time_high():
    frame = bars([(500, 500, 500, 500)] + [(100, 100, 100, 100)] * 20 + [(100, 200, 70, 79)])
    entries, signals = entry_ledger(frame, "previous_20_highest_close", "close_confirmed")
    assert entries[0]["entry_index"] == 21 and entries[0]["reference_price"] == 500
    assert signals[-1]["reference_price"] == 100  # oldest close and today's high excluded
    assert not entry_ledger(frame.iloc[:20], "previous_20_highest_close", "close_confirmed")[1]


def test_intraday_touch_uses_known_limit_not_daily_close():
    frame = bars([(100, 100, 100, 100), (95, 110, 79, 90), (90, 90, 85, 89)])
    entries, _ = entry_ledger(frame, "previous_close", "intraday_touch")
    entry = entries[0]
    assert entry["entry_raw"] == 80 and not entry["entry_at_open"]
    trade = simulate_trade(frame, entry, .10)
    assert trade["uncertain_entry_high"] == 1
    assert trade["exit_index"] == 2 and trade["exit_reason"] == "target_gap"


def test_gap_down_entry_gets_open_and_stop_can_gap_beyond_ten_percent():
    frame = bars([(100, 100, 100, 100), (70, 73, 69, 71), (50, 55, 45, 50)])
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    assert entry["entry_raw"] == 70 and entry["entry_at_open"]
    trade = simulate_trade(frame, entry, .20)
    assert trade["exit_reason"] == "stop_gap" and trade["exit_raw"] == 50
    assert trade["net_return"] < -.28


def test_both_hit_stop_first_and_gap_target_no_improvement():
    frame = bars([(100, 100, 100, 100), (80, 90, 70, 80)])
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    trade = simulate_trade(frame, entry, .10)
    assert trade["exit_reason"] == "stop_both"
    assert trade["both_hit_sessions"] == 1 and not trade["target_hit"]
    frame = bars([(100, 100, 100, 100), (80, 81, 79, 80), (99, 101, 98, 100)])
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    trade = simulate_trade(frame, entry, .10)
    assert trade["exit_reason"] == "target_gap"
    assert trade["exit_raw"] == trade["target_price"] < 99


def test_unknown_entry_high_is_not_target_but_stop_counts():
    frame = bars([(100, 100, 100, 100), (95, 100, 60, 90)])
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    trade = simulate_trade(frame, entry, .10)
    assert trade["exit_reason"] == "stop" and trade["uncertain_entry_high"] == 1


def test_identical_entries_lockout_independent_of_exit_and_costs():
    frame = bars([(100, 100, 100, 100)] * 20 + [(80, 90, 79, 81)] * 40)
    result = run_study(frame)
    trades = result["trades"]
    for _, group in trades.groupby(["reference", "mode"]):
        first = group[group.target == .10].reset_index(drop=True)
        second = group[group.target == .20].reset_index(drop=True)
        fields = ["entry_date", "entry_fill", "cash_amount", "units", "entry_index"]
        pd.testing.assert_frame_equal(first[fields], second[fields])
        assert first.entry_index.diff().dropna().ge(10).all()
    assert "common_lockout" in set(result["signals"].status)


def test_end_of_data_and_no_next_open_are_explicit():
    frame = bars([(100, 100, 100, 100), (80, 81, 79, 80)])
    entries, signals = entry_ledger(frame, "previous_close", "close_confirmed")
    assert not entries and signals[0]["status"] == "unfilled_no_next_open"
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    trade = simulate_trade(frame, entry, .20)
    assert trade["exit_reason"] == "data_end" and trade["net_return"] < 0


def test_horizon_dividends_net_profit_without_target_and_mtm_drawdown():
    frame = bars([(100, 100, 100, 100), (80, 82, 79, 80), (80, 82, 73, 74), (82, 84, 81, 83)])
    p = replace(DEFAULT, hold_sessions=3)
    frame.loc[frame.index[1], "Dividends"] = 10  # buyer on ex-date gets none
    frame.loc[frame.index[2], "Dividends"] = .5
    entry = entry_ledger(frame, "previous_close", "intraday_touch", p)[0][0]
    trade = simulate_trade(frame, entry, .20, p)
    assert trade["exit_reason"] == "horizon" and trade["holding_sessions"] == 3
    assert trade["dividends"] == pytest.approx(entry["units"] * .5)
    curve = equity_curve(frame, [trade], p)
    assert curve.drawdown.min() < -.006
    assert curve.equity.iloc[-1] == pytest.approx(p.capital + trade["net_pnl"])
    summary = summarize("previous_close", "intraday_touch", .20, [trade], curve)
    assert summary["target_hit_rate"] == 0 and summary["net_win_rate"] == 1


def test_prefix_entry_schedule_has_no_future_dependence():
    frame = bars([(100, 100, 100, 100)] * 20 + [(79, 110, 60, 79)] * 40)
    for reference in ("previous_close", "previous_20_highest_close"):
        for mode in ("close_confirmed", "intraday_touch"):
            full, _ = entry_ledger(frame, reference, mode)
            for n in range(22, len(frame)):
                prefix, _ = entry_ledger(frame.iloc[:n], reference, mode)
                assert prefix == [e for e in full if e["entry_index"] < n]


@pytest.mark.parametrize("bad", ["nan", "bounds", "duplicate", "session", "split"])
def test_rejects_missing_bad_or_unadjusted_data(bad):
    frame = bars([(100, 101, 99, 100), (100, 101, 99, 100)])
    expected = frame.index
    if bad == "nan":
        frame.iloc[1, 0] = np.nan
    elif bad == "bounds":
        frame.iloc[1, 1] = 90
    elif bad == "duplicate":
        frame.index = [frame.index[0]] * 2
    elif bad == "session":
        expected = expected[:1]
    else:
        frame.iloc[1, :4] /= 3
        frame.loc[frame.index[1], "Stock Splits"] = 3
    with pytest.raises(ValueError):
        validate_prices(frame, expected)


def test_split_adjusted_prices_not_adjusted_twice_and_scale_invariant():
    frame = bars([(100, 100, 100, 100)] * 20 + [(79, 85, 78, 79)] * 15)
    frame.loc[frame.index[21], "Stock Splits"] = 15
    validate_prices(frame)
    original = run_study(frame)["summary"]
    frame[["Open", "High", "Low", "Close", "Dividends"]] /= 15
    scaled = run_study(frame)["summary"]
    pd.testing.assert_frame_equal(original, scaled, atol=1e-9)


def test_no_signals_have_missing_rates_not_zero_win_rate():
    result = run_study(bars([(100, 101, 99, 100)] * 30))["summary"]
    assert result.entries.eq(0).all()
    assert result.net_win_rate.isna().all() and result.strategy_mdd.isna().all()


def test_fees_and_slippage_use_actual_fill_and_cash_debit():
    frame = bars([(100, 100, 100, 100), (80, 89, 79, 85)])
    entry = entry_ledger(frame, "previous_close", "intraday_touch")[0][0]
    trade = simulate_trade(frame, entry, .10)
    expected_fill = 80 * 1.001
    expected_units = 10_000 / (expected_fill * 1.0005)
    expected_proceeds = expected_units * (expected_fill * 1.10) * .999 * .9995
    assert entry["entry_fill"] == pytest.approx(expected_fill)
    assert entry["units"] == pytest.approx(expected_units)
    assert trade["net_return"] == pytest.approx(expected_proceeds / 10_000 - 1)


def test_horizon_includes_entry_day_and_close_signal_on_last_lock_day_is_eligible():
    frame = bars([(100, 100, 100, 100)] * 20 + [(80, 82, 79, 80)] * 30)
    entries, _ = entry_ledger(frame, "previous_20_highest_close", "close_confirmed")
    assert entries[0]["entry_index"] == 21
    assert entries[1]["entry_index"] == 31
    assert entries[1]["signal_date"] == str(frame.index[30].date())
    first = simulate_trade(frame, entries[0], .20)
    assert first["exit_index"] == 30 and first["holding_sessions"] == 10


def test_committed_snapshot_offline_replay_and_crlf_are_reproducible(tmp_path):
    import json
    from research_soxl_drawdown import DEFAULT_DIR, replay, sha
    source = tmp_path / "windows_checkout"
    source.mkdir()
    for filename in ("prices.csv", "data_manifest.json"):
        content = (DEFAULT_DIR / filename).read_bytes().replace(b"\r\n", b"\n")
        (source / filename).write_bytes(content.replace(b"\n", b"\r\n"))
    output = tmp_path / "output"
    replay(source, output)
    manifest = json.loads((DEFAULT_DIR / "replay_manifest.json").read_text())
    for filename, digest in manifest["output_sha256"].items():
        assert sha(output / filename) == digest


def test_snapshot_corruption_is_rejected_before_replay(tmp_path):
    import json
    from research_soxl_drawdown import DEFAULT_DIR, replay
    manifest = json.loads((DEFAULT_DIR / "data_manifest.json").read_text())
    (tmp_path / "data_manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "prices.csv").write_text("corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay(tmp_path)
