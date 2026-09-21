import pandas as pd

from stock_lab_core.chart_execution import (
    build_chart_execution_check_rows,
    build_chart_execution_guide,
    pick_support_zone,
)


def _sample_price_df(close=71.89):
    return pd.DataFrame(
        {
            "Close": [70.8, 71.2, close],
            "Volume": [100, 110, 115],
        }
    )


def test_far_upper_resistance_is_reference_not_entry_condition():
    patterns = [{
        "name": "상승 깃발형",
        "direction": "bullish",
        "lifecycle": "현재유효",
        "trigger_price": 69.80,
        "invalid_price": 67.20,
    }]
    trendlines = [
        {"kind": "resistance", "direction": "상승", "y1": 84.96},
        {"kind": "support", "direction": "상승", "y1": 72.17},
    ]
    liquidity = {"ok": True, "support": {"low": 70.06, "high": 71.51}}

    guide = build_chart_execution_guide(patterns, trendlines, {}, liquidity, "FCX", 71.89)
    rows = build_chart_execution_check_rows(
        _sample_price_df(),
        patterns,
        trendlines,
        {},
        liquidity,
        "FCX",
        {"rr_ratio": 1.13, "rr_target": 78.64, "rr_stop": 65.94},
    )

    assert "상단 목표" in guide
    assert "$84.96 위 돌파" not in guide
    target_row = next(row for row in rows if row["조건"] == "상단 목표/큰 저항")
    assert target_row["상태"] == "참고"
    assert "1차 매수 조건이 아니라" in target_row["해석"]


def test_nearest_valid_support_zone_wins_over_far_fvg():
    smc = {
        "visible_fvg": {"type": "Bullish FVG", "bottom": 70.30, "top": 70.48},
        "visible_order_blocks": [
            {"direction": "support", "low": 65.71, "high": 67.08},
        ],
    }
    liquidity = {"ok": True, "support": {"low": 70.06, "high": 71.51}}
    trendlines = [{"kind": "support", "direction": "상승", "y1": 72.17}]

    zone = pick_support_zone(trendlines, smc, liquidity, "FCX", 71.89)

    assert zone["label"] == "유동성 지지"
