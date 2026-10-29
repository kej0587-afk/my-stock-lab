from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_brief import brief_theme, news_brief_lines

NOW = datetime.fromisoformat("2026-10-21T20:15:00+09:00")
CONTEXT = {"sessions": {"KR": "2026-10-21", "US": "2026-10-20"}}


def article(title, **kwargs):
    return {"title": title, "publisher": "Reuters", "link": "https://www.reuters.com/fixture",
            "published_at": "2026-10-20T15:00:00-04:00", "market": "US",
            "session_date": "2026-10-20", "news_bucket": "session_news", **kwargs}


@pytest.mark.parametrize("title,theme", [
    ("CoreWeave debt worries deepen", "반도체·AI"),
    ("MSCI earnings beat forecasts", "금융·기업실적"),
    ("Tesla unveils Roadster", "자동차·모빌리티"),
    ("BAE Systems signs APKWS supply agreement", "방산·군수"),
    ("US retail sales rise", "시장·업종"),
    ("Bitcoin gains", "암호화폐"),
])
def test_company_identity_prevents_example_classification_errors(title, theme):
    assert brief_theme(article(title)) == theme


def test_brief_uses_existing_dated_news_links_underlyings_and_never_changes_gates():
    held = [{"티커": "SOXL", "보유량": 1, "게이트상태": "방어우선"},
            {"티커": "RAM", "보유량": 1, "게이트상태": "방어우선"}]
    rows = [article("엔비디아, 신규 AI 칩 공급 계획 발표")]
    before = deepcopy((CONTEXT, rows, held))
    result = "\n".join(news_brief_lines(CONTEXT, rows, held, NOW))
    assert "SOXL" in result and "RAM" in result
    assert "10/21 04:00 KST" in result and "US 2026-10-20 종가 세션" in result
    assert rows[0]["link"] in result and "실제 가격 기여도나 매매 허용" in result
    assert "\n\n보도 내용은" in result
    assert (CONTEXT, rows, held) == before


def test_wrong_day_future_forecast_and_next_session_are_not_market_catalysts():
    rows = [article("CoreWeave financing", session_date="2026-10-19"),
            article("CoreWeave financing", news_bucket="next_session_news"),
            article("Wall St set for lower open as oil jumps"),
            article("CoreWeave financing", published_at="2026-10-22T10:00:00-04:00")]
    result = "\n".join(news_brief_lines(CONTEXT, rows, [], NOW))
    assert "미확보" in result and "원문" not in result


def test_brief_caps_rows_and_per_theme_instead_of_filling_every_row_with_ai():
    rows = [article(f"NVIDIA chip supply plan {i}", link=f"https://www.reuters.com/fixture-{i}") for i in range(10)]
    rows.append(article("Bitcoin gains", link="https://www.reuters.com/btc-fixture"))
    output = news_brief_lines(CONTEXT, rows, [], NOW)
    assert sum(line.startswith("반도체·AI |") for line in output) == 2
    assert any(line.startswith("암호화폐 |") for line in output)


def test_official_company_catalyst_is_not_discarded_for_lacking_price_keywords():
    from stock_lab_core.report_evidence import curate_news, news_category
    row = article("AWS announces TorchNeuron: Native PyTorch Support for AWS Trainium (Public Beta)",
                  publisher="AWS", link="https://aws.amazon.com/about-aws/whats-new/2026/10/fixture/")
    assert len(curate_news([row], now=NOW)) == 1
    assert news_category("CoreWeave ROI and debt concerns", "암호화폐") == "반도체/AI"
    assert news_category("MSCI EPS beats", "매크로") == "금융/기업실적"


def test_korean_sector_story_is_not_presented_as_direct_us_constituent_exposure():
    row = article("코스피 한국 반도체 강세", market="KR", session_date="2026-10-21",
                  published_at="2026-10-21T16:00:00+09:00")
    held = [{"티커": "SOXL", "보유량": 1}]
    assert "타시장 동종업종 참고: SOXL" in "\n".join(news_brief_lines(CONTEXT, [row], held, NOW))


def test_cybersecurity_etf_does_not_inherit_every_chip_catalyst():
    held = [{"티커": "CIBR", "종목명": "사이버보안", "보유량": 1}]
    chips = "\n".join(news_brief_lines(CONTEXT, [article("NVIDIA AI chip supply rises")], held, NOW))
    assert "CIBR" not in chips
    cyber = "\n".join(news_brief_lines(CONTEXT, [article("F5 and Fortinet guidance disappoints")], held, NOW))
    assert "사이버보안" in cyber and "CIBR(보안업종 간접)" in cyber
    assert "하락 주도" not in cyber


def test_alphabet_is_identified_as_company_earnings_not_unrelated_market_news():
    assert brief_theme(article("Alphabet capex rises and free cash flow falls")) == "빅테크·기업실적"


def test_summary_connects_rebound_drivers_but_rejects_a_relabelled_previous_day_article():
    from stock_lab_core.report_market_summary import market_summary
    from stock_lab_core.report_session import market_session_states
    context = {**CONTEXT, "prices": {"^KS11": {"date": "2026-10-21", "return": .0329},
                                    "^GSPC": {"date": "2026-10-20", "return": .0028}}}
    rows = [article("코스피, 반도체주 반등에 강세 마감", market="KR", session_date="2026-10-21",
                    published_at="2026-10-21T16:02:00+09:00"),
            article("U.S. Stocks Mostly Higher as AI Credit Worries Abate", published_at="2026-10-19T16:58:00-04:00"),
            article("U.S. Stocks Mixed as Strong Earnings Offset AI Credit Fears", published_at="2026-10-20T16:06:00-04:00",
                    retrospective_close_wrap=True)]
    headline = market_summary(context, rows, [], market_session_states(NOW, context["sessions"]), NOW)["headline"]
    assert "반도체주 반등" in headline and "실적 호조·AI 신용우려 교차" in headline
    assert "AI 신용우려 완화" not in headline


@pytest.mark.parametrize("title", [
    "'삼전닉스 쌍끌이' 코스피 3%↑…환율 2년 만에 최저 (MTN 마감시황)",
    "(증시-마감) 코스피 3.3% 급반등해 5,735…'삼전닉스' 6%↑",
])
def test_korean_rebound_headline_connects_explicit_samsung_hynix_strength(title):
    from stock_lab_core.report_market_summary import market_summary
    from stock_lab_core.report_session import market_session_states
    context = {**CONTEXT, "prices": {"^KS11": {"date": "2026-10-21", "return": .0329}}}
    row = article(title, market="KR", session_date="2026-10-21", published_at="2026-10-21T16:05:00+09:00")
    result = market_summary(context, [row], [], market_session_states(NOW, context["sessions"]), NOW)
    assert "삼성전자·SK하이닉스 강세" in result["headline"]


def test_two_character_digit_company_names_remain_news_subjects():
    from stock_lab_core.news import _company_in_headline

    assert _company_in_headline("F5 reports earnings", "F5")
    assert _company_in_headline("3M reports earnings", "3M")
    assert not _company_in_headline("Stocks rise on earnings", "ON")
