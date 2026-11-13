"""Session/observation checks must not mutate decision inputs."""

from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock

import pytest

from stock_lab_core.leveraged_quote_view import quote_evidence, render_quote_evidence
from stock_lab_core.report_quotes import extended_quote_observation, extended_quote_status


def payload(ticker, clock, field):
    at = datetime.fromisoformat(clock)
    close = at.replace(hour=16, minute=0)
    if at.hour < 16:
        close -= timedelta(days=1)
    return at, {"symbol": ticker, "regularMarketPrice": 100,
                "regularMarketPreviousClose": 102, "regularMarketTime": close.timestamp(),
                field + "MarketPrice": 92.87,
                field + "MarketTime": (at - timedelta(minutes=1)).timestamp()}


@pytest.mark.parametrize("ticker", ["SOXL", "RAM", "BITX"])
@pytest.mark.parametrize("clock,field,label,kst", [
    ("2026-11-12T17:10:00-05:00", "post", "애프터마켓", "2026-11-13 07:09:00 KST"),
    ("2026-11-13T00:10:00-05:00", "overnight", "데이마켓", "2026-11-13 14:09:00 KST"),
    ("2026-11-13T06:10:00-05:00", "pre", "프리마켓", "2026-11-13 20:09:00 KST"),
    ("2026-10-21T00:10:00-04:00", "day", "데이마켓", "2026-10-21 13:09:00 KST"),
])
def test_product_session_time_and_negative_sign(ticker, clock, field, label, kst):
    now, q = payload(ticker, clock, field)
    before = deepcopy(q)
    result = quote_evidence(ticker, q, now)
    assert result["status"] == "연결됨"
    assert label in result["session"] and result["as_of"] == kst
    assert result["change"] == pytest.approx(-7.13)
    assert q == before


@pytest.mark.parametrize("field", ["pre", "post"])
def test_wrong_session_field_cannot_borrow_daymarket_time(field):
    now, q = payload("RAM", "2026-11-13T00:10:00-05:00", field)
    assert not extended_quote_observation(q, "RAM", now, allow_delayed=True)
    assert "세션 불일치" in extended_quote_status(q, "RAM", now)
    assert "price" not in quote_evidence("RAM", q, now)


@pytest.mark.parametrize("kind", ["empty", "wrong_symbol", "future", "stale", "missing_time", "bad_sign"])
def test_unverified_price_is_not_filled(kind):
    now, q = payload("BITX", "2026-11-13T00:10:00-05:00", "overnight")
    if kind == "empty":
        q = {}
    elif kind == "wrong_symbol":
        q["symbol"] = "BTC-USD"
    elif kind == "future":
        q["overnightMarketTime"] = (now + timedelta(minutes=1)).timestamp()
    elif kind == "stale":
        q["overnightMarketTime"] = (now - timedelta(minutes=21)).timestamp()
    elif kind == "missing_time":
        q.pop("overnightMarketTime")
    else:
        q["overnightMarketChangePercent"] = 7.13
    result = quote_evidence("BITX", q, now)
    assert result["status"] != "연결됨" and "price" not in result


def test_korean_product_and_unrelated_stock_do_not_fetch_us_quote():
    st, fetch = MagicMock(), Mock()
    for ticker in ("418660.KS", "MSFT"):
        render_quote_evidence(st, ticker, fetch_quote=fetch)
    fetch.assert_not_called()
    assert any("한국 상장 상품" in str(call) for call in st.caption.call_args_list)


def test_renderer_reads_one_selected_quote_and_marks_manual_input():
    now, q = payload("SOXL", "2026-11-12T17:10:00-05:00", "post")
    st, fetch = MagicMock(), Mock(return_value=q)
    render_quote_evidence(st, "SOXL", manual_price=90, now=now, fetch_quote=fetch)
    fetch.assert_called_once_with("SOXL")
    assert "-7.13%" in st.markdown.call_args.args[0]
    assert any("수동 보정" in str(call) for call in st.caption.call_args_list)
