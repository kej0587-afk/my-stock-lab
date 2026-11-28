"""Restore a manual calculation's discovery inputs without running discovery again."""
from copy import deepcopy
import logging

import pandas as pd

from stock_lab_core.today_queue_session import (
    CLEARED_OWNERS_KEY, LAST_RUN_KEY, ORIGIN_KEY, SIGNATURE_KEY, STALE_KEY, SUMMARY_KEY,
)


def restore_discovery_context(state, *, owner, raw_watch_items, mode, logic_version,
                              account_context, flow_snapshot, build_items, signature, load):
    """Only hydrate missing discovery; never replace a newly fetched market snapshot."""
    if flow_snapshot is not None or not owner or owner in state.get(CLEARED_OWNERS_KEY, ()):
        return None
    from stock_lab_core.today_restore_inputs import validate_restore_inputs

    frame = state.get(SUMMARY_KEY) if state.get("today_queue_summary_owner") == owner else None
    saved_sig, last_run = state.get(SIGNATURE_KEY, ""), state.get(LAST_RUN_KEY, "")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        frame, saved_sig, last_run = load(owner_scope=owner, expected_signature=None)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    envelope = frame.attrs.get("today_restore_inputs")
    if not isinstance(envelope, dict):
        return None
    reason = validate_restore_inputs(
        envelope, raw_watch_items=raw_watch_items, base_items=build_items(raw_watch_items),
        mode=mode, logic_version=logic_version, account_context=account_context,
    )
    enabled = envelope.get("refresh_flow_candidates")
    if "today_queue_refresh_flow_candidates" in state and state["today_queue_refresh_flow_candidates"] != enabled:
        reason = "돈흐름 자동후보 설정 변경 · 재계산 필요"
    items = envelope.get("watch_items", ())
    if not reason and (envelope.get("account_context") != frame.attrs.get("portfolio_signal_context")
                       or envelope.get("calculated_at") != last_run):
        reason = "원계산 시각·계좌 근거 불일치 · 재계산 필요"
    if not reason and signature(items, mode, logic_version=logic_version) != saved_sig:
        reason = "저장 후보 범위와 원계산 서명 불일치 · 재계산 필요"
    restored = frame.copy(deep=True)
    if reason:
        restored.attrs[STALE_KEY] = reason
    if state.get("today_queue_summary_owner") not in (None, owner):
        from stock_lab_core.today_queue_session import clear_cached_summary
        clear_cached_summary(state, explicit=False)
    state.update({SUMMARY_KEY: restored, SIGNATURE_KEY: saved_sig, LAST_RUN_KEY: last_run,
                  ORIGIN_KEY: "저장 결과 복원", "today_queue_summary_owner": owner})
    if reason:
        return None
    state["today_queue_refresh_flow_candidates"] = enabled
    snapshot = deepcopy(envelope.get("flow_snapshot"))
    if isinstance(snapshot, dict):
        state["today_market_flow_snapshot"] = snapshot
        state["today_market_flow_last_nonempty_snapshot"] = snapshot
        state["today_market_flow_snapshot_last_run"] = envelope["calculated_at"]
    state["today_queue_current_input_counts"] = {
        "registered": len(raw_watch_items), "calculated": len(items),
        "auto_flow_candidates": len(envelope.get("flow_auto_items", ())),
        "refresh_flow_candidates": enabled,
    }
    if isinstance(frame.attrs.get("today_observation_cache"), dict):
        state["today_market_observation_cache"] = deepcopy(frame.attrs["today_observation_cache"])
    return tuple(deepcopy(items)), tuple(deepcopy(envelope.get("flow_auto_items", ())))


def capture_discovery_context(state, summary, *, mode, raw_watch_items, base_items,
                              watch_items, flow_auto_items, logic_version, refresh_flow_candidates,
                              flow_snapshot, calculated_at):
    if not isinstance(summary, pd.DataFrame) or summary.empty:
        return
    if not isinstance(summary.attrs.get("portfolio_signal_context"), str) or not summary.attrs["portfolio_signal_context"]:
        return
    from stock_lab_core.today_restore_inputs import capture_restore_inputs

    fields = ("acc_filter", "_app_holdings_table", "_app_krw_cash", "_app_usd_cash",
              "_app_reserve_target_weight", "fin_score_map")
    if flow_snapshot is None:
        flow_snapshot = state.get("today_market_flow_snapshot") or state.get("today_market_flow_last_nonempty_snapshot")
    envelope = capture_restore_inputs(
        raw_watch_items=raw_watch_items, base_items=base_items, watch_items=watch_items,
        flow_auto_items=flow_auto_items, mode=mode, logic_version=logic_version,
        account_context=summary.attrs.get("portfolio_signal_context"),
        flow_snapshot=flow_snapshot, calculated_at=calculated_at,
        refresh_flow_candidates=refresh_flow_candidates,
        account_inputs={key: deepcopy(state.get(key)) for key in fields},
    )
    if envelope:
        summary.attrs["today_restore_inputs"] = envelope
    else:
        logging.warning("Today restoration inputs could not be preserved; original calculation retained")


def saved_display_for_context(summary, metadata):
    if metadata.get("점검입력맥락") != "일치" or metadata.get("점검결과출처") == "새 전체 계산":
        return None
    saved = summary.attrs.get("today_saved_display")
    if (not isinstance(saved, pd.DataFrame) or saved.empty
            or saved.get("티커", pd.Series(dtype=object)).tolist() != summary.get("티커", pd.Series(dtype=object)).tolist()):
        return None
    out = saved.copy(deep=True)
    out.attrs = {key: deepcopy(value) for key, value in summary.attrs.items()
                 if key not in {"today_restore_inputs", "today_saved_display", "today_observation_cache", "today_saved_market_guard"}}
    from stock_lab_core.today_result_observation import attach_result_metadata
    return attach_result_metadata(out, metadata)


def save_completed_display(state, original, displayed, *, signature, owner, save, market_guard=None):
    """Atomic second save adds frozen display evidence; raw calculation stays raw."""
    if not original.attrs.get("today_restore_inputs"):
        return
    raw = original.copy(deep=True)
    # Result metadata describes this rendering, not original numerical inputs.
    from stock_lab_core.today_result_observation import META_COLUMNS
    raw = raw.drop(columns=list(META_COLUMNS), errors="ignore")
    frozen = displayed.copy(deep=True)
    frozen.attrs = {}
    raw.attrs["today_saved_display"] = frozen
    if isinstance(market_guard, dict):
        raw.attrs["today_saved_market_guard"] = deepcopy(market_guard)
    raw.attrs["today_observation_cache"] = deepcopy(state.get("today_market_observation_cache", {}))
    state[SUMMARY_KEY] = raw
    state["today_queue_summary_last_nonempty_df"] = raw.copy(deep=True)
    save(raw, signature, state.get(LAST_RUN_KEY, ""), owner_scope=owner)


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
