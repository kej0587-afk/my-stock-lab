"""Summary is derived from dated sources, not the user's sample claims."""
from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.report_brief import material_news
from stock_lab_core.report_digest import weekly_themes, weekly_theme_lines, connection_checks, check_lines

NOW = datetime.fromisoformat("2026-11-15T23:00:00+09:00")


def article(title="Fed officials discuss inflation and rate outlook", **changes):
    return dict({"title": title, "link": "https://www.reuters.com/world/example",
                 "publisher": "Reuters", "published_at": "2026-11-13T20:00:00+00:00", "market": "US"}, **changes)


def test_weekly_dedup_counts_urls_and_titles_once_across_buckets_and_does_not_mutate():
    row = article()
    context = {"other_market_news": [dict(row, link=row["link"] + "?utm_source=copy"),
                                    dict(row, link=row["link"] + "/mirror")], "next_session_news": [row]}
    before = deepcopy(context)
    digest = weekly_themes(context, [row], [], NOW)
    assert digest["headlines"] == 1 and digest["themes"][0]["count"] == 1
    assert context == before
    lines = "\n".join(weekly_theme_lines(digest))
    assert "11/09~11/15 23:00" in lines and "1건 · 본문 근거 0건" in lines
    assert "확인된 테마 1개" in lines
    assert "사임" not in lines and "폭락" not in lines


@pytest.mark.parametrize("changes", [
    {"published_at": "2026-11-08T23:59:59+09:00"},
    {"published_at": "2026-11-16T00:01:00+09:00"}, {"published_at": ""},
    {"link": "https://unknown.example/story", "publisher": "unknown"},
    {"title": "Banks offer cashback rewards to open an account"},
])
def test_prior_week_future_undated_untrusted_promotional_rows_not_counted(changes):
    assert weekly_themes({}, [article(**changes)], [], NOW)["headlines"] == 0


def test_top_five_are_collected_topics_not_fixed_claims_and_ties_are_stable():
    titles = ["Fed rate outlook", "AI data center investment falls", "Iran oil supply risk",
              "Bitcoin price falls", "NVIDIA CEO resigns as chip shares fall", "Bank earnings beat forecasts"]
    rows = [article(title, link=f"https://www.reuters.com/world/{i}") for i, title in enumerate(titles)]
    a = weekly_themes({}, rows, [], NOW)
    b = weekly_themes({}, list(reversed(rows)), [], NOW)
    assert len(a["themes"]) == 5 and a["headlines"] == 6
    assert [g["label"] for g in a["themes"]] == [g["label"] for g in b["themes"]]
    assert all(g["count"] == 1 for g in a["themes"])


def test_known_body_duplicate_wins_and_holdings_only_connect_actual_inputs():
    row = article("Bitcoin price falls amid liquidity concerns")
    body = dict(row, body_status="verified", body_facts=[{
        "topic": "crypto", "evidence_basis": "body", "concrete_summary": "현물 가격 하락 보도",
        "evidence": "현물 가격 하락 보도"}])
    held = [{"티커": "BITX", "보유여부": True}, {"티커": "NVDA", "보유여부": False}]
    before = deepcopy(held)
    digest = weekly_themes({"other_market_news": [body]}, [row], held, NOW)
    group = digest["themes"][0]
    assert group["count"] == group["body_count"] == 1
    assert "BITX" in group["related"] and "NVDA" not in group["related"]
    assert held == before


@pytest.mark.parametrize("title", [
    "Pfizer Stock Down 6% Post Q3 Earnings: Time to Buy, Hold or Exit?",
    "Should Updated Earnings Guidance Require Action From Sempra (SRE) Investors?",
    "美 규제공포 AI인프라株 실적은 좋은데 저가매수 해볼까",
])
def test_unverified_investment_advice_is_not_a_market_event(title):
    assert not material_news(article(title))


def test_real_earnings_and_policy_material_not_filtered():
    assert material_news(article("Immunic shares fall 5% on third quarter earnings miss"))
    assert material_news(article("Fed officials discuss inflation and rate outlook"))


@pytest.mark.parametrize("market", ["GLOBAL", "JP", "CN", ""])
def test_global_theme_links_existing_exposure_without_relabelling_market(market):
    row = article("AI 데이터센터 투자·차입 부담에 반도체주 하락", market=market)
    holdings = [{"티커": "SOXL", "보유여부": True}]
    result = weekly_themes({}, [row], holdings, NOW)
    assert "SOXL" in result["themes"][0]["related"]
    assert "타시장" in result["themes"][0]["related"]
    assert row["market"] == market


def test_checks_do_not_mark_missing_data_or_wrong_date_passed():
    digest = weekly_themes({}, [article()], [], NOW)
    context = {"sessions": {"KR": "2026-11-13", "US": "2026-11-13"},
               "prices": {"^KS11": {"date": "2026-11-12"}, "^GSPC": {"date": "2026-11-13"}}}
    checks = connection_checks(context, [], digest, "", NOW)
    states = {name: state for name, state, _ in checks}
    assert states["KR 대표지수 기준일"] == "실패"
    assert states["US 대표지수 기준일"] == "통과"
    assert states["상위 테마 본문"] == states["개인 수급 이력"] == states["계좌 입력"] == "미확인"
    summary, detail = check_lines(checks)
    assert "통과 1 · 실패 1 · 미확인 4" in summary
    assert "정확도 보증은 아닙니다" in "\n".join(detail)
