import numpy as np
import pandas as pd

from stock_lab_core.chart_patterns import (
    build_chart_pattern_timing_note,
    build_recent_trendline_guides,
    chart_pattern_caption,
    chart_pattern_price_text,
    detect_chart_pattern_candidates,
    summarize_chart_pattern_for_dashboard,
    trendline_guides_caption,
)


def _sample_ohlc(periods=90):
    idx = pd.date_range("2026-01-01", periods=periods, freq="D")
    base = np.linspace(100, 130, periods) + np.sin(np.arange(periods) / 4) * 3
    return pd.DataFrame(
        {
            "Open": base - 0.4,
            "High": base + 1.2,
            "Low": base - 1.2,
            "Close": base,
        },
        index=idx,
    )


def test_chart_pattern_price_text_formats_positive_number():
    assert chart_pattern_price_text(1234.567) == "1,234.57"
    assert chart_pattern_price_text(0) == "-"


def test_detect_chart_pattern_candidates_returns_empty_for_missing_ohlc():
    assert detect_chart_pattern_candidates(pd.DataFrame({"Close": [1, 2, 3]})) == []


def test_detect_chart_pattern_candidates_survives_polyfit_failure(monkeypatch):
    import stock_lab_core.chart_patterns as chart_patterns

    def _raise(*args, **kwargs):
        raise np.linalg.LinAlgError("synthetic fit failure")

    monkeypatch.setattr(chart_patterns.np, "polyfit", _raise)

    assert detect_chart_pattern_candidates(_sample_ohlc()) == []


def test_build_recent_trendline_guides_returns_stable_list():
    idx = pd.date_range("2026-01-01", periods=90, freq="D")
    base = np.linspace(100, 140, 90) + np.sin(np.arange(90) / 3) * 6
    df = pd.DataFrame(
        {
            "Open": base - 0.5,
            "High": base + 1.5,
            "Low": base - 1.5,
            "Close": base,
        },
        index=idx,
    )

    guides = build_recent_trendline_guides(df)

    assert isinstance(guides, list)
    assert all({"kind", "direction", "y1"}.issubset(guide.keys()) for guide in guides)


def test_recent_trendline_prefers_post_peak_resistance_after_spike():
    idx = pd.date_range("2026-01-01", periods=100, freq="D")
    base = np.linspace(100, 150, 100)
    high = base + 1
    low = base - 1
    close = base.copy()
    for pos, price in [(54, 171), (66, 162), (78, 155), (90, 151)]:
        high[pos] = price
        close[pos] = price - 3
        low[pos] = price - 8
        for offset in (-2, -1, 1, 2):
            p = pos + offset
            if 0 <= p < len(high):
                high[p] = min(high[p], price - 12)
                close[p] = min(close[p], price - 14)
    df = pd.DataFrame(
        {"Open": close - 0.5, "High": high, "Low": low, "Close": close},
        index=idx,
    )

    guides = build_recent_trendline_guides(df)
    resistance = next((g for g in guides if g.get("kind") == "resistance"), None)

    assert resistance is not None
    assert resistance["direction"] == "하락"


def test_recent_trendline_ignores_fresh_breakout_wick_for_resistance():
    idx = pd.date_range("2026-01-01", periods=120, freq="D")
    base = np.linspace(120, 136, 120)
    high = base + 1
    low = base - 1
    close = base.copy()
    for pos, price in [(70, 150), (85, 145), (100, 140), (114, 170)]:
        high[pos] = price
        close[pos] = min(price - 8, base[pos])
        low[pos] = close[pos] - 2
        for offset in (-2, -1, 1, 2):
            p = pos + offset
            if 0 <= p < len(high):
                high[p] = min(high[p], price - 12)
                close[p] = min(close[p], price - 14)
    df = pd.DataFrame(
        {"Open": close - 0.5, "High": high, "Low": low, "Close": close},
        index=idx,
    )

    guides = build_recent_trendline_guides(df)
    resistance = next((g for g in guides if g.get("kind") == "resistance"), None)

    assert resistance is not None
    assert resistance["direction"] == "하락"
    assert resistance["x0"] <= idx[100]


def test_chart_pattern_summary_marks_overheated_valid_pattern_as_wait():
    pattern = {
        "name": "역헤드앤숄더",
        "direction": "bullish",
        "lifecycle": "현재유효",
        "trigger_price": 271500,
        "invalid_price": 186362,
    }

    timing, reason, bucket = summarize_chart_pattern_for_dashboard([pattern], {"rsi": 72, "mfi": 50, "pct_b": 0.5})
    note = build_chart_pattern_timing_note([pattern], {"rsi": 72, "mfi": 50, "pct_b": 0.5})

    assert timing == "🚦패턴성공: 눌림대기"
    assert bucket == "wait"
    assert "RSI 72" in reason
    assert note["title"] == "🚦 패턴 성공 후 과열"


def test_chart_pattern_caption_and_trendline_caption_are_human_readable():
    pattern = {
        "name": "쌍바닥",
        "direction": "bullish",
        "lifecycle": "관찰",
        "trigger_price": 2006000,
        "invalid_price": 1645935,
    }
    guides = [
        {"kind": "resistance", "direction": "하락"},
        {"kind": "support", "direction": "상승"},
    ]

    assert "기준 2,006,000.00 위 안착" in chart_pattern_caption([pattern])
    assert trendline_guides_caption(guides) == "추세선: 저항 하락 · 지지 상승 · 가격이 두 선 사이에서 위/아래 어느 쪽을 돌파하는지 봅니다."
