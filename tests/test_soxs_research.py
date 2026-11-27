"""Offline synthetic exchange-session fixtures; no account data or production imports."""

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from soxs_research import main, run_study


def fixture(n=65):
    # Synthetic schedule is explicit; the engine must never derive it from prices.
    dates = pd.bdate_range("2026-01-05", periods=n)
    soxs = pd.DataFrame({col: np.full(n, 100.0) for col in ("Open", "High", "Low", "Close")}, index=dates)
    close = np.r_[np.full(49, 100.), np.full(n - 49, 80.)]
    soxx = pd.DataFrame({"Close": close}, index=dates)
    spy = soxx.copy()
    return soxs, soxx, spy, dates


def study(data, **kwargs):
    x, sector, broad, dates = data
    return run_study(x, sector, broad, sessions=dates, completed_through=dates[-1],
                     adjusted_ohlc=True, **kwargs)


def test_next_open_five_sessions_costs_and_no_overlap():
    data = fixture(60)
    x, _, _, dates = data
    x.loc[dates[50], ["Open", "High"]] = [110., 110.]
    result = study(data)
    a, b = (result["cases"][key] for key in ("30", "60"))
    first = a["trades"].iloc[0]
    assert first.signal_date == dates[49] and first.entry_date == dates[50]
    assert first.entry_price == 110 and first.exit_date == dates[54]
    assert first.holding_sessions == 5
    expected = 100 * (1 - .0015) / (110 * (1 + .0015)) - 1
    assert first.net_return == pytest.approx(expected)
    assert a["curve"].loc[dates[50], "soxs_5pct"] == pytest.approx(95000 + 5000 / (110 * 1.0015) * 100)
    assert a["curve"].loc[dates[54], "soxs_5pct"] == pytest.approx(100000 + 5000 * expected)
    assert a["trades"].iloc[1].entry_date == dates[55]
    assert a["summary"]["signal_status_counts"]["blocked_overlap"] == 8
    assert b["trades"].iloc[0].net_return < first.net_return
    pd.testing.assert_frame_equal(a["trades"][["entry_date", "exit_date"]], b["trades"][["entry_date", "exit_date"]])


def test_constant_prices_roundtrip_and_mdd_include_initial_capital():
    result = study(fixture(55))["cases"]["30"]
    trade = result["trades"].iloc[0]
    loss = 1 - .9985 / 1.0015
    assert trade.net_return == pytest.approx(-loss)
    assert trade.cost_amount == pytest.approx(5000 * loss)
    assert result["summary"]["accounts"]["soxs_5pct"]["mdd"] == pytest.approx(-.05 * loss)
    assert result["summary"]["trade_statistics"]["all"]["max_trade_loss"] == pytest.approx(loss)
    assert result["summary"]["accounts"]["cash"] == {"verified": True, "net_return": 0., "mdd": 0.}


def test_rising_soxx_below_ma_is_separate_group():
    data = fixture(55)
    data[1].iloc[48, 0] = 70.
    result = study(data)["cases"]["30"]
    assert result["summary"]["soxx_up_signal_count"] == 1
    assert result["summary"]["trade_statistics"]["soxx_up_signal"]["completed_trades"] == 1


def test_portfolio_hedge_uses_same_risky_sleeve_and_existing_cash():
    data = fixture(55)
    returns = pd.Series(.001, index=data[3], name="PRIVATE_ACCOUNT_NAME")
    result = study(data, portfolio_returns=returns, cash_weight=.2)["cases"]["30"]
    curve = result["curve"]
    risky = 80000 * 1.001 ** np.arange(1, 56)
    np.testing.assert_allclose(curve.portfolio_cash, risky + 20000)
    np.testing.assert_allclose(curve.portfolio_hedge - curve.portfolio_cash, curve.soxs_5pct - curve.cash)
    assert "PRIVATE_ACCOUNT_NAME" not in repr(result)
    with pytest.raises(ValueError, match="cash fraction"):
        study(data, portfolio_returns=returns, cash_weight=.04)
    with pytest.raises(ValueError, match="cover every"):
        study(data, portfolio_returns=returns.iloc[1:], cash_weight=.2)


def test_missing_signal_day_is_not_forward_filled_or_skipped_in_ma():
    data = fixture(60)
    data = (data[0], data[1].drop(data[3][40]), data[2], data[3])
    result = study(data)["cases"]["30"]
    assert result["signals"].empty
    assert result["summary"]["signal_unavailable_sessions"] == 60


def test_hedge_losses_use_remaining_cash_without_blocking_standalone():
    data = fixture(60)
    returns = pd.Series(0., index=data[3])
    hedged = study(data, portfolio_returns=returns, cash_weight=.05)["cases"]["30"]
    standalone = study(data)["cases"]["30"]
    pd.testing.assert_series_equal(hedged["curve"].soxs_5pct, standalone["curve"].soxs_5pct)
    trades = hedged["trades"]
    assert len(trades) == 2
    assert trades.iloc[1].hedge_allocation == pytest.approx(5000 * .9985 / 1.0015)
    assert trades.iloc[1].allocation == 5000
    assert hedged["curve"].portfolio_hedge.min() >= 95000


@pytest.mark.parametrize("bad", [0., np.nan, -1., np.inf])
def test_invalid_next_open_skips_without_fallback(bad):
    data = fixture(56)
    data[0].loc[data[3][50], "Open"] = bad
    result = study(data)["cases"]["30"]
    assert result["signals"].iloc[0].status == "excluded_missing_or_zero_open"
    assert result["trades"].iloc[0].entry_date == data[3][51]


def test_missing_holding_day_excludes_trade_and_does_not_shorten_hold():
    data = fixture(55)
    data = (data[0].drop(data[3][52]), *data[1:])
    result = study(data)["cases"]["30"]
    trade = result["trades"].iloc[0]
    assert trade.status == "excluded_missing_ohlc" and trade.exit_date == data[3][54]
    assert pd.isna(result["curve"].loc[data[3][52], "soxs_5pct"])
    assert result["summary"]["trade_statistics"]["all"]["completed_trades"] == 0
    assert result["summary"]["accounts"]["soxs_5pct"]["mdd"] is None
    assert result["summary"]["mark_to_market"]["accounts"]["soxs_5pct"]["mdd"] is None


def test_missing_exit_never_invents_cash_or_new_trade():
    data = fixture(60)
    data[0].loc[data[3][54], "Close"] = np.nan
    result = study(data)["cases"]["30"]
    assert len(result["trades"]) == 1
    assert result["curve"].soxs_5pct.iloc[54:].isna().all()
    assert "blocked_unknown_cash" in result["summary"]["signal_status_counts"]


def test_incomplete_position_is_not_a_completed_trade_but_endpoint_mtm_is_available():
    result = study(fixture(53))["cases"]["30"]
    assert result["trades"].iloc[0].status == "incomplete_end"
    assert result["trades"].iloc[0].holding_sessions == 3
    assert pd.isna(result["trades"].iloc[0].exit_date)
    assert result["summary"]["accounts"]["soxs_5pct"]["net_return"] is None
    assert result["curve"].soxs_5pct.notna().all()  # provisional MTM, not a fake realized exit
    mtm = result["summary"]["mark_to_market"]
    assert mtm["terminal_open_position"] is True
    expected_loss = 1 - .9985 / 1.0015
    assert mtm["accounts"]["soxs_5pct"]["net_return"] == pytest.approx(-.05 * expected_loss)
    assert mtm["accounts"]["soxs_5pct"]["mdd"] == pytest.approx(-.05 * expected_loss)
    assert mtm["terminal_exit_cost"] == pytest.approx(5000 / 1.0015 * .0015)
    assert result["summary"]["trade_statistics"]["all"]["completed_trades"] == 0
    assert len(result["mark_to_market_curve"]) == len(result["curve"])


def test_terminal_hedge_liquidation_is_separate_and_missing_still_blocks_mtm():
    data = fixture(53)
    result = study(data, portfolio_returns=pd.Series(0., index=data[3]), cash_weight=.2)["cases"]["30"]
    mtm = result["summary"]["mark_to_market"]
    assert mtm["accounts"]["portfolio_hedge"] == mtm["accounts"]["soxs_5pct"]
    assert mtm["terminal_hedge_exit_cost"] == mtm["terminal_exit_cost"]
    data[0].loc[data[3][51], "High"] = np.nan
    missing = study(data)["cases"]["30"]
    assert missing["trades"].iloc[0].status == "incomplete_end_missing_ohlc"
    assert missing["summary"]["mark_to_market"]["accounts"]["soxs_5pct"]["net_return"] is None


def test_future_prices_cannot_change_prior_entry_or_curve():
    data = fixture(60)
    full = study(data)["cases"]["30"]
    partial = study(tuple(frame.iloc[:52] for frame in data[:3]) + (data[3][:52],))["cases"]["30"]
    pd.testing.assert_frame_equal(partial["curve"], full["curve"].iloc[:52])
    assert partial["trades"].iloc[0].entry_date == full["trades"].iloc[0].entry_date
    data[0].loc[data[3][50], "High"] = np.nan  # unavailable AFTER entry open
    altered = study(data)["cases"]["30"]
    assert altered["trades"].iloc[0].entry_date == full["trades"].iloc[0].entry_date
    assert altered["trades"].iloc[0].status == "excluded_missing_ohlc"


def test_uncompleted_bars_are_ignored_and_final_signal_has_no_next_open():
    x, sector, broad, dates = fixture(60)
    result = run_study(x, sector, broad, sessions=dates, completed_through=dates[49], adjusted_ohlc=True)["cases"]["30"]
    assert result["trades"].empty
    assert result["signals"].iloc[-1].status == "no_next_open"
    assert result["curve"].index[-1] == dates[49]


def test_calendar_holiday_is_not_counted_as_holding_day():
    x, sector, broad, dates = fixture(56)
    dates = dates.delete(52)
    result = study((x.loc[dates], sector.loc[dates], broad.loc[dates], dates))["cases"]["30"]
    assert result["trades"].iloc[0].exit_date == dates[54]


def test_input_contract_and_empty_sample():
    x, sector, broad, dates = fixture(55)
    with pytest.raises(ValueError, match="adjusted"):
        run_study(x, sector, broad, sessions=dates, completed_through=dates[-1], adjusted_ohlc=False)
    with pytest.raises(ValueError, match="columns"):
        study((x.drop(columns="High"), sector, broad, dates))
    with pytest.raises(ValueError, match="unique"):
        study((x, sector, broad, dates[::-1]))
    sector["Close"] = 100.
    result = study((x, sector, broad, dates))["cases"]["30"]
    assert result["summary"]["trade_statistics"]["all"]["max_trade_loss"] is None
    assert result["summary"]["accounts"]["soxs_5pct"]["mdd"] == 0.


def test_krw_conversion_leaves_cash_fixed_and_uses_entry_open_exit_close():
    data = fixture(55)
    fx = pd.DataFrame({"Open": 1000., "Close": 1000.}, index=data[3])
    fx.loc[data[3][54], "Close"] = 1100.
    result = study(data, usdkrw=fx)
    case = result["cases"]["30"]
    trade = case["trades"].iloc[0]
    assert result["currency"] == "KRW"
    assert trade.entry_price == 100000 and trade.exit_price == 110000
    assert trade.net_return == pytest.approx(1.1 * .9985 / 1.0015 - 1)
    assert case["curve"].cash.eq(100000).all()
    fx.loc[data[3][50], "Open"] = np.nan
    missing = study(data, usdkrw=fx)["cases"]["30"]
    assert missing["signals"].iloc[0].status == "excluded_missing_or_zero_open"


def test_missing_fx_close_never_forward_fills_or_certifies_endpoint():
    data = fixture(53)
    fx = pd.DataFrame({"Open": 1000., "Close": 1000.}, index=data[3])
    fx.loc[data[3][51], "Close"] = np.nan
    result = study(data, usdkrw=fx)["cases"]["30"]
    assert pd.isna(result["curve"].loc[data[3][51], "soxs_5pct"])
    assert result["summary"]["mark_to_market"]["accounts"]["soxs_5pct"]["mdd"] is None


def test_evaluation_start_keeps_warmup_but_does_not_import_prior_position():
    data = fixture(60)
    result = study(data, evaluation_start=data[3][49])["cases"]["30"]
    assert result["signals"].iloc[0].signal_date == data[3][49]
    assert result["trades"].iloc[0].entry_date == data[3][50]
    assert result["curve"].iloc[0].soxs_5pct == 100000


def test_cli_only_emits_aggregate_results(tmp_path, capsys):
    x, sector, broad, dates = fixture(55)
    argv = []
    for name, frame in (("soxs", x), ("soxx", sector), ("spy", broad)):
        path = tmp_path / (name + ".csv")
        frame.to_csv(path, index_label="Date")
        argv.extend(["--" + name, str(path)])
    path = tmp_path / "sessions.csv"
    pd.DataFrame({"Date": dates}).to_csv(path, index=False)
    main(argv + ["--sessions", str(path), "--completed-through", str(dates[-1].date()), "--adjusted-ohlc"])
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert "curve" not in output and "portfolio_returns" not in output
    assert json.loads(output)["cases"]["30"]["trade_statistics"]["all"]["completed_trades"] == 1
