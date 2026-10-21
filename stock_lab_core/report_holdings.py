"""Report estimates reuse portfolio exposure multipliers; never trade signals."""

import math
from datetime import timedelta

import pandas as pd

from stock_lab_core.portfolio import infer_scenario_shock_multiplier
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
from stock_lab_core.report_evidence import first, number, text

UNDERLYINGS = {
    "379800": ("^GSPC",), "379810": ("QQQ", "^NDX"), "418660": ("QQQ", "^NDX"),
    "SOXL": ("SOXX",), "RAM": ("DRAM",), "TQQQ": ("QQQ",), "QLD": ("QQQ",),
    "BITX": ("BTC-US-CLOSE",), "BITU": ("BTC-US-CLOSE",),
}


HEDGE_POLICIES = {
    "379800": ("환노출(환헤지 안 함)", "삼성자산운용 상품정보", "https://m.samsungfund.com/etf/search.do?searchText=379800"),
    "379810": ("환노출(환헤지 안 함)", "삼성자산운용 상품정보", "https://www.samsungfund.com/etf/search.do?searchText=379810"),
    "418660": ("환노출(운용사 인용 보도 기준·최신 원문 재확인)", "미래에셋 운용담당자 인용 보도(2023-12-19); 최신 운용사 원문 HTTP 403",
               "https://www.newsway.co.kr/news/view?ud=2023121915341181083"),
}


def hedge_policy_line(row):
    code = text(first(row, "티커", "ticker")).upper().split(".")[0]
    return HEDGE_POLICIES.get(code, ("환헤지 여부 미확인",))[0]


def hedge_source_lines(rows):
    codes = {text(first(row, "티커", "ticker")).upper().split(".")[0] for row in rows}
    return [f"- 환헤지 출처 {code}: [{source}]({url})" for code, (_, source, url) in HEDGE_POLICIES.items() if code in codes]


def cumulative_holding_comparison(row, observations, sessions, now, price_frames, *, intraday_prices=None):
    """Compare the as-yet-unreflected US sessions to cumulative KR closes."""
    from stock_lab_core.report_evidence import closed_daily_frame
    from stock_lab_core.prices import _us_equity_market_holidays

    ticker = text(first(row, "티커", "ticker")).upper()
    code = ticker.split(".")[0]
    own = observations.get(ticker, {})
    if code not in {"379800", "379810", "418660"}:
        return {}
    current = (intraday_prices or {}).get(ticker, {})
    current_price = number(current.get("price"))
    from stock_lab_core.report_intraday import valid_live_observation
    is_live = (valid_live_observation(current, "KR", now) and current_price is not None and current_price > 0)
    if intraday_prices is not None and not is_live:
        return {"error": "한국 장중 시세 미연결/지연 또는 시세시각 미확인"}
    end_kr = current["date"] if is_live else own.get("date")
    end_us = sessions.get("US")
    if not end_kr or (not is_live and end_kr != sessions.get("KR")) or not end_us:
        return {"error": "양국 확정 종가 기준일 불일치"}
    own_frame = closed_daily_frame((price_frames or {}).get(ticker), ticker, now)
    for base in UNDERLYINGS[code]:
        proxy = observations.get(base, {})
        if proxy.get("date") != end_us:
            continue
        proxy_frame = closed_daily_frame((price_frames or {}).get(base), base, now)
        if own_frame.empty or proxy_frame.empty:
            continue
        own_close = pd.to_numeric(own_frame["Close"], errors="coerce")
        proxy_close = pd.to_numeric(proxy_frame["Close"], errors="coerce")
        own_close.index = own_close.index.strftime("%Y-%m-%d")
        proxy_close.index = proxy_close.index.strftime("%Y-%m-%d")
        if is_live:
            own_close = own_close.copy()
            own_close.loc[end_kr] = current_price
            own_close = own_close.sort_index()
        anchor = text(proxy.get("previous_date"))
        if not anchor:
            earlier = proxy_close.index[proxy_close.index < end_us]
            anchor = max(earlier, default="")
        # A US trading day can be a Korean holiday. Select a real KR close,
        # disclose its date, and then recompute the US information-time anchor.
        eligible_kr = own_close.index[(own_close.index <= anchor) & (own_close.index < end_kr)]
        anchor = max(eligible_kr, default="")
        if not anchor or not (anchor < end_us and anchor < end_kr):
            continue
        # KR's 15:30 close precedes that calendar day's US opening. Include the
        # US return starting that day, not just its later close-to-close move.
        kr_start_at = pd.Timestamp(anchor + " 15:30", tz="Asia/Seoul")
        ny_start = kr_start_at.tz_convert("America/New_York")
        us_start = ny_start.date() - timedelta(days=int(ny_start.hour < 16))
        while us_start.weekday() >= 5 or us_start in _us_equity_market_holidays(us_start.year):
            us_start -= timedelta(days=1)
        anchor_us = us_start.isoformat()
        if anchor not in own_close or end_kr not in own_close or anchor_us not in proxy_close or end_us not in proxy_close:
            continue
        path = proxy_close.loc[anchor_us:end_us]
        required = {day.date().isoformat() for day in pd.bdate_range(anchor_us, end_us)
                    if day.date() not in _us_equity_market_holidays(day.year)}
        if not required.issubset(set(path.index)):
            continue
        endpoints = [own_close.loc[anchor], own_close.loc[end_kr], *path.tolist()]
        if any(number(value) is None or value <= 0 for value in endpoints):
            continue
        multiplier = infer_scenario_shock_multiplier({"티커": ticker, "자산명": text(first(row, "종목명", "name"))})
        actual = float(own_close.loc[end_kr] / own_close.loc[anchor] - 1)
        underlying = float(path.iloc[-1] / path.iloc[0] - 1)
        # Daily-reset products compound daily shocks, not multiplier * total.
        reference = float((1 + path.pct_change().dropna() * multiplier).prod() - 1)
        if not all(math.isfinite(value) for value in (actual, underlying, reference)):
            continue
        return {"anchor": anchor, "us_anchor": anchor_us, "kr_date": end_kr, "us_date": end_us, "proxy": base,
                "actual": actual, "underlying": underlying, "reference": reference,
                "residual_pp": (actual - reference) * 100, "multiplier": multiplier,
                "intraday": is_live, "as_of": current.get("as_of") or current.get("retrieved_at", "")}
    return {"error": "같은 시작일의 한국 ETF·미국 기초자산 가격 이력 미수집"}


def completed_scenario_comparison(row, observations, sessions, now, *, price_frames=None, intraday_prices=None):
    """Cumulative close comparison; one-day scenarios are only a reference."""
    ticker = text(first(row, "티커", "ticker")).upper()
    code = ticker.split(".")[0]
    own = (intraday_prices or {}).get(ticker) or observations.get(ticker, {})
    actual = number(own.get("return"))
    if code not in {"379800", "379810", "418660", "0167A0", "0227L0"}:
        return None
    if actual is None or own.get("date") != now.date().isoformat():
        return "당일 시세 미수집: 누적 비교 보류" if intraday_prices is not None else "당일 종가 미수집: 시나리오와 실제 비교 보류"
    if code not in UNDERLYINGS:
        return f"당일 종가 {actual * 100:+.2f}% · 구성종목 기반 수치 시나리오 미제공, 갭 위험 문구로 실제 결과를 대체하지 않음"
    comparison = cumulative_holding_comparison(row, observations, sessions, now, price_frames, intraday_prices=intraday_prices)
    policy = hedge_policy_line(row)
    if comparison.get("error") or not comparison:
        return "누적 비교 보류: " + comparison.get("error", "누적 비교 기초자산 미연결") + " · " + policy
    c = comparison
    from stock_lab_core.report_presentation import kst_time
    live_note = f" 장중·미확정({kst_time(c['as_of'])})" if c.get("intraday") else ""
    reference_label = f"{c['multiplier']:g}배 일간복리 참고" if c["multiplier"] != 1 else "누적"
    return (f"누적 비교: 한국 {c['anchor']}→{c['kr_date']}{live_note} 실제 {c['actual'] * 100:+.2f}% vs "
            f"{c['proxy']} 미국 {c['us_anchor']}→{c['us_date']} {reference_label} {c['reference'] * 100:+.2f}% · "
            f"잔차 {c['residual_pp']:+.2f}%p · {policy}")


def holding_estimate(row, observations, sessions, now, *, intraday_prices=None):
    ticker = text(first(row, "티커", "ticker")).upper()
    name = text(first(row, "종목명", "자산명", "name"))
    multiplier = infer_scenario_shock_multiplier({"티커": ticker, "자산명": name})
    bases = UNDERLYINGS.get(ticker.split(".")[0], ())
    if not bases:
        return "해당없음", abs(multiplier) > 1
    expected = sessions.get("US")
    own = observations.get(ticker, {})
    domestic = ticker.split(".")[0] in {"379800", "379810", "418660"}
    if domestic and intraday_prices:
        for base in bases:
            current = intraday_prices.get(base, {})
            value = number(current.get("return"))
            if value is None or not current.get("date") or current["date"] < own.get("date", ""):
                continue
            from stock_lab_core.report_presentation import kst_time
            return (f"다음 한국장 갭 예상 영향(추정): {base} {value * 100:+.2f}% × {multiplier:g} = "
                    f"{value * multiplier * 100:+.2f}% · 미국 {current['date']} 장중 진행·확정 아님 · "
                    f"{kst_time(current.get('as_of', current.get('retrieved_at')))} · 환율·선물·추적오차 미반영"), abs(multiplier) > 1
    for base in bases:
        obs = observations.get(base, {})
        value = number(obs.get("return"))
        if value is None or not expected or obs.get("date") != expected:
            continue
        if domestic and own.get("date", "") > expected:
            return f"미국 {expected} 종가 영향은 한국 {own['date']}에 이미 반영 · 다음 세션 자료 대기(중복 계상 안 함)", abs(multiplier) > 1
        if not domestic and own.get("date") and obs.get("date") != own["date"]:
            continue
        label = "BTC(미국장 마감→마감)" if base == "BTC-US-CLOSE" else base
        prefix = ("월요일 갭 예상 영향(추정)" if now.weekday() == 6 else "다음 한국장 갭 예상 영향(추정)") if domestic else "일간 배수 환산(추정)"
        if domestic and now.weekday() < 5 and now.hour >= 9:
            prefix = "개장 전 기준 갭 시나리오(추정, 실제 등락 아님)"
        note = "환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님" if domestic else "대용 기초자산, 보수·선물 베이시스·추적오차 미반영"
        return (f"{prefix}: {label} {value * 100:+.2f}% × {multiplier:g} = "
                f"{value * multiplier * 100:+.2f}% · {expected} · {note}"), abs(multiplier) > 1
    return "추정 보류: 기준 미국장 마감 시점 기초자산 자료 미수집", abs(multiplier) > 1
