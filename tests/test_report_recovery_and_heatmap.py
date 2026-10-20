from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest

from stock_lab_core import economic_cache, market_board
from stock_lab_core.economic_bulletins import apply_official_bulletins
from stock_lab_core.report_analysis import economic_story_lines, sector_evidence
from stock_lab_core.report_presentation import account_metrics, candidate_line, sector_related_news

NOW = datetime.fromisoformat("2026-10-19T10:47:00+09:00")


def success():
    return dict(indicator="KR_CPI", period="2026-09", actual=2.9, previous=3.1, unit="%", basis="YoY",
                status="released", retrieved_at="2026-10-18T03:00:00+00:00", source="Bank of Korea ECOS")


def test_economic_success_survives_failure_without_stale_as_fresh():
    now = NOW.astimezone(timezone.utc)
    row = success()
    assert economic_cache.retain_successful_observations([row], now)[0] == row
    bad = dict(row, actual=None, period="", status="unavailable", missing_reason="request_failed:ReadTimeout")
    result = economic_cache.retain_successful_observations([bad], now)[0]
    assert result["status"] == "stale" and result["actual"] == 2.9 and result["period"] == "2026-09"
    assert result["last_success_at"] == row["retrieved_at"]
    assert economic_cache.collection_status(result) == "응답 시간 초과"
    assert not economic_story_lines([result])
    assert json.loads(economic_cache.CACHE_PATH.read_text(encoding="utf-8"))["KR_CPI"]["actual"] == 2.9
    result = economic_cache.retain_successful_observations([dict(row, actual=3.0)], now)[0]
    assert result["status"] == "released" and result["actual"] == 3.0


def test_failure_never_seeds_disk_and_expired_or_future_success_not_reused():
    bad = dict(success(), actual=None, status="unavailable", missing_reason="http_403")
    assert economic_cache.retain_successful_observations([bad], NOW)[0]["actual"] is None
    assert not economic_cache.CACHE_PATH.exists()
    economic_cache.retain_successful_observations([success()], NOW)
    for now in (NOW + timedelta(days=200), NOW - timedelta(days=5)):
        assert economic_cache.retain_successful_observations([bad], now)[0]["actual"] is None


def test_verified_bulletins_use_latest_vintage_and_expire_without_live_claim():
    rows = [dict(success(), actual=None, period="", status="unavailable"),
            dict(success(), indicator="KR_EXPORTS", period="2026-08", actual=68.7)]
    revised = apply_official_bulletins(rows, NOW)
    # The ministry's manual CPI fallback is retired. Without an explicitly
    # enabled primary-source fetch, do not manufacture an official observation.
    assert revised[0]["actual"] is None and revised[0]["status"] == "unavailable"
    assert revised[1]["actual"] == 83.7 and revised[1]["previous"] == 68.9
    assert round((revised[1]["raw_actual"] / revised[1]["raw_year_ago"] - 1) * 100, 1) == 83.7
    assert revised[1]["history"] == [] and revised[1]["forecast"] is None
    unchanged = [dict(rows[0], fallback_mode="unavailable", bulletin_collection_error="cpi_primary_automatic_fetch_not_enabled"), rows[1]]
    assert apply_official_bulletins(rows, NOW + timedelta(days=40)) == unchanged
    assert apply_official_bulletins(rows, NOW - timedelta(days=1)) == unchanged
    fresh = dict(success(), period="2026-10", actual=3.0)
    assert apply_official_bulletins([fresh], NOW) == [fresh]


def test_replacement_not_sum_and_no_double_leverage():
    rows = [{"티커": "379810.KS", "현재비중": 30}, {"티커": "418660.KS", "현재비중": 10},
            {"티커": "SOXL", "현재비중": 5}, {"티커": "0167A0.KS", "현재비중": 10}]
    prices = {t: {"return": v, "date": "2026-10-16"} for t, v in
              {"379810.KS": .03, "418660.KS": .06, "QQQ": -.02, "SOXL": -.12, "0167A0.KS": .01}.items()}
    m = account_metrics(rows, prices, {"KR": "2026-10-16", "US": "2026-10-16"})
    assert m["daily"] == pytest.approx(1.0)
    assert m["gap"] == pytest.approx(-1.0)
    assert m["replacement"] == pytest.approx(-1.6)  # Remove domestic returns, insert proxy once.
    assert m["replacement_coverage"] == 45 and m["concentration"] == 40
    prices["QQQ"]["date"] = "2026-10-15"
    m = account_metrics(rows, prices, {"KR": "2026-10-16", "US": "2026-10-16"})
    assert m["replacement_coverage"] == 5


def test_grade_uses_quality_before_gate_decorated_grade():
    line = candidate_line({"티커": "AAPL", "종목명": "애플", "후보품질": "A급 (분할 매수)",
                           "📌후보등급": "방어우선", "게이트상태": "방어우선"})
    assert "개별 신호 A급, 게이트로 보류" in line and "분할 매수" not in line


def test_us_wrap_matches_exposure_not_korean_cxmt_for_tech():
    base = dict(market="US", session_date="2026-10-16")
    news = [dict(base, title="Wall Street doubts CXMT 4F² DRAM edge as Korea retains density and yield lead"),
            dict(base, title="美 AI·반도체 급락 쇼크"), dict(base, title="美 소프트웨어 약세 마감"),
            dict(base, title="美 AI주 중심 약세 마감")]
    for ticker in ("SOXX", "XLK", "IGV"):
        matched = sector_related_news(ticker, "2026-10-16", news)
        assert matched and all("CXMT" not in row["title"] for row in matched)
        assert not sector_related_news(ticker, "2026-10-15", news)
    matched = sector_related_news("IGV", "2026-10-16", [news[-1]])
    assert matched[0]["market_context_only"]
    row = {"Ticker": "IGV", "1일수익률": -.04, "기준일": "2026-10-16"}
    assert "직접 원인 아님" in sector_evidence(row, {}, matched)["reading"]
    xlk = sector_evidence(dict(row, Ticker="XLK"), {"10Y 금리": {"as_of": "2026-10-16", "day_change_bp": .9}}, [])
    assert "연준 할인율 설명" not in xlk["reading"]


def test_inflation_facts_and_opposite_yield_reaction_are_separate():
    row = dict(indicator="US_PPI", period="2026-09", actual=1.3, previous=.5, unit="%", basis="MoM",
               reaction="10Y -10.10bp", reaction_source="Yahoo daily")
    output = "\n".join(economic_story_lines([row]))
    assert "생산단계 비용 압력" in output and "동일일 움직임이 단순 해석과 어긋남" in output


@pytest.mark.parametrize("market,count", [("KR", 36), ("US", 52)])
def test_stock_heatmap_coverage_and_negative_live_bar(market, count):
    instruments = market_board.market_instruments(market, "stocks")
    stocks = [item for item in instruments if item.kind == "stock"]
    assert len(stocks) == count and len({i.ticker for i in instruments}) == count + 4
    frame = pd.DataFrame({"Close": [100, 110, 99]}, index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"]))
    now = "2026-10-19T18:00:00Z"
    frames = {item.ticker: frame for item in stocks[:-1]}
    snapshot = market_board.build_market_snapshot(market, frames, scope="stocks", now=now, include_current=True)
    view = snapshot[snapshot.kind == "stock"]
    counts = market_board.breadth_counts(view)
    assert counts == dict(positive=0, negative=count-1, neutral=0, missing=1)
    assert view.return_pct.dropna().lt(0).all()
    figure = market_board.build_treemap(view)
    assert len([i for i in figure.data[0].ids if not i.startswith("group:")]) == count
    assert figure.layout.height == 620
    assert any(stocks[0].name in label for label in figure.data[0].labels)


def test_stock_view_apptest_is_lazy_and_switch_safe(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(market_board, "load_market_frames", lambda *args: pytest.fail("unexpected network"))
    as_utc = market_board._as_utc
    monkeypatch.setattr(market_board, "_as_utc", lambda now=None: as_utc(
        now if now is not None else "2026-10-19T18:00:00Z"))
    source = '''
import pandas as pd
import streamlit as st
from stock_lab_core import market_board as b
frames = {item.ticker: pd.DataFrame({'Close':[100,110,99]}, index=pd.to_datetime(['2026-10-15','2026-10-16','2026-10-19']))
          for m in ('KR','US') for item in b.market_instruments(m, 'stocks')}
b.render_market_board(st, key='test', frames=frames)
'''
    app = AppTest.from_string(source, default_timeout=20).run()
    assert app.radio(key="test_scope").value == "대표 종목"
    assert not app.exception and len(app.dataframe[0].value) == 36
    assert app.dataframe[0].value["수익률(%)"].notna().all()
    app.radio(key="test_market").set_value("US").run()
    assert not app.exception and len(app.dataframe[0].value) == 52
    assert app.dataframe[0].value["수익률(%)"].notna().all()
    app.selectbox(key="test_US_stocks_group").select("하드웨어").run()
    assert set(app.dataframe[0].value["티커"]) == {"AAPL", "DELL", "HPE", "ANET"}
    app.radio(key="test_scope").set_value("섹터 ETF").run()
    assert not app.exception and len(app.dataframe[0].value) == 11
