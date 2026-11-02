"""Existing Today Queue display adjustments, separate from data fetch and UI."""

from dataclasses import dataclass

import pandas as pd

from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product
from stock_lab_core.formatters import is_kr_listed, sanitize_ticker_value
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.today_queue import (
    leveraged_market_defense_mask as _leveraged_market_defense_mask,
    leveraged_recovery_tracking_mask as _leveraged_recovery_tracking_mask,
    leveraged_scout_execution_mask as _leveraged_scout_execution_mask,
    today_queue_reason_bucket as _today_queue_reason_bucket,
)

register_loaded_source(__name__, __file__)


@dataclass
class _DisplayText:
    # Keep the original series refresh points; do not reread every label after
    # each frame assignment, which would change downstream precedence.
    label: pd.Series
    final_read: pd.Series
    grade: pd.Series
    action: pd.Series


def _apply_leverage_labels(summary_df, market_guard, reason_bucket, leveraged_display_mask, code_series, text):
    ticker_series = summary_df.get("티커", pd.Series("", index=summary_df.index)).astype(str)
    data_error_mask = code_series.isin({"DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA", "NEW_ETF_MIN_DATA_WATCH"})
    macro_state_series = summary_df.get("매크로상태", pd.Series("", index=summary_df.index)).astype(str).str.upper()
    kr_market_mask = ticker_series.map(lambda t: is_kr_listed(sanitize_ticker_value(t)))
    us_market_mask = ~kr_market_mask
    leveraged_recovery_watch_mask = _leveraged_recovery_tracking_mask(summary_df, leveraged_display_mask)
    if leveraged_recovery_watch_mask.any():
        reason_bucket.loc[leveraged_recovery_watch_mask & reason_bucket.eq("시장방어")] = "관심/눌림대기"
        needs_recovery_label = leveraged_recovery_watch_mask & text.label.str.contains(r"시장위험|시장방어|추매중단|보유점검", regex=True, na=False)
        summary_df.loc[needs_recovery_label, "🔥기술적 타점"] = "⚡레버리지 회복추적: 눌림대기"
        text.label = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
    leveraged_market_defense_mask = _leveraged_market_defense_mask(
        summary_df,
        leveraged_display_mask,
        kr_market_mask,
        us_market_mask,
        market_guard,
    )
    if leveraged_market_defense_mask.any():
        reason_bucket.loc[leveraged_market_defense_mask] = "시장방어"
        needs_market_label = leveraged_market_defense_mask & ~data_error_mask & ~text.label.str.contains(r"시장위험|시장방어|추매중단|보유점검", regex=True, na=False)
        summary_df.loc[needs_market_label, "🔥기술적 타점"] = "🛡️레버리지 시장위험: 신규/DCA 대기"
        text.label = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
    kr_guard_mode = str(((market_guard or {}).get("kr_stats", {}) or {}).get("mode", ""))
    us_guard_mode = str(((market_guard or {}).get("us_stats", {}) or {}).get("mode", ""))
    whole_guard_mode = str((market_guard or {}).get("mode", ""))
    leverage_scout_block_modes = {"비상", "위험", "방어", "위험장 반등", "전시장 비상", "국장 비상", "미장 비상"}
    leveraged_scout_market_block = pd.Series(False, index=summary_df.index)
    if whole_guard_mode in {"전시장 비상", "위험", "방어", "위험장 반등"}:
        leveraged_scout_market_block = leveraged_display_mask.copy()
    else:
        if kr_guard_mode in leverage_scout_block_modes or whole_guard_mode == "국장 비상":
            leveraged_scout_market_block = leveraged_scout_market_block | (leveraged_display_mask & kr_market_mask)
        if us_guard_mode in leverage_scout_block_modes or whole_guard_mode == "미장 비상":
            leveraged_scout_market_block = leveraged_scout_market_block | (leveraged_display_mask & us_market_mask)
    scout_candidates = _leveraged_scout_execution_mask(summary_df, leveraged_display_mask)
    leveraged_scout_mask = (
        scout_candidates
        & ~leveraged_market_defense_mask
        & ~leveraged_scout_market_block
    )
    blocked_leveraged_scout_mask = (
        scout_candidates
        & leveraged_scout_market_block
        & ~leveraged_market_defense_mask
    )
    if blocked_leveraged_scout_mask.any():
        summary_df.loc[blocked_leveraged_scout_mask, "실행메모"] = "레버리지 시장대기"
        text.action = summary_df.get("실행메모", pd.Series("", index=summary_df.index)).astype(str)
    if leveraged_scout_mask.any():
        reason_bucket.loc[leveraged_scout_mask] = "관심/눌림대기"
        summary_df.loc[leveraged_scout_mask, "최종읽기"] = "⏳DCA조건부"
        summary_df.loc[leveraged_scout_mask, "실행메모"] = "조건부 소액 관찰"
        if "📌후보등급" in summary_df.columns:
            summary_df.loc[leveraged_scout_mask, "📌후보등급"] = "⚡레버리지DCA조건부"
        needs_scout_label = leveraged_scout_mask & text.label.str.contains(r"시장위험|시장방어|추매중단|보유점검|DCA\s*대기", regex=True, na=False)
        summary_df.loc[needs_scout_label, "🔥기술적 타점"] = "⚡레버리지 회복관찰: 조건부 1차 대기"
        text.label = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
        text.final_read = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)
        text.grade = summary_df.get("📌후보등급", pd.Series("", index=summary_df.index)).astype(str)
        text.action = summary_df.get("실행메모", pd.Series("", index=summary_df.index)).astype(str)


def _apply_defense_labels(summary_df, reason_bucket, leveraged_display_mask, code_series, text):
    defense_reason_mask = reason_bucket.isin([
        "비중초과 방어",
        "시장방어",
        "급락방어",
        "가격방어",
        "추세방어",
        "데이터확인",
        "기타 하드차단",
    ])
    market_reason_mask = reason_bucket.eq("시장방어")
    core_storm_mask = market_reason_mask & text.label.str.contains(r"코어\s*방어|코어\s*ETF|거치\s*적립|감속\s*적립", regex=True, na=False)
    defense_final_label = pd.Series("🛡️방어우선", index=summary_df.index)
    defense_final_label.loc[market_reason_mask] = "🛡️시장방어(추매중단)"
    defense_final_label.loc[market_reason_mask & leveraged_display_mask] = "🛡️레버리지시장방어"
    defense_final_label.loc[core_storm_mask] = "🧱코어방어(적립확인)"
    defense_final_label.loc[reason_bucket.eq("비중초과 방어")] = "🛡️비중방어"
    defense_final_label.loc[reason_bucket.eq("급락방어")] = "🛡️급락방어(종가확인)"
    defense_final_label.loc[reason_bucket.eq("가격방어")] = "🛡️가격방어(원인점검)"
    defense_final_label.loc[reason_bucket.eq("추세방어")] = "🛡️추세방어(추매보류)"
    defense_final_label.loc[reason_bucket.eq("데이터확인")] = "⚪데이터확인"
    defense_final_override_mask = (
        defense_reason_mask
        & (
            text.final_read.str.contains(r"정밀확인|눌림대기|돌파대기|관망", regex=True, na=False)
            | (market_reason_mask & ~text.final_read.str.contains(r"시장방어|레버리지시장방어|코어방어", regex=True, na=False))
        )
    )
    if defense_final_override_mask.any():
        summary_df.loc[defense_final_override_mask, "최종읽기"] = defense_final_label.loc[defense_final_override_mask]

    planned_entry_mask = (
        summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str).str.contains("방어우선", regex=False, na=False)
        & (
            text.label + " " + text.grade + " " + text.action + " " + code_series
        ).str.contains(r"최종\s*투입|현금\s*투입|코어\s*집중|패닉.*투입|위기.*코어", regex=True, case=False, na=False)
    )
    if planned_entry_mask.any():
        summary_df.loc[planned_entry_mask, "최종읽기"] = "🛡️패닉진입대기"
        if "📌후보등급" in summary_df.columns:
            summary_df.loc[
                planned_entry_mask
                & text.grade.str.contains(r"위기/패닉|방어우선", regex=True, na=False),
                "📌후보등급",
            ] = "🛡️패닉진입대기(계획확인)"
        text.final_read = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)
        text.grade = summary_df.get("📌후보등급", pd.Series("", index=summary_df.index)).astype(str)

    core_accumulation_mask = (
        summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str).str.contains("방어우선", regex=False, na=False)
        & (
            text.label + " " + text.grade + " " + text.action + " " + code_series
        ).str.contains(r"코어\s*눌림.*(?:적립|매수)|눌림\s*100%\s*적립|코어.*적립", regex=True, case=False, na=False)
    )
    if core_accumulation_mask.any():
        summary_df.loc[core_accumulation_mask, "최종읽기"] = "🧱코어적립확인"
        text.final_read = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)

    market_action_label = pd.Series("시장방어 점검", index=summary_df.index)
    market_action_label.loc[text.action.str.contains(r"R/R 회복 대기", regex=True, na=False)] = "시장방어/RR대기"
    market_action_label.loc[leveraged_display_mask] = "레버리지 신규대기"
    market_action_label.loc[core_storm_mask] = "코어 적립확인"
    if market_reason_mask.any():
        summary_df.loc[market_reason_mask, "실행메모"] = market_action_label.loc[market_reason_mask]
        text.final_read = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)
        text.action = summary_df.get("실행메모", pd.Series("", index=summary_df.index)).astype(str)
    return defense_reason_mask


def _build_display_masks(signal_group, code_series, text, defense_reason_mask):
    leveraged_dca_watch_mask = (
        code_series.str.contains(r"LEVERAGED_(?:RECOVERY_)?DCA_CONDITIONAL", regex=True, na=False)
        | text.final_read.str.contains("DCA조건부", regex=False, na=False)
        | text.grade.str.contains("레버리지DCA조건부", regex=False, na=False)
        | text.label.str.contains(r"레버리지.*DCA.*조건부|레버리지.*조건부.*DCA", regex=True, na=False)
    )
    hard_block_mask = (code_series.str.contains("HARD_BLOCK", na=False) | text.label.str.contains("하드차단", na=False)) & ~code_series.isin({"HARD_BLOCK_BOLLINGER_UPPER", "HARD_BLOCK_MFI_OVERHEAT"})
    dca_watch_override_mask = leveraged_dca_watch_mask & ~hard_block_mask
    buyish_mask = (signal_group.eq("buyish") | dca_watch_override_mask) & ~hard_block_mask
    caution_mask = (signal_group.eq("caution") & ~dca_watch_override_mask) | hard_block_mask | defense_reason_mask
    return {"hard_block_mask": hard_block_mask, "buyish_mask": buyish_mask, "caution_mask": caution_mask}


def prepare_today_queue_display(summary_df, market_guard, signal_group):
    """Return a private display frame, reason buckets and the unchanged masks."""
    summary_df = summary_df.copy()
    type_series = summary_df.get("유형", pd.Series("", index=summary_df.index)).astype(str)
    code_series = summary_df.get("판정코드", pd.Series("", index=summary_df.index)).astype(str)
    label_series = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
    final_read_series = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)
    grade_series = summary_df.get("📌후보등급", pd.Series("", index=summary_df.index)).astype(str)
    action_series = summary_df.get("실행메모", pd.Series("", index=summary_df.index)).astype(str)
    reason_bucket = summary_df.apply(_today_queue_reason_bucket, axis=1)
    leveraged_display_mask = summary_df.apply(
        lambda row: is_leveraged_or_inverse_product(row.get("종목명", ""), row.get("티커", ""), row.get("asset_class", "")), axis=1,
    )
    text = _DisplayText(label_series, final_read_series, grade_series, action_series)
    _apply_leverage_labels(summary_df, market_guard, reason_bucket, leveraged_display_mask, code_series, text)
    defense_reason_mask = _apply_defense_labels(summary_df, reason_bucket, leveraged_display_mask, code_series, text)
    masks = _build_display_masks(signal_group, code_series, text, defense_reason_mask)
    return summary_df, reason_bucket, masks
