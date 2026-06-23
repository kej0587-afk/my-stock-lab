import pandas as pd

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.news import (
    NEWS_CATEGORY_DIRECT,
    NEWS_CATEGORY_MARKET,
    assess_news_item,
    dedupe_news_by_publisher_latest,
)


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


def test_auto_market_memo_switches_fomc_d_day_to_result_mode_from_news():
    market_news = pd.DataFrame(
        [
            {
                "market_category": "외환/금리",
                "title": "美 FOMC 금리 또 동결…연내 인하→인상 전환",
                "publisher": "연합뉴스",
                "published": "06/18 08:41",
            }
        ]
    )
    macro_data = {
        "10Y 금리": {"val": 4.46, "chg": -0.024, "icon": "🔻"},
        "환율": {"val": 1523.72, "chg": 0.011, "icon": "🔺", "storm": False},
        "VIX": {"val": 18.44, "chg": 0.057, "icon": "🔺"},
        "MOVE": {"val": 70.66, "chg": -0.133, "icon": "🔻"},
        "유가": {"val": 75.16, "chg": -0.235, "icon": "🔻"},
    }
    event_rows = pd.DataFrame(
        [{"이벤트": "FOMC", "상태": "당일", "D-Day": "D-Day", "시장": "미국 주식/달러/금리"}]
    )

    memo = build_auto_market_memo(
        macro_data=macro_data,
        event_rows=event_rows,
        market_news_rows=market_news,
        summary_rows=pd.DataFrame(),
    )

    assert "FOMC D-Day(결과 소화)" in memo
    assert "FOMC 전에는" not in memo
    assert "FOMC 전후에는" not in memo
    assert "이벤트 리스크는 FOMC 일정 때문에" not in memo
    assert "환율 부담" in memo
    assert "혼재/부담 우위" in memo


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


def test_index_news_drops_listing_compliance_and_single_company_listing_noise():
    compliance = assess_news_item(
        "브릿지라인 디지털, 나스닥 최소 주가 요건 재충족",
        "테스트",
        "379810.KS",
        ["나스닥"],
        [],
        NEWS_CATEGORY_DIRECT,
        strict=False,
    )
    adr = assess_news_item(
        "SK하이닉스, 미국 나스닥 ADR 상장 임박",
        "테스트",
        "379810.KS",
        ["나스닥"],
        [],
        NEWS_CATEGORY_DIRECT,
        strict=False,
    )
    index_close = assess_news_item(
        "[3분증시] 기술주 반등에 나스닥·S&P500 상승 마감",
        "연합뉴스",
        "379810.KS",
        ["나스닥"],
        [],
        NEWS_CATEGORY_DIRECT,
        strict=False,
    )

    assert compliance["ok"] is False
    assert adr["ok"] is False
    assert index_close["ok"] is True


def test_news_dedupes_same_publisher_to_latest_item():
    older = {
        "title": "[3분증시] 기술주 반등에 나스닥·S&P500 상승 마감",
        "publisher": "연합뉴스",
        "_pub_dt": pd.Timestamp("2026-06-18 06:00").to_pydatetime(),
        "quality_score": 10,
    }
    newer = {
        "title": "[3분증시] 메모리주 급등…S&P500·나스닥 최고치 마감",
        "publisher": "연합뉴스",
        "_pub_dt": pd.Timestamp("2026-06-18 08:00").to_pydatetime(),
        "quality_score": 5,
    }

    deduped = dedupe_news_by_publisher_latest([older, newer])

    assert len(deduped) == 1
    assert deduped[0]["title"] == newer["title"]


def test_auto_market_memo_marks_korea_crash_before_sector_rotation():
    index_rotation_rows = pd.DataFrame(
        [
            {"시장": "한국", "지수/스타일": "KOSPI", "Ticker": "^KS11", "1D": -0.0749, "5D": -0.02, "3M": 0.1},
            {"시장": "한국", "지수/스타일": "KOSDAQ", "Ticker": "^KQ11", "1D": -0.065, "5D": -0.08, "3M": -0.1},
            {"시장": "미국", "지수/스타일": "반도체", "Ticker": "SOXX", "1D": 0.024, "5D": 0.099, "3M": 0.9},
            {"시장": "미국", "지수/스타일": "산업재", "Ticker": "XLI", "1D": 0.007, "5D": 0.034, "3M": 0.05},
        ]
    )

    memo = build_auto_market_memo(
        index_rotation_rows=index_rotation_rows,
        summary_rows=pd.DataFrame(),
    )

    assert "한국 시장은 1D 기준 주요지수 평균 -7.0%" in memo
    assert "섹터 주도보다 지수 안정" in memo
    assert "한국 주요지수 1D 평균 -7.0%" in memo
    assert "📉 시장 급락" in memo
    assert "사이드카/서킷브레이커 공시 확인 우선" in memo
