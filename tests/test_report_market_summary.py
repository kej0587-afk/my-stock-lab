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
    # The interpretation is written once (quick summary), not appended to the story.
    reading = result["interpretation"]
    assert reading not in headline and "금리" not in headline
    assert reading.startswith("미국 반도체가 +0.42% 소폭 상승 중입니다") and "코스피 -3.73%로 급락" in reading
    assert "제목 기준" in reading and "원인으로 확정하지 않습니다" in reading
    assert "10Y 금리 5.14%" in reading and "3개월 -7.70%" in reading
    assert "계좌" not in headline + reading and "%p" not in headline + reading
    assert (context, news) == original


def test_mislabeled_morning_wrap_not_used_as_closing_cause(monkeypatch):
    context, news = case()
    morning = dict(news[0], title="코스피 장 초반 2% 상승, 기관 순매수",
                   link="https://www.yna.co.kr/view/fixture-morning", published_at="2026-10-20T10:00:00+09:00")
    monkeypatch.setattr("stock_lab_core.article_context.verified_body_facts", lambda row: [])
    result = market_summary(context, [morning, *news], [], market_session_states(NOW, context["sessions"]), NOW)
    assert "기관 순매수" not in result["market_readings"]["KR"]
    assert "AI 신용우려" in result["market_readings"]["KR"]
    assert morning not in result["background_news"]


def test_wrap_with_morning_rally_and_later_reversal_is_not_rejected():
    from stock_lab_core.report_market_summary import _intraday_snapshot_only
    assert not _intraday_snapshot_only({"title": "코스피 장 초반 반등했지만 하락 마감"}, {"live": False})
    assert not _intraday_snapshot_only({"title": "코스피 장 초반 상승"}, {"live": True})


def test_full_report_keeps_market_conclusion_independent_of_account_and_moves_history_down():
    context, _ = case()
    # Connect the account leg so independence is tested against a changed total.
    context["prices"]["SOXX"]["previous_date"] = "2026-10-16"
    context["intraday_prices"]["SOXX"]["previous_date"] = "2026-10-19"
    reports = [build_auto_market_memo(report_context=context, now=NOW, summary_rows=rows) for rows in (
        [], [{"티커": "SOXX", "현재비중": 99.9, "보유량": 1}])]
    # Nov15 reader layout moves the unchanged detailed blocks into one appendix.
    # Check main market/account independence, then the retained numerical/date
    # assertions below. Original headings and golden values remain unchanged.
    from stock_lab_core.report_view import split_report_sections
    main_sections = [dict(split_report_sections(report)) for report in reports]
    for market in ("한국 시황", "미국 시황"):
        assert main_sections[0][market].split("\n\n")[1] == main_sections[1][market].split("\n\n")[1]
    statuses = [report.split("## 지금 상태 3줄\n", 1)[1].split("\n## ", 1)[0] for report in reports]
    status_lines = [[line for line in status.splitlines() if line.strip()] for status in statuses]
    for lines in status_lines:
        assert len(lines) == 3
        assert lines[0].startswith("**한국 현재**")
        assert lines[1].startswith("**미국 현재")
        assert lines[2].startswith("**계좌**")
    assert status_lines[0][:2] == status_lines[1][:2]
    assert all("계좌" not in line for line in status_lines[0][:2])
    assert status_lines[0][2] != status_lines[1][2]
    assert "입력 미수집" in status_lines[0][2]  # Nov13 distinguishes missing input from partial coverage.
    assert "통합 누적 추정 -0.58%p" in status_lines[1][2] and "연결 99.9%" in status_lines[1][2]
    market_details = [report.split("### 중기·최근 거래일·현재 맥락\n", 1)[1].split("\n\n계좌:", 1)[0]
                      for report in reports]
    assert market_details[0] == market_details[1] and "계좌" not in market_details[0]
    assert "코스피는 하락했습니다(-3.73%" in market_details[0]
    assert "미국 반도체는 반등을 시도 중입니다(+0.42%" in market_details[0]
    assert "AI 신용우려" in market_details[0] and "기사 주장" in market_details[0]
    assert "[중기]" in market_details[0] and "[최근 2거래일]" in market_details[0]
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
    reading = result["interpretation"]
    assert reading.startswith("미국 반도체가 -2.00% 하락 중입니다")
    assert "미국장 배경으로는 AI 신용우려" in reading and "한국장 배경" not in reading.split("미국장 배경")[0]
    assert "하락이 다른 업종으로 번지는지" in reading and "반등폭" not in reading


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
    context["session_news"].extend(dict(context["session_news"][0], title=f"US banks gain after earnings update {i}",
                                      link=f"https://www.reuters.com/bank-fixture-{i}") for i in range(6))
    report = build_auto_market_memo(report_context=context, now=NOW)
    additional = report.split("## 추가 핵심 뉴스")[1].split("## 판정 이력 비교")[0]
    assert "뉴스 1 · " in additional and "\n1. " not in additional


def test_account_opening_promotion_is_not_market_news():
    from stock_lab_core.report_evidence import curate_news
    article = {"title": "모니모서 삼성증권 계좌 만들고 코스피200 주식 받으세요", "publisher": "조선일보",
               "link": "https://www.chosun.com/promotion-fixture", "published_at": "2026-10-20T20:00:00+09:00"}
    assert not curate_news([article], now=NOW)


def test_close_summary_explains_rebound_divergence_and_distinct_medium_trends():
    context, _ = case()
    now = datetime.fromisoformat("2026-10-21T16:30:00+09:00")
    context["sessions"] = {"KR": "2026-10-21", "US": "2026-10-20"}
    context["prices"] = {
        "^KS11": {"date": "2026-10-21", "return": .0329, "return_5d": -.0455},
        "^GSPC": {"date": "2026-10-20", "return": .0028},
        "^IXIC": {"date": "2026-10-20", "return": -.0002},
        "^DJI": {"date": "2026-10-20", "return": .0102},
    }
    context["closed_flow_rows"] = [
        {"Ticker": "SMH", "기준일": "2026-10-20", "3개월수익률": -.0691},
        {"Ticker": "IGV", "기준일": "2026-10-20", "3개월수익률": .2012},
    ]
    original = deepcopy(context)
    result = market_summary(context, [], [], market_session_states(now, context["sessions"]), now)
    headline = result["headline"]
    assert "오늘 반등이 최근 하락분을 모두 회복한 것은 아닙니다" in headline
    assert "최근 5거래일은 -4.55%" in headline
    assert "지수 방향이 엇갈린 혼조" in headline
    reading = result["interpretation"]
    assert reading.startswith("코스피가 +3.29% 급등했습니다(2026-10-21 확정 종가)")
    assert "나스닥 -0.02%, S&P500 +0.28%로 혼조" in reading
    assert "코스피 5거래일 수익률 -4.55%" in reading and "반도체(SMH) 3개월 -6.91%" in reading
    assert "소프트웨어(IGV)" not in reading  # a medium-term strength is not a remaining risk
    assert len(headline.split("\n\n")) == 2
    assert "기사 주장" not in headline  # No news supplied, so no invented catalyst.
    assert context == original


def test_closed_korea_is_not_mislabeled_as_missing_live_quote():
    from stock_lab_core.report_intraday import account_overview_lines

    metrics = {"coverage": 22.4, "total": 1.14, "groups": {
        "KR": {"count": 0, "coverage": 0, "contribution": None},
        "US_EXT": {"count": 4, "coverage": 22.4, "contribution": 1.14}}}
    original = deepcopy(metrics)
    after_close = "\n".join(account_overview_lines(metrics, {}, {}, "closed"))
    assert "한국 상장 장중 | 해당없음 | - | 마감 후" in after_close
    assert "미국 데이마켓·시간외 | +1.14%p | 22.4%" in after_close
    intraday = "\n".join(account_overview_lines(metrics, {}, {}, "intraday"))
    assert "한국 상장 장중 | 미연결" in intraday
    assert metrics == original
