import numpy as np
import pandas as pd

from stock_lab_core.chart_patterns import (
    build_recent_trendline_guides,
    chart_pattern_price_text,
    detect_chart_pattern_candidates,
)


def test_chart_pattern_price_text_formats_positive_number():
    assert chart_pattern_price_text(1234.567) == "1,234.57"
    assert chart_pattern_price_text(0) == "-"


def test_detect_chart_pattern_candidates_returns_empty_for_missing_ohlc():
    assert detect_chart_pattern_candidates(pd.DataFrame({"Close": [1, 2, 3]})) == []


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
