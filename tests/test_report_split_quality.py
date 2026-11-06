from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_price_quality import validate_report_prices
from stock_lab_core.report_holdings import holding_estimate
from stock_lab_core.report_evidence import price_observation

NOW = datetime.fromisoformat("2026-11-06T09:43:00+09:00")


def history(previous=450., current=131.79):
    dates = pd.bdate_range(end="2026-11-05", periods=30)
    closes = [previous] * 29 + [current]
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": 100.}, index=dates)


def quote(previous=150., current=131.79):
    return {"symbol": "SOXX", "regularMarketPrice": current,
            "regularMarketPreviousClose": previous,
            "regularMarketTime": pd.Timestamp("2026-11-05T16:00:00-05:00").timestamp()}


def test_verified_split_repairs_entire_basis_without_mutating_decision_frame():
    original = history()
    before = original.copy(deep=True)
    frames, notes, issues, _ = validate_report_prices({"SOXX": original}, {"SOXX": quote()}, NOW)
    pd.testing.assert_frame_equal(original, before)
    fixed = frames["SOXX"]
    assert fixed.Close.iloc[-2] == 150
    assert fixed.Volume.iloc[-2] == 300
    assert fixed.Volume.iloc[-1] == 100
    assert notes and not issues
    obs = price_observation(fixed, "SOXX", NOW)
    assert obs["return"] == pytest.approx(-.1214)
    assert obs["return_5d"] == pytest.approx(-.1214)
    again, _, errors, _ = validate_report_prices(frames, {"SOXX": quote()}, NOW)
    pd.testing.assert_frame_equal(fixed, again["SOXX"])
    assert not errors


def test_already_adjusted_and_xlc_are_unchanged():
    frames = {"SOXX": history(150), "XLC": history(100, 99.41)}
    result, notes, issues, _ = validate_report_prices(frames, {"SOXX": quote()}, NOW, etf_tickers=("XLC",))
    for key in frames:
        pd.testing.assert_frame_equal(result[key], frames[key])
    assert not notes and not issues


def test_unknown_or_unverified_outlier_is_not_guessed():
    frames, _, issues, _ = validate_report_prices({"SOXX": history()}, {}, NOW)
    assert frames["SOXX"].empty and issues
    frames, _, issues, _ = validate_report_prices({"OTHER": history()}, {}, NOW, etf_tickers=("OTHER",))
    assert frames["OTHER"].empty and issues


def test_true_large_loss_with_matching_quote_is_not_falsely_corrected():
    original = history(150, 40)
    frames, _, issues, _ = validate_report_prices({"SOXX": original}, {"SOXX": quote(150, 40)}, NOW)
    pd.testing.assert_frame_equal(frames["SOXX"], original)
    assert not issues


def test_adjusted_close_ratio_is_independent_basis_evidence():
    original = history()
    original["Adj Close"] = [150.] * 29 + [131.79]
    frames, _, issues, _ = validate_report_prices({"SOXX": original}, {}, NOW)
    assert frames["SOXX"].Close.iloc[-2] == 150 and not issues
    assert frames["SOXX"]["Adj Close"].iloc[-2] == 150


def test_raw_adjusted_column_is_not_left_on_old_scale():
    original = history()
    original["Adj Close"] = original["Close"]
    frames, _, issues, _ = validate_report_prices({"SOXX": original}, {"SOXX": quote()}, NOW)
    assert not issues
    assert frames["SOXX"].Close.iloc[-2] == frames["SOXX"]["Adj Close"].iloc[-2] == 150


def test_leveraged_reference_below_minus_100_is_invalid_not_clipped():
    message, leveraged = holding_estimate({"ticker": "SOXL"}, {
        "SOXX": {"date": "2026-11-05", "return": -.7072},
        "SOXL": {"date": "2026-11-05"}}, {"US": "2026-11-05"}, NOW)
    assert leveraged and "무효" in message and "-212" not in message


def test_mixed_adjusted_history_uses_only_verified_daily_quote():
    original = history()
    original.loc[original.index[:-4], ["Open", "High", "Low", "Close"]] /= 3
    before = original.copy(deep=True)
    frames, notes, issues, daily = validate_report_prices({"SOXX": original}, {"SOXX": quote()}, NOW)
    assert frames["SOXX"].empty and issues and notes
    assert daily["SOXX"]["return"] == pytest.approx(-.1214)
    assert daily["SOXX"]["return_5d"] is None
    pd.testing.assert_frame_equal(original, before)


def test_missing_split_day_bar_does_not_hide_verified_daily_quote():
    frames, _, issues, daily = validate_report_prices({"SOXX": history().iloc[:-1]}, {"SOXX": quote()}, NOW)
    assert frames["SOXX"].empty and issues
    assert daily["SOXX"]["date"] == "2026-11-05"
    assert daily["SOXX"]["previous_date"] == "2026-11-04"


def test_unresolved_split_cannot_pollute_longer_returns_next_day():
    original = history()
    original.loc[pd.Timestamp("2026-11-06")] = original.iloc[-1]
    later = datetime.fromisoformat("2026-11-07T09:43:00+09:00")
    frames, _, issues, daily = validate_report_prices({"SOXX": original}, {}, later)
    assert frames["SOXX"].empty and issues and not daily


def test_report_pipeline_uses_daily_quote_and_excludes_mixed_medium_term():
    from stock_lab_core.report_context import collect_report_context
    mixed = history()
    mixed.loc[mixed.index[:-4], ["Open", "High", "Low", "Close"]] /= 3
    frames = {"SOXX": mixed, "^GSPC": history(100, 99), "^IXIC": history(100, 98),
              "^DJI": history(100, 99), "XLC": history(100, 99.41)}
    context = collect_report_context(now=NOW, price_frames=frames, quote_data={"US": {"SOXX": quote()}},
                                     economic_releases=[], calendar={"events": [], "sources": []})
    assert context["prices"]["SOXX"]["return"] == pytest.approx(-.1214)
    assert context["prices"]["SOXX"]["return_5d"] is None
    assert all(r["Ticker"] != "SOXX" for r in context["closed_flow_rows"])
    sector = next(r for r in context["sector_rows"] if r["Ticker"] == "SOXX")
    assert sector["1일수익률"] == pytest.approx(-.1214)
    assert "3개월수익률" not in sector
