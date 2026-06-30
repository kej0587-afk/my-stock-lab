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
