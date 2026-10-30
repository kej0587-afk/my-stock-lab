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


def current_state_lines(context, states, now, metrics):
    from stock_lab_core.report_intraday import _latest_observation
    from stock_lab_core.report_session import us_extended_session
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    kr_parts = []
    for ticker in ("^KS11", "^KQ11"):
        group, obs = _latest_observation(ticker, "KR", context, states, checked)
        basis = ("장중" if group == "KR" else "종가") if obs else "미연결"
        kr_parts.append(f"{INDEX_BOARD[ticker]} {_pct(obs.get('return'))}"
                        + (f"({obs['date']} {basis})" if obs else ""))
    window = us_extended_session(now)
    phase = "정규장 장중" if states["US"]["phase"] == "intraday" else window.get("label", "정규장 외")
    us_parts = []
    for ticker in ("SOXX", "RAM"):
        group, obs = _latest_observation(ticker, "US", context, states, checked)
        if obs and group != "US_CLOSE":
            us_parts.append(f"{ticker} {_pct(obs['return'])}")
    futures = (context.get("scenario_observations") or {}).get("latest", {})
    for ticker in ("NQ=F", "ES=F"):
        obs = futures.get(ticker, {})
        if number(obs.get("return")) is not None:
            us_parts.append(f"{ticker} {_pct(obs['return'])}")
    # No stale closing return is advertised as a current overnight quote.
    us_line = " · ".join(us_parts) or "현재 시세 미연결(직전 종가는 아래 표)"
    coverage = number((metrics or {}).get("coverage")) or 0
    total = number((metrics or {}).get("total"))
    if (metrics or {}).get("error") or total is None or coverage < 90:
        account = f"전체 추정 보류 · 연결 {coverage:.1f}% (90% 미만 또는 입력 확인 필요)"
    else:
        account = f"통합 누적 추정 {round(total, 2) or 0:+.2f}%p · 연결 {coverage:.1f}% · 확정 손익 아님"
    return ["**한국 현재** · " + " / ".join(kr_parts),
            f"**미국 현재 · {phase}** · {us_line} (미확정·지연 가능)",
            "**계좌** · " + account]


def market_board_lines(context, states, now):
    from stock_lab_core.report_intraday import _latest_observation
    from stock_lab_core.report_presentation import kst_time
    from stock_lab_core.report_prices import MACRO_SYMBOLS
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
    lines += ["", "지수 종가·장중과 매크로 1개월 변화는 비교 구간이 다릅니다. 금·은·구리는 연속 선물 일봉이며 현물·실시간 가격이나 공식 정산가가 아닙니다."]
    return lines
