"""Dashboard cache identity and display-only execution context."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real

import pandas as pd

from stock_lab_core.decision_engine import classify_decision_signal
from stock_lab_core.decision_workflow import attach_market_execution_context
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, apply_execution_gate_columns,
)
from stock_lab_core.formatters import sanitize_ticker_value
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.today_enrichment import attach_today_analyst_context, build_today_analyst_upside_map
from stock_lab_core.today_queue import build_today_queue_signature

register_loaded_source(__name__, __file__)

_HOLDING_INPUTS = (
    "티커", "자산명", "보유량", "매입가", "목표비중",
    "bucket", "asset_class", "is_etf",
)
_PRIMARY_COLUMNS = ("종목명", "티커", "게이트상태", "게이트근거", "데이터상태", "가격자료기준일", "가격반영")
_DETAIL_COLUMNS = (
    "시장", "유형", "종목명", "티커", "현재가", "현재비중", "목표비중", "MDD",
    "후보품질", "후보점수", "후보검토사항", "횡보품질", "📌후보등급", "재무점수",
    "재무자료상태", "재무자료기간", "재무계산시각",
    "RS", "시장벤치", "기초자산", "기초벤치", "섹터RS", "섹터벤치", "섹터RS기준일",
    "RSI", "MFI", "볼린저 %B", "🔥기술적 타점", "패턴타점", "패턴근거", "핵심근거",
    "판정코드", "판정분류", "원천최종읽기", "최종읽기", "Adj점수",
    "시장실행상태", "돈흐름_판정", "애널목표가표시", "애널목표Upside", "애널목표상태",
    "애널목표사유", "애널목표출처", "애널목표기준일", "수급기준",
    "지표마지막봉", "수급자료기준", "자료주의", "계산시각",
)


def _stable(value):
    if isinstance(value, Mapping):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if value is None or isinstance(value, (str, bool)):
        return value
    return None if pd.isna(value) else str(value)


def build_dashboard_signature(items, mode, *, fin_score_map, holdings, account_inputs, owner, logic_version):
    """Sign user inputs; live valuations are labelled calculation-time snapshots."""
    ordered = sorted(items, key=lambda item: sanitize_ticker_value(item.get("ticker", "")))
    holding_rows = []
    if isinstance(holdings, pd.DataFrame):
        columns = [column for column in _HOLDING_INPUTS if column in holdings]
        holding_rows = holdings[columns].to_dict("records")
    holding_rows = sorted((_stable(row) for row in holding_rows), key=lambda row: json.dumps(row, sort_keys=True))
    payload = {
        "schema": 1,
        "items": build_today_queue_signature(ordered, mode, logic_version=logic_version),
        "fin_score_map": fin_score_map,
        "holdings": holding_rows,
        "account": account_inputs,
        "owner": owner,
    }
    encoded = json.dumps(_stable(payload), ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dashboard_cache_matches(frame, stored_signature, current_signature):
    return isinstance(frame, pd.DataFrame) and not frame.empty and stored_signature == current_signature


def cached_dashboard_analyst_loader(frames, *, now):
    """Reuse observed snapshots only; never warm a provider cache during display."""
    snapshots = {}
    for frame in frames:
        if not isinstance(frame, pd.DataFrame):
            continue
        saved = frame.attrs.get("today_analyst_snapshots", {})
        if not isinstance(saved, Mapping):
            continue
        for ticker, snapshot in saved.items():
            if not isinstance(snapshot, Mapping) or snapshot.get("ok") is not True or snapshot.get("stale"):
                continue
            try:
                stamp = datetime.fromisoformat(str(snapshot.get("fetched_at", "")).replace("Z", "+00:00"))
                if stamp.tzinfo is None or not 0 <= (now - stamp).total_seconds() < 21600:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            key = sanitize_ticker_value(ticker)
            previous = snapshots.get(key)
            if previous is None or stamp > previous[0]:
                snapshots[key] = (stamp, deepcopy(dict(snapshot)))

    def load(ticker):
        entry = snapshots.get(sanitize_ticker_value(ticker))
        if entry:
            return deepcopy(entry[1])
        return {"ok": False, "status": "lookup_error", "data": {},
                "source": "표시용 캐시 미확인", "reason": "최신 애널리스트 캐시 미확보 · 추가 조회 안 함"}

    return load


def prepare_dashboard_display(raw, *, snapshot, flow_shortlist, market_guard,
                              attach_flow_context, get_analyst_snapshot, load_latest_price):
    """Use the existing precision/Today context pipeline without caching its output."""
    out = raw.copy(deep=True)
    out.attrs = deepcopy(raw.attrs)
    if out.empty:
        return out
    out = attach_flow_context(out, flow_shortlist, snapshot=snapshot)
    out = attach_market_execution_context(out, market_guard)
    out = attach_today_analyst_context(
        out, get_analyst_snapshot=get_analyst_snapshot, load_latest_price=load_latest_price,
    )
    return apply_execution_gate_columns(out, upside_value_map=build_today_analyst_upside_map(out))


def _column(frame, name):
    return frame.get(name, pd.Series("", index=frame.index)).fillna("").astype(str)


def dashboard_tables(frame, group_label):
    """Build compact routing and separate raw diagnostics; never invent a source date."""
    view = frame.copy(deep=True)
    if group_label != "전체":
        view = view.loc[_column(view, "전광판그룹").eq(group_label)].copy()
    signals = (_column(view, "판정분류") if "판정분류" in view
               else _column(view, "🔥기술적 타점").map(classify_decision_signal))
    gates = _column(view, "게이트상태")
    counts = {
        "표시 종목": len(view),
        "원시 후보 신호": int(signals.eq("buyish").sum()),
        "실행가능": int(gates.eq(GATE_EXECUTABLE).sum()),
        "방어·데이터확인": int(gates.isin([GATE_DEFENSE, GATE_DATA_CHECK]).sum()),
    }
    primary = view.reindex(columns=_PRIMARY_COLUMNS).copy()
    for column in ("가격자료기준일", "가격반영"):
        values = _column(view, column).str.strip()
        primary[column] = values.mask(values.str.lower().isin({"", "-", "nan", "none", "nat"}), "미확인")
    primary["게이트상태"] = primary["게이트상태"].fillna(GATE_DATA_CHECK).replace("", GATE_DATA_CHECK)
    primary["게이트근거"] = primary["게이트근거"].fillna("실행 맥락 미확인").replace("", "실행 맥락 미확인")
    primary["데이터상태"] = primary["데이터상태"].fillna("미확인").replace("", "미확인")
    detail = view[[column for column in _DETAIL_COLUMNS if column in view]].copy()
    detail = detail.rename(columns={"현재비중": "계산 당시 비중", "목표비중": "계산 당시 목표비중"})
    return primary, detail, counts


def render_dashboard_group_summary(st, frame, group_label):
    primary, detail, counts = dashboard_tables(frame, group_label)
    if primary.empty:
        st.info(f"{group_label}에 표시할 종목이 없습니다.")
        return
    for column, (label, value) in zip(st.columns(len(counts)), counts.items()):
        column.metric(label, f"{value}개")
    st.dataframe(primary, width="stretch", hide_index=True, height=min(520, 40 + 35 * len(primary)))
    with st.expander("후보품질·기술 신호 상세", expanded=False):
        st.dataframe(detail, width="stretch", hide_index=True, height=min(640, 40 + 35 * len(detail)))
