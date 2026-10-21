"""Observed holdings contributions, separate from proxy scenarios and closes."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, number, stamp, text

register_loaded_source(__name__, __file__)


def valid_live_observation(obs, market, now, *, states=None, extended=False):
    from stock_lab_core.report_session import market_session_states
    at = stamp(obs.get("as_of"))
    if number(obs.get("return")) is None or at is None or not obs.get("date"):
        return False
    if not 0 <= (now - at).total_seconds() <= (1200 if extended else 900):
        return False
    if extended:
        return True
    state = (states or market_session_states(now))[market]
    return state["phase"] == "intraday" and obs["date"] == state["active_date"]


def layered_market_headline(context, flow_rows, states, now, metrics):
    """Keep medium-term observations, two completed sessions and live prices apart."""
    from stock_lab_core.report_market_summary import _flow_evidence, _market_fact
    medium, _ = _flow_evidence(context, flow_rows)
    prices, sessions = context.get("prices", {}), context.get("sessions", {})
    recent = []
    for ticker, label, market in (("SOXX", "미국 반도체", "US"), ("^KS11", "코스피", "KR")):
        obs = prices.get(ticker, {})
        change, prior = number(obs.get("return")), number(obs.get("previous_return"))
        if change is None or obs.get("date") != sessions.get(market):
            recent.append(label + " 종가 미연결")
            continue
        two_days = f"최근 2거래일 {(1 + change) * (1 + prior) * 100 - 100:+.2f}%, " if prior is not None else "최근 2거래일 미연결, "
        recent.append(f"{label} {two_days}최신 일간 {change * 100:+.2f}%({obs['date']} 종가)")
    kr = _market_fact(context, "KR", states, now)["phrase"]
    if number(context.get("intraday_prices", {}).get("^KS11", {}).get("return")) is None:
        kr = "코스피 지수 장중 시세 미연결(보유 ETF와 별도)"
    return ("[중기] " + medium + " · [최근 2거래일] " + " / ".join(recent)
            + " · [장중] " + kr + " / " + intraday_account_line(metrics, compact=True))


def intraday_account_metrics(held, live, extended=None, *, states=None, now=None):
    groups = {key: {"contribution": None, "coverage": 0.0, "count": 0} for key in ("KR", "US", "US_EXT")}
    seen, times, missing = set(), [], []
    total_weight = 0.0
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        weight = number(first(row, "현재비중", "current_w"))
        if not ticker or ticker in seen or weight is None or not 0 <= weight <= 100:
            return {"error": "중복 종목 또는 비중 결측·범위 오류"}
        seen.add(ticker)
        total_weight += weight
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        group, obs = region, live.get(ticker, {})
        if region == "US" and (not states or states["US"]["phase"] != "intraday"):
            if (extended or {}).get(ticker):
                group, obs = "US_EXT", extended[ticker]
        move = number(obs.get("return"))
        at = stamp(obs.get("as_of"))
        valid = move is not None and at is not None and bool(obs.get("date"))
        if states and group != "US_EXT":
            valid = valid and states[region]["phase"] == "intraday" and obs["date"] == states[region]["active_date"]
        if now:
            valid = valid and valid_live_observation(obs, region, now, states=states, extended=group == "US_EXT")
        if not valid:
            missing.append(ticker)
            continue
        item = groups[group]
        item["contribution"] = (item["contribution"] or 0.0) + weight * move
        item["coverage"] += weight
        item["count"] += 1
        times.append(at)
    if total_weight > 100.01:
        return {"error": "현재비중 합계가 100% 초과"}
    coverage = sum(item["coverage"] for item in groups.values())
    total = sum(item["contribution"] or 0 for item in groups.values()) if coverage else None
    return {"groups": groups, "coverage": coverage, "total": total, "missing": missing,
            "earliest": min(times).isoformat() if times else "", "latest": max(times).isoformat() if times else ""}


def intraday_account_line(metrics, *, compact=False):
    from stock_lab_core.report_presentation import kst_time
    if metrics.get("error"):
        return "장중 계좌 추정 보류: " + metrics["error"]
    if metrics.get("total") is None:
        return "장중 계좌 추정 미연결: 보유 종목의 해당 세션 시세 없음(0%가 아님)"
    main = (f"장중 계좌 영향 추정 {metrics['total']:+.2f}%p" if metrics["coverage"] >= 90
            else f"장중 연결분 기여 {metrics['total']:+.2f}%p · 전체 계좌 추정 보류(연결 90% 미만)")
    main += f"(연결 비중 {metrics['coverage']:.1f}%, 확정 아님)"
    if compact:
        return main
    parts = []
    for key, name in (("KR", "한국 상장"), ("US", "미국 정규장"), ("US_EXT", "미국 데이마켓·시간외")):
        group = metrics["groups"][key]
        if key == "US" and not group["count"]:
            continue
        parts.append(f"{name} {group['contribution']:+.2f}%p(비중 {group['coverage']:.1f}%)"
                     if group["count"] else name + " 미연결")
    earliest, latest = kst_time(metrics["earliest"]), kst_time(metrics["latest"])
    time_range = earliest if earliest == latest else earliest + "~" + latest
    return (main + " · " + " / ".join(parts) + f". 시세 {time_range} · "
            "각 시장 직전 정규장 종가 대비, 비동시·현재비중 가중 추정이며 환율·거래 미반영. "
            "데이마켓은 거래가 얇고 증권사·거래장소별 가격 차이가 클 수 있습니다.")
