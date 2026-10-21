"""Session-aware report presentation; execution inputs must remain unchanged."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_intraday import extended_quote_text, intraday_account_metrics
from stock_lab_core.report_quotes import extended_quote_observation, parse_us_quote_page
from stock_lab_core.report_session import market_session_states, us_extended_session

NOW = datetime.fromisoformat("2026-10-21T14:37:00+09:00")


def quote(age=129, ticker="RAM"):
    return {"symbol": ticker, "regularMarketPrice": 8.35, "regularMarketPreviousClose": 8.52,
            "regularMarketTime": datetime.fromisoformat("2026-10-20T16:00:00-04:00").timestamp(),
            "overnightMarketPrice": 8.9, "overnightMarketTime": (NOW - timedelta(minutes=age)).timestamp()}


@pytest.mark.parametrize("at,label", [
    ("2026-10-21T14:37:00+09:00", "데이마켓"),
    ("2026-11-04T17:30:00+09:00", "데이마켓"),  # Standard time starts in November.
    ("2026-10-21T17:00:00+09:00", "프리마켓"),
    ("2026-10-21T22:30:00+09:00", ""),
    ("2026-10-21T06:00:00+09:00", "애프터마켓"),
    ("2026-10-24T14:00:00+09:00", ""),
    ("2026-10-26T10:00:00+09:00", "데이마켓"),  # Sunday ET, Monday trading date.
    ("2026-12-25T14:00:00+09:00", ""),
])
def test_extended_window_does_not_relabel_regular_market(at, label):
    now = datetime.fromisoformat(at)
    before = market_session_states(now)
    window = us_extended_session(now)
    assert (label in window.get("label", "")) if label else not window
    assert market_session_states(now) == before
    if now == NOW:
        assert before["US"]["phase"] == "preopen"
        assert window["date"] == "2026-10-21"


def test_old_daymarket_is_visible_reference_but_excluded_from_account():
    stale = quote()
    assert not extended_quote_observation(stale, "RAM", NOW)
    obs = extended_quote_observation(stale, "RAM", NOW, allow_delayed=True)
    assert obs["return"] == pytest.approx(8.9 / 8.35 - 1)
    context = {"extended_reference_prices": {"RAM": obs}}
    text = extended_quote_text(context, "RAM", NOW)
    assert "$8.90" in text and "12:28 KST" in text and "129분 전" in text
    assert "지연 참고·현재 합산 제외" in text
    # Even an accidentally supplied stale observation cannot enter the current sum.
    metrics = intraday_account_metrics([{"티커": "RAM", "현재비중": 13}], {}, {"RAM": obs}, now=NOW)
    assert metrics["total"] is None and metrics["coverage"] == 0
    assert metrics["missing_weight"] == 13
    assert not extended_quote_text(context, "RAM", NOW.replace(hour=18))  # Next venue session.


@pytest.mark.parametrize("age", [-1, 345, 1500])
def test_reference_rejects_future_or_another_session(age):
    assert not extended_quote_observation(quote(age), "RAM", NOW, allow_delayed=True)


def test_fresh_daymarket_contribution_remains_available():
    obs = extended_quote_observation(quote(2), "RAM", NOW)
    assert obs and not obs["delayed"]
    metrics = intraday_account_metrics([{"티커": "RAM", "현재비중": 13}], {}, {"RAM": obs}, now=NOW)
    assert metrics["total"] == pytest.approx(13 * (8.9 / 8.35 - 1))
    assert metrics["groups"]["US_EXT"]["coverage"] == 13


def test_friday_after_extended_close_is_not_current_account_contribution():
    now = datetime.fromisoformat("2026-10-23T20:05:00-04:00")
    at = datetime.fromisoformat("2026-10-23T19:59:00-04:00")
    q = {"symbol": "RAM", "regularMarketPrice": 100, "regularMarketPreviousClose": 100,
         "regularMarketTime": datetime.fromisoformat("2026-10-23T16:00:00-04:00").timestamp(),
         "postMarketPrice": 110, "postMarketTime": at.timestamp()}
    assert not extended_quote_observation(q, "RAM", now)
    obs = {"date": "2026-10-23", "as_of": at.isoformat(), "return": .1}
    metrics = intraday_account_metrics([{"티커": "RAM", "현재비중": 100}], {}, {"RAM": obs}, now=now)
    assert metrics["total"] is None


def test_stale_us_indices_do_not_explain_current_direction():
    from stock_lab_core.report_market_summary import broad_market_reading, _market_fact
    now = datetime.fromisoformat("2026-10-21T12:00:00-04:00")
    states = market_session_states(now)
    ctx = {"intraday_prices": {ticker: {"date": "2026-10-21", "return": .01, "as_of": "2026-10-21T09:35:00-04:00"}
                               for ticker in ("^GSPC", "^IXIC", "^DJI")}}
    assert broad_market_reading(ctx, states, now) == ""
    assert _market_fact(ctx, "US", states, now)["change"] is None


def test_parser_keeps_newest_exact_symbol_row_atomic():
    old, fresh = quote(129), quote(2)
    html = "".join('<script type="application/json">' + json.dumps(
        {"status": 200, "body": json.dumps({"quoteResponse": {"result": [row]}})}) + '</script>'
        for row in (old, quote(1, "RAMX"), fresh))
    assert parse_us_quote_page(html, "RAM") == fresh


def context():
    prices = {ticker: {"date": "2026-10-20", "return": change} for ticker, change in
              (("^GSPC", .0028), ("^IXIC", -.0002), ("^DJI", .0102),
               ("SOXX", -.0038), ("IGV", .0089), ("^KS11", -.0373),
               ("305540.KS", -.02), ("RAM", -.02))}
    live = {ticker: {"date": "2026-10-21", "return": value, "as_of": NOW.isoformat()}
            for ticker, value in (("^KS11", .0273), ("305540.KS", .01))}
    return {"sessions": {"US": "2026-10-20", "KR": "2026-10-20"}, "prices": prices,
            "intraday_prices": live, "sector_rows": [{"Ticker": "305540.KS", "섹터": "2차전지", "구분": "한국 섹터", "기준일": "2026-10-20", "1일수익률": -.02}],
            "extended_reference_prices": {
                "RAM": extended_quote_observation(quote(), "RAM", NOW, allow_delayed=True)},
            "economic_releases": [{"indicator": "US_PPI", "actual": .3, "previous": .2,
                "unit": "%", "basis": "MoM", "period": "2026-09", "status": "released",
                "release_at": "2026-10-15T08:30:00-04:00", "source": "fixture"}]}


def test_report_explains_breadth_and_tables_without_promoting_stale_quotes():
    ctx = context()
    rows = [{"티커": "305540.KS", "종목명": "2차전지", "보유량": 1, "현재비중": 75,
             "게이트상태": "방어우선", "최종읽기": "추가매수 보류"},
            {"티커": "RAM", "종목명": "RAM ETF", "보유량": 1, "현재비중": 25,
             "게이트상태": "방어우선", "최종읽기": "추가매수 보류"}]
    before = deepcopy(rows)
    report = build_auto_market_memo(report_context=ctx, summary_rows=rows, now=NOW)
    headline = report.split("## 한 줄 결론\n")[1].split("\n## ")[0]
    assert "S&P500" in headline and "다우" in headline and "나스닥" in headline
    assert "혼조" in headline and "미국 데이마켓" in headline and "지연 참고" in headline
    assert "구분 | 계좌 기여(추정) | 연결 비중 | 기준·상태" in report
    assert "장중 연결분 기여 | +0.75%p | 75.0%" in report
    assert "미국 데이마켓·시간외 | 미연결 | 0.0%" in report
    assert "종가 기여 분해 | 미국 상장 -0.50%p / 한국 상장 -1.50%p" in report
    assert "미연결분 ±3% 가정 민감도 | ±0.75%p" in report
    assert "해석(조건부)" in report and "물가 압력 확대" in report
    assert "오늘 등락의 원인 확정이나 매수 신호가 아닙니다" in report
    sector = report.split("## 업종별 왜")[1].split("\n## ")[0]
    assert "2차전지" in sector and "+1.00%" in sector
    assert rows == before


@pytest.mark.parametrize("connected", [True, False])
def test_context_reuses_release_calendar_including_failed_sources(monkeypatch, connected):
    from stock_lab_core import economic_releases, release_calendar, economic_bulletins
    calendar = {"events": [], "sources": [{"name": "BLS", "status": "connected" if connected else "unavailable"}]}
    loader = Mock(return_value=([], calendar))
    monkeypatch.setattr(economic_releases, "load_economic_releases", loader)
    monkeypatch.setattr(economic_bulletins, "apply_official_bulletins", lambda rows, now: rows)
    duplicate = Mock(side_effect=AssertionError("Calendar collected twice"))
    monkeypatch.setattr(release_calendar, "load_release_calendar", duplicate)
    result = collect_report_context(now=NOW, price_frames={}, quote_data={})
    loader.assert_called_once_with(event_rows=None, now=NOW, include_calendar=True)
    duplicate.assert_not_called()
    assert result["calendar_sources"] == calendar["sources"]


def test_sector_quotes_collected_for_nonheld_report_assets_in_one_kr_batch(monkeypatch):
    from stock_lab_core import prices, report_quotes, report_live
    from stock_lab_core.report_prices import SECTORS
    monkeypatch.setattr(prices, "load_price_frames_batch", lambda *a, **k: {})
    monkeypatch.setattr(prices, "load_price_df", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(report_live, "supplement_kr_indices", lambda frames: frames)
    quotes = Mock(return_value={})
    monkeypatch.setattr(report_quotes, "load_report_quotes", quotes)
    collect_report_context(now=NOW, economic_releases=[], calendar={"events": [], "sources": []}, scenario_frames={})
    quotes.assert_called_once()
    symbols = set(quotes.call_args.args[0])
    assert symbols == {t for t in SECTORS if not t.endswith((".KS", ".KQ"))}
    assert set(quotes.call_args.kwargs["kr_tickers"]) == {t for t in SECTORS if t.endswith((".KS", ".KQ"))} | {"0167A0.KS"}
