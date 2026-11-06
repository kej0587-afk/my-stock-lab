"""Read account-scoped signal snapshots without re-scoring or fetching prices."""

import pandas as pd

from stock_lab_core.portfolio import portfolio_flow_ticker_key


DASHBOARD_SIGNAL_KEY = "portfolio_dashboard_signal_df"
SIGNAL_SOURCES = {
    "_ticker_signal_detail_df": "자산현황",
    "portfolio_today_signal_df": "오늘점검",
    DASHBOARD_SIGNAL_KEY: "전광판",
}
SIGNAL_KEYS = tuple(SIGNAL_SOURCES)
LEGACY_COLUMNS = [
    "티커", "기술적타점", "ADJ점수", "후보등급", "추세", "RS", "RSI", "MFI",
    "MACD", "SQZ", "판정코드", "실행메모", "핵심근거",
]


def capture_dashboard_signals(state, source, prepared, context):
    """Publish the displayed gate with its original calculation scope/time.

    A render is not a new calculation. Never re-stamp an unscoped cached frame
    with the current account, or splice a newer gate into an older source row.
    """
    if (
        not context
        or not isinstance(source, pd.DataFrame) or source.empty
        or not isinstance(prepared, pd.DataFrame) or prepared.empty
        or source.attrs.get("portfolio_signal_context") != context
        or pd.isna(pd.to_datetime(source.attrs.get("portfolio_signal_at"), utc=True, errors="coerce"))
        or not {"티커", "게이트상태"}.issubset(prepared.columns)
    ):
        state.pop(DASHBOARD_SIGNAL_KEY, None)
        return False
    result = prepared.copy(deep=True)
    result.attrs["portfolio_signal_context"] = context
    result.attrs["portfolio_signal_at"] = source.attrs["portfolio_signal_at"]
    state[DASHBOARD_SIGNAL_KEY] = result
    return True


def select_portfolio_signals(state, context, *, detailed=False):
    candidates = []
    for key in SIGNAL_KEYS:
        frame = state.get(key)
        if not isinstance(frame, pd.DataFrame) or frame.empty or "티커" not in frame:
            continue
        if frame.attrs.get("portfolio_signal_context") != context:
            continue
        work = frame.copy()
        for src, dst in {"🔥기술적 타점": "기술적타점", "📌후보등급": "후보등급", "RR값": "R/R"}.items():
            if src in work and dst not in work:
                work[dst] = work[src]
        cols = [col for col in LEGACY_COLUMNS if col in work]
        if len(cols) <= 1:
            continue
        if not detailed:
            work = work[cols].copy()
        work["_signal_at"] = pd.to_datetime(frame.attrs.get("portfolio_signal_at"), utc=True, errors="coerce")
        work["_signal_key"] = work["티커"].map(portfolio_flow_ticker_key)
        if detailed:
            work["연결출처"] = SIGNAL_SOURCES[key]
            work["저장시각"] = frame.attrs.get("portfolio_signal_at") or "미확인"
        work.attrs = {}
        candidates.append(work)
    if not candidates:
        return pd.DataFrame()
    merged = pd.concat(candidates, ignore_index=True).sort_values("_signal_at", na_position="first", kind="stable")
    merged = merged[merged["_signal_key"].ne("")].drop_duplicates("_signal_key", keep="last")
    return merged.drop(columns=["_signal_at", "_signal_key"]).reset_index(drop=True)


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
