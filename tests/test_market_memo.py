from datetime import datetime

from stock_lab_core.market_memo import analyze_market_memo, build_auto_market_memo


def test_market_memo_links_semiconductor_watchlist_and_flags_sources():
    text = """
    🖥 반도체·AI
    • Micron(MU) HBM 서사 절정, 콜옵션 언급 급증
    • NVIDIA(NVDA) 200억 달러 규모 채권 발행 계획

    📉 매크로
    • 중국 5월 소매판매 YoY -0.6% 하락, 예상 미달
    """
    universe = [
        {"ticker": "NVDA", "name": "NVIDIA", "source": "관심", "asset_class": "us_stock_ai"},
        {"ticker": "SOXL", "name": "SOXL", "source": "보유", "asset_class": "us_etf_semiconductor"},
    ]

    result = analyze_market_memo(text, universe)

    assert result["has_content"] is True
    assert any(row["카테고리"] == "반도체/AI" for row in result["category_rows"])
    assert any(row["티커"] == "NVDA" and row["연결방식"] == "직접언급" for row in result["ticker_rows"])
    assert any(row["티커"] == "SOXL" and row["연결방식"] == "테마연결" for row in result["ticker_rows"])
    assert any("출처" in row["확인사유"] or "숫자" in row["확인사유"] for row in result["verification_flags"])


def test_market_memo_macro_negative_bias_is_detected():
    text = "• BOJ 기준금리 1.0%로 25bp 인상, 인플레이션 고점 지속"

    result = analyze_market_memo(text, [])

    macro = next(row for row in result["category_rows"] if row["카테고리"] in {"매크로", "외환/금리"})
    assert macro["점수"] < 0
    assert result["verification_flags"]


def test_auto_market_memo_builds_newspick_style_draft():
    flow_snapshot = {
        "flow_df": [
            {
                "구분": "미국 섹터",
                "섹터": "반도체",
                "Ticker": "SOXX",
                "돈흐름점수": 24.5,
                "3개월수익률": 0.12,
                "가속도": 0.03,
                "상태": "주도",
            }
        ],
        "us_top5": [
            {
                "섹터": "반도체",
                "Ticker": "SOXX",
                "돈흐름점수": 24.5,
                "3개월수익률": 0.12,
                "가속도": 0.03,
                "상태": "주도",
            }
        ],
    }
    macro_data = {
        "10Y 금리": {"val": 4.3, "chg": -1.2, "icon": "🔻", "storm": False},
    }
    news_rows = [{"ticker": "NVDA", "name": "NVIDIA", "title": "NVIDIA AI 수요 강세", "sentiment": "호재"}]

    memo = build_auto_market_memo(
        flow_snapshot=flow_snapshot,
        macro_data=macro_data,
        news_rows=news_rows,
        now=datetime(2026, 6, 16, 15, 0),
    )

    assert "Stock Lab 자동 뉴스픽" in memo
    assert "핵심 해석" in memo
    assert "반도체·AI" in memo
    assert "SOXX" in memo
    assert "10Y 금리" in memo
    assert "1개월 -1.2%" in memo
    assert "NVIDIA AI 수요 강세" in memo


def test_auto_market_memo_does_not_double_scale_macro_change():
    memo = build_auto_market_memo(
        macro_data={"10Y 금리": {"val": 4.49, "chg": -2.942, "icon": "🔻", "storm": False}},
        now=datetime(2026, 6, 16, 16, 0),
    )

    assert "1개월 -2.9%" in memo
    assert "-294.2%" not in memo
