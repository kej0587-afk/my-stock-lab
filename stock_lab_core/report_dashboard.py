"""Compact report surfaces over the existing, timestamp-checked observations."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, text, stamp, _cell

register_loaded_source(__name__, __file__)

INDEX_BOARD = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500",
               "^IXIC": "나스닥종합", "^SOX": "필라델피아 반도체", "^DJI": "다우"}
COMMODITY_BOARD = {"GC=F": ("금 선물", "USD/트로이온스"),
                   "SI=F": ("은 선물", "USD/트로이온스"),
                   "HG=F": ("구리 선물", "USD/파운드")}


def _pct(value, unit="%"):
    value = number(value)
    return f"{round(value * 100, 2) or 0:+.2f}{unit}" if value is not None else "미연결"


def current_state_lines(context, states, now, metrics, *, summary_available=True):
    from stock_lab_core.report_intraday import _latest_observation, extended_day_comparison
    from stock_lab_core.report_session import us_extended_session
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    kr_parts = []
    for ticker in ("^KS11", "^KQ11"):
        group, obs = _latest_observation(ticker, "KR", context, states, checked)
        basis = ("장중" if group == "KR" else "종가") if obs else "미연결"
        kr_parts.append(f"{INDEX_BOARD[ticker]} {_pct(obs.get('return'))}"
                        + (f"({obs['date']} {basis})" if obs else ""))
    kr_parts.extend(_kr_risk_brief(context, states, checked))
    window = us_extended_session(now)
    closed_session = states["US"]["phase"] in {"holiday", "closed"} and not window
    phase = "정규장 장중" if states["US"]["phase"] == "intraday" else window.get("label", "정규장 외")
    us_parts = []
    for ticker in ("SOXX", "RAM"):
        group, obs = _latest_observation(ticker, "US", context, states, checked)
        if obs and group != "US_CLOSE":
            if group == "US_EXT":
                basis = extended_day_comparison(context, ticker, obs, checked)
                if basis.get("postmarket"):
                    us_parts.append(f"{ticker} 전일 종가 대비 {_pct(basis['return'])} / 마감 후 {_pct(basis['leg_return'])}")
                else:
                    us_parts.append(f"{ticker} {_pct(obs['return'])}(직전 종가 대비)")
            else:
                us_parts.append(f"{ticker} {_pct(obs['return'])}(직전 종가 대비)")
    futures = (context.get("scenario_observations") or {}).get("latest", {})
    for ticker in (() if closed_session else ("NQ=F", "ES=F")):
        obs = futures.get(ticker, {})
        if number(obs.get("return")) is not None:
            us_parts.append(f"{ticker} {_pct(obs['return'])}")
    # No stale closing return is advertised as a current overnight quote.
    us_line = " · ".join(us_parts) or "현재 시세 미연결(직전 종가는 아래 표)"
    us_label, us_note = f"미국 현재 · {phase}", " (미확정·지연 가능)"
    if closed_session:
        # No active venue window is not a failed live lookup. Reuse only dated,
        # validated closes; never promote weekend futures or old extended quotes.
        closes = []
        for ticker in ("^GSPC", "^IXIC", "^SOX"):
            group, obs = _latest_observation(ticker, "US", context, states, checked)
            if group == "US_CLOSE":
                closes.append(f"{INDEX_BOARD[ticker]} {_pct(obs['return'])}({obs['date']} 종가)")
        status = "휴장" if states["US"]["phase"] == "holiday" else "거래시간 외"
        us_label, us_note = f"미국 · {status} · 최근 확정 종가", ""
        us_line = " / ".join(closes) or "기준일이 확인된 종가 자료 미연결"
    coverage = number((metrics or {}).get("coverage")) or 0
    total = number((metrics or {}).get("total"))
    if not summary_available:
        from stock_lab_core.report_input_status import MISSING_ACCOUNT
        account = MISSING_ACCOUNT
    elif (metrics or {}).get("error") or total is None or coverage < 90:
        account = f"전체 추정 보류 · 연결 {coverage:.1f}% (90% 미만 또는 입력 확인 필요)"
    else:
        account = f"통합 누적 추정 {round(total, 2) or 0:+.2f}%p · 연결 {coverage:.1f}% · 확정 손익 아님"
        from stock_lab_core.report_account import cumulative_account_decomposition
        decomposition = cumulative_account_decomposition(metrics)
        if decomposition:
            account += " · " + decomposition
    return ["**한국 현재** · " + " / ".join(kr_parts),
            f"**{us_label}** · {us_line}{us_note}",
            "**계좌** · " + account]


def _kr_risk_brief(context, states, now):
    """Reuse dated evidence already collected; no extra network or gate changes."""
    from stock_lab_core.report_intraday import _latest_observation
    from stock_lab_core.public_market_data import validated_investor_flows
    from stock_lab_core.market_safeguards import safeguard_events
    day = (states["KR"].get("active_date") if states["KR"]["phase"] == "intraday"
           else context.get("sessions", {}).get("KR"))
    parts = []
    _, obs = _latest_observation("396500.KS", "KR", context, states, now)
    if obs and obs.get("date") == day:
        parts.append("한국 반도체 " + _pct(obs.get("return")))
    flows = validated_investor_flows(context.get("public_market_evidence"), session_date=day,
                                    checked_at=context.get("market_evidence_checked_at"))
    flow = [f"{r['label']} {r['value']:+,.0f}억" for r in flows
            if r["market"] == "KOSPI" and r["label"] in {"외국인", "기관"}]
    if flow:
        parts.append("KOSPI 잠정 순매수 " + "·".join(flow))
    events = safeguard_events(context.get("current_session_news", []) + context.get("session_news", []), now)
    events += context.get("safeguard_events", [])
    names = {"circuit_breaker": "서킷브레이커", "sidecar": "사이드카"}
    observed = sorted({r["market"] + " " + names[r["kind"]] for r in events
                       if r.get("date") == day and r.get("kind") in names})
    if observed:
        parts.append("발동 보도: " + "·".join(observed) + "(근거는 안전장치 표)")
    return parts


def market_board_lines(context, states, now):
    from stock_lab_core.report_intraday import _latest_observation
    from stock_lab_core.report_presentation import kst_time
    from stock_lab_core.report_prices import MACRO_SYMBOLS
    from stock_lab_core.report_energy_basis import REPORT_ONLY_DAILY
    lines = ["", "## 지수·매크로 한눈에", "대상 | 수준 | 등락·비교 기준 | 기준일·시각 | 출처", "--- | --- | --- | --- | ---"]
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    for ticker, label in INDEX_BOARD.items():
        market = "KR" if ticker in {"^KS11", "^KQ11"} else "US"
        group, obs = _latest_observation(ticker, market, context, states, checked)
        price = number(obs.get("price"))
        basis = "장중·직전 종가 대비" if group in {"KR", "US"} else "정규장 종가·전 거래일 대비"
        if not obs:
            basis = "동일 기준 관측 미확보"
        at = kst_time(obs.get("as_of")) if group in {"KR", "US"} else obs.get("date", "미연결")
        lines.append(" | ".join(_cell(x) for x in (f"{label}({ticker})", f"{price:,.2f} pt" if price is not None else "미연결",
                     _pct(obs.get("return")) + " · " + basis, at, obs.get("source", "미연결"))))
    for name, ticker in MACRO_SYMBOLS.items():
        obs = context.get("macro_data", {}).get(name, {})
        value, change = number(obs.get("val")), number(obs.get("chg"))
        unit = "%" if ticker == "^TNX" else "원/USD" if ticker.endswith("=X") else "USD/배럴" if ticker == "CL=F" else "pt"
        lines.append(" | ".join(_cell(x) for x in (f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
                     f"{change:+.2f}% · 1개월 변화" if change is not None else "1개월 변화 미연결",
                     obs.get("as_of") or obs.get("date") or "미연결", obs.get("source", "공급처 기준값"))))
    for ticker, (name, unit) in COMMODITY_BOARD.items():
        obs = context.get("prices", {}).get(ticker, {})
        value = number(obs.get("price"))
        lines.append(" | ".join(_cell(x) for x in (f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
                     _pct(obs.get("return")) + " · 전 거래일 대비", obs.get("date") or "미연결", obs.get("source", "미연결"))))
    for ticker, (name, unit) in REPORT_ONLY_DAILY.items():
        obs = context.get("energy_daily", {}).get(ticker) or context.get("prices", {}).get(ticker, {})
        value, previous = number(obs.get("price")), number(obs.get("previous_price"))
        if ticker == "^TYX":
            change = f"{(value - previous) * 100:+.2f}bp" if value is not None and previous is not None else "변화 미연결"
            basis = "일봉 수익률 수준(%) · 이전 관측 대비"
        else:
            change, basis = _pct(obs.get("return")), "공급처 연속 선물 일봉 · 이전 관측 대비 · 공식 정산가 아님"
        dates = f"{obs.get('previous_date') or '미연결'} → {obs.get('date') or '미연결'}"
        lines.append(" | ".join(_cell(x) for x in (f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
                     change + " · " + basis, dates, obs.get("source") or "미연결")))
    lines += ["", "지수 종가·장중과 매크로 1개월 변화는 비교 구간이 다릅니다. 금·은·구리·Brent는 연속 선물 일봉이며 현물·실시간 가격이나 공식 정산가가 아닙니다.",
              "WTI 매크로는 NY 16:00 완료 5분봉 기준값이며 CME 14:28~14:30 ET VWAP 공식 정산가가 아닙니다. Brent·30년물은 보고서 전용이며 회전·매매 대상에 추가되지 않습니다."]
    return lines
