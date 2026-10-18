from datetime import datetime
import pandas as pd
import pytest

from stock_lab_core.report_evidence import KST, comparison_lines
from stock_lab_core.report_analysis import economic_story_lines, outlier_check
from stock_lab_core.report_history import update_report_history
from stock_lab_core.report_prices import aligned_macro, btc_at_us_close, release_day_reaction
from stock_lab_core.report_holdings import holding_estimate
from stock_lab_core.market_memo import build_auto_market_memo, _flow_bullet
from stock_lab_core.chart_scorecard import build_chart_scorecard, volume_review
from stock_lab_core.report_context import apply_verified_release_dates

NOW = datetime(2026, 10, 18, 21, tzinfo=KST)
SESSIONS = {"US": "2026-10-16", "KR": "2026-10-16"}


def test_stories_include_ppi_and_jobs_with_incompatible_units_not_raw_ranked():
    rows = [{"indicator": "US_PPI", "period": "2026-09", "basis": "MoM", "unit": "%", "actual": 1.3, "previous": .5},
            {"indicator": "US_NONFARM_PAYROLLS", "period": "2026-09", "basis": "MoM", "unit": "thousand persons", "actual": 29, "previous": 133},
            {"indicator": "US_CPI", "period": "2026-09", "basis": "MoM", "unit": "%", "actual": .6, "previous": .4}]
    lines = economic_story_lines(rows)
    assert "PPI" in lines[0] and "비농업고용" in lines[1]
    assert "컨센서스 서프라이즈 아님" in lines[0]
    row = dict(rows[0], history=[{"period": f"2025-{i:02d}", "value": .2} for i in range(1, 13)])
    assert outlier_check(row)["flag"]


def test_report_trading_history_overwrites_weekend_and_compares_reasons(tmp_path):
    path = tmp_path / "history.json"
    before = [{"티커": "379810.KS", "최종읽기": "대기", "현재비중": 25, "목표비중": 27}]
    after = [{"티커": "379810.KS", "최종읽기": "대기", "현재비중": 29, "목표비중": 27}]
    old = {"KR": "2026-10-15", "US": "2026-10-15"}
    update_report_history(before, old, owner_scope="alice", path=path)
    for _ in range(3):
        result = update_report_history(after, SESSIONS, owner_scope="alice", path=path)
        assert result["previous_date"] == "2026-10-15/2026-10-15"
        lines = comparison_lines(after, result["previous_summary"], previous_date=result["previous_date"], current_date=result["summary_date"])
        assert "비중초과" in lines[0]
    bob = update_report_history(after, SESSIONS, owner_scope="bob", path=path)
    assert not bob["previous_summary"]


@pytest.mark.parametrize("ticker,mult", [("379810.KS", 1), ("379800.KS", 1), ("418660.KS", 2)])
def test_domestic_us_asset_gap_is_separate_from_kr_actual(ticker, mult):
    observations = {"QQQ": {"date": "2026-10-16", "return": -.03}, "^GSPC": {"date": "2026-10-16", "return": -.02}}
    note, _ = holding_estimate({"티커": ticker}, observations, SESSIONS, NOW)
    assert "월요일 갭 예상 영향(추정)" in note
    assert f"× {mult} =" in note and "환율·선물·추적오차 미반영" in note


def test_btc_close_uses_new_york_end_and_excludes_partial_bar():
    frame = pd.DataFrame({"Close": [100, 999, 98, 999]}, index=pd.to_datetime([
        "2026-10-15T19:55:00Z", "2026-10-15T20:00:00Z", "2026-10-16T19:55:00Z", "2026-10-16T20:00:00Z"]))
    obs = btc_at_us_close(frame, "2026-10-16", "2026-10-15")
    assert obs["return"] == pytest.approx(-.02)
    note, _ = holding_estimate({"티커": "BITX"}, {"BTC-US-CLOSE": obs}, SESSIONS, NOW)
    assert "마감→마감" in note and "= -4.00%" in note


def test_macro_ignores_sunday_and_keeps_monthly_base_date():
    index = pd.date_range("2026-09-01", "2026-10-18")
    frame = pd.DataFrame({"Close": range(100, 100 + len(index))}, index=index)
    macro = aligned_macro({"USDKRW=X": frame}, "2026-10-16", NOW)
    assert macro["환율"]["as_of"] == "2026-10-16"
    assert macro["환율"]["val"] == frame.loc["2026-10-16", "Close"]
    assert macro["환율"]["base_date"] == "2026-09-25"
    reaction = release_day_reaction({"actual": 1.3, "release_at": "2026-10-15T08:30:00-04:00"},
                                  {"^TNX": frame * .01}, NOW)
    assert "10Y +1.00bp" in reaction and "인과가 아님" in reaction


def test_official_archive_date_is_not_inferred_for_another_observation_month():
    rows = [{"indicator": "US_PPI", "period": "2026-09", "basis": "YoY", "actual": 6.3},
            {"indicator": "US_PPI", "period": "2026-10", "basis": "YoY", "actual": 6.3}]
    apply_verified_release_dates(rows, NOW)
    assert rows[0]["release_at"] == "2026-10-15T08:30:00-04:00"
    assert "일치" in rows[0]["verification"]
    assert "release_at" not in rows[1] and "verification" not in rows[1]


def test_nested_price_scopes_keep_each_exact_period_and_copy_frames(monkeypatch):
    from stock_lab_core import prices
    calls = []
    monkeypatch.setattr(prices, "_fetch_yfinance_ohlcv", lambda *a: calls.append(a))
    with prices.price_frame_scope({"NVDA": pd.DataFrame({"Close": [1.]})}, "1y"):
        with prices.price_frame_scope({"NVDA": pd.DataFrame({"Close": [3.]})}, "3mo"):
            assert prices.load_price_df("NVDA", "1y").iloc[0, 0] == 1
            assert prices.load_price_df("NVDA", "3mo").iloc[0, 0] == 3
            frame = prices.load_price_df("NVDA", "1y")
            frame.iloc[0, 0] = 99
            assert prices.load_price_df("NVDA", "1y").iloc[0, 0] == 1
    assert not calls


def test_report_has_only_one_holdings_table_and_three_sector_labels():
    context = {"sessions": SESSIONS, "prices": {"QQQ": {"date": "2026-10-16", "return": -.03}},
               "sector_rows": [{"구분": "미국 섹터", "섹터": "기술", "Ticker": "XLK", "1일수익률": -.03, "기준일": "2026-10-16"}],
               "calendar_sources": [{"name": "BLS", "status": "connected"}], "calendar_events": []}
    rows = [{"티커": "418660.KS", "보유량": 1, "판정코드": "MACRO", "게이트상태": "차단"}]
    report = build_auto_market_memo(summary_rows=rows, report_context=context, now=NOW)
    assert report.count("종목 | 일간 등락 | 레버리지 환산 | 상태/사유") == 1
    assert "🧭 오늘점검" not in report and "시장방어" not in report
    assert "사실:" in report and "해석(추정):" in report and "미확인:" in report
    assert "일정 없음(연결된 공식 일정" in report
    assert "월요일 갭 예상 영향" in report


def test_crashing_sector_is_not_mislabeled_relative_leader():
    line = _flow_bullet({"Ticker": "SOXX", "3개월수익률": -.1, "돈흐름점수": -4, "상태": "급락 경보"})
    assert "상대 상위" not in line


def test_chart_scorecard_has_six_axes_without_missing_as_zero():
    frame = pd.DataFrame({"Close": range(100, 400), "Volume": 1000}, index=pd.bdate_range("2025-01-01", periods=300))
    rows, _ = build_chart_scorecard({"returnOnEquity": "25%", "trailingPE": -5, "revenueGrowth": "12.5%"}, frame)
    by_axis = {row["축"]: row for row in rows}
    assert len(rows) == 6
    assert by_axis["품질"]["점수"] == 100
    assert by_axis["성장"]["점수"] == 50
    assert by_axis["가치"]["점수"] is None
    assert by_axis["주주환원"]["점수"] is None
    volume, note = volume_review(frame, "379810.KS")
    assert volume[1]["단위"] == "KRW" and "매수 확정 불가" in note


def test_chart_scorecard_and_volume_render_without_network():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
import pandas as pd
from stock_lab_core.chart_scorecard import render_chart_scorecard, render_volume_review
frame = pd.DataFrame({"Close": range(100, 400), "Volume": 1000}, index=pd.bdate_range("2025-01-01", periods=300))
render_chart_scorecard(st, frame, info={"returnOnEquity": "25%", "trailingPE": 15}, ticker="TEST")
render_volume_review(st, frame, "TEST")
''').run(timeout=15)
    assert not app.exception
    assert len(app.dataframe) == 3
    assert len(app.dataframe[0].value) == 6


def test_news_curation_is_idempotent_and_keeps_index_only_titles():
    from stock_lab_core.report_evidence import curate_news
    row = {"title": "코스피 2% 반등 - 한국경제", "publisher": "한국경제", "published_at": "2026-10-16T15:35:00+09:00"}
    once = curate_news([row], now=NOW)
    assert len(once) == 1 and once[0]["title"] == "코스피 2% 반등"
    assert curate_news(once, now=NOW) == once


def test_previous_session_close_wrap_is_not_todays_story():
    from stock_lab_core.today_news import partition_session_market_news
    result = partition_session_market_news([
        {"title": "코스피 하락 마감", "market": "KR", "published_at": "2026-10-15T15:40:00+09:00"},
        {"title": "코스피 반등 마감", "market": "KR", "published_at": "2026-10-16T15:40:00+09:00"},
    ], {"KR": {"date": "2026-10-16", "previous_date": "2026-10-15"}}, now=NOW)
    assert len(result["session_news"]) == 1
    assert result["session_news"][0]["retrospective_close_wrap"]
