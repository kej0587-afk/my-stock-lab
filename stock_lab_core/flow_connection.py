"""Connect existing ticker history without loading the entire radar universe."""

from collections.abc import Mapping
import math

import pandas as pd

from stock_lab_core.data_freshness import input_freshness_fields, session_date
from stock_lab_core.formatters import normalize_ticker, sanitize_ticker_value
from stock_lab_core.report_build import register_loaded_source


SOURCE_PATH = "종목 원자료 재사용"
RADAR_PATH = "레이더 원자료"
PREFIX = "돈흐름_"


def build_price_flow_row(frame, ticker, name=""):
    """Reuse the radar formula, not its universe ranking or external loaders."""
    row = {"Ticker": ticker, "종목명": name or ticker, "후보군": "종목 자체 흐름",
           "연결경로": SOURCE_PATH, "연결상태": "자료부족"}
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {**row, "연결사유": "종목 가격 이력 없음"}
    if not isinstance(frame.index, pd.DatetimeIndex) or isinstance(frame.columns, pd.MultiIndex):
        return {**row, "연결사유": "종목별 일봉 형식 확인 필요"}
    required = ("Close", "High", "Low")
    if not all(col in frame for col in required):
        return {**row, "연결사유": "종가·고가·저가 원자료 부족"}
    px = frame.loc[frame.index.notna(), [col for col in (*required, "Volume") if col in frame]].copy()
    px = px.loc[~px.index.duplicated(keep="last")].sort_index()
    # Match the radar's one-year history, including crypto's seven-day weeks.
    if not px.empty:
        px = px.loc[px.index > px.index[-1] - pd.DateOffset(years=1)]
    for col in px:
        px[col] = pd.to_numeric(px[col], errors="coerce").replace([math.inf, -math.inf], math.nan)
    valid = px[list(required)].notna().all(axis=1) & px[list(required)].gt(0).all(axis=1)
    px = px.loc[valid].copy()
    if "Volume" in px:
        px["Volume"] = px["Volume"].where(px["Volume"].ge(0))
        missing_sessions = set(frame.attrs.get("volume_missing_sessions") or [])
        px.loc[[day.strftime("%Y-%m-%d") in missing_sessions for day in px.index], "Volume"] = math.nan
    if len(px) < 20:
        return {**row, "연결사유": f"유효 일봉 {len(px)}개 · 최소 20봉 필요"}
    from stock_lab_core.money_flow import _compute_ticker_metrics

    metrics = _compute_ticker_metrics(px)
    missing = [label for key, label in (("1개월수익률", "1M"), ("3개월수익률", "3M"),
                                       ("6개월수익률", "6M"), ("거래량증가", "거래량 비교"))
               if not math.isfinite(float(metrics[key]))]
    return {**row, **metrics, "연결상태": "부분연결" if missing else "연결",
            "연결사유": "미산출: " + ", ".join(missing) if missing else "같은 종목 일봉 · 레이더 공통 계산식",
            "자료봉수": len(px)}


def _fields(row):
    return {key: value for key, value in row.items() if key.startswith(PREFIX)}


def _aligned(row, fields):
    volume_day = session_date(fields.get(PREFIX + "거래량기준일"))
    return bool(volume_day) and input_freshness_fields({**row, **fields}, reference={})["돈흐름신선도"] == "aligned"


def select_flow_fields(row, radar):
    """Prefer a same-session radar row, otherwise retain actual ticker evidence."""
    existing = _fields(row)
    incoming = _fields(radar)
    if incoming:
        incoming.setdefault(PREFIX + "연결경로", RADAR_PATH)
    if _aligned(row, incoming):
        chosen = incoming
    elif _aligned(row, existing):
        chosen = existing
    elif _has_veto(existing):
        chosen = existing
    else:
        # Keep invalid radar evidence visible; never silently turn a veto into a pass.
        chosen = incoming or existing
    result = dict(chosen)
    if incoming and chosen is existing:
        result[PREFIX + "레이더기준일"] = session_date(incoming.get(PREFIX + "기준일"))
        result[PREFIX + "레이더판정"] = incoming.get(PREFIX + "판정", "")
        result[PREFIX + "연결보완사유"] = (
            "레이더 기준일/거래량 불일치 · 종목 원자료 사용" if _aligned(row, existing)
            else "신규 레이더 기준일/거래량 불일치 · 기존 대기 근거 유지"
        )
    return result


def _has_veto(fields):
    from stock_lab_core.execution_gate import _RE_FLOW_WAIT, _RE_FLOW_WEAK

    text = str(fields.get(PREFIX + "판정", "")) + " " + str(fields.get(PREFIX + "후보군", ""))
    try:
        score = float(fields.get(PREFIX + "돈흐름점수"))
    except (TypeError, ValueError):
        score = math.nan
    return bool(_RE_FLOW_WAIT.search(text) or (score <= -10 and _RE_FLOW_WEAK.search(text)))


def merge_flow_context(summary, flow):
    """Row-wise merge preserves fallback evidence, order, index, and trace attrs."""
    by_key = {}
    for row in flow.to_dict("records"):
        by_key.setdefault(row.get("_검토키"), row)
    records = []
    for row in summary.to_dict("records"):
        key = row.get("_검토키", normalize_ticker(sanitize_ticker_value(row.get("티커", ""))))
        selected = select_flow_fields(row, by_key.get(key, {}))
        records.append({**{k: v for k, v in row.items() if not k.startswith(PREFIX)}, **selected})
    out = pd.DataFrame(records, index=summary.index)
    out.attrs = summary.attrs.copy()
    return out


def flow_connection_rows(workflow):
    row = workflow if isinstance(workflow, Mapping) else {}

    def number(key, *, percent=False):
        try:
            value = float(row.get(PREFIX + key))
        except (TypeError, ValueError):
            return "미수집"
        return (f"{value * 100:+.2f}%" if percent else f"{value:.1f}") if math.isfinite(value) else "미수집"

    return [{"연결경로": row.get(PREFIX + "연결경로") or "미연결",
             "기준일": row.get("돈흐름기준일") or row.get(PREFIX + "기준일") or "미확인",
             "흐름 판정": row.get(PREFIX + "판정") or "미확인",
             "1일": number("1일수익률", percent=True), "1M": number("1개월수익률", percent=True),
             "3M": number("3개월수익률", percent=True), "거래량 증감": number("거래량증가", percent=True),
             "자료상태": row.get(PREFIX + "연결사유") or row.get("돈흐름신선도근거") or "미연결"}]


register_loaded_source(__name__, __file__)
