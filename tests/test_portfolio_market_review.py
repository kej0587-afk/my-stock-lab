from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core import portfolio_market_review as mod

NOW = "2026-11-04T10:00:00+09:00"


def context():
    return {"quote_checked_at": NOW, "sessions": {"US": "2026-11-03", "KR": "2026-11-03"},
            "prices": {"RAM": {"date": "2026-11-03", "return": -.07, "source": "test"},
                       "DRAM": {"date": "2026-11-03", "return": -.035, "source": "test"}},
            "closed_flow_rows": [{"Ticker": "DRAM", "기준일": "2026-11-03", "5일수익률": -.08, "3개월수익률": .20}],
            "earnings": [], "news": []}


def packet(ticker="MSFT"):
    return {"ticker": ticker, "name": ticker, "date": "2026-11-01", "fiscal_period": "FY2027Q1",
            "release_status": "공식 발표 확인", "official": True, "event": {},
            "stages": {"capex": "확인", "guidance": "확인"},
            "metrics": {"capex": {"text": "CAPEX actual", "source_url": "https://www.microsoft.com/ir"},
                        "guidance": {"text": "forecast", "source_url": "https://www.microsoft.com/ir"}}}


def test_capture_is_scoped_small_and_does_not_mutate_decisions(monkeypatch):
    source = context()
    source.update(price_frames={"RAM": pd.DataFrame({"Close": [100]})}, secret="not copied")
    summary = pd.DataFrame([{"티커": "RAM", "판정": "unchanged"}])
    monkeypatch.setattr(mod, "build_earnings_pipeline", lambda *a, **kw: {"packets": [packet()]})
    state = {"decisions": summary.copy(deep=True)}
    assert mod.capture_market_review(state, "account-A", source, summary)
    data, status = mod.select_market_review(state, "account-A", now=NOW)
    assert "수집" in status and data["earnings"]
    assert "price_frames" not in data and "secret" not in data
    source["prices"]["RAM"]["return"] = 99
    assert data["prices"]["RAM"]["return"] == -.07
    assert not mod.select_market_review(state, "account-B", now=NOW)[0]
    pd.testing.assert_frame_equal(summary, state["decisions"])


@pytest.mark.parametrize("now", ["2026-11-04T10:31:00+09:00", "2026-11-04T09:59:00+09:00"])
def test_old_or_future_collection_not_used_as_latest(now):
    state = {mod.EVIDENCE_KEY: {"scope": "A", "data": context()}}
    assert not mod.select_market_review(state, "A", now=now)[0]


def test_flow_and_proxy_join_preserve_units_and_do_not_change_trade_rules():
    data = context()
    before = deepcopy(data)
    view = mod.holding_market_review("RAM", data, {}, now=NOW)
    assert "중기 상승과 최근 5일 약세" in view["reading"]
    assert view["facts"][0]["관측"] == "-7.00%"
    assert "ETF 자체 수익률 아님" in view["facts"][1]["근거"]
    assert view["facts"][2]["관측"] == "5D -8.00% / 3M +20.00%"
    assert "실제 순매수 아님" in view["facts"][2]["근거"]
    assert data == before
    assert "decision" not in view and "score" not in view


def test_mismatched_close_and_old_live_quotes_are_not_used():
    data = context()
    data["prices"]["RAM"]["date"] = "2026-11-02"
    data["closed_flow_rows"][0]["기준일"] = "2026-11-02"
    data["extended_prices"] = {"RAM": {"return": .0713, "as_of": "2026-11-03T10:00:00+09:00"}}
    view = mod.holding_market_review("RAM", data, {}, now=NOW)
    assert "미정합" in view["facts"][0]["관측"]
    assert "7.13" not in str(view) and "중기 상승" not in view["reading"]


def test_real_money_flow_return_units_match_report_display():
    import numpy as np
    from stock_lab_core.money_flow import _compute_ticker_metrics
    close = np.linspace(80, 120, 150)
    frame = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": np.full(150, 1000)},
                         index=pd.bdate_range(end="2026-11-03", periods=150))
    metrics = _compute_ticker_metrics(frame)
    data = context()
    data["closed_flow_rows"] = [dict(metrics, Ticker="DRAM", 기준일="2026-11-03")]
    view = mod.holding_market_review("RAM", data, {}, now=NOW)
    expected = f"5D {metrics['5일수익률'] * 100:+.2f}% / 3M {metrics['3개월수익률'] * 100:+.2f}%"
    assert view["facts"][2]["관측"] == expected


def test_live_negative_sign_is_kept_separate_from_close():
    data = context()
    data["extended_prices"] = {"RAM": {"return": -.0713, "as_of": NOW, "source": "test"}}
    view = mod.holding_market_review("RAM", data, {}, now=NOW)
    assert any(r["관측"] == "-7.13%" and "시간외" in r["근거"] for r in view["facts"])


def test_direct_earnings_metrics_and_forecasts_keep_sources_and_missing_values():
    data = context()
    data["earnings"] = [packet()]
    view = mod.holding_market_review("MSFT", data, {}, now=NOW)
    assert len(view["earnings"]) == 6
    assert view["earnings"][0]["근거"] == "미연결/재확인 필요"
    assert view["earnings"][2]["근거"] == "CAPEX actual"
    assert view["earnings"][4]["구분"] == "회사 전망 · 실제치 아님"
    assert not mod.holding_market_review("RAM", data, {}, now=NOW)["earnings"]


def test_constituent_earnings_need_fresh_dated_membership_and_never_etf_results():
    data = context()
    data["earnings"] = [packet()]
    state = {"etf_constituents_TEST": {"status": "ok", "observed_at": NOW, "as_of": "2026-11-03",
             "source_url": "https://example.com/fund", "holdings_basis": "reported",
             "rows": [{"ticker": "MSFT", "kind": "security", "reviewable": True}]}}
    view = mod.holding_market_review("TEST", data, state, now=NOW)
    assert "구성기업 간접" in view["earnings"][0]["연결"]
    assert "ETF 전체 실적" in view["reading"]
    state["etf_constituents_TEST"]["status"] = "stale"
    assert not mod.holding_market_review("TEST", data, state, now=NOW)["earnings"]


def test_stale_official_metrics_do_not_become_fresh_after_collection():
    data = context()
    p = packet()
    p["event"] = {"result_stale": True}
    data["earnings"] = [p]
    view = mod.holding_market_review("MSFT", data, {}, now=NOW)
    assert all(r["근거"] == "미연결/재확인 필요" for r in view["earnings"])


def test_wrong_market_or_date_news_cannot_explain_proxy_movement():
    data = context()
    news = {"title": "Micron stocks fall on memory demand concerns", "market": "US", "session_date": "2026-11-03",
            "published_at": "2026-11-03T23:45:00+09:00", "news_bucket": "session_news", "link": "https://example.com/news"}
    data["news"] = [news, dict(news, link="https://example.com/kr", market="KR"),
                    dict(news, link="https://example.com/old", session_date="2026-11-02")]
    view = mod.holding_market_review("RAM", data, {}, now=NOW)
    assert [r["출처"] for r in view["news"]] == [news["link"]]


def test_streamlit_holding_switch_does_not_fetch_and_refresh_is_explicit():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string('''
import streamlit as st
from datetime import datetime, timezone
from stock_lab_core.portfolio_market_review import render_market_review, EVIDENCE_KEY
def refresh():
    st.session_state['calls'] = st.session_state.get('calls', 0) + 1
    st.session_state[EVIDENCE_KEY] = {'scope':'A', 'data': {
      'quote_checked_at':datetime.now(timezone.utc).isoformat(), 'sessions':{}, 'prices':{}, 'earnings':[]}}
ticker = st.selectbox('Holding', ['RAM','MSFT'])
render_market_review(st, ticker, 'A', refresh=refresh)
''').run(timeout=30)
    assert not at.exception
    at.button[0].click().run(timeout=30)
    assert not at.exception and at.session_state['calls'] == 1
    at.selectbox[0].select("MSFT").run(timeout=30)
    assert not at.exception and at.session_state['calls'] == 1


def test_failed_refresh_does_not_show_previous_evidence_as_success():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string('''
import streamlit as st
from stock_lab_core.portfolio_market_review import render_market_review
def refresh():
    raise TimeoutError('private provider details')
render_market_review(st, 'RAM', 'A', refresh=refresh)
''').run(timeout=30)
    at.button[0].click().run(timeout=30)
    assert not at.exception
    assert '갱신 실패' in at.warning[0].value
    assert 'private' not in str(at.warning[0].value)


def test_app_refresh_uses_report_sources_without_rescoring(app_module, monkeypatch):
    from types import SimpleNamespace
    from stock_lab_core import report_context
    holdings = pd.DataFrame([{"티커": "RAM", "자산명": "RAM", "보유량": 1}])
    before = holdings.copy(deep=True)
    state, calls = {}, []
    def collect(summary, events, **kwargs):
        calls.append(kwargs)
        assert summary.iloc[0]["종목명"] == "RAM"
        return context()
    monkeypatch.setattr(report_context, "collect_report_context", collect)
    monkeypatch.setattr(app_module, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(app_module, "get_report_build_info", lambda *a: {"restart_required": False})
    monkeypatch.setattr(app_module, "portfolio_signal_input_context", lambda: "A")
    monkeypatch.setattr(app_module, "get_cached_today_market_flow_snapshot", lambda: {})
    def forbidden(*a, **kw):
        raise AssertionError("Decision calculation must not run")
    monkeypatch.setattr(app_module, "build_portfolio_action_decision_df", forbidden)
    app_module.refresh_portfolio_market_evidence(holdings)
    assert len(calls) == 1 and calls[0]["include_news"] is True
    assert state[mod.EVIDENCE_KEY]["scope"] == "A"
    pd.testing.assert_frame_equal(holdings, before)


def test_intraday_news_is_separate_from_previous_close():
    data = context()
    data["market_states"] = {"US": {"active_date": "2026-11-04"}}
    data["news"] = [{"title": "Micron stocks fall on memory demand concerns", "market": "US",
                     "session_date": "2026-11-04", "news_bucket": "current_session_news",
                     "published_at": "2026-11-05T00:00:00+09:00", "link": "https://example.com/current"}]
    view = mod.holding_market_review("RAM", data, {}, now="2026-11-05T00:05:00+09:00")
    assert view["news"][0]["시장/세션"] == "US / 2026-11-04"
    assert view["facts"][0]["기준"] == "2026-11-03"
