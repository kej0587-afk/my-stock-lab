from stock_lab_core.today_news import (
    build_today_action_news_brief,
    normalize_today_action_news_row,
    rank_today_action_news_rows,
)


def test_today_news_ranking_filters_low_quality_noise():
    rows = [
        normalize_today_action_news_row(
            {
                "title": "알바생 걱정한 사장님의 당부",
                "market_category": "국채/유동성",
                "publisher": "news.sbs.co.kr",
            },
            "시장/속보",
        ),
        normalize_today_action_news_row(
            {
                "title": "CPI outlook sends Treasury yields lower before Fed decision",
                "market_category": "외환/금리",
                "publisher": "Reuters",
            },
            "핵심속보",
        ),
    ]

    ranked = rank_today_action_news_rows(rows)

    assert len(ranked) == 1
    assert ranked[0]["출처"] == "Reuters"
    assert ranked[0]["읽기분류"] == "환율/금리"
    assert ranked[0]["중요도"] >= 8


def test_today_news_brief_explains_priority_for_beginners():
    rows = [
        normalize_today_action_news_row(
            {
                "title": "Gold and copper prices rise on commodity demand",
                "market_category": "원자재/금속",
                "publisher": "Reuters",
            },
            "시장/속보",
        ),
        normalize_today_action_news_row(
            {
                "title": "TSMC revenue jumps on AI demand",
                "market_category": "실적/대장주",
                "publisher": "Reuters",
            },
            "핵심속보",
        ),
    ]

    ranked = rank_today_action_news_rows(rows)
    brief = build_today_action_news_brief(ranked)

    assert any("금" in line and "구리" in line for line in brief)
    assert any("반도체" in line or "실적" in line for line in brief)
