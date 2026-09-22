import pandas as pd

from stock_lab_core.today_queue import (
    build_dashboard_final_read,
    build_today_queue_execution_snapshot,
    clear_today_queue_summary_snapshot,
    format_dashboard_candidate_grade,
    format_dashboard_reason,
    format_dashboard_timing_label,
    is_today_queue_defense_signal,
    leveraged_market_defense_mask,
    leveraged_recovery_tracking_mask,
    load_today_queue_summary_snapshot,
    save_today_queue_summary_snapshot,
    sort_today_queue_detail_table,
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


def test_today_queue_summary_snapshot_roundtrips(tmp_path):
    path = tmp_path / "today_queue_summary_snapshot.json"
    source = pd.DataFrame({
        "ticker": ["AMD"],
        "price": ["USD122.50"],
        "Adj점수": [3.5],
    })

    save_today_queue_summary_snapshot(source, "sig-1", "2026-09-22 11:00", path=path)
    loaded, signature, last_run = load_today_queue_summary_snapshot(path=path)

    assert list(loaded["ticker"]) == ["AMD"]
    assert list(loaded["price"]) == ["USD122.50"]
    assert float(loaded["Adj점수"].iloc[0]) == 3.5
    assert signature == "sig-1"
    assert last_run == "2026-09-22 11:00"

    clear_today_queue_summary_snapshot(path=path)
    reloaded, _, _ = load_today_queue_summary_snapshot(path=path)
    assert reloaded.empty


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


def test_leveraged_recovery_tracking_survives_broad_market_defense():
    summary_df = pd.DataFrame([{
        "종목명": "2x Bitcoin ETF",
        "티커": "BITX",
        "유형": "ETF",
        "매크로상태": "CAUTION",
        "🔥기술적 타점": "⚡레버리지 신규 추격금지: 눌림 대기",
        "패턴타점": "-",
        "최종읽기": "⏳눌림대기",
        "📌후보등급": "✅ETF 양호",
        "핵심근거": "미보유 관찰 ×0 · 회복 6/6(회복 우세) · 기초축 1W +4.7%",
        "R/R": "2.00",
        "Adj점수": 6.5,
        "현재비중": 0.0,
        "목표비중": 2.0,
    }])
    leveraged_mask = pd.Series([True], index=summary_df.index)
    kr_mask = pd.Series([False], index=summary_df.index)
    us_mask = pd.Series([True], index=summary_df.index)
    market_guard = {"mode": "위험", "macro_risk": 4.5, "us_stats": {"mode": "위험"}}

    assert bool(leveraged_recovery_tracking_mask(summary_df, leveraged_mask).iloc[0])
    assert not bool(leveraged_market_defense_mask(summary_df, leveraged_mask, kr_mask, us_mask, market_guard).iloc[0])


def test_leveraged_recovery_tracking_recovers_cached_market_label():
    summary_df = pd.DataFrame([{
        "종목명": "2x Bitcoin ETF",
        "티커": "BITX",
        "유형": "ETF",
        "매크로상태": "CAUTION",
        "🔥기술적 타점": "🛡️레버리지 시장위험: 신규/DCA 대기",
        "최종읽기": "🛡️레버리지시장방어",
        "📌후보등급": "✅ETF 양호",
        "핵심근거": "레버리지 전용 단계: 미보유 관찰 ×0",
        "R/R": "2.00",
        "Adj점수": 6.5,
        "현재비중": 0.0,
        "목표비중": 2.0,
    }])

    assert bool(leveraged_recovery_tracking_mask(summary_df).iloc[0])


def test_leveraged_storm_still_forces_market_defense():
    summary_df = pd.DataFrame([{
        "종목명": "2x Bitcoin ETF",
        "티커": "BITX",
        "유형": "ETF",
        "매크로상태": "STORM",
        "🔥기술적 타점": "⚡레버리지 신규 추격금지: 눌림 대기",
        "최종읽기": "⏳눌림대기",
        "📌후보등급": "✅ETF 양호",
        "핵심근거": "미보유 관찰 ×0 · 회복 6/6(회복 우세)",
        "R/R": "2.00",
        "Adj점수": 6.5,
        "현재비중": 0.0,
        "목표비중": 2.0,
    }])
    leveraged_mask = pd.Series([True], index=summary_df.index)
    kr_mask = pd.Series([False], index=summary_df.index)
    us_mask = pd.Series([True], index=summary_df.index)

    assert bool(leveraged_market_defense_mask(summary_df, leveraged_mask, kr_mask, us_mask, {"mode": "위험"}).iloc[0])


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


def test_today_queue_detail_sort_prefers_adj_score_over_rr():
    df = pd.DataFrame([
        {
            "종목명": "Credo",
            "티커": "CRDO",
            "최종읽기": "🛡️방어우선",
            "📌후보등급": "🛡️위기/패닉(방어우선)",
            "🔥기술적 타점": "💣패닉(-40%↓): 현금 투입",
            "안전상태": "RED",
            "Adj점수": -1.5,
            "R/R": "2.94",
        },
        {
            "종목명": "지엔씨에너지",
            "티커": "119850.KQ",
            "최종읽기": "⏳눌림대기",
            "📌후보등급": "💎S급 (최우선 후보) / 🟡정찰",
            "🔥기술적 타점": "🟡상위과열 눌림: 1차 정찰만",
            "안전상태": "GREEN",
            "Adj점수": 5.5,
            "R/R": "0.24",
        },
    ])

    sorted_df = sort_today_queue_detail_table(df)

    assert sorted_df.iloc[0]["종목명"] == "지엔씨에너지"


def test_today_queue_detail_sort_uses_rr_as_adj_tiebreaker():
    df = pd.DataFrame([
        {
            "종목명": "낮은RR",
            "티커": "LOW",
            "최종읽기": "✅정밀확인",
            "📌후보등급": "✅A급",
            "🔥기술적 타점": "눌림/종가 확인",
            "안전상태": "GREEN",
            "Adj점수": 3.5,
            "R/R": "0.55",
        },
        {
            "종목명": "높은RR",
            "티커": "HIGH",
            "최종읽기": "🛡️방어우선",
            "📌후보등급": "🛡️가격방어(신규금지)",
            "🔥기술적 타점": "⚠️가격위험: 신규진입 보류",
            "안전상태": "GREEN",
            "Adj점수": 3.5,
            "R/R": "1.43",
        },
    ])

    sorted_df = sort_today_queue_detail_table(df)

    assert list(sorted_df["종목명"]) == ["높은RR", "낮은RR"]


def test_today_queue_detail_sort_risk_first_for_defense_tabs():
    df = pd.DataFrame([
        {
            "종목명": "우량대기",
            "티커": "GOOD",
            "최종읽기": "⏳눌림대기",
            "📌후보등급": "✅A급",
            "🔥기술적 타점": "눌림대기",
            "안전상태": "GREEN",
            "Adj점수": 3.5,
            "R/R": "0.60",
        },
        {
            "종목명": "위험방어",
            "티커": "RISK",
            "최종읽기": "🛡️방어우선",
            "📌후보등급": "🛡️추세방어(신규금지)",
            "🔥기술적 타점": "⚠️추세훼손: 신규진입 보류",
            "안전상태": "RED",
            "Adj점수": -1.5,
            "R/R": "2.50",
        },
    ])

    sorted_df = sort_today_queue_detail_table(df, risk_first=True)

    assert sorted_df.iloc[0]["종목명"] == "위험방어"


def test_panic_deploy_label_is_distinct_from_avoidance_defense():
    deploy = {
        "decision_code": "PANIC_CASH_DEPLOY",
        "decision_group": "caution",
        "dec": "💣패닉(-40%↓): 현금 투입",
    }
    avoid = {
        "decision_code": "CRISIS_PANIC_SELL_OFF",
        "decision_group": "caution",
        "dec": "🚨위기: 투매 위험",
    }

    assert format_dashboard_candidate_grade(deploy) == "🛡️패닉진입대기(계획확인)"
    assert build_dashboard_final_read(deploy, pattern_timing="🛑하락패턴 유효") == "🛡️패닉진입대기"
    assert format_dashboard_candidate_grade(avoid) == "🛡️위기방어(회피)"
    assert build_dashboard_final_read(avoid, pattern_timing="🛑하락패턴 유효") == "🛡️위기방어(회피)"


def test_panic_deploy_text_overrides_generic_defense_label():
    deploy_text = {
        "decision_code": "PRICE_DRAWDOWN_HOLDING_CHECK",
        "decision_group": "caution",
        "dec": "💣패닉(-50%↓): 최종투입",
        "grade": "🛡️위기/패닉(방어우선)",
    }
    core_focus_text = {
        "decision_code": "PRICE_DRAWDOWN_HOLDING_CHECK",
        "decision_group": "caution",
        "dec": "🚨위기(-30%↓): 코어 집중",
        "grade": "🛡️위기/패닉(방어우선)",
    }

    assert format_dashboard_candidate_grade(deploy_text) == "🛡️패닉진입대기(계획확인)"
    assert build_dashboard_final_read(
        deploy_text,
        dashboard_timing="💣패닉(-50%↓): 최종투입",
        dashboard_grade="🛡️위기/패닉(방어우선)",
    ) == "🛡️패닉진입대기"
    assert build_dashboard_final_read(
        core_focus_text,
        dashboard_timing="🚨위기(-30%↓): 코어 집중",
        dashboard_grade="🛡️위기/패닉(방어우선)",
    ) == "🛡️패닉진입대기"


def test_core_pullback_accumulation_is_not_generic_defense():
    decision = {
        "decision_code": "PRICE_DRAWDOWN_HOLDING_CHECK",
        "decision_group": "caution",
        "dec": "🧱코어 눌림: 눌림 100% 적립",
        "grade": "⚖️ETF 보통",
    }

    final_read = build_dashboard_final_read(
        decision,
        dashboard_timing="🧱코어 눌림: 눌림 100% 적립",
        dashboard_grade="⚖️ETF 보통",
    )

    assert final_read == "🧱코어적립확인"


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
