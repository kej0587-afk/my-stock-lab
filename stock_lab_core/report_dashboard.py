"""Compact report surfaces over the existing, timestamp-checked observations."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, text, stamp, _cell

register_loaded_source(__name__, __file__)

INDEX_BOARD = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500",
               "^IXIC": "나스닥종합", "^SOX": "필라델피아 반도체", "^DJI": "다우", "^RUT": "러셀2000"}
COMMODITY_BOARD = {"GC=F": ("금 선물", "USD/트로이온스"),
                   "SI=F": ("은 선물", "USD/트로이온스"),
                   "HG=F": ("구리 선물", "USD/파운드")}


# Observatory items already priced by the same Yahoo daily batch (2026-11-24, status #10/#11).
# Report-only: never added to rotation, scores or trading inputs.
OBSERVATORY_DAILY = {"EWZ": ("브라질 ETF", "USD"), "INDA": ("인도 ETF", "USD"),
                     "VNM": ("베트남 ETF", "USD"), "EWJ": ("일본 ETF", "USD"),
                     "^SKEW": ("SKEW", "pt"), "^VVIX": ("VVIX", "pt"), "^OVX": ("OVX", "pt")}
COUNTRY_ETFS = ("EWZ", "INDA", "VNM", "EWJ")
# Local benchmark indices beside the country ETFs and other regions (status #12). Local currency,
# local exchange calendar; a bar counts only after that exchange's close + 30 min.
# Report-only: never added to rotation, scores or trading inputs. VN-Index is not
# connected: the Yahoo daily series checked on 2026-11-24 returned a single bar.
LOCAL_INDICES = {"^N225": ("닛케이225", "JPY", "Asia/Tokyo", (15, 30), "EWJ"),
                 "^NSEI": ("니프티50", "INR", "Asia/Kolkata", (15, 30), "INDA"),
                 "^BVSP": ("보베스파", "BRL", "America/Sao_Paulo", (18, 0), "EWZ"),
                 "^TWII": ("대만 가권", "TWD", "Asia/Taipei", (13, 30), ""),
                 "000001.SS": ("상하이종합", "CNY", "Asia/Shanghai", (15, 0), ""),
                 "^HSI": ("항셍", "HKD", "Asia/Hong_Kong", (16, 10), ""),
                 "^STOXX50E": ("유로스톡스50", "EUR", "Europe/Berlin", (17, 30), "")}
LOCAL_INDEX_MISSING = {"VNM": "베트남 VN-Index · 미연결(공급 일봉 불안정, 추정하지 않음)"}


def observatory_daily_observations(frames, now):
    """Last two completed daily closes per item; missing stays empty, never filled."""
    from stock_lab_core.report_evidence import closed_daily_frame
    result = {}
    for ticker in OBSERVATORY_DAILY:
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if frame.empty:
            result[ticker] = {}
            continue
        current = float(frame["Close"].iloc[-1])
        previous = float(frame["Close"].iloc[-2]) if len(frame) > 1 else None
        result[ticker] = {"price": current, "date": str(frame.index[-1].date()), "previous_price": previous,
                          "previous_date": str(frame.index[-2].date()) if previous is not None else "",
                          "return": current / previous - 1 if previous else None,
                          "source": frame.attrs.get("source") or "Yahoo Finance daily"}
    return result


# 2026-11-27 (priority 5): FRED items the observatory already loads but the report never showed.
# Same loader and cache key (symbol, 1 year, KST date) as the observatory's default view; nothing estimated.
OBSERVATORY_FRED = ("STLFSI4", "T10Y2Y", "M2SL", "ICSA", "WALCL", "WRESBAL", "RRPONTSYD", "WTREGEN")
OBSERVATORY_FRED_YEARS = 1


def observatory_fred_observations(now, *, loader=None, symbols=OBSERVATORY_FRED):
    """Return ({symbol: observation row}, meta). meta keeps elapsed seconds and per-item status so the
    report can say how long the reuse took; a failed item keeps its reason and stays 미연결."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    import pandas as pd
    from stock_lab_core.macro_monitor import CATALOG, load_macro_series, observation
    loader = loader or load_macro_series
    clock = pd.Timestamp(now)
    clock = clock.tz_convert("Asia/Seoul") if clock.tzinfo is not None else clock
    as_of = str(clock.date())
    started = time.perf_counter()

    def one(symbol):
        try:
            series, reason = loader(symbol, OBSERVATORY_FRED_YEARS, as_of)
        except Exception as exc:  # never fill a value; keep the reason
            series, reason = pd.Series(dtype=float), type(exc).__name__
        row, _ = observation(CATALOG[symbol], series, clock.tz_localize(None) if clock.tzinfo else clock, reason)
        return symbol, row

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = dict(pool.map(one, symbols))
    meta = {"seconds": time.perf_counter() - started, "requested": len(symbols),
            "connected": sum(1 for row in rows.values() if row.get("값") != "미연결"), "as_of": as_of}
    return rows, meta


def observatory_fred_table_lines(context):
    rows = context.get("observatory_fred") or {}
    if not rows:
        return []
    from stock_lab_core.macro_monitor import CATALOG
    meta = context.get("observatory_fred_meta") or {}
    body = []
    for symbol in OBSERVATORY_FRED:
        row = rows.get(symbol) or {}
        name = CATALOG[symbol].name
        body.append(" | ".join(_cell(x) for x in (
            f"{name}({symbol})", row.get("값", "미연결"), row.get("직전 관측 대비", "-"),
            f"{row.get('관측일', '-')} · {row.get('주기', CATALOG[symbol].frequency)}",
            row.get("상태", "미연결"), "FRED")))
    note = (f"관측실과 같은 FRED 자료(1년 조회, {meta.get('as_of', '조회일 미확인')} KST 조회)를 재사용했습니다. "
            f"연결 {meta.get('connected', 0)}/{meta.get('requested', len(OBSERVATORY_FRED))}"
            + (f", 준비 {meta['seconds']:.2f}초" if isinstance(meta.get("seconds"), (int, float)) else "")
            + ". 관측일은 발표일·조회시각과 다르며 미수집은 0으로 채우지 않습니다.")
    return ["**유동성·연준 · 관측실 FRED 지표**", "",
            "대상 | 수준 | 직전 관측 대비 | 관측일 · 주기 | 상태 | 출처", "--- | --- | --- | --- | --- | ---",
            *body, "", note, ""]


def _local_closed(frame, zone, close, now):
    """Completed local sessions only: earlier dates, or today after close + 30 minutes."""
    import math
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import pandas as pd
    if not isinstance(frame, pd.DataFrame) or "Close" not in frame or not isinstance(frame.index, pd.DatetimeIndex):
        return pd.DataFrame()
    local = now.astimezone(ZoneInfo(zone))
    closed_at = local.replace(hour=close[0], minute=close[1], second=0, microsecond=0) + timedelta(minutes=30)
    dates = frame.index.tz_localize(None).date
    mask = (dates < local.date()) | ((dates == local.date()) & (local >= closed_at))
    out = frame.loc[mask].sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    values = pd.to_numeric(out["Close"], errors="coerce")
    return out.loc[values.gt(0) & values.map(lambda v: isinstance(v, float) and math.isfinite(v))]


def local_index_observations(frames, now):
    """Last two completed local closes per index; missing stays empty, never filled."""
    result = {}
    for ticker, (_, _, zone, close, _) in LOCAL_INDICES.items():
        frame = _local_closed((frames or {}).get(ticker), zone, close, now)
        if frame.empty:
            result[ticker] = {}
            continue
        current = float(frame["Close"].iloc[-1])
        previous = float(frame["Close"].iloc[-2]) if len(frame) > 1 else None
        result[ticker] = {"price": current, "date": str(frame.index[-1].date()), "previous_price": previous,
                          "previous_date": str(frame.index[-2].date()) if previous is not None else "",
                          "return": current / previous - 1 if previous else None,
                          "source": frame.attrs.get("source") or "Yahoo Finance daily"}
    return result


def local_index_table_lines(context):
    """Local index rows in local currency; absent items stay 미연결."""
    observed = context.get("local_indices") or {}
    rows = []
    for ticker, (name, unit, _, _, etf) in LOCAL_INDICES.items():
        obs = observed.get(ticker) or {}
        value = number(obs.get("price"))
        dates = f"{obs.get('previous_date') or '미연결'} → {obs.get('date') or '미연결'}" if obs else "미연결"
        rows.append(" | ".join(_cell(x) for x in (
            f"{name}({ticker})" + (f" · {etf} 비교" if etf else ""), f"{value:,.2f} {unit}" if value is not None else "미연결",
            _pct(obs.get("return")) + (" · 현지 마감 일봉 · 이전 관측 대비" if obs else ""), dates,
            obs.get("source") or "미연결")))
    rows.extend(f"{label} | 미연결 | - | - | -" for label in LOCAL_INDEX_MISSING.values())
    return ["현지 지수 | 수준(현지 통화) | 등락·비교 기준 | 현지 기준일 | 출처", "--- | --- | --- | --- | ---", *rows, ""]


def observatory_table_lines(context, tickers):
    """Copy collected observations into a reader table; absent items stay 미연결."""
    rows = []
    for ticker in tickers:
        name, unit = OBSERVATORY_DAILY[ticker]
        obs = (context.get("observatory_daily") or {}).get(ticker) or {}
        value = number(obs.get("price"))
        dates = f"{obs.get('previous_date') or '미연결'} → {obs.get('date') or '미연결'}" if obs else "미연결"
        rows.append(" | ".join(_cell(x) for x in (
            f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
            _pct(obs.get("return")) + (" · 완료 일봉 · 이전 관측 대비" if obs else ""), dates, obs.get("source") or "미연결")))
    return ["대상 | 수준 | 등락·비교 기준 | 기준일 | 출처", "--- | --- | --- | --- | ---", *rows, ""]


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
        comparison = f"{change:+.2f}% · 1개월 변화" if change is not None else "1개월 변화 미연결"
        daily = number(obs.get("day_change_bp")) if ticker == "^TNX" else number(obs.get("day_ret"))
        if daily is not None:
            current = f"{daily:+.2f}bp" if ticker == "^TNX" else f"{daily * 100:+.2f}%"
            comparison = current + " · 일간 기준값 변화 / " + comparison
        lines.append(" | ".join(_cell(x) for x in (f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
                     comparison,
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
        elif ticker == "DX-Y.NYB":
            change, basis = _pct(obs.get("return")), "달러지수 일봉 · 이전 관측 대비"
        else:
            change, basis = _pct(obs.get("return")), "공급처 연속 선물 일봉 · 이전 관측 대비 · 공식 정산가 아님"
        dates = f"{obs.get('previous_date') or '미연결'} → {obs.get('date') or '미연결'}"
        lines.append(" | ".join(_cell(x) for x in (f"{name}({ticker})", f"{value:,.2f} {unit}" if value is not None else "미연결",
                     change + " · " + basis, dates, obs.get("source") or "미연결")))
    lines += ["", "지수 종가·장중과 매크로 1개월 변화는 비교 구간이 다릅니다. 금·은·구리·Brent는 연속 선물 일봉이며 현물·실시간 가격이나 공식 정산가가 아닙니다.",
              "WTI 매크로는 NY 16:00 완료 5분봉 기준값이며 CME 14:28~14:30 ET VWAP 공식 정산가가 아닙니다. Brent·30년물은 보고서 전용이며 회전·매매 대상에 추가되지 않습니다."]
    return lines
