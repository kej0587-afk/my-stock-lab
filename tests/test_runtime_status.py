from stock_lab_core.runtime_status import build_speed_check_snapshot, build_speed_check_rows


def test_speed_check_rows_use_refresh_times_in_fixed_order():
    rows = build_speed_check_rows(
        {
            "latest_price_refresh_time": "09:01",
            "chart_price_refresh_time": "09:02",
            "news_report_refresh_time": "09:03",
            "fin_macro_refresh_time": "09:04",
        }
    )

    assert [row["구분"] for row in rows] == ["현재가", "차트/기술", "뉴스/리포트", "재무점수/매크로"]
    assert rows[0]["마지막 수동갱신"] == "09:01"
    assert rows[-1]["체감속도"] == "무거움"


def test_speed_check_snapshot_formats_metrics():
    snapshot = build_speed_check_snapshot(
        {"latest_price_refresh_time": "09:01"},
        holdings_count=3,
        watchlist_count=12,
        current_asset=1234567,
        generated_at="09:05:00",
    )

    metrics = {item["label"]: item["value"] for item in snapshot["metrics"]}
    assert metrics["보유종목"] == "3개"
    assert metrics["전광판"] == "12개"
    assert metrics["현금 포함 자산"] == "1,234,567원"
    assert metrics["화면 생성"] == "09:05:00"
    assert "현재가만 새로고침" in snapshot["info"]
