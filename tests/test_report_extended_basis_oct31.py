"""Keep a small after-hours bounce separate from a full-session loss."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from stock_lab_core.report_account import cumulative_account_metrics
from stock_lab_core.report_dashboard import current_state_lines
from stock_lab_core.report_intraday import extended_day_comparison, extended_quote_text
from stock_lab_core.report_quotes import extended_quote_observation
from stock_lab_core.report_session import market_session_states


NOW = datetime.fromisoformat("2026-10-31T07:16:00+09:00")
CASES = [("SOXX", 513.86, 471.51, 472.21, "-8.11%"),
         ("DRAM", 51.75, 48.01, 48.14, "-6.98%")]


def quote(ticker, previous, close, latest, now=NOW, field="post"):
    return {"symbol": ticker, "regularMarketPrice": close,
            "regularMarketPreviousClose": previous,
            "regularMarketTime": datetime.fromisoformat("2026-10-30T16:00:00-04:00").timestamp(),
            field + "MarketTime": (now - timedelta(minutes=1)).timestamp(),
            field + "MarketPrice": latest,
            field + "MarketChangePercent": (latest / close - 1) * 100}


def context(row, now=NOW):
    ticker = row["symbol"]
    observed = extended_quote_observation(row, ticker, now)
    return {"sessions": {"KR": "2026-10-30", "US": "2026-10-30"},
            "prices": {ticker: {"date": "2026-10-30", "previous_date": "2026-10-29",
                                "price": row["regularMarketPrice"],
                                "return": row["regularMarketPrice"] / row["regularMarketPreviousClose"] - 1}},
            "extended_prices": {ticker: observed}}


@pytest.mark.parametrize("ticker,previous,close,latest,expected", CASES)
def test_screenshot_prices_have_negative_daily_and_positive_after_hours_returns(ticker, previous, close, latest, expected):
    row = quote(ticker, previous, close, latest)
    ctx = context(row)
    original = deepcopy(ctx)
    obs = ctx["extended_prices"][ticker]
    assert obs["return"] == pytest.approx(latest / close - 1)
    assert obs["return"] > 0
    basis = extended_day_comparison(ctx, ticker, obs, NOW)
    assert basis["return"] == pytest.approx(latest / previous - 1)
    assert basis["base_date"] == "2026-10-29"
    rendered = extended_quote_text(ctx, ticker, NOW)
    assert "애프터마켓 전일 종가 대비 " + expected in rendered
    assert "마감 후 +" in rendered and "2026-10-30 정규장 종가 대비" in rendered
    assert f"USD {latest:.2f}" in rendered
    assert ctx == original


def test_top_current_line_cannot_advertise_a_full_day_decline_as_a_gain():
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21))
    line = current_state_lines(ctx, market_session_states(NOW), NOW, {})[1]
    assert "SOXX 전일 종가 대비 -8.11% / 마감 후 +0.15%" in line


@pytest.mark.parametrize("field,now", [("pre", "2026-11-02T18:10:00+09:00"),
                                      ("overnight", "2026-11-02T11:00:00+09:00")])
def test_next_session_premarket_is_not_compounded_with_the_previous_day(field, now):
    at = datetime.fromisoformat(now)
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21, at, field), at)
    observed = ctx["extended_prices"]["SOXX"]
    assert observed
    basis = extended_day_comparison(ctx, "SOXX", observed, at)
    assert basis["return"] == pytest.approx(472.21 / 471.51 - 1)
    assert not basis["postmarket"]
    assert "직전 정규장 종가(2026-10-30) 대비" in extended_quote_text(ctx, "SOXX", at)


def test_daily_basis_survives_missing_history_using_verified_quote_metadata():
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21))
    ctx["prices"] = {}
    assert "전일 종가 대비 -8.11%" in extended_quote_text(ctx, "SOXX", NOW)


def test_legacy_observation_uses_only_a_matching_regular_close():
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21))
    obs = ctx["extended_prices"]["SOXX"]
    for key in list(obs):
        if key.startswith("regular_"):
            obs.pop(key)
    assert "전일 종가 대비 -8.11%" in extended_quote_text(ctx, "SOXX", NOW)
    ctx["prices"]["SOXX"]["price"] = 500
    rendered = extended_quote_text(ctx, "SOXX", NOW)
    assert "전일 종가 대비 미연결" in rendered
    assert "마감 후 +0.15%" in rendered


def test_missing_regular_comparison_never_becomes_zero_or_an_unlabelled_gain():
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21))
    ctx["prices"] = {}
    for key in list(ctx["extended_prices"]["SOXX"]):
        if key.startswith("regular_"):
            ctx["extended_prices"]["SOXX"].pop(key)
    rendered = extended_quote_text(ctx, "SOXX", NOW)
    assert "전일 종가 대비 미연결" in rendered and "마감 후 +0.15%" in rendered
    assert "전일 종가 대비 +0.00%" not in rendered
    assert "SOXX 전일 종가 대비 미연결 / 마감 후 +0.15%" in current_state_lines(ctx, market_session_states(NOW), NOW, {})[1]


@pytest.mark.parametrize("ticker,previous,close,latest,expected", CASES)
def test_account_keeps_exactly_one_compound_not_the_new_display_return_twice(ticker, previous, close, latest, expected):
    ctx = context(quote(ticker, previous, close, latest))
    original = deepcopy(ctx)
    held = [{"ticker": ticker, "current_w": 100}]
    result = cumulative_account_metrics(held, ctx, market_session_states(NOW), NOW)
    assert result["total"] == pytest.approx((latest / previous - 1) * 100)
    assert result["coverage"] == 100
    assert ctx == original


def test_delayed_quote_is_labelled_and_excluded_from_the_current_headline():
    ctx = context(quote("SOXX", 513.86, 471.51, 472.21))
    obs = ctx["extended_prices"].pop("SOXX")
    obs.update(as_of=(NOW - timedelta(minutes=25)).isoformat(), delayed=True)
    ctx["extended_reference_prices"] = {"SOXX": obs}
    rendered = extended_quote_text(ctx, "SOXX", NOW)
    assert "전일 종가 대비 -8.11%" in rendered
    assert "지연 참고·현재 합산 제외" in rendered
    assert "8.11" not in current_state_lines(ctx, market_session_states(NOW), NOW, {})[1]


def test_postmarket_basis_after_us_daylight_saving_time_ends():
    at = datetime.fromisoformat("2026-11-07T07:16:00+09:00")
    row = quote("SOXX", 513.86, 471.51, 472.21, at)
    row["regularMarketTime"] = datetime.fromisoformat("2026-11-06T16:00:00-05:00").timestamp()
    obs = extended_quote_observation(row, "SOXX", at)
    ctx = {"sessions": {"US": "2026-11-06"}, "extended_prices": {"SOXX": obs}}
    assert "기준 종가 2026-11-05" in extended_quote_text(ctx, "SOXX", at)
    assert "2026-11-06 정규장 종가 대비" in extended_quote_text(ctx, "SOXX", at)
    assert "전일 종가 대비 -8.11%" in extended_quote_text(ctx, "SOXX", at)
