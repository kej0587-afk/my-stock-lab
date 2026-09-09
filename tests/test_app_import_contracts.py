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
            "is_fin_score_exempt_asset",
            "is_known_etf_ticker",
            "is_known_individual_stock_ticker",
            "normalize_individual_stock_asset_class",
        ],
    )


def test_db_schema_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.db_schema",
        [
            "get_feedback_create_sql",
            "get_swing_radar_create_sql",
        ],
    )


def test_decision_engine_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.decision_engine",
        [
            "DECISION_GROUP_BY_CODE",
            "apply_safety_state_override",
            "build_core_dca_context_values",
            "build_core_dca_outcome",
            "build_decision_outcome",
            "build_limited_history_etf_outcome",
            "build_position_sizing_hint",
            "build_sideways_quality_state",
            "classify_candidate_grade",
            "classify_core_etf_dca_rate",
            "classify_decision_signal",
            "classify_macro_state",
            "classify_safety_state",
            "compute_sizing_hint",
            "ensure_min_price_rows_for_decision",
            "has_down_session_pressure",
            "is_new_entry_decision_code",
            "score_main_entry",
            "score_technical_components",
            "translate_new_entry_decision_for_holding",
        ],
    )


def test_today_queue_exports_used_by_app():
    _assert_exports(
        "stock_lab_core.today_queue",
        [
            "TODAY_QUEUE_DEFENSE_TEXT_RE",
            "apply_leveraged_dca_dashboard_override",
            "build_dashboard_final_read",
            "build_today_queue_execution_snapshot",
            "format_dashboard_candidate_grade",
            "format_dashboard_reason",
            "format_dashboard_timing_label",
            "is_dashboard_actionable_signal",
            "is_dashboard_block_or_wait_label",
            "is_dashboard_low_rr_caution",
            "is_today_queue_defense_signal",
            "today_queue_reason_bucket",
            "today_queue_wait_mask",
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
