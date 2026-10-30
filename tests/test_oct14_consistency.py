from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from stock_lab_core.decision_workflow import attach_market_execution_context, partition_today_queue
from stock_lab_core.earnings_calendar import EarningsCalendarReader
from stock_lab_core.execution_gate import apply_execution_gate_columns, GATE_DEFENSE, GATE_EXECUTABLE
from stock_lab_core.market_basis import daily_close, align_market_closes
from stock_lab_core.market_evidence_panel import render_snapshot


def candidate(ticker="083450.KQ"):
    return {"티커": ticker, "종목명": "GST", "판정코드": "QUALITY_RECOVERY_CANDIDATE",
            "판정분류": "buyish", "최종읽기": "회복 후보: 분할 검토", "데이터상태": "OK", "R/R": 1.08}


@pytest.mark.parametrize("ticker", ["083450.KQ", "020150.KS", "GST", "SPY", "RAM"])
def test_stop_new_buys_applies_to_all_products_and_cannot_be_bypassed(ticker):
    row = candidate(ticker)
    frame = pd.DataFrame([row])
    guard = {"mode": "위험", "action": "신규매수 중단 · 현금/리스크 점검",
             "kr_stats": {"mode": "위험"}, "us_stats": {"mode": "주의"}}
    result = apply_execution_gate_columns(attach_market_execution_context(frame, guard))
    assert result.loc[0, "게이트상태"] == GATE_DEFENSE
    assert "신규매수 중단" in result.loc[0, "게이트근거"]
    masks = partition_today_queue(result, pd.Series(["관심/눌림대기"]))
    assert not masks["execution"].any()
    assert masks["market_defense"].all()
    assert frame.iloc[0].to_dict() == row
    recovered = apply_execution_gate_columns(attach_market_execution_context(result, {
        "mode": "정상", "kr_stats": {"mode": "정상"}, "us_stats": {"mode": "정상"},
    }))
    assert recovered.loc[0, "게이트상태"] == GATE_EXECUTABLE


def test_local_emergency_does_not_block_other_market_without_global_stop():
    frame = pd.DataFrame([candidate(), candidate("AMAT")])
    guard = {"mode": "국장 비상", "kr_stats": {"mode": "비상"}, "us_stats": {"mode": "정상"}}
    result = apply_execution_gate_columns(attach_market_execution_context(frame, guard))
    assert result["게이트상태"].tolist() == [GATE_DEFENSE, GATE_EXECUTABLE]


def prices(start="2026-08-01", periods=50):
    return pd.DataFrame({"Close": list(range(100, 100 + periods))}, index=pd.bdate_range(start, periods=periods))


def test_common_bar_alignment_never_mixes_kr_rebound_with_previous_index_close():
    index = prices()
    etf = prices(periods=51)
    etf.iloc[-1, 0] = 180
    us = prices(periods=49)
    source = {"^KS11": daily_close(index), "069500.KS": daily_close(etf), "SPY": daily_close(us)}
    aligned, notes = align_market_closes(source, {"^KS11": "KR", "069500.KS": "KR", "SPY": "US"})
    assert aligned["^KS11"].index[-1] == aligned["069500.KS"].index[-1] == index.index[-1]
    assert aligned["SPY"].index[-1] == us.index[-1]
    assert aligned["069500.KS"].iloc[-1] == 149
    assert source["069500.KS"].iloc[-1] == 180
    assert "공통일" in notes["^KS11"]


def test_invalid_or_disjoint_histories_do_not_invent_a_date():
    assert daily_close(pd.DataFrame({"Close": [1, 2]})).empty
    first, second = daily_close(prices()), daily_close(prices("2025-01-01"))
    aligned, notes = align_market_closes({"a": first, "b": second}, {"a": "KR", "b": "KR"})
    assert aligned["a"].empty and aligned["b"].empty
    assert notes["a"] == "공통 거래일 없음"


def test_missing_previous_bar_uses_common_return_denominator():
    full = daily_close(prices())
    missing = full.drop(full.index[-2])
    aligned, _ = align_market_closes({"a": full, "b": missing}, {"a": "KR", "b": "KR"})
    assert aligned["a"].index.equals(aligned["b"].index)
    assert aligned["a"].index[-2] == full.index[-3]


def test_actual_guard_uses_aligned_dates_and_exports_basis(app_module, monkeypatch):
    app = app_module
    frames = {"^KS11": prices(), "069500.KS": prices(periods=51)}
    monkeypatch.setattr(app, "TODAY_MARKET_GUARD_BENCHMARKS", [("^KS11", "KOSPI", "KR"), ("069500.KS", "KOSPI200 ETF", "KR")])
    calls = []
    def load(ticker, period):
        calls.append(ticker)
        return frames[ticker]
    monkeypatch.setattr(app, "load_price_df", load)
    rows = app._build_today_benchmark_guard_rows()
    assert len(calls) == 2
    assert rows[0]["기준일"] == rows[1]["기준일"]
    assert rows[0]["1일"] == rows[1]["1일"]
    assert rows[1]["최근수신봉"] != rows[1]["기준일"]
    assert "→" in rows[0]["1일 기준"]


def test_earnings_throttle_covers_other_tickers_and_recovers_without_day_long_cache():
    clock = [0.0]
    reader = EarningsCalendarReader(clock=lambda: clock[0], cooldown=180)
    calls = []
    def failing(ticker):
        calls.append(ticker)
        raise YFRateLimitError()
    assert reader.read("GOOGL", failing)["status"] == "rate_limited"
    assert reader.read("SOXL", failing)["status"] == "rate_limited"
    assert calls == ["GOOGL"]
    clock[0] = 181
    assert reader.read("GOOGL", lambda _: {"Earnings Date": [date(2026, 11, 1)]})["ok"]


def test_earnings_app_displays_provider_status_and_failure_is_not_success(app_module, monkeypatch):
    app = app_module
    app.fetch_earnings_date.clear()
    reader = EarningsCalendarReader()
    monkeypatch.setattr(app, "earnings_calendar_reader", reader)
    class Ticker:
        @property
        def calendar(self):
            raise YFRateLimitError()
    monkeypatch.setattr(app.yf, "Ticker", lambda *args, **kwargs: Ticker())
    result = app.fetch_earnings_date("TEST-OCT14")
    assert not result["ok"] and result["status"] == "rate_limited"
    app.fetch_earnings_date.clear()


def test_mock_panel_preserves_api_errors_and_shows_successful_reads():
    info, captions, tables = [], [], []
    st = SimpleNamespace(info=info.append, caption=captions.append, dataframe=lambda frame, **kwargs: tables.append(frame))
    assert render_snapshot(st, {"ok": False, "is_mock": True, "status": "auth_error"}) == []
    assert "인증 실패" in info[0]
    rows = [{"코드": "005930", "종목명": "삼성전자", "현재가(원)": 100}]
    assert render_snapshot(st, {"ok": True, "is_mock": True, "rows": rows}) == rows
    assert len(tables) == 1 and any("모의환경" in text for text in captions)


def test_changed_target_weight_is_snapshot_mismatch_not_overwritten(app_module):
    summary = pd.DataFrame([{**candidate("RAM"), "현재비중": 8.08, "목표비중": 7.0}])
    holdings = pd.DataFrame([{"티커": "ram", "자산명": "RAM", "현재비중": 11.10, "목표비중": 9.0}])
    flags = app_module.build_today_review_flags_df(summary, holdings)
    match = flags[flags["문제"].eq("계산 당시와 현재 목표비중 다름")]
    assert len(match) == 1
    assert "7%" in match.iloc[0]["근거"] and "9%" in match.iloc[0]["근거"]
    assert summary.loc[0, "목표비중"] == 7.0 and holdings.loc[0, "목표비중"] == 9.0
