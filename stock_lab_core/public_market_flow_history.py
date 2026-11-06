"""Report-only investor history from already collected public snapshots.

The optional context key public_market_flow_history is a list of unmodified
load_public_market_evidence results (flows plus checked_at), not OHLCV frames
or report decision rows. No transport, persistence, or decision gates live here.
"""

from copy import deepcopy
from datetime import timedelta
from functools import lru_cache

from stock_lab_core.public_market_data import (
    FLOW_SOURCE, INDICATORS_URL, MARKETS, _day, _integer, _timestamp,
    observation_reason, validated_investor_flows,
)
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_eventstudy import _exchange_schedule

register_loaded_source(__name__, __file__)

MAX_SNAPSHOTS = 128
HISTORY_DAYS = 120
SNAPSHOT_FIELDS = (
    "ok", "status", "reason", "source", "source_url", "data_url", "fetched_at",
    "asof", "unit", "is_mock", "market", "exchange", "raw_unit", "raw_value",
    "value", "date_basis", "provisional", "limitation", "http_status",
)


def _raw_value(obs, market, checked_at):
    if (observation_reason(obs, checked_at) or obs.get("market") != market
            or obs.get("exchange") != "KRX" or obs.get("unit") != "억원"
            or obs.get("raw_unit") != "KRW" or obs.get("source_url") != FLOW_SOURCE
            or obs.get("data_url") != INDICATORS_URL
            or obs.get("date_basis") != "investorTrendBaseDate"
            or obs.get("provisional") is not True):
        return None
    raw = _integer(obs.get("raw_value"))
    value = obs.get("value")
    return raw if raw is not None and not isinstance(value, bool) and value == raw / 100_000_000 else None


@lru_cache(maxsize=128)
def _session_closes(day):
    start = (day - timedelta(days=HISTORY_DAYS)).isoformat()
    frame = _exchange_schedule("KR", start, day.isoformat())
    closes = {at.date().isoformat(): _timestamp(close.isoformat())
              for at, close in frame["market_close"].items()}
    if (not closes or day.isoformat() not in closes or None in closes.values()
            or len(closes) != len(frame)):
        raise ValueError("invalid_calendar")
    return closes


def validated_flow_snapshot(evidence, *, checked_at):
    """Project verified post-close observations for the existing report store.

    The caller supplies the collection clock for new evidence, or the original
    clock when revalidating an archive. Never store credentials, extra provider
    payload fields, OHLCV, or a current intraday observation as daily history.
    """
    if not isinstance(evidence, dict):
        return None
    original, cutoff = _timestamp(evidence.get("checked_at")), _timestamp(checked_at)
    flows = evidence.get("flows")
    if original is None or cutoff is None or original > cutoff or not isinstance(flows, dict):
        return None
    accepted, calendars = {}, {}
    for market in MARKETS:
        group = flows.get(market)
        if not isinstance(group, dict):
            continue
        for identity in ("foreign", "institution", "individual"):
            obs = group.get(identity)
            if (_raw_value(obs, market, checked_at) is None
                    or _raw_value(obs, market, evidence["checked_at"]) is None):
                continue
            day = obs["asof"]
            if day not in calendars:
                try:
                    calendars[day] = _session_closes(_day(day)).get(day)
                except Exception:
                    calendars[day] = None
            close = calendars[day]
            if close is None or _timestamp(obs["fetched_at"]) < close:
                continue
            accepted.setdefault(market, {})[identity] = {
                key: deepcopy(obs[key]) for key in SNAPSHOT_FIELDS if key in obs}
    return {"flows": accepted, "checked_at": evidence["checked_at"]} if accepted else None


def saved_public_flow_history(snapshots, *, checked_at):
    """Read at most 128 existing snapshots, without fetching or writing data."""
    cutoff = _timestamp(checked_at)
    if cutoff is None:
        return []
    candidates = [(at, snapshot) for snapshot in snapshots if isinstance(snapshot, dict)
                  if (at := _timestamp(snapshot.get("checked_at"))) is not None and at <= cutoff]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [validated for _, snapshot in candidates[:MAX_SNAPSHOTS]
            if (validated := validated_flow_snapshot(snapshot, checked_at=snapshot["checked_at"]))]


def summarize_daily_values(values, days):
    """Exact-session sums and bounded runs; shared by snapshots and daily backfill."""
    result = dict(sum_5=None, sum_20=None, streak_days=None, streak_direction="", missing_dates={})
    for window in (5, 20):
        selected = days[-window:]
        missing = [d for d in selected if values[d] is None]
        result["missing_dates"][str(window)] = missing
        if len(selected) == window and not missing:
            result[f"sum_{window}"] = sum(values[d] for d in selected) / 100_000_000
    latest = values[days[-1]]
    if latest == 0:
        result.update(streak_days=0, streak_direction="neutral")
    elif latest is not None:
        result["streak_direction"] = "buy" if latest > 0 else "sell"
        count = 0
        for d in reversed(days):
            value = values[d]
            if value is None:
                break
            if value == 0 or (value > 0) != (latest > 0):
                result["streak_days"] = count
                break
            count += 1
    return result


def summarize_public_flow_history(evidence, history, *, session_date, checked_at):
    """5/20 XKRX-session sums and exact trailing sign runs, all provisional.

    Preserve the current snapshot's existing freshness/same-session gate. Old
    snapshots are validated against their own collection clock, but must have
    been collected after that session closed and before this report's clock.
    Duplicate dates use the newest observation; conflicting equal-time copies
    are missing. A missing session is never skipped or replaced with zero.
    Runs require a preceding zero/opposite sign, otherwise their length is not
    known. A current zero explicitly ends both runs. Work is bounded; oversized
    history is rejected, not silently truncated to a plausible result.
    """
    current = validated_investor_flows(evidence, session_date=session_date, checked_at=checked_at)
    result = [dict(row, sum_5=None, sum_20=None, streak_days=None, streak_direction="",
                   history_reason="insufficient_history", missing_dates={}) for row in current]
    if not result:
        return result
    day, checked = _day(session_date), _timestamp(checked_at)
    try:
        closes = _session_closes(day)
    except Exception:
        # Missing dependency/coverage must not fall back to Monday-Friday dates.
        for row in result:
            row["history_reason"] = "calendar_unavailable"
        return result
    days = sorted(closes)
    if history is None:
        history = []
    if not isinstance(history, (list, tuple)) or len(history) > MAX_SNAPSHOTS:
        for row in result:
            row["history_reason"] = "invalid_or_oversized_history"
        return result

    series = {}
    for snapshot in history:
        if not isinstance(snapshot, dict):
            continue
        clock = _timestamp(snapshot.get("checked_at"))
        flows = snapshot.get("flows")
        if clock is None or clock > checked or not isinstance(flows, dict):
            continue
        for row in current:
            market, identity = row["market"], row["identity"]
            group = flows.get(market)
            obs = group.get(identity) if isinstance(group, dict) else None
            if not isinstance(obs, dict):
                continue
            observed_day = obs.get("asof")
            if not isinstance(observed_day, str) or observed_day not in closes or observed_day >= session_date:
                continue
            fetched = _timestamp(obs.get("fetched_at"))
            if fetched is None or fetched > clock or fetched < closes[observed_day]:
                continue
            raw = _raw_value(obs, market, snapshot["checked_at"])
            key = (market, identity, observed_day)
            previous = series.get(key)
            if previous is None or fetched > previous[0]:
                series[key] = (fetched, raw)
            elif fetched == previous[0] and raw != previous[1]:
                series[key] = (fetched, None)

    for row in result:
        market, identity = row["market"], row["identity"]
        values = {d: series.get((market, identity, d), (None, None))[1] for d in days}
        values[session_date] = _raw_value(row, market, checked_at)
        row.update(summarize_daily_values(values, days))
        if all(row[key] is not None for key in ("sum_5", "sum_20", "streak_days")):
            row["history_reason"] = "available"
    return result


def public_flow_history_lines(context, *, session_date):
    """Append a supplemental table; missing history never hides today's flow."""
    if "public_flow_backfill" in context:
        from stock_lab_core.public_flow_backfill import backfill_lines
        return backfill_lines(context["public_flow_backfill"], checked_at=context.get("market_evidence_checked_at"))
    rows = summarize_public_flow_history(
        context.get("public_market_evidence"), context.get("public_market_flow_history"),
        session_date=session_date, checked_at=context.get("market_evidence_checked_at"))
    if not rows:
        return []
    if all(row[key] is None for row in rows for key in ("sum_5", "sum_20", "streak_days")):
        reason = "거래소 달력 미확보·" if any(row["history_reason"] == "calendar_unavailable" for row in rows) else ""
        return ["", "한국 투자자 수급 이력 부족: " + reason + "5·20거래일 합계·연속일수 미확인."]
    lines = ["", "**한국 투자자 수급 이력 · 억원(잠정)**",
             "시장 | 투자자 | 연속 순매수·순매도 | 5거래일 합계 | 20거래일 합계 | 기준일",
             "--- | --- | --- | --- | --- | ---"]
    for row in rows:
        count = row["streak_days"]
        streak = ("자료 부족" if count is None else "중립(0일)" if count == 0 else
                  ("순매수" if row["streak_direction"] == "buy" else "순매도") + f" {count}거래일")
        amounts = ["자료 부족" if row[key] is None else f"{row[key]:+,.2f}" for key in ("sum_5", "sum_20")]
        lines.append(" | ".join((row["market"], row["label"], streak, *amounts, row["asof"])))
    lines.append("XKRX 거래일 기준·기준일 포함·저장된 공개 스냅샷 사용·잠정/정정 가능. "
                 "과거 장중 자료는 제외하며 기준일 장중 수치는 포함될 수 있습니다. "
                 "누락 거래일·연속 구간 시작 미확인 시 자료 부족이며 0으로 보충하지 않습니다.")
    if any(row["history_reason"] == "calendar_unavailable" for row in rows):
        lines.append("거래소 달력 미확보: 거래일 합계·연속일수 자료 부족.")
    return lines
