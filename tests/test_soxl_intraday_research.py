import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from soxl_intraday_engine import audit_window, simulate, equity, guard_at, summary, expected_bars
from soxl_drawdown_engine import Protocol


def fixture_rows(rows, touch=False):
    bars = pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"],
                        index=pd.date_range("2026-11-25T14:30Z", periods=len(rows), freq="5min"))
    daily = pd.DataFrame([dict(Open=rows[0][0], High=bars.High.max(), Low=bars.Low.min(),
                               Close=rows[-1][-1], Dividends=0)], index=pd.to_datetime(["2026-11-25"]))
    entry = dict(entry_index=0, entry_date="2026-11-25", entry_at_open=not touch, trigger=100,
                 entry_raw=100, entry_fill=100.1, units=10000/(100.1*1.0005), cash_amount=10000)
    return bars, daily, entry


def test_between_bar_target_then_stop_is_resolved():
    bars, daily, entry = fixture_rows([[100,101,99,100],[100,111,99,110],[110,111,80,85]])
    ten = simulate(bars, daily, entry, .1)
    twenty = simulate(bars, daily, entry, .2)
    assert ten["target_hit"] and ten["net_return"] > 0
    assert not twenty["target_hit"] and twenty["net_return"] < 0
    assert ten["entry_fill"] == twenty["entry_fill"]
    assert ten["units"] == twenty["units"]
    assert ten["exit_time"] < twenty["exit_time"]
    curve = equity(bars, daily, [ten])
    assert curve.equity.iloc[-1] == pytest.approx(100000 + ten["net_pnl"])


def test_same_bar_both_hits_is_not_optimistic():
    bars, daily, entry = fixture_rows([[100,125,80,100]])
    result = simulate(bars, daily, entry, .1)
    assert result["exit_reason"] == "stop_both"
    assert result["both_hit_bars"] == 1


def test_touch_bar_high_not_assumed_after_entry():
    bars, daily, entry = fixture_rows([[105,125,99,101]], touch=True)
    result = simulate(bars, daily, entry, .1)
    assert result["exit_reason"] == "data_end"
    assert result["uncertain_entry_high"] == 1
    assert not result["target_hit"] and result["net_return"] > 0


def test_gap_stop_uses_observed_open():
    bars, daily, entry = fixture_rows([[100,101,99,100],[70,72,65,68]])
    result = simulate(bars, daily, entry, .2)
    assert result["exit_raw"] == 70 and result["exit_reason"] == "stop_gap"
    assert result["net_return"] < -.30


def test_horizon_and_cost_loss():
    bars, daily, entry = fixture_rows([[100,101,99,100]])
    result = simulate(bars, daily, entry, .1, Protocol(hold_sessions=1))
    assert result["exit_reason"] == "horizon" and result["net_return"] < 0


def test_missing_guard_does_not_pass_and_future_is_not_used():
    assert guard_at("2026-11-25T14:30Z", None) == "unknown"
    archive = pd.DataFrame([dict(known_at="2026-11-25T15:00Z", valid_from="2026-11-25T14:00Z",
                                 valid_until="2026-11-25T21:00Z", allowed=True)])
    assert guard_at("2026-11-25T14:30Z", archive) == "unknown"
    assert guard_at("2026-11-25T15:30Z", archive) == "allowed"
    assert guard_at("2026-11-26T15:30Z", archive) == "unknown"
    archive["allowed"] = False
    assert guard_at("2026-11-25T15:30Z", archive) == "blocked"


def test_calendar_early_close_bar_count():
    schedule = pd.DataFrame(dict(open=pd.to_datetime(["2026-11-27T14:30Z"]),
                                 close=pd.to_datetime(["2026-11-27T18:00Z"])))
    expected = expected_bars(schedule)
    assert len(expected) == 42 and str(expected[-1]) == "2026-11-27 17:55:00+00:00"


def test_audit_rejects_missing_nan_and_basis():
    bars, daily, entry = fixture_rows([[100,101,99,100],[100,101,99,100],[100,101,99,100]])
    schedule = pd.DataFrame(dict(open=[bars.index[0]], close=[bars.index[-1]+pd.Timedelta(minutes=5)]), index=daily.index)
    assert audit_window(daily,bars,schedule,entry)[1] == "verified"
    assert audit_window(daily,bars.drop(bars.index[1]),schedule,entry)[1:] == ("missing_regular_5m",1)
    broken = bars.copy()
    broken.loc[bars.index[1],"High"] = float("nan")
    assert audit_window(daily,broken,schedule,entry)[1] == "invalid_ohlc"
    daily.loc[daily.index[0],"Close"] = 103
    assert audit_window(daily,bars,schedule,entry)[1] == "daily_intraday_basis_mismatch"


def test_empty_result_is_unknown_not_zero_success():
    assert summary([],None)["net_win_rate"] is None


def test_replay_frozen_snapshot():
    from research_soxl_intraday import DIRECTORY, PHASE1, verified_protocol, sha
    import json
    manifest = json.loads((DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    assert sha(verified_protocol(DIRECTORY, manifest)) == manifest["protocol_sha256"]
    assert sha(PHASE1 / "prices.csv") == manifest["phase1_price_sha256"]
    for item in manifest["datasets"]:
        if item["rows"]:
            assert sha(DIRECTORY / f"SOXL_{item['interval']}.csv") == item["sha256"]


def test_replay_rejects_missing_or_changed_protocol(tmp_path):
    from research_soxl_intraday import verified_protocol, sha
    protocol = tmp_path / 'protocol.md'
    protocol.write_text('original\n', encoding='utf8')
    manifest = {'protocol_sha256': sha(protocol)}
    assert verified_protocol(tmp_path, manifest) == protocol
    protocol.write_text('changed\n', encoding='utf8')
    with pytest.raises(ValueError, match='hash changed'):
        verified_protocol(tmp_path, manifest)
    protocol.unlink()
    with pytest.raises(ValueError, match='missing'):
        verified_protocol(tmp_path, manifest)


def test_fetch_freezes_protocol_before_collection_without_overwrite(tmp_path, monkeypatch):
    import json
    import yfinance
    from types import SimpleNamespace
    import research_soxl_intraday as runner
    current = tmp_path / 'current.md'
    current.write_text('research rules\n', encoding='utf8')
    monkeypatch.setattr(runner, 'PROTOCOL', current)
    monkeypatch.setattr(yfinance, 'Ticker', lambda symbol: SimpleNamespace(history=lambda **kw: pd.DataFrame()))
    destination = tmp_path / 'snapshot'
    runner.fetch(destination)
    manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf8'))
    current.write_text('later operating note\n', encoding='utf8')
    frozen = runner.verified_protocol(destination, manifest)
    assert frozen.read_text(encoding='utf8') == 'research rules\n'
    with pytest.raises(ValueError, match='immutable snapshot'):
        runner.fetch(destination)
    assert frozen.read_text(encoding='utf8') == 'research rules\n'


def test_research_is_not_imported_by_production():
    root=Path(__file__).resolve().parents[1]
    for path in [root/"app.py", *list((root/"stock_lab_core").glob("*.py"))]:
        assert "soxl_intraday_engine" not in path.read_text(encoding="utf-8")
