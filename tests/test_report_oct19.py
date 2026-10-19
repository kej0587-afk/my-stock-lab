from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core import market_board, prices
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import intraday_observation, price_observation
from stock_lab_core.report_presentation import account_estimate, macro_change, oil_explanation
from stock_lab_core.report_history import update_report_history
from stock_lab_core.report_analysis import sector_evidence
from stock_lab_core.today_news import partition_session_market_news

NOW = datetime.fromisoformat("2026-10-19T09:39:00+09:00")
SESSIONS = {market: {"date": "2026-10-16", "previous_date": "2026-10-15"} for market in ("KR", "US")}


def review_case():
    # Values/headlines from the user's report; portfolio weights are test-only.
    macro = {"10Y 금리": {"val": 5.10, "chg": 3.05}, "VIX": {"val": 19.99, "chg": 29.47},
             "MOVE": {"val": 101.10, "chg": 25.23}, "유가": {"val": 101.41, "chg": -.49},
             "환율": {"val": 1340.95, "chg": -2.59}}
    for row in macro.values():
        row.update(as_of="2026-10-16", source="Yahoo Finance daily", base_date="2026-09-17")
    previous = deepcopy(macro)
    previous["유가"].update(val=99.02, chg=-2.84)
    news = [
        {"title": "美 AI·반도체 급락 쇼크에…코스피 다시 위기감 고조", "market": "KR",
         "publisher": "뉴시스", "published_at": "2026-10-19T07:39:04+09:00", "link": "https://www.newsis.com/"},
        {"title": "순매수 전환한 외국인…코스피 2% 상승 마감", "market": "KR", "publisher": "아시아경제",
         "published_at": "2026-10-16T16:53:00+09:00", "link": "https://www.asiae.co.kr/"},
        {"title": "전날 7%대 급락 코스피, 1% 내외 강세", "market": "KR", "publisher": "연합뉴스",
         "market_category": "마감 시황", "published_at": "2026-10-16T09:36:15+09:00", "link": "https://www.yna.co.kr/"},
    ]
    observations = {ticker: {"date": "2026-10-16", "return": value} for ticker, value in
                    {"^KS11": .0205, "^KQ11": .0446, "^GSPC": -.0109, "^IXIC": -.0215,
                     "^DJI": -.0034, "SOXX": -.0414, "SOXL": -.1274, "QQQ": -.025,
                     "379810.KS": 0, "0167A0.KS": .0214}.items()}
    context = {"sessions": {m: "2026-10-16" for m in SESSIONS}, "news_sessions": SESSIONS,
               "prices": observations, "macro_data": macro, "previous_macro_data": previous,
               "sector_rows": [{"Ticker": "SOXX", "섹터": "반도체", "구분": "미국 섹터", "기준일": "2026-10-16", "1일수익률": -.0414}],
               "session_news": news, "calendar_events": [{"title": "FOMC", "date": "2026-10-28", "source": "Federal Reserve"}],
               "calendar_sources": [{"name": "BLS CPI", "status": "failed", "reason": "http_403"}]}
    rows = [{"종목명": "반도체 3배(예시)", "티커": "SOXL", "보유량": 1, "현재비중": 10, "게이트상태": "방어우선"},
            {"종목명": "나스닥(예시)", "티커": "379810.KS", "보유량": 1, "현재비중": 30, "게이트상태": "방어우선"},
            {"종목명": "애플", "티커": "AAPL", "보유량": 0, "📌후보등급": "✅A급 (분할 매수)",
             "게이트상태": "방어우선", "게이트근거": "시장방어: 신규매수 중단", "Adj점수": 8}]
    return context, rows


def test_report_acceptance_and_input_immutability():
    context, rows = review_case()
    before = deepcopy((context, rows))
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW)
    assert "# Stock Lab 자동 뉴스픽 · 2026-10-19 09:39 KST" in report
    assert "100달러 이상 수준 경고 → 유가 기여 +18점" in report and "90~100달러 하락 구간의 +0" not in report
    assert "스트레스 74→92" in report and "동일 기준일 자료 변경" in report
    assert "애플(AAPL) · 개별 신호 A급, 게이트로 보류" in report and "A급 (분할 매수)" not in report
    assert "신규매수 중단 해제" in report
    sector = report.split("## 업종별 왜")[1].split("## 내 보유")[0]
    assert "SOXX" in sector and "보도 요약(기사 주장" in sector and "美 AI·반도체 급락" in sector
    assert "전날 7%대 급락" in report and "[장중 보도]" in report
    assert "계좌 일간 기여 합계(추정): -1.27%p" in report and "-0.75%p" in report
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    assert "전날 7%대 급락" in story and "계좌 일간 기여 합계" in story
    assert "개장 후 당일 등락: 미수집" in report and "다음 개장 갭" not in report
    assert "FOMC · D-9" in report and "공식 일정: BLS CPI · http_403" in report
    assert (context, rows) == before


@pytest.mark.parametrize("value,expected", [(101.41, "+18점"), (99.02, "+0점"), (85, "-8점")])
def test_oil_current_branch_only(value, expected):
    result = oil_explanation({"유가": {"val": value, "chg": -2}})
    assert expected in result
    if value >= 100:
        assert "90~100" not in result


def test_market_board_now_declines_even_when_previous_close_rose():
    frame = pd.DataFrame({"Close": [100, 102, 92]}, index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"]))
    frames = {"^KS11": frame}
    old = market_board.build_market_snapshot("KR", frames, now=NOW).iloc[0]
    live = market_board.build_market_snapshot("KR", frames, now=NOW, include_current=True).iloc[0]
    assert old["return_pct"] == pytest.approx(2)
    assert live["return_pct"] == pytest.approx((92 / 102 - 1) * 100)
    assert live["close_date"] == "2026-10-19" and live["base_date"] == "2026-10-16"
    assert "진행 중" in live["status"]
    obs = intraday_observation(frame, "^KS11", NOW)
    assert obs["return"] == pytest.approx(92 / 102 - 1)
    assert not intraday_observation(frame.iloc[:-1], "^KS11", NOW)
    stale = market_board.build_market_snapshot("KR", {"^KS11": frame.iloc[:-1]}, now=NOW, include_current=True).iloc[0]
    assert pd.isna(stale["return_pct"]) and "오늘자 일봉 미수집" in stale["status"]


def test_price_multiday_context_uses_closed_bars_only():
    frame = pd.DataFrame({"Close": [100, 99, 98, 97, 90, 92, 80]}, index=pd.bdate_range("2026-10-09", periods=7))
    row = price_observation(frame, "^KS11", NOW)
    assert row["date"] == "2026-10-16" and row["previous_return"] == pytest.approx(90 / 97 - 1)
    assert row["return_5d"] == pytest.approx(-.08) and row["down_days"] == 0


def test_rate_small_move_is_not_cited_as_discount_pressure():
    row = {"Ticker": "XLK", "1일수익률": -.03, "기준일": "2026-10-16"}
    data = {"10Y 금리": {"as_of": "2026-10-16", "day_change_bp": .9}}
    assert "할인율 부담 가능성" not in sector_evidence(row, data, [])["reading"]
    data["10Y 금리"]["day_change_bp"] = 6
    assert "할인율 부담 가능성" in sector_evidence(row, data, [])["reading"]


def test_macro_history_same_session_updates_and_owner_isolation(tmp_path):
    context, rows = review_case()
    kwargs = dict(path=tmp_path / "history.json", owner_scope="alice")
    update_report_history(rows, context["sessions"], macro_data=context["previous_macro_data"], **kwargs)
    result = update_report_history(rows, context["sessions"], macro_data=context["macro_data"], **kwargs)
    assert "74→92" in macro_change(result["previous_macro_data"], context["macro_data"])
    assert not update_report_history(rows, context["sessions"], path=kwargs["path"], owner_scope="bob").get("previous_macro_data")


def test_account_estimate_does_not_invent_missing_or_double_leverage():
    context, rows = review_case()
    assert "-1.27%p" in account_estimate(rows[:1], context["prices"], context["sessions"])
    bad = dict(rows[0], 현재비중=float("nan"))
    assert "보류" in account_estimate([bad], context["prices"], context["sessions"])
    assert "보류" in account_estimate([rows[0], rows[0]], context["prices"], context["sessions"])


def test_news_recap_not_generic_weekend_or_future_event():
    context, _ = review_case()
    rows = [dict(context["session_news"][0], title="미국 반도체 다음주 실적 발표 예정"),
            dict(context["session_news"][0], title="美 AI 주식 시간외 급락 쇼크")]
    result = partition_session_market_news(rows, SESSIONS, now=NOW)
    assert not result["session_news"] and len(result["next_session_news"]) == 2


def test_naver_quote_shared_across_different_batches_and_manual_clear(monkeypatch):
    calls = []
    class Response:
        def read(self):
            return b'{}'
    monkeypatch.setattr(prices.urllib.request, "urlopen", lambda *a, **k: calls.append(a[0].full_url) or Response())
    monkeypatch.setattr(prices, "_parse_naver_realtime_quotes", lambda body, tickers: {t: {"price": 100, "change_pct": -1} for t in tickers})
    monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda tickers: {})
    prices.clear_latest_price_cache()
    try:
        prices.load_latest_kr_quotes_batch(["005930.KS", "000660.KS"])
        prices.load_latest_kr_quotes_batch(["005930.KS", "267260.KS"])
        prices._fetch_naver_realtime_quote("005930.KS")
        assert len(calls) == 3  # Five lookups, three distinct symbols.
        prices.clear_latest_price_cache()
        prices._fetch_naver_realtime_quote("005930.KS")
        assert len(calls) == 4
    finally:
        prices.clear_latest_price_cache()
