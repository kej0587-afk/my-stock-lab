import pandas as pd
import pytest
import math

import stock_lab_core.us_sector_snapshot as us_snapshot
from stock_lab_core.us_sector_snapshot import build_us_cluster_snapshot


@pytest.fixture(autouse=True)
def disable_live_us_snapshot_prices(monkeypatch):
    monkeypatch.setattr(us_snapshot, "_load_latest_prices_for_snapshot", lambda tickers: {})
    monkeypatch.setattr(us_snapshot, "_latest_close_for_snapshot", lambda ticker: float("nan"))


def test_us_sector_snapshot_builds_semiconductor_detail_segments():
    snapshot = build_us_cluster_snapshot("반도체", detail_name="반도체")

    assert snapshot
    assert snapshot["market"] == "US"
    assert snapshot["industries"]
    assert snapshot["subsectors"]
    assert snapshot["representative_returns_source"] == "unverified"
    assert math.isnan(snapshot["breadth"]) or 0 <= snapshot["breadth"] <= 1
    assert any("반도체" in item["name"] for item in snapshot["subsectors"])


def test_us_sector_snapshot_separates_financial_subsegments():
    snapshot = build_us_cluster_snapshot("금융", detail_name="금융")
    segment_names = [item["name"] for item in snapshot["subsectors"]]

    assert snapshot
    assert "금융서비스·핀테크" in segment_names
    assert "은행" in segment_names
    assert "보험" in segment_names


def test_us_sector_snapshot_maps_photonics_theme_to_us_internal_segments():
    snapshot = build_us_cluster_snapshot("포토닉스·광통신", detail_name="포토닉스·광통신")
    segment_names = [item["name"] for item in snapshot["subsectors"]]

    assert snapshot
    assert snapshot["market"] == "US"
    assert "광통신·통신장비" in segment_names
    assert "반도체·장비" in segment_names


def test_us_sector_snapshot_maps_cluster_card_names():
    expected = {
        "AI·반도체": "AI 하드웨어",
        "소프트웨어·사이버": "소프트웨어·IT서비스",
        "전력·인프라": "그리드·전기장비",
        "방산·우주": "우주항공·국방",
        "소비재": "경기소비재",
        "산업재·원자재": "금속·채광",
        "2차전지·EV": "EV·자동차",
    }

    for cluster_name, expected_segment in expected.items():
        snapshot = build_us_cluster_snapshot(cluster_name, detail_name=cluster_name)
        segment_names = [item["name"] for item in snapshot.get("subsectors", [])]

        assert snapshot, cluster_name
        assert snapshot["market"] == "US"
        assert expected_segment in segment_names


def test_us_sector_snapshot_live_refresh_recomputes_returns_and_splits_leaders(monkeypatch):
    monkeypatch.setattr(
        us_snapshot,
        "_resolve_detail_group",
        lambda detail_name="", cluster_name="": (
            "테스트",
            {
                "sectors": ["Semi"],
                "subsegments": [{"name": "반도체", "sectors": ["Semi"]}],
            },
        ),
    )
    monkeypatch.setattr(
        us_snapshot,
        "load_us_industry_snapshot",
        lambda: pd.DataFrame([{"industry_name": "Semi", "change_pct": 0.2}]),
    )
    monkeypatch.setattr(
        us_snapshot,
        "load_us_sector_constituents",
        lambda: pd.DataFrame(
            [
                {
                    "sector": "Semi",
                    "ticker": "MU",
                    "name": "마이크론 테크놀로지",
                    "current": 1208.0,
                    "change_pct": 14.85,
                    "volume": 10,
                    "market_cap_thousand": 300,
                },
                {
                    "sector": "Semi",
                    "ticker": "AMAT",
                    "name": "어플라이드 머티어리얼즈",
                    "current": 622.14,
                    "change_pct": 6.19,
                    "volume": 20,
                    "market_cap_thousand": 200,
                },
                {
                    "sector": "Semi",
                    "ticker": "LRCX",
                    "name": "램 리서치",
                    "current": 392.65,
                    "change_pct": 5.74,
                    "volume": 30,
                    "market_cap_thousand": 100,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        us_snapshot,
        "_load_latest_prices_for_snapshot",
        lambda tickers: {"MU": 96.26, "AMAT": 100.96, "LRCX": 105.70},
    )
    monkeypatch.setattr(us_snapshot, "_latest_close_for_snapshot", lambda ticker: 100.0)

    snapshot = build_us_cluster_snapshot("AI·반도체", detail_name="AI·반도체")

    leaders = {item["ticker"]: item["change_pct"] for item in snapshot["leaders"]}
    laggards = {item["ticker"]: item["change_pct"] for item in snapshot["laggards"]}
    assert snapshot["representative_returns_source"] == "live"
    assert "MU" not in leaders
    assert laggards["MU"] == pytest.approx(-3.74)
    assert leaders["AMAT"] == pytest.approx(0.96)
    assert leaders["LRCX"] == pytest.approx(5.70)
    assert set(leaders).isdisjoint(laggards)
