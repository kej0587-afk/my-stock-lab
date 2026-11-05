"""Today Queue session and refresh orchestration; investment rules remain in app."""

from datetime import datetime, timedelta, timezone
import logging

import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

SUMMARY_KEY = "today_queue_summary_df"
SIGNATURE_KEY = "today_queue_summary_sig"
LAST_RUN_KEY = "today_queue_summary_last_run"
STALE_KEY = "today_queue_summary_stale_reason"
CLEARED_OWNERS_KEY = "_today_queue_cleared_owners"
RESULT_KEYS = (
    SUMMARY_KEY, SIGNATURE_KEY, LAST_RUN_KEY,
    "today_queue_summary_last_nonempty_df", "today_queue_summary_last_nonempty_sig",
    "portfolio_today_signal_df", STALE_KEY,
)


def clear_cached_summary(state, *, explicit=True):
    """Invalidate only computed results, preserving user inputs and owner scope."""
    for key in RESULT_KEYS:
        state.pop(key, None)
    if explicit:
        owners = set(state.get(CLEARED_OWNERS_KEY, ()))
        owners.add(state.get("today_queue_summary_owner", ""))
        state[CLEARED_OWNERS_KEY] = owners


def _stale_reason(state, frame, queue_sig):
    if frame.attrs.get(STALE_KEY):
        return frame.attrs[STALE_KEY]
    if state.get(SIGNATURE_KEY) != queue_sig:
        return "입력 변경 · 이전 계산 결과 · 재계산 필요"
    return ""


def _guard_cached_summary(state, frame, queue_sig):
    if frame.empty:
        return frame
    reason = _stale_reason(state, frame, queue_sig)
    if not reason:
        state.pop(STALE_KEY, None)
        return frame
    from stock_lab_core.execution_gate import GATE_DATA_CHECK

    frame = frame.copy(deep=True)
    state[STALE_KEY] = frame.attrs[STALE_KEY] = reason
    # The app re-applies execution gates after enrichment; data status survives it.
    if "저장당시데이터상태" not in frame.columns:
        frame["저장당시데이터상태"] = frame.get("데이터상태", "")
    frame["데이터상태"] = reason + " · " + frame["저장당시데이터상태"].fillna("").astype(str)
    for key in ("게이트상태", "게이트근거", "게이트근거ID"):
        saved_key = "저장당시" + key
        if saved_key not in frame.columns:
            frame[saved_key] = frame.get(key, "")
    frame["게이트상태"] = GATE_DATA_CHECK
    frame["게이트근거"] = reason
    frame["게이트근거ID"] = "data.snapshot"
    frame.attrs.pop("portfolio_signal_context", None)
    state.pop("portfolio_today_signal_df", None)
    return frame


def _repair_cached_ownership(state, frame, queue_sig):
    """Fill legacy ownership only from matching, current portfolio inputs."""
    holdings = state.get("_app_holdings_table")
    if (frame.empty or state.get(SIGNATURE_KEY) != queue_sig
            or not isinstance(holdings, pd.DataFrame) or holdings.empty):
        return frame
    from stock_lab_core.formatters import clean_float, finite_num
    from stock_lab_core.portfolio import get_holding_row_by_ticker

    out = frame.copy(deep=True)
    for index, row in out.iterrows():
        if any(finite_num(clean_float(row.get(key), float("nan")))
               for key in ("qty", "보유량", "보유수량")):
            continue
        held = get_holding_row_by_ticker(holdings, row.get("티커", row.get("ticker", "")))
        qty = clean_float(held.get("보유량"), float("nan")) if held is not None else float("nan")
        if finite_num(qty):
            out.loc[index, "qty"] = qty
            out.loc[index, "has_pos"] = qty > 0
    return out


def restore_cached_summary(state, snapshot_owner, queue_sig, *, load_today_queue_summary_snapshot):
    previous_owner = state.get("today_queue_summary_owner")
    if previous_owner is not None and previous_owner != snapshot_owner:
        clear_cached_summary(state, explicit=False)
    state["today_queue_summary_owner"] = snapshot_owner

    cached_summary = state.get(SUMMARY_KEY)
    if not isinstance(cached_summary, pd.DataFrame):
        cached_summary = pd.DataFrame()
    if cached_summary.empty:
        last_nonempty = state.get("today_queue_summary_last_nonempty_df")
        if isinstance(last_nonempty, pd.DataFrame) and not last_nonempty.empty:
            cached_summary = last_nonempty.copy()
            state[SIGNATURE_KEY] = state.get("today_queue_summary_last_nonempty_sig", "")
    if cached_summary.empty and snapshot_owner not in state.get(CLEARED_OWNERS_KEY, ()):
        disk_summary, disk_sig, disk_last_run = load_today_queue_summary_snapshot(
            owner_scope=snapshot_owner, expected_signature=None,
        )
        if isinstance(disk_summary, pd.DataFrame) and not disk_summary.empty:
            cached_summary = disk_summary.copy()
            state[SUMMARY_KEY] = cached_summary
            state[SIGNATURE_KEY] = disk_sig
            state[LAST_RUN_KEY] = disk_last_run
            state["today_queue_summary_last_nonempty_df"] = cached_summary.copy()
            state["today_queue_summary_last_nonempty_sig"] = disk_sig
    cached_summary = _repair_cached_ownership(state, cached_summary, queue_sig)
    cached_summary = _guard_cached_summary(state, cached_summary, queue_sig)
    if not cached_summary.empty:
        state[SUMMARY_KEY] = cached_summary
        state["today_queue_summary_last_nonempty_df"] = cached_summary.copy()
        state["today_queue_summary_last_nonempty_sig"] = state.get(SIGNATURE_KEY, "")
    return cached_summary


def remember_calculated_summary(state, summary_df, queue_sig, last_run_text):
    state.pop(STALE_KEY, None)
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        owners = set(state.get(CLEARED_OWNERS_KEY, ()))
        owners.discard(state.get("today_queue_summary_owner", ""))
        if owners:
            state[CLEARED_OWNERS_KEY] = owners
        else:
            state.pop(CLEARED_OWNERS_KEY, None)
    state[SUMMARY_KEY] = summary_df
    state[SIGNATURE_KEY] = queue_sig
    state[LAST_RUN_KEY] = last_run_text
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        state["today_queue_summary_last_nonempty_df"] = summary_df.copy()
        state["today_queue_summary_last_nonempty_sig"] = queue_sig


def finalize_summary(state, summary_df, queue_sig, run_summary, snapshot_owner, *,
                     dedupe_dashboard_summary_df, save_today_queue_summary_snapshot):
    summary_df = dedupe_dashboard_summary_df(summary_df)
    if not run_summary:
        summary_df = _guard_cached_summary(state, summary_df, queue_sig)
    state[SUMMARY_KEY] = summary_df
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
        state["today_queue_summary_last_nonempty_df"] = summary_df.copy()
        state["today_queue_summary_last_nonempty_sig"] = state.get(SIGNATURE_KEY, "")
        if run_summary and not summary_df.attrs.get(STALE_KEY):
            save_today_queue_summary_snapshot(
                summary_df, queue_sig, state.get(LAST_RUN_KEY, ""), owner_scope=snapshot_owner,
            )
    return summary_df


def refresh_today_summary(st, mode, raw_watch_items, refresh_flow_candidates, queue_logic_version, *,
        build_today_queue_items, refresh_today_market_flow_snapshot,
        build_today_queue_items_with_flow_candidates, build_today_queue_signature,
        calculate_fresh_summary, measure):
    # Begin with user-owned inputs: failed or skipped discovery cannot carry
    # old auto-candidates into a newly signed calculation.
    watch_items, flow_auto_items = build_today_queue_items(raw_watch_items), tuple()
    if refresh_flow_candidates:
        flow_progress = st.empty()
        try:
            with measure("phase", "flow_refresh"), st.spinner("돈흐름 전체 후보 계산 중"):
                flow_snapshot_for_queue = refresh_today_market_flow_snapshot(
                    include_theme=True, force_theme_refresh=True, progress=flow_progress.caption,
                )
            with measure("phase", "flow_candidates_after_refresh"):
                watch_items, flow_auto_items = build_today_queue_items_with_flow_candidates(raw_watch_items, flow_snapshot_for_queue)
            st.session_state["today_queue_open_flow_detail"] = True
        except Exception as exc:
            st.warning(f"돈흐름 전체 조회 실패. 보유·관심종목만 점검합니다: {type(exc).__name__}")
            logging.exception("Today queue money-flow discovery failed")
        finally:
            flow_progress.empty()
    else:
        st.info("보유·관심종목 점검 중 · 돈흐름 자동발굴은 이번 계산에서 제외")
    queue_sig = build_today_queue_signature(watch_items, mode, logic_version=queue_logic_version)
    st.session_state["today_queue_current_input_counts"] = {
        "registered": len(raw_watch_items), "calculated": len(watch_items),
        "auto_flow_candidates": len(flow_auto_items), "refresh_flow_candidates": bool(refresh_flow_candidates),
    }
    with st.spinner("관심/보유 종목 신호를 정리하는 중입니다..."):
        summary_df = calculate_fresh_summary(mode, watch_items, raw_watch_items, flow_auto_items)
    last_run_text = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    remember_calculated_summary(st.session_state, summary_df, queue_sig, last_run_text)
    return summary_df, watch_items, queue_sig
