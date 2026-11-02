"""Prepare price and technical inputs without changing decision policies.

Provider-dependent callbacks stay explicit; these helpers do not fetch extra data
or cache results across calculations.
"""

from stock_lab_core.decision_engine import (
    build_day_return_context,
    build_return_window_context,
    build_squeeze_status_context,
    ensure_min_price_rows_for_decision,
    get_source_close_values,
    resolve_current_price_for_decision,
)
from stock_lab_core.formatters import finite_num
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.ta_engine import get_macd_state, get_sqz_status, get_trend

register_loaded_source(__name__, __file__)


def prepare_decision_price_inputs(
    df, ticker, live_price, *, build_indicators,
    apply_live_price_with_indicators, _live_indicator_context=None,
):
    """Keep original closes separate from live/prepared indicator rows."""
    source_daily_close, source_prev_close = get_source_close_values(df)
    if _live_indicator_context is None:
        df, live_ohlcv_applied, indicator_data_issue = apply_live_price_with_indicators(
            df, live_price, ticker, build_indicators,
        )
    else:
        prepared_df, live_ohlcv_applied, indicator_data_issue = _live_indicator_context
        df = prepared_df.copy(deep=True)
    if indicator_data_issue:
        live_price = 0.0

    df = ensure_min_price_rows_for_decision(df)

    last, prev = df.iloc[-1], df.iloc[-2]
    daily_close = source_daily_close if source_daily_close > 0 else float(last["Close"])
    cur_p, live_price_used = resolve_current_price_for_decision(
        df,
        live_price=live_price,
        source_daily_close=daily_close,
        live_ohlcv_applied=live_ohlcv_applied,
    )
    return_window_context = build_return_window_context(df, cur_p)
    p1m = return_window_context["p1m"]
    p3m = return_window_context["p3m"]
    p6m = return_window_context["p6m"]
    ret_1m = return_window_context["ret_1m"]
    ret_3m = return_window_context["ret_3m"]
    ret_6m = return_window_context["ret_6m"]
    prev_close = float(prev["Close"]) if finite_num(prev["Close"]) else 0.0
    day_return_context = build_day_return_context(
        cur_p=cur_p,
        daily_close=daily_close,
        prev_close=prev_close,
        source_daily_close=source_daily_close,
        source_prev_close=source_prev_close,
        live_price_used=live_price_used,
    )
    regular_day_ret = day_return_context["regular_day_ret"]
    live_ref_ret = day_return_context["live_ref_ret"]
    fallback_day_ret = day_return_context["fallback_day_ret"]
    day_ret = day_return_context["day_ret"]
    day_ret_label = day_return_context["day_ret_label"]
    live_gap_move = day_return_context["live_gap_move"]
    return {
        "df": df,
        "last": last,
        "prev": prev,
        "indicator_data_issue": indicator_data_issue,
        "daily_close": daily_close,
        "cur_p": cur_p,
        "live_price_used": live_price_used,
        "ret_1m": ret_1m,
        "ret_3m": ret_3m,
        "ret_6m": ret_6m,
        "regular_day_ret": regular_day_ret,
        "live_ref_ret": live_ref_ret,
        "day_ret": day_ret,
        "day_ret_label": day_ret_label,
        "live_gap_move": live_gap_move,
    }


def prepare_decision_technical_inputs(
    df, last, prev, ticker, asset_class, *,
    get_rs_score, get_rs_slope, score_technical_components,
):
    """Read technical inputs once, preserving RS and squeeze call order."""
    trend = get_trend(last)
    last_macd, last_sig, prev_macd, prev_sig = last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"]
    macd_state = get_macd_state(last_macd, last_sig, prev_macd, prev_sig)
    rt_macd_label = "📈상승추세" if last_macd > prev_macd else ("📉하락추세" if last_macd < prev_macd else "⏳관망")
    rsi_now, mfi_now, pct_b_now = float(last["RSI"]), float(last["MFI"]), float(last["%B"])
    _, rs_label = get_rs_score(ticker, asset_class)
    rs_slope_val, rs_slope_label, rs_slope_s = get_rs_slope(ticker, asset_class)
    squeeze_status_context = build_squeeze_status_context(df, last, prev, get_sqz_status, release_lookback=20)
    last_sqz_near = squeeze_status_context["last_sqz_near"]
    prev_sqz_near = squeeze_status_context["prev_sqz_near"]
    recent_sqz_near = squeeze_status_context["recent_sqz_near"]
    sqz_status = squeeze_status_context["sqz_status"]

    tech_scores = score_technical_components(rs_label, mfi_now, trend, macd_state, sqz_status)
    rs_s = tech_scores["rs_s"]
    mfi_s = tech_scores["mfi_s"]
    trend_s = tech_scores["trend_s"]
    macd_s = tech_scores["macd_s"]
    sqz_s = tech_scores["sqz_s"]
    tech_total = tech_scores["tech_total"]
    return {
        "trend": trend,
        "macd_state": macd_state,
        "rt_macd_label": rt_macd_label,
        "rsi_now": rsi_now,
        "mfi_now": mfi_now,
        "pct_b_now": pct_b_now,
        "rs_label": rs_label,
        "rs_slope_val": rs_slope_val,
        "rs_slope_label": rs_slope_label,
        "rs_slope_s": rs_slope_s,
        "sqz_status": sqz_status,
        "rs_s": rs_s,
        "mfi_s": mfi_s,
        "trend_s": trend_s,
        "macd_s": macd_s,
        "sqz_s": sqz_s,
        "tech_total": tech_total,
    }

