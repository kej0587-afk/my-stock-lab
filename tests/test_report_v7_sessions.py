"""Midnight KST is not midnight on the US exchange; closed and live stay separate."""

from datetime import datetime, timezone
from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_holdings import holding_estimate
from stock_lab_core.report_live import supplement_kr_indices, us_live_observation
from stock_lab_core.report_session import market_session_states
from stock_lab_core.market_memo import build_auto_market_memo

NOW = datetime.fromisoformat("2026-10-20T00:36:00+09:00")


def frame(dates, values):
    return pd.DataFrame({key: values for key in ("Close", "High", "Low", "Open")}, index=pd.to_datetime(dates))


@pytest.mark.parametrize("now", [NOW, NOW.astimezone(timezone.utc), NOW.replace(tzinfo=None)])
def test_independent_exchange_states_with_one_kst_clock(now):
    states = market_session_states(now, {"KR": "2026-10-19", "US": "2026-10-16"})
    assert states["KR"]["phase"] == "preopen"
    assert states["KR"]["label"] == "마감 후·다음 개장 전"
    assert states["KR"]["last_close"] == "2026-10-19"
    assert states["US"]["phase"] == "intraday"
    assert states["US"]["active_date"] == "2026-10-19"


def test_recent_daily_index_repairs_stale_yahoo_without_mutating_inputs(monkeypatch):
    from stock_lab_core import report_live
    old = frame(["2026-10-15", "2026-10-16"], [5554.22, 5668.05])
    recent = frame(["2026-10-16", "2026-10-19"], [5668.05, 5768.01])
    monkeypatch.setattr(report_live, "load_kr_index_history", lambda code: recent)
    repaired = supplement_kr_indices({"^KS11": old})
    assert len(old) == 2
    assert repaired["^KS11"].index[-1].date().isoformat() == "2026-10-19"
    assert repaired["^KS11"].Close.pct_change().iloc[-1] == pytest.approx(.0176356948)


def test_live_quote_uses_completed_bars_only_and_correct_prior_close():
    live = frame(["2026-10-19T15:25Z", "2026-10-19T15:30Z", "2026-10-19T15:35Z"], [110, 111, 999])
    obs = us_live_observation(live, "SOXL", {"price": 100, "date": "2026-10-16"}, NOW)
    assert obs["return"] == pytest.approx(.11)
    assert obs["as_of"] == "2026-10-19T15:35:00+00:00"
    assert obs["date"] == "2026-10-19" and "확정 아님" in obs["kind"]
    assert not us_live_observation(live, "SOXL", {"price": 100}, NOW.replace(hour=7))
    assert not us_live_observation(live, "SOXL", {"price": 90, "date": "2026-10-15"}, NOW)


def test_context_report_midnight_acceptance_and_no_live_close_contamination():
    dates = pd.bdate_range("2026-06-01", "2026-10-19")
    values = list(range(100, 100 + len(dates)))
    base = frame(dates, values)
    tickers = ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI", "QQQ", "SOXX", "DRAM", "SOXL", "RAM",
               "379810.KS", "418660.KS", "XLK", "XLC", "XLU", "XLF", "XLI", "XLP")
    frames = {t: base.copy() for t in tickers}
    live = frame(["2026-10-19T15:30Z", "2026-10-19T15:35Z"], [210, 999])
    live_frames = {t: live for t in tickers if not t.endswith(".KS")}
    rows = [{"티커": "379810.KS", "보유량": 1, "현재비중": 60},
            {"티커": "418660.KS", "보유량": 1, "현재비중": 39.9}]
    context = collect_report_context(rows, now=NOW.astimezone(timezone.utc), price_frames=frames,
                                     live_frames=live_frames, economic_releases=[], calendar={"events": [], "sources": []})
    assert context["sessions"] == {"KR": "2026-10-19", "US": "2026-10-16"}
    assert context["prices"]["QQQ"]["price"] == values[-2]
    assert context["intraday_prices"]["QQQ"]["price"] == 210
    assert context["current_news_sessions"]["US"]["date"] == "2026-10-19"
    for row in context["closed_flow_rows"]:
        assert row["기준일"] == ("2026-10-19" if row["Ticker"].endswith(".KS") or row["Ticker"] in {"^KS11", "^KQ11"} else "2026-10-16")
    original = deepcopy(context)
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    assert context == original
    assert "한국: 2026-10-19 정규장 종가" in report
    assert "한국 당일 반영 미확인" not in report
    assert "연결 비중 99.9%" in report
    assert "미국 2026-10-19 장중" in report
    assert "418660.KS" in report and "다음 한국장 갭 예상 영향" in report
    assert "미국 기준일 2026-10-16 · 확정 종가(장중 제외)" in report


def test_prior_us_close_cannot_be_reused_after_kr_already_reflected_it():
    row = {"티커": "418660.KS"}
    observations = {"418660.KS": {"date": "2026-10-19", "return": -.0254},
                    "QQQ": {"date": "2026-10-16", "return": -.025}}
    sessions = {"KR": "2026-10-19", "US": "2026-10-16"}
    stale, _ = holding_estimate(row, observations, sessions, NOW)
    assert "이미 반영" in stale and "-5.00%" not in stale
    fresh, _ = holding_estimate(row, observations, sessions, NOW,
        intraday_prices={"QQQ": {"date": "2026-10-19", "return": .02, "as_of": "2026-10-19T15:35:00Z"}})
    assert "+4.00%" in fresh and "2026-10-19 장중 진행·확정 아님" in fresh


def test_common_ai_theme_from_other_market_date_does_not_explain_us_sector():
    from stock_lab_core.report_presentation import sector_related_news
    from stock_lab_core.report_analysis import sector_evidence
    articles = [dict(title=title, market=market, session_date="2026-10-19", published="2026-10-19T18:00:00+09:00",
                     publisher="Reuters", link=f"https://www.reuters.com/markets/test-{i}/")
                for i, (title, market) in enumerate((("日증시 AI 투자 불안", "KR"), ("중국 증시 AI 투자 불안에 반도체 하락", "KR")))]
    linked = sector_related_news("SOXX", "2026-10-16", articles)
    assert not linked
    result = sector_evidence({"Ticker": "SOXX", "기준일": "2026-10-16", "1일수익률": -.04}, {}, linked)
    assert "직접 원인 자료 미연결" in result["reading"]
    assert "AI 투자 불안" not in result["reading"]
    assert "2026-10-16" in result["fact"]


def test_missing_date_flow_cannot_be_merged_into_confirmed_sector_row():
    context = {"sessions": {"KR": "2026-10-19", "US": "2026-10-16"},
               "sector_rows": [{"Ticker": "XLK", "섹터": "기술", "구분": "미국 섹터", "기준일": "2026-10-16", "1일수익률": -.03}]}
    report = build_auto_market_memo(report_context=context, flow_snapshot={"flow_df": [
        {"Ticker": "XLK", "3개월수익률": .999, "가속도": 5}]}, now=NOW)
    line = next(line for line in report.splitlines() if "기술(XLK)" in line)
    assert "99.9%" not in line and "500.0%" not in line


def test_old_cxmt_article_cannot_deduplicate_current_session_rebound():
    from stock_lab_core.report_evidence import curate_news
    rows = [dict(title="CXMT 반도체 주가 하락", market="US", session_date="2026-10-16", publisher="Reuters",
                 published="2026-10-16T19:00:00Z", link="https://www.reuters.com/markets/test-friday/"),
            dict(title="CXMT 반도체 주가 반등", market="US", session_date="2026-10-19", publisher="Reuters",
                 published="2026-10-19T15:30:00Z", link="https://www.reuters.com/markets/test-monday/")]
    assert len(curate_news(rows, now=NOW, session_scoped=True)) == 2
    assert len(curate_news(rows, now=NOW)) == 1


def test_bls_last_success_is_unit_and_series_scoped_and_never_fresh_after_failure():
    from stock_lab_core.economic_cache import retain_successful_observations
    row = dict(indicator="US_PPI", period="2026-09", actual=1.3, previous=.5, unit="%", basis="MoM",
               series_id="WPSFD4", source="BLS", retrieved_at="2026-10-19T15:00:00Z", status="released")
    retain_successful_observations([row], NOW)
    missing = dict(row, actual=None, status="unavailable", missing_reason="http_429")
    restored = retain_successful_observations([missing], NOW)[0]
    assert restored["actual"] == 1.3 and restored["status"] == "stale"
    assert restored["last_success_at"] == row["retrieved_at"]
    other_basis = dict(missing, basis="YoY", series_id="WPUFD4")
    assert retain_successful_observations([other_basis], NOW)[0]["actual"] is None
