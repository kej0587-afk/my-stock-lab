from copy import deepcopy
from datetime import datetime

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_market_summary import market_summary
from stock_lab_core.report_session import market_session_states


NOW = datetime.fromisoformat("2026-10-21T00:36:00+09:00")


def case():
    context = {"sessions": {"KR": "2026-10-20", "US": "2026-10-19"}, "prices": {
        "^KS11": {"date": "2026-10-20", "return": -.0373, "return_5d": -.08},
        "SOXX": {"date": "2026-10-19", "return": -.01}},
        "intraday_prices": {"SOXX": {"date": "2026-10-20", "return": .0042, "as_of": NOW.isoformat()}},
        "macro_data": {key: {"val": value, "chg": change, "as_of": "2026-10-19"}
                       for key, value, change in (("10Y 금리", 5.14, 2.76), ("유가", 103.66, 3.35))},
        "closed_flow_rows": [{"Ticker": "SOXX", "기준일": "2026-10-19", "3개월수익률": -.077}]}
    news = [{"title": "[마감] 코스피 AI 신용우려에 하락, 외국인 기관 동반 매도", "market": "KR",
             "session_date": "2026-10-20", "publisher": "한국경제", "link": "https://www.hankyung.com/article/fixture",
             "published_at": "2026-10-20T16:00:00+09:00", "news_bucket": "session_news", "is_close_wrap": True}]
    context["session_news"] = news
    return context, news


def test_us_intraday_never_overwrites_korean_credit_background_macro_or_flow():
    context, news = case()
    original = deepcopy((context, news))
    result = market_summary(context, news, [], market_session_states(NOW, context["sessions"]), NOW)
    headline = result["headline"]
    assert "AI 신용우려" in headline and "기사 주장" in headline
    assert "코스피는 하락했습니다(-3.73%" in headline
    assert "미국 반도체는 반등을 시도 중입니다(+0.42%" in headline and "2026-10-20 장중·확정 아님" in headline
    assert "금리" in headline and "반도체 중기 약세" in headline
    assert "계좌" not in headline and "%p" not in headline
    assert (context, news) == original


def test_full_report_keeps_market_conclusion_independent_of_account_and_moves_history_down():
    context, _ = case()
    reports = [build_auto_market_memo(report_context=context, now=NOW, summary_rows=rows) for rows in (
        [], [{"티커": "SOXX", "현재비중": 99.9, "보유량": 1}])]
    headlines = [report.split("## 한 줄 결론\n")[1].split("\n\n")[0] for report in reports]
    assert headlines[0] == headlines[1] and "계좌" not in headlines[0]
    assert reports[1].index("## 판정 이력 비교") > reports[1].index("## 오늘의 시장 스토리")
    assert reports[1].count("## 내 보유 종목 영향") == 1


def test_stale_or_wrong_session_macro_and_flow_do_not_create_current_risk_story():
    context, news = case()
    for row in context["macro_data"].values():
        row["as_of"] = "2026-10-16"
    context["closed_flow_rows"][0]["기준일"] = "2026-10-16"
    result = market_summary(context, news, [], market_session_states(NOW, context["sessions"]), NOW)
    assert "부담" not in result["headline"] and "중기 약세" not in result["headline"]
    assert "자료 미연결" in result["evidence"][2][1]


def test_live_korean_rebound_does_not_inherit_last_close_decline_news():
    context, news = case()
    now = datetime.fromisoformat("2026-10-21T10:00:00+09:00")
    context["intraday_prices"]["^KS11"] = {"date": "2026-10-21", "return": .02, "as_of": now.isoformat()}
    result = market_summary(context, news, [], market_session_states(now, context["sessions"]), now)
    assert "코스피는 반등을 시도 중입니다(+2.00%" in result["headline"]
    assert "AI 신용우려" not in result["headline"]


def test_second_up_day_can_still_be_a_rebound_with_verified_negative_five_day_return():
    context, news = case()
    context["prices"]["SOXX"].update({"return": .0173, "return_5d": -.08})
    result = market_summary(context, news, [], market_session_states(NOW, context["sessions"]), NOW)
    assert "반등을 시도 중" in result["headline"]


def test_equity_futures_forecast_is_not_used_as_current_rebound_background():
    context, _ = case()
    forecast = {"market": "US", "session_date": "2026-10-20", "news_bucket": "current_session_news",
                "title": "Wall Street Futures Rise as Technology Stocks Recover and Oil Prices Ease",
                "publisher": "Reuters", "published_at": "2026-10-20T09:00:00-04:00",
                "link": "https://www.reuters.com/futures-fixture"}
    context["session_news"] = []
    context["current_session_news"] = [forecast]
    report = build_auto_market_memo(report_context=context, now=NOW)
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    assert forecast["title"] not in story


def test_english_coreweave_plural_shares_and_axios_survive_source_curation():
    from stock_lab_core.report_evidence import curate_news
    article = {"title": "CoreWeave shares rebound after debt worries", "publisher": "Axios",
               "link": "https://www.axios.com/2026/10/20/fixture", "published_at": "2026-10-20T10:00:00-04:00"}
    assert len(curate_news([article], now=NOW)) == 1


def test_us_credit_background_is_not_attached_to_korean_market_move():
    context, _ = case()
    context["intraday_prices"]["SOXX"]["return"] = -.02
    article = {"title": "US technology stocks fall on AI credit worries", "market": "US",
               "session_date": "2026-10-20", "news_bucket": "current_session_news",
               "published_at": "2026-10-20T10:00:00-04:00", "publisher": "Reuters",
               "link": "https://www.reuters.com/us-credit-fixture"}
    result = market_summary(context, [article], [], market_session_states(NOW, context["sessions"]), NOW)
    assert result["headline"].index("코스피") < result["headline"].index("AI 신용우려")
    assert "약세 확산 여부" in result["headline"] and "반등 지속성" not in result["headline"]


def test_next_session_material_is_not_used_as_generic_story_fallback():
    context, _ = case()
    article = {"title": "US chip stocks recover after funding deal", "market": "US",
               "session_date": "2026-10-20", "news_bucket": "next_session_news",
               "published_at": "2026-10-20T17:00:00-04:00", "publisher": "Reuters",
               "link": "https://www.reuters.com/next-fixture"}
    context["session_news"] = []
    context["next_session_news"] = [article]
    report = build_auto_market_memo(report_context=context, now=datetime.fromisoformat("2026-10-21T09:00:00+09:00"))
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    assert article["title"] not in story


def test_preopen_price_recap_is_not_used_as_intraday_rebound_evidence():
    context, _ = case()
    title = "US stocks recover after AI sell-off"
    article = {"title": title, "market": "US", "session_date": "2026-10-20",
               "news_bucket": "current_session_news", "publisher": "Financial Times",
               "published_at": "2026-10-20T07:00:00-04:00", "link": "https://www.ft.com/recap-fixture"}
    context["session_news"] = []
    context["current_session_news"] = [article]
    report = build_auto_market_memo(report_context=context, now=NOW)
    assert title not in report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    assert "개장 전 가격회고·대상 거래일 미확정" in report


def test_additional_news_rows_do_not_start_markdown_numbered_lists():
    context, _ = case()
    context["session_news"] = [{"title": "US chip stocks advance on earnings", "market": "US",
                               "session_date": "2026-10-19", "publisher": "Reuters",
                               "link": "https://www.reuters.com/earnings-fixture",
                               "published_at": "2026-10-19T15:00:00-04:00"}]
    # Mark the first article as used by the generic story; retain another item.
    context["session_news"].append(dict(context["session_news"][0], title="US banks gain after earnings",
                                         link="https://www.reuters.com/bank-fixture"))
    report = build_auto_market_memo(report_context=context, now=NOW)
    additional = report.split("## 추가 핵심 뉴스")[1].split("## 판정 이력 비교")[0]
    assert "뉴스 1 · " in additional and "\n1. " not in additional


def test_account_opening_promotion_is_not_market_news():
    from stock_lab_core.report_evidence import curate_news
    article = {"title": "모니모서 삼성증권 계좌 만들고 코스피200 주식 받으세요", "publisher": "조선일보",
               "link": "https://www.chosun.com/promotion-fixture", "published_at": "2026-10-20T20:00:00+09:00"}
    assert not curate_news([article], now=NOW)
