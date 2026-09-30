"""Focused unit tests for decision helpers extracted from app.py.

Most helpers now live in stock_lab_core.decision_engine so they can be
tested without importing the full Streamlit app. A small app-level fixture is
kept only for helpers that still belong to app.py.
"""
import pandas as pd
import pytest

from stock_lab_core.decision_engine import (
    apply_safety_state_override,
    build_entry_signal_context,
    build_decision_result,
    build_decision_outcome,
    build_return_window_context,
    build_rr_context,
    build_smc_insight,
    build_sideways_quality_state,
    build_structure_damage_context,
    compute_sizing_hint,
    has_down_session_pressure,
    resolve_current_price_for_decision,
    translate_new_entry_decision_for_holding,
)

class _DecisionHelperAdapter:
    build_decision_outcome = staticmethod(build_decision_outcome)
    _apply_safety_state_override = staticmethod(apply_safety_state_override)
    _translate_new_entry_decision_for_holding = staticmethod(translate_new_entry_decision_for_holding)
    _has_down_session_pressure = staticmethod(has_down_session_pressure)
    build_sideways_quality_state = staticmethod(build_sideways_quality_state)
    _compute_sizing_hint = staticmethod(compute_sizing_hint)


@pytest.fixture(scope="module")
def helpers():
    return _DecisionHelperAdapter


def _outcome(app_module, label, color, code):
    return app_module.build_decision_outcome(label, color, code)


def test_build_decision_result_preserves_core_output_fields():
    outcome = build_decision_outcome("테스트 판정", "#123456", "TEST_CODE")
    ctx = {
        "decision_outcome": outcome,
        "last": {"MA5": 101, "MA20": 100, "MA50": 95, "MA120": 90},
        "fvg_info": {"type": "Bullish FVG", "active": True, "top": 110, "bottom": 105},
        "core_dca_context": {"core_dca_rate": 0.5, "core_dca_label": "정기 적립"},
        "df": [1, 2, 3],
        "cur_p": 100.0,
        "rsi_now": 55.0,
        "mfi_now": 60.0,
        "pct_b_now": 0.45,
        "rs_label": "➖보통",
        "adj_tech_score": 1.0,
        "grade": "⚖️B급",
        "t_score": 5,
        "tech_total": 3,
        "fin_score": 2,
        "current_dd": -0.1,
        "ret_3m": 0.2,
        "ret_6m": 0.3,
        "targ_w": 10.0,
        "curr_w": 6.0,
        "buy_amount": 100000,
        "eff_total": 1000000,
        "weight_gap": 4.0,
        "app_mode": "개인모드",
        "effective_bucket": "성장",
        "short_history": False,
        "is_leveraged_or_inverse": False,
        "day_ret": -0.01,
        "vol_ratio": 1.1,
        "is_structure_damage_entry_risk": False,
        "live_price_used": False,
        "daily_close": 100,
        "is_live_gap_shock": False,
        "sizing_hint": {"rate": 0.5},
        "ext_structure": "Neutral",
        "int_structure": "Bullish",
        "pd_zone": "Neutral",
        "smc_action": "관망",
        "sqz_status": "➖비압축",
        "macd_state": "📈추세유지(상승중)",
        "rt_macd_label": "📈추세유지(상승중)",
        "trend": "⏳혼조세",
        "liq_state": "없음",
        "int_event": "None",
        "ext_event": "None",
        "main_score": 2,
        "rs_s": 1,
        "mfi_s": 0,
        "trend_s": 0,
        "macd_s": 1,
        "sqz_s": 0,
        "rs_slope_s": 0,
        "rs_slope_label": "횡보",
        "rs_slope_val": 0.0,
        "has_pos": False,
        "is_core_etf": False,
        "price_vs_avg": 0.0,
        "rr_ratio": 1.8,
        "rr_target_price": 115,
        "rr_stop_atr": 92,
        "_atr": 4,
        "rr_target_source": "테스트 목표",
        "rr_stop_source": "테스트 손절",
        "rr_target_is_projection": False,
        "rr_tp1_price": 105,
        "rr_tp2_price": 110,
        "rr_tp3_price": 115,
        "is_52w_breakout": False,
        "sector_flow_state": "중립",
        "smc_insight": "테스트",
        "safety_state": "GREEN",
        "macro_state": "NORMAL",
    }

    result = build_decision_result(ctx)

    assert result["dec"] == "테스트 판정"
    assert result["decision_code"] == "TEST_CODE"
    assert result["history_days"] == 3
    assert result["ma20"] == 100
    assert result["fvg_type"] == "Bullish FVG"
    assert result["core_dca_rate"] == 0.5
    assert result["profit_take_signal"] is False


def test_resolve_current_price_for_decision_accepts_reasonable_live_price():
    df = pd.DataFrame({"Close": [100.0, 101.0]})

    cur_p, live_used = resolve_current_price_for_decision(
        df,
        live_price=102.0,
        source_daily_close=101.0,
        live_ohlcv_applied=False,
    )

    assert cur_p == 102.0
    assert live_used is True


def test_resolve_current_price_for_decision_rejects_unapplied_extreme_gap():
    df = pd.DataFrame({"Close": [100.0, 101.0]})

    cur_p, live_used = resolve_current_price_for_decision(
        df,
        live_price=250.0,
        source_daily_close=101.0,
        live_ohlcv_applied=False,
    )

    assert cur_p == 101.0
    assert live_used is False


def test_build_return_window_context_uses_available_history_windows():
    df = pd.DataFrame({"Close": list(range(1, 122))})

    ctx = build_return_window_context(df, cur_p=121.0)

    assert ctx["p1m"] == 101
    assert ctx["p3m"] == 61
    assert ctx["p6m"] == 1
    assert ctx["ret_1m"] == pytest.approx(121 / 101 - 1)
    assert ctx["ret_3m"] == pytest.approx(121 / 61 - 1)
    assert ctx["ret_6m"] == pytest.approx(120.0)


def _flat_ohlc(rows=15, close=10.0, high=11.0, low=9.0):
    return pd.DataFrame({
        "High": [high] * rows,
        "Low": [low] * rows,
        "Close": [close] * rows,
    })


def test_build_rr_context_uses_internal_high_before_atr_projection():
    context = build_rr_context(
        _flat_ohlc(),
        cur_p=10.0,
        levels={"int_high": 15.0, "ext_high": 20.0},
    )

    assert context["_atr"] == pytest.approx(2.0)
    assert context["rr_stop_atr"] == 6.0
    assert context["rr_tp1_price"] == 12.0
    assert context["rr_tp2_price"] == 14.0
    assert context["rr_tp3_price"] == 18.0
    assert context["rr_target_price"] == 15.0
    assert context["rr_target_source"] == "차트 구조: 최근 내부고점"
    assert context["rr_target_is_projection"] is False
    assert context["rr_ratio"] == 1.25


def test_build_rr_context_uses_external_high_when_internal_high_is_below_price():
    context = build_rr_context(
        _flat_ohlc(),
        cur_p=10.0,
        levels={"int_high": 9.0, "ext_high": 16.0},
    )

    assert context["rr_target_price"] == 16.0
    assert context["rr_target_source"] == "차트 구조: 최근 외부고점"
    assert context["rr_target_is_projection"] is False
    assert context["rr_ratio"] == 1.5


def test_build_rr_context_marks_atr_projection_when_no_structure_target_above_price():
    context = build_rr_context(
        _flat_ohlc(),
        cur_p=10.0,
        levels={"int_high": 9.0, "ext_high": 9.5},
    )

    assert context["rr_target_price"] == 18.0
    assert context["rr_target_source"] == "강세 시나리오 상단: 현재가 + 4ATR"
    assert context["rr_target_is_projection"] is True
    assert context["rr_ratio"] == 2.0


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (
            dict(rsi_now=29, mfi_now=85, pct_b_now=0.5, sqz_status="➖비압축", trend="⏳혼조세", rs_label="➖보통", rs_slope_label="➖RS중립"),
            "과매도 극단. 유동성 청산 후 구조적 반등(CHoCH) 여부 관찰.",
        ),
        (
            dict(rsi_now=55, mfi_now=82, pct_b_now=0.5, sqz_status="➖비압축", trend="⏳혼조세", rs_label="➖보통", rs_slope_label="➖RS중립"),
            "스마트머니 익절 가능성이 높은 단기 과열 구간.",
        ),
        (
            dict(rsi_now=55, mfi_now=55, pct_b_now=0.6, sqz_status="🚀해제직후", trend="⏳혼조세", rs_label="➖보통", rs_slope_label="➖RS중립"),
            "응축 후 발산 초기. 모멘텀 실리는 타점 구간.",
        ),
        (
            dict(rsi_now=55, mfi_now=55, pct_b_now=0.9, sqz_status="➖비압축", trend="🚀정배열(상승)", rs_label="🚀강함", rs_slope_label="📉RS하락중"),
            "구조적 상승(BoS) 유지 중이나 RS 기울기 하락 — 상대강도 약화 초기 신호, 추격 자제.",
        ),
        (
            dict(rsi_now=55, mfi_now=55, pct_b_now=0.9, sqz_status="➖비압축", trend="🌊역배열(하락)", rs_label="➖보통", rs_slope_label="➖RS중립"),
            "하락 구조 우세. 추세 전환 전까지 보수적 접근 권장.",
        ),
    ],
)
def test_build_smc_insight_preserves_existing_message_priority(kwargs, expected):
    assert build_smc_insight(**kwargs) == expected


def test_build_position_management_context_flags_leveraged_dca_conditional(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_effective_total_asset", lambda total_eval, fallback: 100000)
    monkeypatch.setattr(app_module, "get_effective_weights", lambda name, ticker, current_w, target_w: (7.0, 10.0))
    monkeypatch.setattr(app_module, "get_effective_buy_amount", lambda name, ticker, total, current_w, target_w: 3000)
    monkeypatch.setattr(app_module, "get_effective_bucket", lambda name, ticker: "satellite")
    monkeypatch.setattr(app_module, "is_leveraged_or_inverse_product", lambda name, ticker, asset_class: True)
    monkeypatch.setattr(app_module, "is_concentrated_non_core_etf", lambda name, ticker, asset_class: False)
    monkeypatch.setattr(app_module, "is_tdf_or_fund_allocation_product", lambda name, ticker, asset_class: False)
    monkeypatch.setattr(
        app_module,
        "build_core_dca_context",
        lambda *args, **kwargs: {"core_dca_rate": 0.0, "core_dca_label": ""},
    )

    context = app_module.build_position_management_context(
        name="RAM",
        ticker="RAM",
        asset_class="us_etf_nasdaq",
        is_etf=True,
        has_pos=True,
        my_price=100.0,
        cur_p=90.0,
        total_eval_value=100000,
        user_total_asset=0.0,
        user_curr_w=7.0,
        user_targ_w=10.0,
        current_dd=-0.25,
        pct_b_now=0.50,
        rsi_now=48.0,
        mfi_now=52.0,
        ma20_now=92.0,
        day_ret=-0.02,
        live_gap_move=-0.01,
        trend="⏳혼조세",
        app_mode="개인모드",
        macro_risk_value=1.5,
        adj_tech_score=2.0,
        has_down_session_pressure=False,
        below_ma5=False,
    )

    assert context["eff_total"] == 100000
    assert context["buy_amount"] == 3000
    assert context["price_vs_avg"] == pytest.approx(-0.10)
    assert context["weight_gap"] == 3.0
    assert context["is_leveraged_or_inverse"] is True
    assert context["is_leveraged_dca_candidate"] is True
    assert context["is_leveraged_dca_wait_high"] is False
    assert context["is_leveraged_dca_conditional"] is True
    assert context["is_core_dca_allowed"] is False


def test_build_position_management_context_marks_core_dca_allowed(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_effective_total_asset", lambda total_eval, fallback: 200000)
    monkeypatch.setattr(app_module, "get_effective_weights", lambda name, ticker, current_w, target_w: (40.0, 50.0))
    monkeypatch.setattr(app_module, "get_effective_buy_amount", lambda name, ticker, total, current_w, target_w: 20000)
    monkeypatch.setattr(app_module, "get_effective_bucket", lambda name, ticker: "core")
    monkeypatch.setattr(app_module, "is_leveraged_or_inverse_product", lambda name, ticker, asset_class: False)
    monkeypatch.setattr(app_module, "is_concentrated_non_core_etf", lambda name, ticker, asset_class: False)
    monkeypatch.setattr(app_module, "is_tdf_or_fund_allocation_product", lambda name, ticker, asset_class: False)
    monkeypatch.setattr(
        app_module,
        "build_core_dca_context",
        lambda *args, **kwargs: {"core_dca_rate": 0.5, "core_dca_label": "코어 50% 적립"},
    )

    context = app_module.build_position_management_context(
        name="S&P500",
        ticker="379800.KS",
        asset_class="us_etf_sp",
        is_etf=True,
        has_pos=True,
        my_price=100.0,
        cur_p=95.0,
        total_eval_value=200000,
        user_total_asset=0.0,
        user_curr_w=40.0,
        user_targ_w=50.0,
        current_dd=-0.08,
        pct_b_now=0.55,
        rsi_now=50.0,
        mfi_now=50.0,
        ma20_now=94.0,
        day_ret=0.01,
        live_gap_move=0.01,
        trend="⏳혼조세",
        app_mode="개인모드",
        macro_risk_value=2.0,
        adj_tech_score=2.0,
        has_down_session_pressure=False,
        below_ma5=False,
    )

    assert context["effective_bucket"] == "core"
    assert context["is_core_etf"] is True
    assert context["core_dca_rate"] == 0.5
    assert context["is_core_dca_allowed"] is True
    assert context["is_leveraged_dca_candidate"] is False


def _entry_signal_kwargs(**overrides):
    kwargs = dict(
        is_etf=False,
        has_pos=False,
        my_price=0.0,
        cur_p=101.5,
        targ_w=10.0,
        weight_gap=5.0,
        price_vs_avg=0.0,
        trend="🚀정배열(상승)",
        rs_label="🚀강함",
        rs_slope_label="📈RS상승중",
        macd_state="🔥매수신호(골든크로스)",
        last_macd=1.2,
        prev_macd=1.0,
        fin_score=4,
        adj_tech_score=4.5,
        mfi_now=55.0,
        rsi_now=58.0,
        pct_b_now=0.70,
        vol_ratio=1.2,
        macro_risk_value=1.5,
        current_dd=-0.05,
        ret_1m=0.04,
        ret_3m=0.08,
        ret_6m=0.12,
        short_history=False,
        is_single_day_breakdown=False,
        ma20_now=98.0,
        ma50_now=95.0,
        ma120_now=90.0,
        ma5_raw=100.0,
        low_now=100.5,
        below_ma20=False,
        below_ma50=False,
        day_ret=0.01,
        fvg_info={"type": "None", "bottom": None, "top": None},
        is_leveraged_or_inverse=False,
    )
    kwargs.update(overrides)
    return kwargs


def test_build_entry_signal_context_flags_exception_ma5_pullback():
    context = build_entry_signal_context(**_entry_signal_kwargs())

    assert context["is_leader_base"] is True
    assert context["is_ma5_pullback"] is True
    assert context["is_exception_not_chasing"] is True
    assert context["is_exception_entry"] is True
    assert context["is_clean_leader_entry"] is True


def test_build_entry_signal_context_extreme_momentum_raises_drawdown_threshold():
    context = build_entry_signal_context(**_entry_signal_kwargs(
        fin_score=3,
        cur_p=130.0,
        low_now=128.0,
        ma5_raw=125.0,
        ma20_now=100.0,
        ma50_now=95.0,
        current_dd=-0.25,
        pct_b_now=0.90,
    ))

    assert context["_is_extreme_momentum"] is True
    assert context["_dd_threshold"] == -0.35
    assert context["is_structure_damage_entry_risk"] is False


def test_build_entry_signal_context_flags_plain_etf_accumulation():
    context = build_entry_signal_context(**_entry_signal_kwargs(
        is_etf=True,
        has_pos=True,
        fin_score=0,
        trend="⏳혼조세",
        rs_label="➖보통",
        rs_slope_label="➖RS중립",
        macd_state="⏳추세관망",
        targ_w=20.0,
        weight_gap=4.0,
        pct_b_now=0.60,
        rsi_now=55.0,
        mfi_now=60.0,
        is_leveraged_or_inverse=False,
    ))

    assert context["is_etf_accumulation_ok"] is True
    assert context["is_breakout_normal"] is False
    assert context["is_exception_entry"] is False


def _structure_damage_kwargs(**overrides):
    kwargs = dict(
        is_structure_damage_entry_risk=True,
        current_dd=-0.18,
        dd_threshold=-0.15,
        ma50_damage=False,
        below_ma20=False,
        rs_strong=True,
        rs_label="🚀강함",
        is_single_day_breakdown=False,
        is_extreme_momentum=False,
        trend="🚀정배열(상승)",
        ret_1m=0.02,
        ret_3m=0.04,
        rsi_now=50.0,
        pct_b_now=0.55,
        ma20_now=100.0,
        cur_p=102.0,
        ma50_now=98.0,
        day_ret=0.01,
        mfi_now=50.0,
    )
    kwargs.update(overrides)
    return kwargs


def test_build_structure_damage_context_labels_drawdown_only_price_risk():
    context = build_structure_damage_context(**_structure_damage_kwargs())

    assert context["_drawdown_only_entry_risk"] is True
    assert context["_single_day_only_entry_risk"] is False
    assert context["_entry_risk_label"] == "⚠️가격위험: 신규진입 보류"
    assert context["_holding_risk_code"] == "PRICE_DRAWDOWN_HOLDING_CHECK"
    assert context["_sd_reasons_t"] == ("고점대비 -18.0% 하락 (임계치 -15%)",)


def test_build_structure_damage_context_labels_single_day_breakdown():
    context = build_structure_damage_context(**_structure_damage_kwargs(
        current_dd=-0.05,
        is_single_day_breakdown=True,
    ))

    assert context["_single_day_only_entry_risk"] is True
    assert context["_drawdown_only_entry_risk"] is False
    assert context["_entry_risk_code"] == "SINGLE_DAY_BREAKDOWN_NO_ENTRY"
    assert context["_holding_risk_label"] == "⚠️단기급락: 추매금지/종가확인"
    assert context["is_capitulation_selloff"] is False


def test_build_structure_damage_context_labels_true_structure_damage():
    context = build_structure_damage_context(**_structure_damage_kwargs(
        current_dd=-0.10,
        ma50_damage=True,
        below_ma20=True,
        rs_strong=False,
        rs_label="🐢약함",
        cur_p=94.0,
    ))

    assert context["_drawdown_only_entry_risk"] is False
    assert context["_single_day_only_entry_risk"] is False
    assert context["_entry_risk_code"] == "STRUCTURE_DAMAGE_NO_ENTRY"
    assert "MA50 하회 (대장주 요건 미충족)" in context["_sd_reasons_t"]
    assert "MA20 하회 + RS 🐢약함" in context["_sd_reasons_t"]


def test_build_structure_damage_context_keeps_recovered_drawdown_out_of_capitulation():
    context = build_structure_damage_context(**_structure_damage_kwargs(
        current_dd=-0.24,
        dd_threshold=-0.35,
        is_structure_damage_entry_risk=False,
        ret_1m=0.05,
        ret_3m=0.10,
        cur_p=105.0,
        ma20_now=100.0,
        ma50_now=103.0,
    ))

    assert context["_is_recovered_drawdown_zone"] is True
    assert context["is_capitulation_selloff"] is False


# ---------------------------------------------------------------------------
# _apply_safety_state_override
# ---------------------------------------------------------------------------

def test_safety_red_downgrades_aggressive_new_entry(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    dec, col, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=4.0, adj_tech_score=4.0,
    )
    assert outcome.code == "SAFETY_RED_NO_NEW_ENTRY"
    assert dec == outcome.label
    assert col == outcome.color
    assert outcome.group == "caution"
    # The original signal should be referenced in the reasons.
    assert any("S_PULLBACK_ENTRY" in r or "탑승 찬스" in r for r in outcome.reasons)


@pytest.mark.parametrize("code", [
    "BREAKOUT_52W_ENTRY", "S_PULLBACK_ENTRY", "OVERSOLD_NEW_ENTRY", "EARLY_ENTRY",
    "EARLY_REVERSAL_ENTRY", "NEW_ENTRY_LEADER", "QUALITY_PULLBACK_ENTRY",
    "TREND_PULLBACK_EXPLORE", "EXCEPTION_ENTRY",
    "LEADER_MA5_FAST_PULLBACK_ENTRY", "LEADER_MA5_PULLBACK_ENTRY",
])
def test_safety_red_downgrades_all_aggressive_codes(helpers, code):
    decision_outcome = _outcome(helpers, "테스트", "#000000", code)
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=0.0, adj_tech_score=0.0,
    )
    assert outcome.code == "SAFETY_RED_NO_NEW_ENTRY"


def test_safety_red_does_not_downgrade_when_holding_position(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=True,
        tech_total=0.0, main_score=4.0, adj_tech_score=4.0,
    )
    assert outcome.code == "S_PULLBACK_ENTRY"


def test_safety_yellow_or_green_does_not_downgrade(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 탑승 찬스", "#8b5cf6", "S_PULLBACK_ENTRY",
    )
    for safety_state in ("YELLOW", "GREEN"):
        _, _, outcome = helpers._apply_safety_state_override(
            decision_outcome, decision_outcome.label, decision_outcome.color,
            safety_state=safety_state, has_pos=False,
            tech_total=2.0, main_score=4.0, adj_tech_score=4.0,
        )
        assert outcome.code == "S_PULLBACK_ENTRY"


def test_safety_red_does_not_touch_non_aggressive_code(helpers):
    decision_outcome = _outcome(
        helpers, "🚨위기/패닉: 투매 포착", "#dc2626", "CRISIS_PANIC_SELL_OFF",
    )
    _, _, outcome = helpers._apply_safety_state_override(
        decision_outcome, decision_outcome.label, decision_outcome.color,
        safety_state="RED", has_pos=False,
        tech_total=0.0, main_score=3.0, adj_tech_score=2.0,
    )
    assert outcome.code == "CRISIS_PANIC_SELL_OFF"


def test_holding_position_translates_new_entry_leader_label(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )

    outcome = helpers._translate_new_entry_decision_for_holding(
        decision_outcome, has_pos=True, weight_gap=4.02,
    )

    assert outcome.code == "HOLDING_LEADER_ADD_REVIEW"
    assert "신규진입" not in outcome.label
    assert "보유" in outcome.label
    assert outcome.group == "caution"
    assert any("4.0%p" in r for r in outcome.reasons)


def test_non_holding_position_keeps_new_entry_leader_label(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )

    outcome = helpers._translate_new_entry_decision_for_holding(
        decision_outcome, has_pos=False, weight_gap=4.02,
    )

    assert outcome.code == "NEW_ENTRY_LEADER"
    assert outcome.label == "🆕신규진입: 대장주 포착"


def test_today_market_guard_reasons_name_triggering_indexes(app_module):
    stats = app_module._today_benchmark_guard_stats(pd.DataFrame([
        {"시장": "KOSPI", "티커": "^KS11", "1일": 0.046, "5일": 0.026, "20일": 0.118, "MA20": "상회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSDAQ", "티커": "^KQ11", "1일": 0.011, "5일": -0.015, "20일": 0.029, "MA20": "하회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSPI200 ETF", "티커": "069500.KS", "1일": 0.048, "5일": 0.030, "20일": 0.130, "MA20": "상회", "MA50": "상회", "연속하락": 0},
        {"시장": "KOSDAQ150 ETF", "티커": "229200.KS", "1일": 0.015, "5일": -0.024, "20일": 0.031, "MA20": "하회", "MA50": "상회", "연속하락": 0},
    ]))

    reason_text = " · ".join(stats["reasons"])

    assert stats["score"] == 1
    assert "주요지수 2개" in reason_text
    assert "KOSDAQ(^KQ11)" in reason_text
    assert "KOSDAQ150 ETF(229200.KS)" in reason_text


def test_down_session_pressure_detects_regular_or_live_drop(helpers):
    assert helpers._has_down_session_pressure(
        day_ret=-0.025,
        regular_day_ret=-0.025,
        live_ref_ret=-0.007,
        live_gap_move=-0.007,
        live_price_used=True,
    )
    assert not helpers._has_down_session_pressure(
        day_ret=-0.012,
        regular_day_ret=-0.012,
        live_ref_ret=-0.004,
        live_gap_move=-0.004,
        live_price_used=True,
    )


def test_holding_pullback_wait_code_is_caution(helpers):
    outcome = _outcome(
        helpers,
        "🟡보유주 단기하락: 추매는 종가 확인",
        "#d97706",
        "HOLDING_PULLBACK_WAIT_CLOSE",
    )

    assert outcome.group == "caution"


def test_sideways_quality_blocks_leveraged_overheat_even_after_recovery(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 17.58,
            "rsi": 70.7,
            "mfi": 63.7,
            "pct_b": 0.81,
            "ma5": 17.2,
            "ma20": 14.3,
            "ma50": 12.8,
            "ma120": 15.4,
            "rr_ratio": 2.0,
            "dd": -0.738,
            "trend": "⏳혼조세",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 1.0,
        },
        is_leveraged_product=True,
    )

    assert state["status"] == "차단"
    assert "레버리지" in state["label"]


def test_sideways_quality_allows_stable_ma20_support_for_normal_asset(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 102.0,
            "rsi": 55.0,
            "mfi": 58.0,
            "pct_b": 0.55,
            "ma5": 101.5,
            "ma20": 100.0,
            "ma50": 98.0,
            "ma120": 90.0,
            "rr_ratio": 2.1,
            "dd": -0.04,
            "trend": "🚀정배열(상승)",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 1.0,
            "bucket": "swing",
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "통과"
    assert "매수 가능 횡보" in state["label"]


def test_sideways_quality_blocks_poor_rr_despite_uptrend(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 135.86,
            "rsi": 63.0,
            "mfi": 64.0,
            "pct_b": 0.73,
            "ma5": 145.2,
            "ma20": 94.93,
            "ma50": 76.75,
            "rr_ratio": 0.64,
            "dd": -0.231,
            "trend": "🚀정배열(상승)",
            "rs_label": "🚀강함",
            "macd": "📈추세유지(상승중)",
            "vol_ratio": 0.8,
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "차단"
    assert "손익비" in state["label"]


def test_sideways_quality_keeps_core_dca_as_rate_limited_not_blocked(helpers):
    state = helpers.build_sideways_quality_state(
        {
            "cur_p": 98.0,
            "rsi": 38.0,
            "mfi": 43.0,
            "pct_b": 0.30,
            "ma5": 99.0,
            "ma20": 100.0,
            "ma50": 104.0,
            "rr_ratio": 0.8,
            "dd": -0.12,
            "trend": "🌊역배열(하락)",
            "rs_label": "➖보통",
            "bucket": "core",
            "core_dca_rate": 1.0,
        },
        is_leveraged_product=False,
    )

    assert state["status"] == "주의"
    assert "코어" in state["label"]


def test_none_decision_outcome_is_normalized(helpers):
    dec, col, outcome = helpers._apply_safety_state_override(
        None, "그냥 보유", "#6b7280",
        safety_state="GREEN", has_pos=True,
        tech_total=3.0, main_score=2.0, adj_tech_score=3.0,
    )
    assert outcome is not None
    assert dec == "그냥 보유"
    assert col == "#6b7280"


# ---------------------------------------------------------------------------
# _compute_sizing_hint
# ---------------------------------------------------------------------------

def test_sizing_hint_for_new_entry_signal(helpers):
    decision_outcome = _outcome(
        helpers, "🆕신규진입: 대장주 포착", "#16a34a", "NEW_ENTRY_LEADER",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=False, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=10.0, ticker="TST.KS",
    )
    assert hint  # build_position_sizing_hint should produce a non-empty hint


def test_sizing_hint_ma5_pullback_addon_kr_stock(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=5.0, ticker="TST.KS",
    )
    assert "MA5 눌림" in hint
    assert "원" in hint  # KR ticker -> KRW formatting
    assert "5.0%p" in hint


def test_sizing_hint_ma5_pullback_addon_us_ticker(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_FAST_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=100.0,
        is_etf=False, weight_gap=5.0, ticker="AAPL",
    )
    assert "MA5 눌림" in hint
    assert "$" in hint  # US ticker -> USD formatting


def test_sizing_hint_no_addon_when_weight_gap_small(helpers):
    decision_outcome = _outcome(
        helpers, "🎯S급 눌림목: 추매", "#8b5cf6", "LEADER_MA5_PULLBACK_ENTRY",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=0.5, ticker="TST.KS",
    )
    assert hint == ""

def test_sizing_hint_no_addon_for_unrelated_code(helpers):
    decision_outcome = _outcome(
        helpers, "📈A급 비중여유: 소액 추가 검토", "#22c55e", "A_GRADE_ADD_ON_REVIEW",
    )
    hint = helpers._compute_sizing_hint(
        decision_outcome,
        has_pos=True, targ_w=10.0, eff_total=10_000_000, cur_p=10_000.0,
        is_etf=False, weight_gap=5.0, ticker="TST.KS",
    )
    assert hint == ""
