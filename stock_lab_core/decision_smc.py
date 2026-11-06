"""Assemble existing SMC evidence without changing detectors or decision rules."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def build_decision_smc_context(
    *, df, levels, trend, rs_label, macd_state, rsi_now, mfi_now, pct_b_now,
    sqz_status, rs_slope_label, build_smc_structure_labels, detect_structure_event,
    detect_liquidity_grab, detect_recent_fvg, get_pd_zone, summarize_smc_action,
    build_smc_insight,
):
    """Return the original locals, using the same dependencies in the same order."""
    smc_structure_labels = build_smc_structure_labels(trend, rs_label, macd_state)
    ext_structure = smc_structure_labels["ext_structure"]
    int_structure = smc_structure_labels["int_structure"]

    int_event, ext_event = detect_structure_event(df, levels)
    liq_state = detect_liquidity_grab(df, levels)
    fvg_info = detect_recent_fvg(df)
    pd_zone = get_pd_zone(df)
    smc_action = summarize_smc_action(ext_structure, int_structure, int_event, ext_event, liq_state, fvg_info, pd_zone)

    smc_insight = build_smc_insight(
        rsi_now, mfi_now, pct_b_now, sqz_status, trend, rs_label, rs_slope_label
    )
    return (smc_structure_labels, ext_structure, int_structure, int_event, ext_event,
            liq_state, fvg_info, pd_zone, smc_action, smc_insight)
