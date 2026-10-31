"""Observe input dates without inventing provider timestamps or new scores."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
import re

import pandas as pd

from stock_lab_core.report_build import register_loaded_source


VERSION = "input-dates-v1"
PRICE_BLOCK_STATES = {"stale", "future", "unknown"}
FLOW_INVALID_STATES = {"older", "newer", "unknown", "conflict", "volume_lag"}


def session_date(value):
    """Daily candle labels are session dates, not instants to convert to KST."""
    if isinstance(value, (datetime, date, pd.Timestamp)) and pd.notna(value):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", value.strip()):
        try:
            return date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            pass
    return ""


def session_reference(ticker, now=None):
    """Cached local exchange schedules; no quote/network calls or weekday guesses."""
    from stock_lab_core.report_eventstudy import _exchange_schedule
    ticker = str(ticker).strip().upper()
    clock = pd.Timestamp(now if now is not None else datetime.now(timezone.utc))
    if clock.tzinfo is None:
        raise ValueError("freshness clock must include a timezone")
    clock = clock.tz_convert("UTC")
    if ticker in {"BTC-USD", "ETH-USD"}:
        return {"completed": (clock - pd.Timedelta(days=1)).date().isoformat(),
                "active": clock.date().isoformat(), "source": "UTC 일봉 · 24시간 거래"}
    if ticker in {"^KS11", "^KQ11", "KS11", "KQ11"} or (
        re.fullmatch(r"[A-Z0-9]{6}(?:\.KS|\.KQ)?", ticker) and any(c.isdigit() for c in ticker)
    ):
        market = "KR"
    elif ticker in {"^GSPC", "^IXIC", "^DJI", "^SOX", "^RUT", "^NDX", "BRK.B", "BRK.A"} or re.fullmatch(r"[A-Z][A-Z0-9-]*", ticker):
        market = "US"
    else:
        return {"completed": "", "active": "", "source": "거래소 달력 미연결", "unsupported": True}
    try:
        schedule = _exchange_schedule(market, (clock-pd.Timedelta(days=14)).date().isoformat(), clock.date().isoformat())
        opens = pd.to_datetime(schedule.market_open, utc=True)
        closes = pd.to_datetime(schedule.market_close, utc=True)
        completed = schedule.loc[closes <= clock]
        active = schedule.loc[(opens <= clock) & (clock < closes)]
        return {"completed": session_date(completed.index[-1]) if not completed.empty else "",
                "active": session_date(active.index[-1]) if not active.empty else "",
                "source": str(schedule.attrs.get("source") or "거래소 달력")}
    except (ImportError, KeyError, ValueError, OSError):
        return {"completed": "", "active": "", "source": "거래소 달력 조회불가"}


def input_freshness_fields(row, *, reference):
    """Preserve all raw inputs; flag source dates, not calculation/cache times."""
    row = row if isinstance(row, Mapping) else row.to_dict()
    price = session_date(row.get("가격자료기준일"))
    expected, active = reference.get("completed", ""), reference.get("active", "")
    if not price:
        state, note = "unknown", "가격 원자료 기준일 미확인"
    elif not expected:
        state = "unsupported" if reference.get("unsupported") else "unknown"
        note = reference.get("source", "거래소 달력 조회불가")
    elif price < expected:
        state, note = "stale", f"원자료 {price} · 최근 확정 종가 {expected}"
    elif price == expected:
        state, note = "current", "최근 확정 거래일까지 수집"
    elif price == active:
        state, note = "in_progress", "정규장/UTC 일봉 진행 중 · 확정 종가 아님"
    else:
        state, note = "future", f"가격 기준일 {price}의 거래 세션 확인 필요"
    # A quote-only overlay must not relabel yesterday's volume as today's.
    flow_dates = {session_date(row.get(key)) for key in (
        "돈흐름_기준일", "돈흐름_source_asof", "돈흐름_가격자료기준일", "돈흐름_자료기준일",
    )} - {""}
    has_flow = any(isinstance(row.get(key), str) and row[key].strip() not in {"", "-", "nan"}
                   for key in ("돈흐름_Ticker", "돈흐름_판정", "돈흐름_후보군"))
    if not has_flow and not flow_dates:
        flow_state, flow_note, flow_day = "not_connected", "종목별 돈흐름 미연결", ""
    elif len(flow_dates) > 1:
        flow_state, flow_note, flow_day = "conflict", "돈흐름 원자료 날짜 간 불일치", " / ".join(sorted(flow_dates))
    else:
        flow_day = next(iter(flow_dates), "")
        if not price or not flow_day:
            flow_state, flow_note = "unknown", "가격/돈흐름 기준일 미확인"
        elif flow_day == price:
            flow_state, flow_note = "aligned", "가격 원자료와 같은 기준일"
        elif flow_day < price:
            flow_state, flow_note = "older", f"돈흐름 {flow_day} · 가격 원자료 {price}"
        else:
            flow_state, flow_note = "newer", f"돈흐름 {flow_day} · 가격 원자료 {price}"
    volume_day = session_date(row.get("돈흐름_거래량기준일"))
    if flow_state == "aligned" and "돈흐름_거래량기준일" in row and volume_day != flow_day:
        flow_state, flow_note = "volume_lag", f"돈흐름 가격 {flow_day} · 거래량 {volume_day or '미확인'}"
    return {
        "자료신선도버전": VERSION, "가격신선도": state, "가격신선도근거": note,
        "최근확정종가일": expected, "진행중세션": active,
        "가격신선도검증대상": "가격자료기준일" in row,
        "돈흐름신선도": flow_state, "돈흐름기준일": flow_day, "돈흐름신선도근거": flow_note,
        "돈흐름거래량기준일": volume_day,
        "돈흐름사용범위": "같은 기준일 참고" if flow_state == "aligned" else
        "미연결" if flow_state == "not_connected" else "참고 전용 · 실행근거 제외",
    }


def attach_input_freshness(frame, *, now=None):
    out = frame.copy()
    if out.empty:
        return out
    clock = now if now is not None else datetime.now(timezone.utc)
    references = {}
    records = []
    for row in out.to_dict("records"):
        ticker = str(row.get("티커") or "")
        if ticker not in references:
            references[ticker] = session_reference(ticker, clock) if "가격자료기준일" in row else {}
        records.append(input_freshness_fields(row, reference=references[ticker]))
    fields = pd.DataFrame(records, index=out.index)
    for col in fields:
        out[col] = fields[col]
    out.attrs = frame.attrs.copy()
    return out


def input_freshness_rows(workflow):
    row = workflow if isinstance(workflow, Mapping) else {}
    return [
        {"자료": "가격·지표 원자료", "기준일/기간": row.get("가격자료기준일") or "미확인",
         "상태": row.get("가격신선도근거") or "미확인", "비교기준": row.get("최근확정종가일") or "달력 미확인"},
        {"자료": "돈흐름", "기준일/기간": row.get("돈흐름기준일") or "미확인",
         "상태": row.get("돈흐름신선도근거") or "미연결", "비교기준": row.get("돈흐름사용범위") or "같은 종목 가격 원자료"},
        {"자료": "저장 재무", "기준일/기간": row.get("재무자료기간") or "보고기간 미저장",
         "상태": row.get("재무자료상태") or "최신 발표 반영 미확인", "비교기준": "재무 계산 " + str(row.get("재무계산시각") or "시각 미저장")},
    ]


register_loaded_source(__name__, __file__)
