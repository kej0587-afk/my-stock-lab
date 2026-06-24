from stock_lab_core.kr_sector_snapshot import build_kr_cluster_snapshot


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
