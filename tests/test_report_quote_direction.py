"""Synthetic sign regressions, not a reconstruction of the missing night quote."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from stock_lab_core.report_intraday import extended_quote_text
from stock_lab_core.report_quotes import regular_quote_observation, extended_quote_observation, extended_quote_status


def quote():
    return {"symbol": "SOXL", "regularMarketPrice": 100, "regularMarketPreviousClose": 100,
            "regularMarketTime": datetime.fromisoformat("2026-10-29T16:00:00-04:00").timestamp()}


@pytest.mark.parametrize("field,hour", [("post", 6), ("overnight", 10), ("day", 10), ("pre", 18)])
@pytest.mark.parametrize("direction", [-1, 1])
def test_extended_minus_and_plus_713_keep_their_sign(field, hour, direction):
    now = datetime.fromisoformat(f"2026-10-30T{hour:02}:00:00+09:00")
    row = dict(quote(), **{field + "MarketPrice": 100 + direction * 7.13,
        field + "MarketChangePercent": {"raw": direction * 7.13},
        field + "MarketChange": direction * 7.13,
        field + "MarketTime": (now - timedelta(minutes=1)).timestamp()})
    original = deepcopy(row)
    observed = extended_quote_observation(row, "SOXL", now)
    assert observed["return"] == pytest.approx(direction * .0713)
    assert f"{direction * 7.13:+.2f}%" in extended_quote_text({"extended_prices": {"SOXL": observed}}, "SOXL", now)
    assert row == original


@pytest.mark.parametrize("field,hour", [("post", 6), ("overnight", 10), ("day", 10), ("pre", 18)])
@pytest.mark.parametrize("suffix", ["ChangePercent", "Change"])
def test_opposite_provider_sign_is_rejected_not_reversed(field, hour, suffix, caplog):
    now = datetime.fromisoformat(f"2026-10-30T{hour:02}:00:00+09:00")
    row = dict(quote(), **{field + "MarketPrice": 107.13,
        field + "Market" + suffix: -7.13,
        field + "MarketTime": (now - timedelta(minutes=1)).timestamp()})
    assert not extended_quote_observation(row, "SOXL", now)
    assert not extended_quote_observation(row, "SOXL", now, allow_delayed=True)
    assert "시세 부호 불일치" in extended_quote_status(row, "SOXL", now)
    assert "SOXL" in caplog.text and "기준가 100" in caplog.text


def test_regular_decline_and_after_hours_rise_are_not_a_sign_conflict():
    now = datetime.fromisoformat("2026-10-30T06:00:00+09:00")
    row = dict(quote(), regularMarketPrice=92.87, regularMarketChangePercent=-7.13,
               postMarketPrice=92.87 * 1.0713, postMarketChangePercent=7.13,
               postMarketTime=(now - timedelta(minutes=1)).timestamp())
    assert regular_quote_observation(row, "SOXL", now)["return"] == pytest.approx(-.0713)
    assert extended_quote_observation(row, "SOXL", now)["return"] == pytest.approx(.0713)


def test_regular_conflict_cannot_supply_extended_reference():
    now = datetime.fromisoformat("2026-10-30T06:00:00+09:00")
    row = dict(quote(), regularMarketPrice=107.13, regularMarketChangePercent=-7.13)
    assert not regular_quote_observation(row, "SOXL", now)
    assert not extended_quote_observation(row, "SOXL", now)
    assert "시세 부호 불일치" in extended_quote_status(row, "SOXL", now)


def test_missing_direction_fields_preserve_price_based_calculation():
    now = datetime.fromisoformat("2026-10-30T06:00:00+09:00")
    row = dict(quote(), regularMarketPrice=92.87)
    assert regular_quote_observation(row, "SOXL", now)["return"] == pytest.approx(-.0713)


def test_rounded_zero_does_not_cause_false_conflict():
    now = datetime.fromisoformat("2026-10-30T06:00:00+09:00")
    row = dict(quote(), regularMarketPrice=99.999, regularMarketChangePercent=.001)
    assert regular_quote_observation(row, "SOXL", now)["return"] < 0
