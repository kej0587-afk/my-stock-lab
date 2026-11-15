from copy import deepcopy
from datetime import datetime

from stock_lab_core.report_coverage import company_coverage_lines, context_news_lines, sector_coverage_lines

NOW = datetime.fromisoformat("2026-11-15T18:00:00+09:00")
DAY = "2026-11-13"


def test_all_collected_sectors_not_just_winners_and_tech_no_input_mutation():
    tickers = ["XLF", "XLP", "XLV", "XLE", "XLK", "XLI", "VNQ", "IBB", "SOXX", "SMH", "SOXL"]
    rows = [dict(Ticker=t, 섹터=t, 구분="미국 섹터", 기준일=DAY, 수치종류="확정 종가", **{"1일수익률": .02}) for t in tickers]
    context = dict(sessions={"US": DAY}, closed_flow_rows=rows,
                   prices={"^GSPC": dict(date=DAY, **{"return": -.01})})
    context["closed_flow_rows"] += [dict(Ticker="CIBR", 기준일="2026-11-12", **{"1일수익률": .09}),
                                   dict(Ticker="XHB", 기준일=DAY, 수치종류="장중", **{"1일수익률": .09})]
    before = deepcopy(context)
    rendered = "\n".join(sector_coverage_lines(context, [], "US", NOW))
    for ticker in tickers[:-2]:
        if ticker != "SMH":
            assert f"({ticker})" in rendered
    assert all(t not in rendered for t in ("SMH", "SOXL", "CIBR", "XHB"))
    assert "+3.00%p" in rendered
    assert context == before


def test_company_breadth_counts_only_available_same_session_and_period():
    prices = {t: dict(date=DAY, previous_date="2026-11-12", source="fixture", **{"return": value})
              for t, value in [("NVDA", -.02), ("AMD", .03), ("WMT", .01), ("JPM", .01), ("LLY", -.01)]}
    prices.update(AVGO=dict(date="2026-11-12", **{"return": .8}),
                  MU=dict(date=DAY, stale=True, **{"return": .7}),
                  AMAT=dict(date=DAY, previous_date="2026-11-11", **{"return": .2}),
                  **{"^GSPC": dict(date=DAY, previous_date="2026-11-12")})
    rendered = "\n".join(company_coverage_lines(dict(sessions={"US": DAY}, prices=prices), [], "US"))
    assert "반도체 | 1/2" in rendered
    assert "소비재 | 1/1" in rendered and "금융 | 1/1" in rendered
    assert "AMD(AMD) +3.00%" in rendered and "fixture" in rendered
    assert "AVGO" not in rendered and "AMAT" not in rendered and "MU)" not in rendered
    assert "이번 보고서에 가격이 연결된 종목만" in rendered


def test_company_prices_are_separate_from_portfolio_prices_and_missing_is_explicit():
    context = dict(sessions={"US": DAY}, prices={"NVDA": dict(date=DAY, **{"return": .9}),
        "^GSPC": dict(date=DAY, previous_date="2026-11-12")}, company_prices={})
    assert "기업 가격 미확보" in "\n".join(company_coverage_lines(context, [], "US"))
    context["company_prices"] = {"NVDA": dict(date=DAY, previous_date="2026-11-12", source="fixture", **{"return": -.01})}
    rendered = "\n".join(company_coverage_lines(context, [], "US"))
    assert "NVIDIA(NVDA) -1.00%" in rendered and "+90.00%" not in rendered


def test_company_coverage_reports_connected_scope_and_shares_attributed_sources_once():
    prices = {ticker: dict(date=DAY, source=source, **{"return": value}) for ticker, source, value in
              [("NVDA", "fixture-source-a", .01), ("AMD", "fixture-source-a", -.01), ("JPM", "fixture-source-b", .02)]}
    context = dict(sessions={"US": DAY}, company_prices=prices,
                   company_price_diagnostics={"coverage": {"US": {"expected": 8, "connected": 3}}})
    output = "\n".join(company_coverage_lines(context, [], "US"))
    assert "수집 연결 3/8 · 동일 세션 표기 3개" in output
    assert output.count("fixture-source-a") == output.count("fixture-source-b") == 1
    assert "NVIDIA(NVDA) +1.00% [1]" in output and "JPMorgan(JPM) +2.00% [2]" in output
    assert "분야 | 상승/관측 | 종목별 등락\n" in output
    context["company_prices"] = {}
    context["company_price_diagnostics"]["coverage"]["US"]["connected"] = 0
    output = "\n".join(company_coverage_lines(context, [], "US"))
    assert "수집 연결 0/8" in output and "기업 가격 미확보" in output


def article(title, path, published="2026-11-13T22:00:00+00:00", **fields):
    return dict(title=title, link="https://www.reuters.com/markets/" + path, publisher="Reuters",
                published_at=published, market="US", session_date=DAY, **fields)


def test_post_close_market_report_not_limited_to_fixed_company_list():
    rows = [article("Fed financial stability report warns about stock market valuations", "fed"),
            article("Modine shares rise on acquisition talks", "modine"),
            article("Future earnings report", "future", "2026-11-16T01:00:00+00:00"),
            article("Stocks fall before the close", "before", "2026-11-13T19:00:00+00:00")]
    context = dict(sessions={"US": DAY}, next_session_news=rows,
                   windows=[dict(market="US", date=DAY, end="2026-11-13T21:00:00+00:00")])
    output = "\n".join(context_news_lines(context, NOW, bucket="next_session_news", market="US"))
    assert "financial stability" in output and "Modine" in output
    assert "Future earnings" not in output and "before the close" not in output
    assert "제목 확인·기사 주장" in output and "마감 후·다음 세션" in output
    assert context_news_lines({**context, "windows": []}, NOW, bucket="next_session_news") == []


def test_global_topics_retained_without_claiming_us_close_cause_and_no_duplicate():
    row = article("China banks raise capital as financial stocks rise", "china")
    row.update(market="CN", news_bucket="other_market_news")
    context = {"other_market_news": [row, dict(row)]}
    output = "\n".join(context_news_lines(context, NOW, bucket="other_market_news"))
    assert output.count("China banks") == 1
    assert "해외·공통 맥락" in output
    assert context_news_lines(context, NOW, bucket="other_market_news", excluded=[row["link"]]) == []


def test_distinct_boj_events_survive_old_topic_cluster_and_prior_exclusion(monkeypatch):
    a = article("BOJ raises interest rates as yen strengthens", "boj-rate")
    b = article("BOJ cuts bond purchases in liquidity policy update", "boj-bond")
    a["market"] = b["market"] = "JP"
    context = {"other_market_news": [a, b]}
    result = "\n".join(context_news_lines(context, NOW, bucket="other_market_news"))
    assert a["title"] in result and b["title"] in result
    result = "\n".join(context_news_lines(context, NOW, bucket="other_market_news", excluded=[a["link"]]))
    assert a["title"] not in result and b["title"] in result
    facts = [dict(summary=f"확인 사실 {i}", implication=f"의미 {i}", check=f"확인 {i}") for i in range(3)]
    monkeypatch.setattr("stock_lab_core.article_context.verified_body_facts", lambda _: facts + facts[:1])
    result = "\n".join(context_news_lines({"other_market_news": [a]}, NOW, bucket="other_market_news"))
    assert result.count("확인 사실 0") == 1 and "확인 사실 2" in result and "의미 2" in result
