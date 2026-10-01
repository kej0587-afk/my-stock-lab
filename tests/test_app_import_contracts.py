"""Import contracts for helpers used by app.py.

These tests catch missing exports before Streamlit Cloud turns them into
startup ImportError failures.
"""

import importlib


def _assert_exports(module_name, names):
    module = importlib.import_module(module_name)
    missing = [name for name in names if not hasattr(module, name)]
    assert not missing, f"{module_name} missing exports: {missing}"


def test_formatters_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.formatters",
        [
            "clean_bool",
            "clean_float",
            "clean_int",
            "clean_symbol",
            "dataframe_from_rows",
            "ensure_kr_suffix_if_code",
            "escape_html_value",
            "finite_num",
            "format_currency",
            "format_report_money",
            "format_report_pct",
            "format_report_price",
            "format_report_ratio",
            "is_kr_listed",
            "is_ticker_like_text",
            "normalize_bucket",
            "normalize_text",
            "normalize_ticker",
            "parse_num",
            "report_num",
            "sanitize_ticker_value",
            "strip_search_prefix",
        ],
    )


def test_asset_classifier_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.asset_classifier",
        [
            "asset_class_marks_fin_score_exempt",
            "infer_asset_class_for_ticker",
            "is_domestic_kr_core_etf",
            "is_fin_score_exempt_asset",
            "is_known_etf_ticker",
            "is_known_individual_stock_ticker",
            "is_leveraged_or_inverse_product",
            "is_concentrated_non_core_etf",
            "is_tdf_or_fund_allocation_product",
            "is_us_broad_index_core_etf",
            "normalize_individual_stock_asset_class",
            "resolve_effective_investment_bucket",
        ],
    )


def test_db_schema_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.db_schema",
        [
            "get_feedback_create_sql",
            "get_signal_journal_create_sql",
            "get_swing_radar_create_sql",
        ],
    )


def test_backup_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.backup",
        [
            "build_portfolio_backup_zip",
            "build_review_export_zip",
            "dataframe_to_csv_bytes",
        ],
    )


def test_decision_engine_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.decision_engine",
        [
            "DECISION_GROUP_BY_CODE",
            "apply_safety_state_override",
            "apply_live_price_to_ohlcv",
            "build_breakdown_risk_flags",
            "build_day_return_context",
            "build_live_rebound_context",
            "build_price_history_context",
            "build_tactical_price_context",
            "build_core_dca_context_values",
            "build_core_dca_outcome",
            "build_decision_result",
            "build_decision_outcome",
            "build_entry_signal_context",
            "build_leveraged_dca_outcome",
            "build_limited_history_etf_outcome",
            "build_position_sizing_hint",
            "build_return_window_context",
            "build_rr_context",
            "build_smc_insight",
            "build_smc_structure_labels",
            "build_sideways_quality_state",
            "build_squeeze_status_context",
            "build_structure_damage_context",
            "classify_candidate_grade",
            "classify_core_etf_dca_rate",
            "classify_decision_signal",
            "classify_macro_state",
            "classify_safety_state",
            "compute_sizing_hint",
            "ensure_min_price_rows_for_decision",
            "get_source_close_values",
            "has_down_session_pressure",
            "is_new_entry_decision_code",
            "normalize_decision_runtime_inputs",
            "resolve_current_price_for_decision",
            "score_main_entry",
            "score_technical_components",
            "translate_new_entry_decision_for_holding",
        ],
    )


def test_ta_engine_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.ta_engine",
        [
            "build_indicators",
            "build_smc_overlay_features",
            "detect_equal_highs_lows",
            "detect_liquidity_grab",
            "detect_order_block_zones",
            "detect_recent_fvg",
            "detect_smc_features",
            "detect_structure_event",
            "get_macd_state",
            "get_pd_zone",
            "get_pivot_highs_lows",
            "get_recent_levels",
            "get_sqz_status",
            "get_trend",
            "summarize_smc_action",
        ],
    )


def test_today_queue_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.today_queue",
        [
            "TODAY_QUEUE_DEFENSE_TEXT_RE",
            "TODAY_QUEUE_LOGIC_VERSION",
            "apply_leveraged_dca_dashboard_override",
            "build_dashboard_final_read",
            "build_today_queue_execution_snapshot",
            "build_today_queue_signature",
            "clear_today_queue_summary_snapshot",
            "format_dashboard_candidate_grade",
            "format_dashboard_reason",
            "format_dashboard_timing_label",
            "is_dashboard_actionable_signal",
            "is_dashboard_block_or_wait_label",
            "is_dashboard_low_rr_caution",
            "is_today_queue_defense_signal",
            "leveraged_market_defense_mask",
            "leveraged_recovery_tracking_mask",
            "leveraged_scout_execution_mask",
            "load_today_queue_summary_snapshot",
            "save_today_queue_summary_snapshot",
            "sort_today_queue_detail_table",
            "today_queue_reason_bucket",
            "today_queue_wait_mask",
        ],
    )


def test_today_news_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.today_news",
        [
            "TODAY_BREAKING_STORY_RSS_PLAN",
            "TODAY_MARKET_STORY_RSS_PLAN",
            "build_today_action_news_brief",
            "fetch_today_breaking_story_news",
            "fetch_today_market_story_news",
            "normalize_today_action_news_row",
            "rank_today_action_news_rows",
        ],
    )


def test_today_flow_candidates_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.today_flow_candidates",
        [
            "classify_flow_candidate_type",
            "classify_money_flow_candidate_scope",
            "classify_money_flow_radar_label",
            "normalize_money_flow_state",
        ],
    )


def test_money_flow_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.money_flow",
        [
            "ETF_TO_THEME",
            "IMAGE_THEME_META",
            "SECTOR_CLUSTERS",
            "SECTOR_CLUSTERS_KR",
            "SECTOR_CLUSTERS_US",
            "calculate_image_theme_flow_df",
            "calculate_image_theme_group_df",
            "calculate_image_theme_rotation_df",
            "calculate_money_flow_df",
            "calculate_rotation_df",
            "calculate_sector_rotation_df",
            "classify_money_flow_state",
            "download_money_flow_prices",
            "fetch_naver_theme_coverage_snapshot",
            "get_image_theme_names",
            "get_sector_flow_state",
        ],
    )


def test_sector_snapshot_exports_used_by_app():
    _assert_exports("stock_lab_core.kr_sector_snapshot", ["build_kr_cluster_snapshot"])
    _assert_exports("stock_lab_core.us_sector_snapshot", ["build_us_cluster_snapshot"])


def test_prices_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.prices",
        [
            "_extract_yahoo_overnight_price_from_html",
            "_fetch_yahoo_regular_close_price",
            "_us_equity_market_closed_today",
            "clear_latest_price_cache",
            "clear_selected_price_cache",
            "enable_force_live_price_refresh",
            "load_latest_price",
            "load_latest_prices_batch",
            "load_price_df",
            "load_usdkrw_rate",
            "normalize_price_lookup_key",
        ],
    )


def test_data_quality_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.data_quality",
        [
            "add_quality_issue",
            "build_asset_quick_quality_report",
            "build_data_quality_report_from_frames",
        ],
    )


def test_runtime_status_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.runtime_status",
        [
            "build_speed_check_snapshot",
            "build_speed_check_rows",
        ],
    )


def test_hold_judgement_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.hold_judgement",
        [
            "HoldDecision",
            "HoldJudgement",
            "build_hold_decision",
        ],
    )


def test_swing_radar_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.swing_radar",
        [
            "build_swing_radar_df",
            "fill_empty_swing_templates",
            "get_swing_editor_base_key",
            "is_swing_candidate_allowed",
            "is_swing_excluded_ticker",
            "make_swing_candidate_row",
            "merge_swing_editor_with_saved",
            "remove_swing_row",
            "set_swing_row_status",
        ],
    )


def test_portfolio_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.portfolio",
        [
            "add_portfolio_risk_note",
            "annualize_period_return",
            "append_cash_rows",
            "apply_holdings_weight_columns",
            "PORTFOLIO_ADD_ACTIONS",
            "PORTFOLIO_CAUTION_ACTIONS",
            "build_asset_overview_dashboard_state",
            "build_asset_overview_kpis",
            "build_asset_label_map",
            "build_benchmark_return_df",
            "build_cash_buffer_scenario",
            "build_correlation_pair_summary",
            "build_market_scenario_summary",
            "build_monthly_record_status",
            "build_portfolio_action_decision_df_from_inputs",
            "build_portfolio_blended_benchmark_spec",
            "build_portfolio_market_alignment_brief",
            "build_portfolio_market_alignment_df_from_inputs",
            "build_portfolio_next_check_candidates_df_from_inputs",
            "build_portfolio_next_check_summary",
            "build_portfolio_rebalance_playbook_df",
            "build_portfolio_recommendation_df_from_inputs",
            "build_risk_contribution_df",
            "build_scenario_context",
            "calc_asset_shock_table",
            "calc_benchmark_comparison",
            "calc_blended_benchmark_comparison",
            "calc_downside_volatility",
            "calc_drawdown_details",
            "calc_portfolio_leverage_summary",
            "calc_portfolio_summary",
            "calc_reserve_summary",
            "calc_rolling_metrics",
            "calc_series_mdd",
            "calc_var_cvar",
            "classify_corr_value",
            "classify_portfolio_risk",
            "get_active_portfolio_rows",
            "get_holding_row_by_ticker",
            "get_portfolio_analysis_start_date",
            "infer_scenario_shock_multiplier",
            "make_cash_rows",
            "normalize_datetime_index_no_tz",
            "parse_month_end_date",
            "prepare_monthly_performance_df",
            "ratio_or_nan",
        ],
    )
