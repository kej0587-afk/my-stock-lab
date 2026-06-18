import pandas as pd

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.news import NEWS_CATEGORY_MARKET, assess_news_item


def test_auto_market_memo_keeps_today_check_block_when_summary_empty():
    memo = build_auto_market_memo(summary_rows=pd.DataFrame())

    assert "🧭 오늘점검" in memo
    assert "오늘점검 데이터가 비어 있습니다" in memo


def test_auto_market_memo_uses_post_fomc_hawkish_context_and_timeline_groups():
    market_news = pd.DataFrame(
        [
            {
                "market_category": "외환/금리",
                "title": "美 FOMC 금리 또 동결…연내 인하→인상 전환",
                "publisher": "연합뉴스",
                "published": "06/18 08:41",
            },
            {
                "market_category": "미국증시",
                "title": "기술주 반등에 뉴욕증시 상승 마감",
                "publisher": "테스트",
                "published": "06/18 05:30",
            },
        ]
    )
    macro_data = {
        "10Y 금리": {"val": 4.46, "chg": -0.024, "icon": "🔻"},
        "환율": {"val": 1523.72, "chg": 0.011, "icon": "🔺", "storm": True},
        "VIX": {"val": 18.44, "chg": 0.057, "icon": "🔺"},
        "MOVE": {"val": 70.66, "chg": -0.133, "icon": "🔻"},
        "유가": {"val": 75.16, "chg": -0.235, "icon": "🔻"},
    }
    event_rows = pd.DataFrame(
        [{"이벤트": "FOMC", "상태": "잔여", "D-Day": "D+1", "시장": "미국 주식/달러/금리"}]
    )

    memo = build_auto_market_memo(
        macro_data=macro_data,
        event_rows=event_rows,
        market_news_rows=market_news,
        summary_rows=pd.DataFrame(),
    )

    assert "혼재/부담 우위" in memo
    assert "연내 인상 가능성/매파 해석" in memo
    assert "🇰🇷 현재 국장/매크로" in memo
    assert "🇺🇸 전일 미증시 요약" in memo


def test_market_news_tightening_fear_is_bad_news_not_neutral():
    result = assess_news_item(
        "긴축 공포에 코스피 빨간불…외국인 귀환 랠리 꺾이나",
        "테스트",
        "0167A0.KS",
        [],
        ["반도체"],
        NEWS_CATEGORY_MARKET,
        strict=False,
    )

    assert result["ok"] is True
    assert result["sentiment"] == "악재"
