import pandas as pd

from stock_lab_core.today_queue import (
    build_dashboard_final_read,
    build_today_queue_execution_snapshot,
    format_dashboard_candidate_grade,
    format_dashboard_reason,
    format_dashboard_timing_label,
    is_today_queue_defense_signal,
    today_queue_reason_bucket,
    today_queue_wait_mask,
)


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


def test_today_queue_defense_signal_detects_price_drawdown_code():
    assert is_today_queue_defense_signal({
        "decision_code": "PRICE_DRAWDOWN_NO_ENTRY",
        "dec": "⚠️가격위험: 신규진입 보류",
    })


def test_today_queue_reason_bucket_marks_price_drawdown_as_defense():
    row = pd.Series({
        "🔥기술적 타점": "⚠️가격위험: 신규진입 보류",
        "패턴타점": "🚦패턴성공: 눌림대기",
        "최종읽기": "🛡️방어우선",
        "📌후보등급": "✅A급",
        "핵심근거": "고점대비 -23.1%",
        "판정코드": "PRICE_DRAWDOWN_NO_ENTRY",
    })

    assert today_queue_reason_bucket(row) == "가격방어"


def test_today_queue_marks_holding_macro_storm_as_market_defense():
    decision = {
        "decision_code": "MACRO_STORM_HOLDING_CAUTION",
        "decision_group": "caution",
        "dec": "🛡️시장위험: 추매중단/보유점검",
    }
    row = pd.Series({
        "🔥기술적 타점": decision["dec"],
        "패턴타점": "-",
        "최종읽기": "🛡️시장방어(추매중단)",
        "📌후보등급": "🛡️시장방어(추매중단)",
        "핵심근거": "퍼펙트스톰 지수 4.8",
        "판정코드": decision["decision_code"],
    })

    assert today_queue_reason_bucket(row) == "시장방어"
    assert is_today_queue_defense_signal(decision)
    assert format_dashboard_candidate_grade(decision) == "🛡️시장방어(추매중단)"
    assert build_dashboard_final_read(
        decision,
        dashboard_timing=decision["dec"],
        dashboard_grade="🛡️시장방어(추매중단)",
    ) == "🛡️시장방어(추매중단)"


def test_today_queue_marks_new_macro_storm_as_market_buy_block():
    decision = {
        "decision_code": "HARD_BLOCK_MACRO_STORM",
        "decision_group": "caution",
        "dec": "🛑하드차단: 퍼펙트스톰(대피)",
    }

    assert is_today_queue_defense_signal(decision)
    assert format_dashboard_candidate_grade(decision) == "🛡️시장방어(매수금지)"
    assert build_dashboard_final_read(decision) == "🛡️시장방어(매수금지)"


def test_today_queue_routes_storm_leverage_wait_to_market_defense():
    row = pd.Series({
        "종목명": "2x Bitcoin ETF",
        "티커": "BITX",
        "유형": "ETF",
        "매크로상태": "STORM",
        "🔥기술적 타점": "⚡레버리지 신규 타점 대기: R/R 부족",
        "패턴타점": "-",
        "최종읽기": "⏳눌림대기",
        "📌후보등급": "✅ETF 양호",
        "핵심근거": "레버리지 전용 단계: 미보유 관찰 ×0",
    })

    assert today_queue_reason_bucket(row) == "시장방어"


def test_today_wait_mask_keeps_overheat_hard_block_visible_as_wait_watch():
    summary_df = pd.DataFrame([{
        "종목명": "FCX",
        "티커": "FCX",
        "🔥기술적 타점": "🚫하드차단: 볼린상단 이탈",
        "패턴타점": "🚦패턴성공: 눌림대기",
        "최종읽기": "🚫추격금지",
        "📌후보등급": "🚫상단과열(추격금지)",
        "핵심근거": "%B 1.08 / MFI 74 / RSI 73",
        "판정코드": "HARD_BLOCK_BOLLINGER_UPPER",
    }])
    buyish_mask = pd.Series([False], index=summary_df.index)

    mask = today_queue_wait_mask(summary_df, buyish_mask)

    assert bool(mask.iloc[0])


def test_today_wait_mask_still_hides_non_timing_hard_blocks():
    summary_df = pd.DataFrame([{
        "종목명": "FILLED",
        "티커": "FILLED",
        "🔥기술적 타점": "🚫하드차단: 목표비중 충족",
        "패턴타점": "🚦패턴성공: 눌림대기",
        "최종읽기": "🛡️방어우선",
        "📌후보등급": "⛔비중관리",
        "핵심근거": "목표비중 충족",
        "판정코드": "HARD_BLOCK_TARGET_FILLED",
    }])
    buyish_mask = pd.Series([False], index=summary_df.index)

    mask = today_queue_wait_mask(summary_df, buyish_mask)

    assert not bool(mask.iloc[0])


def test_today_wait_mask_keeps_plain_precision_check_executable():
    summary_df = pd.DataFrame([{
        "종목명": "Leader",
        "티커": "LEAD",
        "🔥기술적 타점": "🚀신규진입: 대장주 포착",
        "패턴타점": "-",
        "최종읽기": "✅정밀확인",
        "📌후보등급": "✅A급",
        "핵심근거": "RS 강함",
        "판정코드": "NEW_ENTRY_LEADER",
    }])
    buyish_mask = pd.Series([True], index=summary_df.index)

    mask = today_queue_wait_mask(summary_df, buyish_mask)

    assert not bool(mask.iloc[0])


def test_dashboard_final_read_downgrades_quality_recovery_when_bearish_pattern_valid():
    final_read = build_dashboard_final_read(
        {"decision_code": "QUALITY_RECOVERY_CANDIDATE", "decision_group": "buyish"},
        dashboard_timing="✅우량주 회복 후보: 분할 검토",
        dashboard_grade="✅우량주 회복후보",
        pattern_timing="🛑하락패턴 유효",
    )

    assert final_read == "👀회복관찰"


def test_dashboard_final_read_distinguishes_trend_risk_from_cost_loss():
    trend_read = build_dashboard_final_read(
        {"decision_code": "TREND_RISK_CAUSE_CHECK", "decision_group": "caution"},
        dashboard_timing="🚫추세위험: 원인 점검",
        dashboard_grade="⚖️ETF 보통",
        pattern_timing="-",
    )
    cost_read = build_dashboard_final_read(
        {"decision_code": "COST_MINUS_15_CAUSE_CHECK", "decision_group": "caution"},
        dashboard_timing="🚫평단 -15%↓: 원인 점검",
        dashboard_grade="⚖️ETF 보통",
        pattern_timing="-",
    )

    assert trend_read == "🛡️추세방어(추매보류)"
    assert cost_read == "🛡️평단방어(원인점검)"


def test_dashboard_final_read_marks_fund_oversold_as_rebalance_wait():
    final_read = build_dashboard_final_read(
        {"decision_code": "FUND_OVERSOLD_REBALANCE_REVIEW", "decision_group": "caution"},
        dashboard_timing="⏳TDF/펀드 낙폭과대: 소액 리밸런싱 검토",
        dashboard_grade="⏳펀드리밸런싱",
        pattern_timing="-",
    )

    assert final_read == "⏳리밸런싱대기"


def test_dashboard_read_turns_low_rr_new_leader_entry_into_wait():
    decision = {
        "decision_code": "NEW_ENTRY_LEADER",
        "decision_group": "buyish",
        "dec": "🚀신규진입: 대장주 포착",
        "grade": "✅A급 (분할 매수)",
        "rr_ratio": 0.64,
    }

    timing = format_dashboard_timing_label(decision)
    grade = format_dashboard_candidate_grade(decision)
    reason = format_dashboard_reason({
        **decision,
        "decision_reasons": ("RS 강함",),
    })
    final_read = build_dashboard_final_read(
        decision,
        dashboard_timing=timing,
        dashboard_grade=grade,
    )

    assert timing.startswith("🔍대장주 포착: R/R 대기")
    assert "신규진입" not in timing
    assert "R/R<1" in grade
    assert "현재가 풀진입 보류" in reason
    assert final_read == "⏳눌림대기"
