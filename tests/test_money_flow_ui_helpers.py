import pandas as pd


def test_us_etf_composition_fallback_has_cibr_top5(app_module):
    comp_df, meta = app_module._composition_fallback_frame("CIBR")

    assert meta["name"] == "First Trust NASDAQ Cybersecurity ETF"
    assert comp_df["티커"].head(5).tolist() == ["CRWD", "FTNT", "PANW", "CSCO", "AVGO"]
    assert comp_df["비중(%)"].iloc[0] == 8.91


def test_cluster_list_prioritizes_current_timing_over_stale_strength(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_load_index_rotation_recent_returns", lambda ticker: {"1D": 0.0, "5D": 0.0})
    monkeypatch.setattr(
        app_module,
        "_get_market_cluster_snapshot_cached",
        lambda *args, **kwargs: {},
    )
    rotation_df = pd.DataFrame(
        [
            {
                "Ticker": "STRONG",
                "섹터": "중기강도",
                "RS(3M)": 0.30,
                "RS모멘텀": 0.25,
                "사분면": "주도",
                "1개월수익률": -0.06,
                "2주수익률": -0.04,
                "단기가속도": -0.03,
                "거래량증가": 0.2,
                "가격수준": 0.5,
            },
            {
                "Ticker": "READY",
                "섹터": "단기확인",
                "RS(3M)": 0.10,
                "RS모멘텀": 0.06,
                "사분면": "개선",
                "1개월수익률": 0.04,
                "2주수익률": 0.02,
                "단기가속도": 0.02,
                "거래량증가": 0.1,
                "가격수준": 0.6,
            },
        ]
    )
    clusters = {"오래강함": ["STRONG"], "지금확인": ["READY"]}

    result = app_module._build_cluster_list(rotation_df, clusters, market_context={}, market_key="미국")

    assert result[0]["name"] == "지금확인"
    assert result[0]["timing_state"] == "진입 가능"
    assert result[1]["timing_state"] == "하락 중"
