"""Pure entry-signal preparation, separate from outcome selection and data loading."""

import math

from stock_lab_core.formatters import clean_float, finite_num
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)



def _build_momentum_entry_flags(
    *,
    is_etf, has_pos, my_price, targ_w, weight_gap, price_vs_avg, trend, rs_label, macd_state,
    last_macd, prev_macd, fin_score, adj_tech_score, mfi_now, rsi_now, pct_b_now, vol_ratio,
    macro_risk_value,
) -> dict:
    """Stock add-on, early entry, and breakout flags in the original order."""
    is_stock_add_on_strength = (
        (not is_etf)
        and has_pos
        and my_price > 0
        and targ_w > 0
        and weight_gap >= 2
        and 0.00 < price_vs_avg <= 0.05
        and trend in ["🚀정배열(상승)", "⏳혼조세"]
        and rs_label in ["🚀강함"]
        and last_macd > prev_macd
        and mfi_now < 80
        and rsi_now < 70
        and pct_b_now < 1.00
        and vol_ratio < 2.5
        and macro_risk_value < 4.5
    )

    is_early_entry = (
        trend == "🚀정배열(상승)"
        and rs_label == "🚀강함"
        and last_macd > prev_macd
        and macd_state in ["📉하락주의(데드크로스)", "⏳추세관망"]
        and mfi_now < 80
        and pct_b_now < 0.85
        and 50 <= rsi_now <= 65
        and adj_tech_score >= 4.0
    )
    is_breakout_extreme = (
        (not is_etf)
        and fin_score == 4
        and adj_tech_score >= 4.0
        and pct_b_now > 1.02
        and rs_label == "🚀강함"
    )
    is_breakout_normal = (
        (not is_etf)
        and fin_score == 4
        and adj_tech_score >= 4.0
        and 0.95 <= pct_b_now <= 1.02
        and rs_label == "🚀강함"
    )
    return {
        "is_stock_add_on_strength": is_stock_add_on_strength,
        "is_early_entry": is_early_entry,
        "is_breakout_extreme": is_breakout_extreme,
        "is_breakout_normal": is_breakout_normal,
    }


def _build_pullback_entry_flags(
    *,
    is_etf, cur_p, trend, rs_label, rs_slope_label, macd_state, fin_score, adj_tech_score, mfi_now,
    rsi_now, pct_b_now, vol_ratio, ma5_raw, low_now, fvg_info,
) -> dict:
    """MA5/FVG pullback flags without changing missing-value behavior."""
    ma5_now = clean_float(ma5_raw, 0.0) if finite_num(ma5_raw) else 0.0
    is_leader_base = (
        (not is_etf)
        and fin_score == 4
        and trend == "🚀정배열(상승)"
        and rs_label == "🚀강함"
        and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
        and adj_tech_score >= 4.0
    )
    ma5_gap = ((cur_p - ma5_now) / ma5_now) if ma5_now > 0 else math.nan
    is_ma5_pullback = (
        ma5_now > 0
        and low_now <= ma5_now * 1.01
        and cur_p <= ma5_now * 1.025
        and (not finite_num(ma5_gap) or ma5_gap >= -0.02)
    )
    is_bullish_fvg_pullback = (
        fvg_info["type"] == "Bullish FVG"
        and fvg_info["bottom"] is not None
        and fvg_info["top"] is not None
        and float(fvg_info["bottom"]) * 0.995 <= cur_p <= float(fvg_info["top"]) * 1.01
    )
    is_exception_not_chasing = mfi_now < 82 and pct_b_now < 1.00 and rsi_now < 70 and vol_ratio < 2.5
    is_exception_entry = (
        is_leader_base
        and rs_slope_label != "📉RS하락중"
        and (is_ma5_pullback or is_bullish_fvg_pullback)
        and is_exception_not_chasing
    )
    return {
        "ma5_now": ma5_now,
        "low_now": low_now,
        "is_leader_base": is_leader_base,
        "ma5_gap": ma5_gap,
        "is_ma5_pullback": is_ma5_pullback,
        "is_bullish_fvg_pullback": is_bullish_fvg_pullback,
        "is_exception_not_chasing": is_exception_not_chasing,
        "is_exception_entry": is_exception_entry,
    }


def _build_quality_recovery_flags(
    *,
    is_etf, cur_p, trend, rs_label, rs_slope_label, macd_state, last_macd, prev_macd, fin_score,
    mfi_now, rsi_now, pct_b_now, macro_risk_value, current_dd, ret_1m, ret_3m, ret_6m,
    short_history, is_single_day_breakdown, ma20_now, ma50_now, ma120_now, day_ret,
) -> dict:
    """Recovery watch/scout/candidate flags with unchanged thresholds."""
    is_macd_recovering = (
        macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
        or last_macd > prev_macd
    )
    is_rs_recovering = (
        rs_label == "🚀강함"
        or (rs_label == "➖보통" and rs_slope_label == "📈RS상승중")
    )
    ret_1m_ok = finite_num(ret_1m)
    ret_3m_ok = finite_num(ret_3m)
    ret_6m_ok = finite_num(ret_6m)
    was_quality_drawdown_or_trend_damage = (
        current_dd <= -0.12
        or (not ret_3m_ok)
        or ret_3m <= 0
        or (not ret_6m_ok)
        or ret_6m <= 0
        or trend != "🚀정배열(상승)"
    )
    is_quality_recovery_base = (
        (not is_etf)
        and (not short_history)
        and fin_score >= 3
        and was_quality_drawdown_or_trend_damage
        and mfi_now < 82
        and rsi_now < 72
        and pct_b_now < 0.98
        and not is_single_day_breakdown
        and macro_risk_value < 4.5
    )
    is_quality_recovery_watch = (
        is_quality_recovery_base
        and ma20_now > 0
        and cur_p >= ma20_now * 0.97
        and is_macd_recovering
        and (is_rs_recovering or rs_label != "🐢약함")
    )
    is_quality_recovery_scout = (
        is_quality_recovery_base
        and ma20_now > 0
        and ma50_now > 0
        and cur_p >= ma20_now * 0.99
        and cur_p >= ma50_now * 0.98
        and is_macd_recovering
        and is_rs_recovering
        and ret_1m_ok
        and ret_1m > -0.08
        and day_ret > -0.04
    )
    is_quality_recovery_candidate = (
        is_quality_recovery_scout
        and rs_label == "🚀강함"
        and cur_p >= ma20_now
        and cur_p >= ma50_now
        and (ma120_now <= 0 or cur_p >= ma120_now * 0.95)
        and ret_1m_ok
        and ret_1m >= -0.03
    )
    return {
        "is_macd_recovering": is_macd_recovering,
        "is_rs_recovering": is_rs_recovering,
        "was_quality_drawdown_or_trend_damage": was_quality_drawdown_or_trend_damage,
        "is_quality_recovery_base": is_quality_recovery_base,
        "is_quality_recovery_watch": is_quality_recovery_watch,
        "is_quality_recovery_scout": is_quality_recovery_scout,
        "is_quality_recovery_candidate": is_quality_recovery_candidate,
    }


def _build_structure_and_accumulation_flags(
    *,
    is_etf, has_pos, cur_p, targ_w, weight_gap, trend, rs_label, fin_score, adj_tech_score,
    mfi_now, rsi_now, pct_b_now, macro_risk_value, current_dd, short_history,
    is_single_day_breakdown, ma20_now, below_ma20, below_ma50, day_ret, is_leveraged_or_inverse,
) -> dict:
    """Structure-risk precedence and ETF accumulation eligibility."""
    rs_strong = rs_label == "🚀강함"
    is_leader_grade = (not is_etf) and fin_score == 4 and trend == "🚀정배열(상승)"
    is_momentum_leader = (
        (not is_etf)
        and fin_score >= 3
        and trend == "🚀정배열(상승)"
        and rs_strong
        and ma20_now > 0
        and cur_p > ma20_now * 1.05
    )
    ma50_damage = below_ma50 and not (rs_strong and (is_leader_grade or is_momentum_leader))
    is_extreme_momentum = (
        (not is_etf)
        and fin_score >= 3
        and trend == "🚀정배열(상승)"
        and rs_strong
        and ma20_now > 0
        and cur_p > ma20_now * 1.20
    )
    if is_extreme_momentum:
        dd_threshold = -0.35
    elif (is_leader_grade or is_momentum_leader) and rs_strong:
        dd_threshold = -0.20
    else:
        dd_threshold = -0.15

    is_recovering_from_drop = (
        trend == "🚀정배열(상승)"
        and day_ret > 0.0
        and ma20_now > 0
        and cur_p > ma20_now * 0.93
    )
    is_structure_damage_entry_risk = (
        (not is_etf)
        and (not short_history)
        and (
            current_dd <= dd_threshold
            or ma50_damage
            or (below_ma20 and not rs_strong and not is_recovering_from_drop)
            or is_single_day_breakdown
        )
    )
    is_clean_leader_entry = (
        (not is_etf)
        and adj_tech_score >= 4.5
        and rs_label == "🚀강함"
        and trend == "🚀정배열(상승)"
        and day_ret > -0.04
        and current_dd > -0.15
        and (ma20_now <= 0 or cur_p >= ma20_now * 0.98)
        and not is_structure_damage_entry_risk
    )
    is_etf_accumulation_ok = (
        is_etf
        and not is_leveraged_or_inverse
        and has_pos
        and targ_w > 0
        and weight_gap >= 3
        and (trend != "🌊역배열(하락)" or weight_gap >= 10)
        and mfi_now < 85
        and rsi_now < 75
        and pct_b_now < 1.03
        and macro_risk_value < 4.5
    )
    return {
        "_rs_strong": rs_strong,
        "_is_leader_grade": is_leader_grade,
        "_is_momentum_leader": is_momentum_leader,
        "_ma50_damage": ma50_damage,
        "_is_extreme_momentum": is_extreme_momentum,
        "_dd_threshold": dd_threshold,
        "_is_recovering_from_drop": is_recovering_from_drop,
        "is_structure_damage_entry_risk": is_structure_damage_entry_risk,
        "is_clean_leader_entry": is_clean_leader_entry,
        "is_etf_accumulation_ok": is_etf_accumulation_ok,
    }


def build_entry_signal_context(
    *,
    is_etf: bool,
    has_pos: bool,
    my_price: float,
    cur_p: float,
    targ_w: float,
    weight_gap: float,
    price_vs_avg: float,
    trend: str,
    rs_label: str,
    rs_slope_label: str,
    macd_state: str,
    last_macd: float,
    prev_macd: float,
    fin_score: int,
    adj_tech_score: float,
    mfi_now: float,
    rsi_now: float,
    pct_b_now: float,
    vol_ratio: float,
    macro_risk_value: float,
    current_dd: float,
    ret_1m: float,
    ret_3m: float,
    ret_6m: float,
    short_history: bool,
    is_single_day_breakdown: bool,
    ma20_now: float,
    ma50_now: float,
    ma120_now: float,
    ma5_raw: float,
    low_now: float,
    below_ma20: bool,
    below_ma50: bool,
    day_ret: float,
    fvg_info: dict,
    is_leveraged_or_inverse: bool,
) -> dict:
    """Assemble signal stages; keep keys, evaluation order, and policy inputs stable."""
    result = _build_momentum_entry_flags(
        is_etf=is_etf, has_pos=has_pos, my_price=my_price, targ_w=targ_w, weight_gap=weight_gap,
        price_vs_avg=price_vs_avg, trend=trend, rs_label=rs_label, macd_state=macd_state,
        last_macd=last_macd, prev_macd=prev_macd, fin_score=fin_score,
        adj_tech_score=adj_tech_score, mfi_now=mfi_now, rsi_now=rsi_now, pct_b_now=pct_b_now,
        vol_ratio=vol_ratio, macro_risk_value=macro_risk_value,
    )
    result.update(_build_pullback_entry_flags(
        is_etf=is_etf, cur_p=cur_p, trend=trend, rs_label=rs_label, rs_slope_label=rs_slope_label,
        macd_state=macd_state, fin_score=fin_score, adj_tech_score=adj_tech_score, mfi_now=mfi_now,
        rsi_now=rsi_now, pct_b_now=pct_b_now, vol_ratio=vol_ratio, ma5_raw=ma5_raw,
        low_now=low_now, fvg_info=fvg_info,
    ))
    result.update(_build_quality_recovery_flags(
        is_etf=is_etf, cur_p=cur_p, trend=trend, rs_label=rs_label, rs_slope_label=rs_slope_label,
        macd_state=macd_state, last_macd=last_macd, prev_macd=prev_macd, fin_score=fin_score,
        mfi_now=mfi_now, rsi_now=rsi_now, pct_b_now=pct_b_now, macro_risk_value=macro_risk_value,
        current_dd=current_dd, ret_1m=ret_1m, ret_3m=ret_3m, ret_6m=ret_6m,
        short_history=short_history, is_single_day_breakdown=is_single_day_breakdown,
        ma20_now=ma20_now, ma50_now=ma50_now, ma120_now=ma120_now, day_ret=day_ret,
    ))
    result.update(_build_structure_and_accumulation_flags(
        is_etf=is_etf, has_pos=has_pos, cur_p=cur_p, targ_w=targ_w, weight_gap=weight_gap,
        trend=trend, rs_label=rs_label, fin_score=fin_score, adj_tech_score=adj_tech_score,
        mfi_now=mfi_now, rsi_now=rsi_now, pct_b_now=pct_b_now, macro_risk_value=macro_risk_value,
        current_dd=current_dd, short_history=short_history,
        is_single_day_breakdown=is_single_day_breakdown, ma20_now=ma20_now, below_ma20=below_ma20,
        below_ma50=below_ma50, day_ret=day_ret, is_leveraged_or_inverse=is_leveraged_or_inverse,
    ))
    return result

