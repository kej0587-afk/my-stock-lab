from stock_lab_core.us_sector_snapshot import build_us_cluster_snapshot


def test_us_sector_snapshot_builds_semiconductor_detail_segments():
    snapshot = build_us_cluster_snapshot("반도체", detail_name="반도체")

    assert snapshot
    assert snapshot["market"] == "US"
    assert snapshot["industries"]
    assert snapshot["subsectors"]
    assert 0 <= snapshot["breadth"] <= 1
    assert any("반도체" in item["name"] for item in snapshot["subsectors"])


def test_us_sector_snapshot_separates_financial_subsegments():
    snapshot = build_us_cluster_snapshot("금융", detail_name="금융")
    segment_names = [item["name"] for item in snapshot["subsectors"]]

    assert snapshot
    assert "금융서비스·핀테크" in segment_names
    assert "은행" in segment_names
    assert "보험" in segment_names
