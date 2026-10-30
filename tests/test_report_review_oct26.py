from datetime import datetime
from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.report_evidence import curate_news, korean_headline_reading, news_category
from stock_lab_core.report_economic_reading import economic_reading_with_reaction
from stock_lab_core.report_fx import adjusted_reference, portfolio_fx_lines
from stock_lab_core.report_presentation import sector_display_name, sector_related_news, sector_news_topics
from stock_lab_core.report_session import market_session_states
from stock_lab_core.today_news import _resolve_query_news_market
from stock_lab_core.market_memo import build_auto_market_memo

NOW = datetime.fromisoformat("2026-10-26T23:15:00+09:00")


def test_english_oil_subject_is_not_combined_with_stock_decline():
    title = "Oil prices rise while stocks fall"
    assert "상승" in korean_headline_reading({"title": title})
    assert "하락" not in korean_headline_reading({"title": title})
    assert news_category(title) == "에너지"


def test_korean_market_comparison_is_not_us_session_news():
    result = _resolve_query_news_market({"title": '"美보다 더 빠진 국장"…실적 두 배인데 주가 왜 이러나',
        "query_market": "US", "market": "US", "published_at": "2026-10-24T00:16:00+09:00"}, {})
    assert result["market"] == "KR"


def test_closing_event_dedup_covers_declined_synonyms_and_dual_index_titles():
    titles = ["코스피, 1.46% 내린 5,469.47 마감…코스닥은 3%대 하락",
              "코스피, 5500선 하회…1.46% 밀린 5,469.47 마감",
              "[속보]코스피, 80.83포인트(1.46%) 내린 5469.47 마감",
              "코스닥, 3.00% 하락 마감", "코스피, 1.47% 하락 마감"]
    rows = [dict(title=title, publisher="뉴시스", link=f"https://newsis.com/{i}",
                 published_at="2026-10-26T15:34:00+09:00", market="KR", session_date="2026-10-26",
                 news_bucket="session_news", is_close_wrap=True) for i, title in enumerate(titles)]
    result = curate_news(rows, now=NOW, limit=10, session_scoped=True)
    assert len(result) == 3
    assert result[0]["duplicate_count"] == 3 and len(result[0]["related_articles"]) == 2


def test_duplicate_closing_recap_does_not_exhaust_news_category_budget(monkeypatch):
    from stock_lab_core import today_news

    titles = ["코스피, 1.46% 내린 5469.47 마감",
              "코스피, 5500선 하회…1.46% 밀린 5469.47 마감",
              "코스피, 시장 제도 개편 발표"]
    rows = [dict(title=title, publisher="뉴시스", link=f"https://newsis.com/story-{i}",
                 published_at=f"2026-10-26T15:{34-i:02d}:00+09:00", market="KR", query_market="KR")
            for i, title in enumerate(titles)]
    assert len({news_category(title) for title in titles}) == 1
    monkeypatch.setattr(today_news, "_session_query_specs", lambda *a, **k: [{}])
    monkeypatch.setattr(today_news, "_fetch_session_rss", lambda spec: (rows, ""))
    result = today_news.fetch_session_market_news({"KR": {"date": "2026-10-26", "previous_date": "2026-10-23"}},
                                                  now=NOW, per_category=2)
    accepted = result["session_news"]
    assert {row["title"] for row in accepted} == set(titles)
    grouped = curate_news(accepted, now=NOW, limit=10, session_scoped=True)
    assert len(grouped) == 2


def test_same_kr_semiconductor_exposure_and_no_ranking_table_as_cause():
    assert sector_news_topics("0167A0.KS") == sector_news_topics("396500.KS")
    assert "SOL AI" in sector_display_name({"Ticker": "0167A0.KS", "섹터": "0167A0.KS"})
    rows = [dict(title=title, market="KR", session_date="2026-10-26", news_bucket="session_news")
            for title in ("[표] 코스닥 외국인 순매수도 상위종목(26일)", "삼성전자·SK하이닉스 반도체 수출 기대감에 상승")]
    assert [r["title"] for r in sector_related_news("0167A0.KS", "2026-10-26", rows)] == [rows[1]["title"]]


@pytest.mark.parametrize("rate,show", [(-10.1, True), (-2.7, False), (10.1, False)])
def test_inflation_reaction_caveat_requires_material_opposite_move(rate, show):
    row = dict(indicator="US_PPI", actual=1.1, previous=.6, forecast=.5, forecast_source="survey fixture",
               unit="%", basis="MoM", status="released", release_at="2026-10-15", reaction_source="fixture",
               reaction=f"2026-10-15 · 10Y {rate:+.2f}bp")
    assert ("동일일 움직임이 단순 해석과 어긋남" in economic_reading_with_reaction(row)) == show
    assert "동일일 움직임" not in economic_reading_with_reaction(dict(row, status="stale"))
    assert "동일일 움직임" not in economic_reading_with_reaction(dict(row, release_at=""))


def test_fx_display_keeps_same_timestamps_and_does_not_double_count():
    days = pd.to_datetime(["2026-10-23", "2026-10-26"])
    at = pd.to_datetime(["2026-10-23T15:25:00+09:00", "2026-10-26T15:25:00+09:00"])
    held = [{"티커": "379810.KS", "현재비중": 30}]
    context = {"sessions": {"KR": "2026-10-26", "US": "2026-10-23"},
               "prices": {"379810.KS": {"date": "2026-10-26", "return": .01}},
               "price_frames": {"379810.KS": pd.DataFrame({"Close": [100, 101]}, index=days)},
               "scenario_frames": {"NQ=F": pd.DataFrame({"Close": [100, 100.54]}, index=at),
                                   "USDKRW=X": pd.DataFrame({"Close": [100, 99.77]}, index=at)}}
    states = market_session_states(NOW, context["sessions"])
    lines = "\n".join(portfolio_fx_lines(held, context, states, NOW))
    assert "30.0%" in lines and "-0.07%p" in lines and "다시 더하지" in lines
    assert "2026-10-23 15:30" in lines and "2026-10-26 15:30" in lines
    assert "+0.31%" in adjusted_reference({"reference": .0054, "fx_return": -.0023}, "379810")
    assert adjusted_reference({"reference": .0054, "fx_return": -.0023}, "418660") == ""
    context["scenario_frames"] = {}
    assert "환율 영향 미연결" in "\n".join(portfolio_fx_lines(held, context, states, NOW))


@pytest.mark.parametrize("held", [
    [{"ticker": "379810.KS", "current_w": 60}, {"ticker": "SOXX", "current_w": 60}],
    [{"ticker": "379810.KS", "current_w": 30}, {"ticker": "379810.KS", "current_w": 30}],
    [{"ticker": "379810.KS", "current_w": 30}, {"ticker": "SOXX", "current_w": None}],
])
def test_fx_withholds_numbers_for_invalid_portfolio_weights(held):
    lines = "\n".join(portfolio_fx_lines(held, {}, {}, NOW))
    assert "추정 보류" in lines and "%p" not in lines


def test_fx_report_uses_quote_collection_completion_time(monkeypatch):
    import stock_lab_core.report_fx as fx

    checked = []
    monkeypatch.setattr(fx, "portfolio_fx_lines", lambda held, context, states, at: checked.append(at) or [])
    now = datetime.fromisoformat("2026-10-26T10:32:00+09:00")
    quote_at = datetime.fromisoformat("2026-10-26T10:32:08+09:00")
    build_auto_market_memo(now=now, report_context={"quote_checked_at": quote_at.isoformat(),
        "sessions": {"KR": "2026-10-23", "US": "2026-10-23"}, "prices": {}})
    assert checked == [quote_at]


def test_report_restores_layers_after_kr_close_and_combines_latest_without_gate_changes():
    context = {"sessions": {"KR": "2026-10-26", "US": "2026-10-23"},
               "prices": {"^KS11": {"date": "2026-10-26", "return": -.01, "previous_return": .02},
                          "396500.KS": {"date": "2026-10-26", "return": -.02},
                          "0167A0.KS": {"date": "2026-10-26", "previous_date": "2026-10-23", "return": -.01},
                          "DRAM": {"date": "2026-10-23", "previous_date": "2026-10-22", "return": .01},
                          "SOXX": {"date": "2026-10-23", "return": -.01, "previous_return": -.02}},
               "intraday_prices": {symbol: {"date": "2026-10-26", "previous_date": "2026-10-23", "return": .02, "as_of": NOW.isoformat()}
                                   for symbol in ("SOXX", "DRAM")}}
    rows = [{"티커": "0167A0.KS", "보유량": 1, "현재비중": 60, "최종읽기": "추세방어", "게이트상태": "방어우선"},
            {"티커": "DRAM", "보유량": 1, "현재비중": 40, "최종읽기": "대기", "게이트상태": "대기/관찰"}]
    before = deepcopy((context, rows))
    report = build_auto_market_memo(report_context=context, now=NOW, summary_rows=rows)
    status = report.split("## 지금 상태 3줄\n", 1)[1].split("\n## ", 1)[0]
    assert "**계좌** · 통합 누적 추정 +0.61%p" in status and "연결 100.0%" in status
    headline = report.split("### 중기·최근 거래일·현재 맥락\n", 1)[1].split("\n관측 축 |", 1)[0]
    assert all(marker in headline for marker in ("[중기]", "[최근 2거래일]", "[한국 마감·미국 현재]", "SOXX +2.00%", "DRAM +2.00%"))
    assert "통합 누적 계좌 영향 추정 +0.61%p" in headline and "연결 100.0%" in headline
    assert "한국 상장 -0.60%p" in headline and "미국 상장 +1.21%p" in headline
    assert (context, rows) == before
