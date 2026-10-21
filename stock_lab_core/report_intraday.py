"""Observed holdings contributions, separate from proxy scenarios and closes."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, number, records, stamp, text

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


def layered_market_headline(context, flow_rows, states, now, metrics, *, synthesis=None):
    """Keep medium-term observations, two completed sessions and live prices apart."""
    from stock_lab_core.report_market_summary import _market_fact
    from stock_lab_core.report_presentation import kst_time
    prices, sessions = context.get("prices", {}), context.get("sessions", {})
    source = records(context.get("closed_flow_rows")) + records(context.get("sector_rows")) + records(flow_rows)
    medium, moves = [], []
    for symbols, label in ((("SMH", "SOXX"), "반도체"), (("IGV",), "소프트웨어")):
        selected = next((r for symbol in symbols for r in source
                         if text(first(r, "Ticker", "티커")) == symbol
                         and text(first(r, "기준일", "date")) == sessions.get("US")
                         and number(first(r, "3개월수익률", "3M")) is not None), None)
        if selected is None:
            medium.append(label + " 중기 자료 미연결")
            continue
        move = number(first(selected, "3개월수익률", "3M"))
        moves.append(move)
        medium.append(f"{label}({first(selected, 'Ticker', '티커')})는 3M {move * 100:+.2f}%로 "
                      + ("하락권" if move < 0 else "상승권" if move > 0 else "보합권"))
    medium_read = ("업종 흐름이 갈려 시장 전체의 동반 강세로 보기는 어렵습니다."
                   if len(moves) == 2 and min(moves) < 0 < max(moves) else
                   "중기 가격 방향이며 오늘 장중 반등과는 별도입니다.")
    recent = []
    for ticker, label, market in (("SOXX", "미국 반도체", "US"), ("^KS11", "코스피", "KR")):
        obs = prices.get(ticker, {})
        change, prior = number(obs.get("return")), number(obs.get("previous_return"))
        if change is None or obs.get("date") != sessions.get(market):
            recent.append(label + " 종가 미연결")
            continue
        two = (1 + change) * (1 + prior) - 1 if prior is not None else None
        reading = ("반등 뒤 하루 되돌림" if two is not None and two > 0 and change < 0 else
                   "최근 하락 뒤 하루 반등" if two is not None and two < 0 and change > 0 else
                   "최근 하락 누적" if two is not None and two < 0 else
                   "최근 상승 누적" if two is not None and two > 0 else "방향 판단 보류")
        two_days = f"2거래일 {two * 100:+.2f}%, " if two is not None else "2거래일 미연결, "
        recent.append(f"{label}는 {reading}({two_days}최신 {change * 100:+.2f}%, {obs['date']} 종가)")
    kr = _market_fact(context, "KR", states, now)["phrase"]
    if number(context.get("intraday_prices", {}).get("^KS11", {}).get("return")) is None:
        kr = "코스피 지수 장중 시세 미연결(보유 ETF와 별도)"
    semis = []
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    for ticker, label in (("396500.KS", "한국 반도체"), ("0167A0.KS", "SOL AI반도체")):
        obs = context.get("intraday_prices", {}).get(ticker, {})
        if valid_live_observation(obs, "KR", checked, states=states):
            semis.append(f"{label} {obs['return'] * 100:+.2f}%({kst_time(obs['as_of'])})")
    current = context.get("intraday_prices", {}).get("^KS11", {})
    prior_kr = number(prices.get("^KS11", {}).get("return"))
    rebound = (number(current.get("return")) or 0) > 0 and prior_kr is not None and prior_kr < 0
    inference = ("직전 하락 이후 반등이지만, 장중 반등만으로 중기 추세 회복을 확정할 수 없습니다."
                 if rebound else "장중 방향은 미확정이며 확정 종가·중기 흐름과 구분합니다.")
    # Only reuse same-market/session background selected by the report synthesizer.
    kr_news = [r for r in (synthesis or {}).get("background_news", [])
               if r.get("market") == "KR" and r.get("session_date") == states["KR"].get("active_date")]
    if kr_news:
        topics = (synthesis or {}).get("market_claims", {}).get("KR", [])
        if topics:
            inference += " 보도상 배경은 " + "·".join(topics) + "(기사 주장, 출처는 아래 스토리)."
    return ("[중기] " + "; ".join(medium) + ". " + medium_read
            + "\n\n[최근 2거래일] " + "; ".join(recent) + "."
            + "\n\n[장중] " + kr + ("; " + " / ".join(semis) if semis else "")
            + ". " + inference + " " + intraday_account_line(metrics, compact=True)
            + ". 시장·종목 실행 게이트는 기존 판정을 유지합니다")


def intraday_account_metrics(held, live, extended=None, *, states=None, now=None):
    groups = {key: {"contribution": None, "coverage": 0.0, "count": 0} for key in ("KR", "US", "US_EXT")}
    seen, times, missing = set(), [], []
    total_weight = missing_weight = 0.0
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
            missing_weight += weight
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
    return {"groups": groups, "coverage": coverage, "total": total, "missing": missing, "missing_weight": missing_weight,
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


def missing_quote_sensitivity(metrics):
    weight, total = number(metrics.get("missing_weight")), number(metrics.get("total"))
    if not weight or total is None or metrics.get("error"):
        return ""
    shock = weight * .03
    return (f"미연결 비중 {weight:.1f}% 단순 민감도: 해당 자산이 모두 ±3% 움직인다고 가정하면 "
            f"계좌 영향 ±{shock:.2f}%p, 연결분 포함 {total - shock:+.2f}~{total + shock:+.2f}%p. "
            "연결분 가격 고정·환율/거래 제외 가정이며 예측 범위나 실제 장중 수익률이 아닙니다.")
