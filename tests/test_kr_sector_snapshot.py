import pandas as pd
import pytest

import stock_lab_core.kr_sector_snapshot as kr_snapshot
from stock_lab_core.kr_sector_snapshot import build_kr_cluster_snapshot


@pytest.fixture(autouse=True)
def disable_live_snapshot_prices(monkeypatch):
    monkeypatch.setattr(kr_snapshot, "_load_latest_prices_for_snapshot", lambda tickers: {})


def test_kr_cluster_snapshot_filters_fund_like_noise_for_ai_semis():
    snapshot = build_kr_cluster_snapshot("AI·반도체")

    assert snapshot
    assert snapshot["industries"]
    assert 0 <= snapshot["breadth"] <= 1

    representative_names = [item["name"] for item in snapshot["leaders"]]
    joined_names = " ".join(representative_names)
    assert "SK하이닉스" in joined_names or "삼성전자" in joined_names
    assert not any("KODEX" in name or "레버리지" in name or "인버스" in name for name in representative_names)


def test_kr_cluster_snapshot_deduplicates_representatives():
    snapshot = build_kr_cluster_snapshot("금융")
    tickers = [item["ticker"] for item in snapshot["leaders"]]

    assert tickers
    assert len(tickers) == len(set(tickers))


def test_kr_cluster_snapshot_uses_detail_segments_for_overlapping_industries():
    semi = build_kr_cluster_snapshot("AI·반도체", detail_name="반도체")
    mlcc = build_kr_cluster_snapshot("AI·반도체", detail_name="전자부품·MLCC")

    semi_segments = [item["name"] for item in semi["subsectors"]]
    mlcc_segments = [item["name"] for item in mlcc["subsectors"]]

    assert semi_segments
    assert mlcc_segments
    assert semi_segments != mlcc_segments
    assert any("HBM" in name or "반도체" in name for name in semi_segments)
    assert any("MLCC" in name or "기판" in name for name in mlcc_segments)


def test_kr_cluster_snapshot_live_refresh_recomputes_representative_returns(monkeypatch):
    rows = pd.DataFrame(
        [
            {
                "sector": "전기,전자",
                "rank": 3,
                "ticker": "009150.KS",
                "name": "삼성전기",
                "current": 1985000,
                "change_abs": "▼",
                "change_sign": -5000,
                "change_pct": -0.25,
                "volume": 1000000,
                "is_fund_like": False,
            },
            {
                "sector": "전기,전자",
                "rank": 6,
                "ticker": "011070.KS",
                "name": "LG이노텍",
                "current": 977000,
                "change_abs": "▼",
                "change_sign": -14000,
                "change_pct": -1.41,
                "volume": 380000,
                "is_fund_like": False,
            },
        ]
    )
    monkeypatch.setattr(
        kr_snapshot,
        "_load_latest_prices_for_snapshot",
        lambda tickers: {"009150.KS": 2144000.0, "011070.KS": 1062500.0},
    )

    refreshed = kr_snapshot._refresh_constituent_rows_with_live_prices(rows)

    samsung = refreshed[refreshed["ticker"] == "009150.KS"].iloc[0]
    lg = refreshed[refreshed["ticker"] == "011070.KS"].iloc[0]
    assert samsung["change_pct"] > 7.0
    assert lg["change_pct"] > 7.0
    assert samsung["change_abs"] == "▲"
    assert lg["change_abs"] == "▲"


def test_kr_cluster_snapshot_can_skip_live_refresh_for_bulk_tables(monkeypatch):
    called = {"count": 0}

    def fake_loader(tickers):
        called["count"] += 1
        return {"009150.KS": 2144000.0}

    monkeypatch.setattr(kr_snapshot, "_load_latest_prices_for_snapshot", fake_loader)

    snapshot = build_kr_cluster_snapshot("AI·반도체", detail_name="전자부품·MLCC", live_prices=False)

    assert snapshot
    assert called["count"] == 0
