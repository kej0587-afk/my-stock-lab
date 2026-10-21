"""Reproduce missing RAM close and stale same-day KOSPI; no trade-rule changes."""

from copy import deepcopy
from datetime import datetime, timedelta
import json

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_quotes import (parse_us_quote_page, regular_quote_observation,
    repair_held_us_closes, extended_quote_observation, kr_index_observations)

NOW = datetime.fromisoformat("2026-10-21T10:00:00+09:00")


def epoch(value):
    return int(pd.Timestamp(value).timestamp())


def frame(dates, prices):
    return pd.DataFrame({col: prices for col in ("Open", "High", "Low", "Close")}, index=pd.to_datetime(dates))


def ram_quote():
    return {"symbol": "RAM", "regularMarketPrice": {"raw": 8.35}, "regularMarketPreviousClose": {"raw": 8.52},
            "regularMarketTime": {"raw": epoch("2026-10-20T16:00:00-04:00")},
            "regularMarketOpen": {"raw": 8.0}, "regularMarketDayHigh": {"raw": 8.61},
            "regularMarketDayLow": {"raw": 7.954}, "regularMarketVolume": 10214145,
            "overnightMarketPrice": {"raw": 8.8}, "overnightMarketTime": {"raw": epoch("2026-10-21T09:59:00+09:00")},
            "postMarketPrice": {"raw": 8.7}, "postMarketTime": epoch("2026-10-20T19:59:00-04:00")}


def kr_payload():
    return {"time": epoch("2026-10-21T09:59:45+09:00") * 1000, "areas": [{"name": "SERVICE_INDEX", "datas": [
        {"cd": "KOSPI", "ms": "OPEN", "nv": 567934, "cv": 12660, "cr": 2.28, "rf": "2"}]}]}


def test_exact_symbol_structured_quote_parser():
    wrong = dict(ram_quote(), symbol="RAMX", regularMarketPrice=999)
    body = json.dumps({"quoteResponse": {"result": [wrong, ram_quote()]}})
    html = '<script type="application/json">' + json.dumps({"status": 200, "body": body}) + '</script>'
    assert parse_us_quote_page(html, "RAM") == ram_quote()
    assert not parse_us_quote_page(html, "MSFT")
    assert not parse_us_quote_page('<script type="application/json">null</script>', "RAM")


def test_missing_daily_close_uses_confirmed_regular_quote_not_overnight():
    histories = {"RAM": frame(["2026-10-16", "2026-10-19"], [7.94, 8.52])}
    before = histories["RAM"].copy(deep=True)
    result = repair_held_us_closes(histories, {"RAM": ram_quote()}, NOW)
    assert result["RAM"].Close.iloc[-1] == 8.35
    assert result["RAM"].Close.pct_change().iloc[-1] == pytest.approx(-.01995305)
    assert "정규장" in result["RAM"].attrs["source"]
    pd.testing.assert_frame_equal(before, histories["RAM"])
    obs = extended_quote_observation(ram_quote(), "RAM", NOW)
    assert obs["return"] == pytest.approx(.0538922)
    assert obs["previous_date"] == "2026-10-20" and obs["previous_price"] == 8.35
    assert "데이마켓" in obs["kind"]


@pytest.mark.parametrize("changes", [
    {"regularMarketTime": epoch("2026-10-19T16:00:00-04:00")},
    {"regularMarketTime": epoch("2026-10-21T16:00:00-04:00")},
    {"regularMarketTime": epoch("2026-10-20T15:00:00-04:00")},
    {"regularMarketPreviousClose": 85.2}, {"regularMarketDayHigh": 1},
    {"regularMarketOpen": None}, {"regularMarketPrice": float("nan")}, {"symbol": "MSFT"}])
def test_bad_quote_cannot_repair_history(changes):
    old = frame(["2026-10-16", "2026-10-19"], [7.94, 8.52])
    result = repair_held_us_closes({"RAM": old}, {"RAM": dict(ram_quote(), **changes)}, NOW)
    pd.testing.assert_frame_equal(result["RAM"], old)


@pytest.mark.parametrize("stamp", [None, epoch("2026-10-21T08:00:00+09:00"), epoch("2026-10-21T10:01:00+09:00")])
def test_missing_old_future_extended_timestamp_rejected(stamp):
    quote = dict(ram_quote(), overnightMarketTime=stamp)
    assert not extended_quote_observation(quote, "RAM", NOW)


def test_regular_close_waits_for_session_completion():
    assert not regular_quote_observation(ram_quote(), "RAM", datetime.fromisoformat("2026-10-21T04:00:00+09:00"))


def test_kr_current_direction_and_stale_same_day_history(monkeypatch):
    from stock_lab_core import report_live
    old = frame(["2026-10-20", "2026-10-21"], [5552.74, 5300])
    newer = frame(["2026-10-20", "2026-10-21"], [5552.74, 5679.34])
    monkeypatch.setattr(report_live, "load_kr_index_history", lambda code: newer)
    result = report_live.supplement_kr_indices({"^KS11": old})
    assert result["^KS11"].Close.iloc[-1] == 5679.34
    assert old.Close.iloc[-1] == 5300
    obs = kr_index_observations(kr_payload(), NOW)["^KS11"]
    assert obs["price"] == 5679.34 and obs["return"] == pytest.approx(.02279955)
    assert not kr_index_observations(kr_payload(), NOW + timedelta(minutes=5))
    assert not kr_index_observations(kr_payload(), NOW - timedelta(minutes=5))


def test_down_index_sign_is_not_assumed_positive():
    payload = kr_payload()
    payload["areas"][0]["datas"][0].update(nv=542614, rf="5")
    assert kr_index_observations(payload, NOW)["^KS11"]["return"] < 0


def histories():
    base = frame(["2026-10-19", "2026-10-20"], [100, 99])
    return {"^GSPC": base, "^IXIC": base, "^DJI": base, "^KS11": base, "^KQ11": base,
            "RAM": frame(["2026-10-16", "2026-10-19"], [7.94, 8.52])}


def test_complete_report_shows_both_sessions_without_changing_trade_decision():
    from stock_lab_core.market_memo import build_auto_market_memo
    rows = [{"티커": "RAM", "종목명": "RAM ETF", "보유량": 1, "현재비중": 10,
             "게이트상태": "방어우선", "최종읽기": "추가매수 보류", "Adj점수": 4}]
    before = deepcopy(rows)
    context = collect_report_context(rows, now=NOW, price_frames=histories(), economic_releases=[],
                                     calendar={"events": [], "sources": []}, quote_data={"KR": kr_payload(), "US": {"RAM": ram_quote()}})
    assert context["prices"]["RAM"]["return"] == pytest.approx(-.01995305)
    assert context["extended_prices"]["RAM"]["return"] == pytest.approx(.0538922)
    assert not context["intraday_prices"]["RAM"]
    assert "RAM" not in context["price_alignment"]["unaligned"]
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    line = next(line for line in report.splitlines() if line.startswith("RAM ETF(RAM) |"))
    assert "-2.00%" in line and "+5.39%" in line and "데이마켓" in line
    assert "+7.30%" not in line
    assert "코스피 당일 +2.28%" in report and "09:59" in report
    assert rows == before


def test_unavailable_quotes_are_not_old_current_prices():
    from stock_lab_core.market_memo import build_auto_market_memo
    rows = [{"티커": "RAM", "종목명": "RAM ETF", "보유량": 1, "현재비중": 10}]
    frames = histories()
    frames["^KS11"] = frame(["2026-10-20", "2026-10-21"], [100, 90])
    context = collect_report_context(rows, now=NOW, price_frames=frames, economic_releases=[],
                                     calendar={"events": [], "sources": []}, quote_data={})
    assert not context["intraday_prices"]["^KS11"]
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    line = next(line for line in report.splitlines() if line.startswith("RAM ETF(RAM) |"))
    assert "최신 종가 미수집 · 과거 참고" in line and "시간외 시세 미연결" in line
    assert "한국 2026-10-21 장중 시세 미수집" in report


def test_quote_loader_bounded_to_unique_held_symbols(monkeypatch):
    from stock_lab_core import report_quotes
    calls = []
    monkeypatch.setattr(report_quotes, "load_us_report_quote", lambda ticker: calls.append(ticker) or ram_quote())
    monkeypatch.setattr(report_quotes, "load_kr_report_quotes", kr_payload)
    result = report_quotes.load_report_quotes(("RAM", "RAM", "SOXL"), include_kr=True)
    assert sorted(calls) == ["RAM", "SOXL"]
    assert result["KR"] == kr_payload()
