from stock_lab_core.today_queue import build_today_queue_execution_snapshot


def test_today_queue_execution_snapshot_uses_nearest_support_for_wait_signal():
    snap = build_today_queue_execution_snapshot(
        "Apple",
        "AAPL",
        {
            "cur_p": 100.0,
            "rr_target": 115.0,
            "rr_stop": 90.0,
            "rr_ratio": 1.5,
            "atr": 4.0,
            "ma5": 98.0,
            "ma20": 94.0,
            "fvg_top": 96.0,
            "fvg_bottom": 93.0,
            "target_w": 10.0,
            "current_w": 6.0,
            "weight_gap": 4.0,
            "buy_amt": 560_000.0,
            "decision_code": "S_UPTREND_WAIT_PULLBACK",
            "dec": "🔍S급 정배열: 눌림 구간 진입 대기",
            "pct_b": 0.80,
            "pd_zone": "Neutral",
            "asset_class": "us_stock",
        },
        has_pos=True,
        usdkrw_value=1400.0,
    )

    assert snap["R/R"] == "1.50"
    assert "98" in snap["1차기준"]
    assert "MA5" in snap["1차조건"]
    assert snap["실행메모"] == "눌림/종가 확인"
    assert snap["부족액"].startswith("$400")


def test_today_queue_execution_snapshot_hides_entry_price_for_weight_block():
    snap = build_today_queue_execution_snapshot(
        "Freeport McMoRan",
        "FCX",
        {
            "cur_p": 78.0,
            "rr_target": 86.0,
            "rr_stop": 72.0,
            "rr_ratio": 1.33,
            "atr": 3.0,
            "ma5": 76.0,
            "target_w": 5.0,
            "current_w": 5.2,
            "weight_gap": 0.0,
            "buy_amt": 0.0,
            "decision_code": "HARD_BLOCK_TARGET_FILLED",
            "dec": "⏸️하드차단: 비중 충족(관망)",
            "asset_class": "us_stock",
        },
        has_pos=True,
    )

    assert snap["실행메모"] == "추가매수 제외"
    assert snap["1차기준"] == "추가매수 제외"
    assert snap["1차조건"] == "목표비중 기준 추가 필요 없음"
