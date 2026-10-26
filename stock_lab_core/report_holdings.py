"""Report estimates reuse portfolio exposure multipliers; never trade signals."""

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


def cumulative_holding_comparison(row, observations, sessions, now, price_frames, *, intraday_prices=None, scenario_frames=None):
    """Compare KR and futures at identical completed timestamps, never US daily closes."""
    from stock_lab_core.report_evidence import closed_daily_frame, stamp
    from stock_lab_core.report_intraday import valid_live_observation
    from stock_lab_core.report_scenario import FUTURES, interval_observation

    ticker = text(first(row, "티커", "ticker")).upper()
    code = ticker.split(".")[0]
    if code not in FUTURES:
        return {}
    daily = closed_daily_frame((price_frames or {}).get(ticker), ticker, now)
    if daily.empty:
        return {"error": "한국 ETF 종가 이력 미연결"}
    close = pd.to_numeric(daily["Close"], errors="coerce")
    current = (intraday_prices or {}).get(ticker, {})
    live = intraday_prices is not None
    end_day = current.get("date") if live else observations.get(ticker, {}).get("date")
    if not end_day or (not live and end_day != sessions.get("KR")):
        return {"error": "한국 종가 기준일 불일치"}
    if live and not valid_live_observation(current, "KR", now):
        return {"error": "한국 장중 시세 미연결/지연"}
    earlier = close.loc[close.index.strftime("%Y-%m-%d") < end_day]
    if earlier.empty:
        return {"error": "직전 한국 종가 미연결"}
    anchor = earlier.index[-1].date().isoformat()
    start = pd.Timestamp(anchor + " 15:30", tz="Asia/Seoul")
    end = pd.Timestamp(end_day + " 15:30", tz="Asia/Seoul")
    base_price = number(earlier.iloc[-1])
    last_price = number(close.iloc[-1])
    frames = scenario_frames or {}
    symbol = FUTURES[code]

    def bars(frame):
        if (not isinstance(frame, pd.DataFrame) or frame.empty or
                not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None or
                not isinstance(frame.get("Close"), pd.Series)):
            return pd.Series(dtype=float)
        values = pd.to_numeric(frame["Close"], errors="coerce").copy()
        values.index = values.index.tz_convert("Asia/Seoul") + pd.Timedelta(minutes=5)
        values = values.loc[~values.index.duplicated(keep="last")].sort_index()
        return values.loc[values.map(lambda x: number(x) is not None and x > 0)]

    future_bars = bars(frames.get(symbol))
    if live:
        own_bars = bars(frames.get(ticker))
        if own_bars.empty or future_bars.empty:
            return {"error": "한국 ETF·선물의 동일 시각 완료 5분봉 미연결(일봉으로 잔차 대체 안 함)"}
        cutoff = min(pd.Timestamp(stamp(now)), pd.Timestamp(stamp(current["as_of"])))
        common = own_bars.index.intersection(future_bars.index)
        common = common[(common > start) & (common <= cutoff) &
                        (common >= cutoff - pd.Timedelta(minutes=10))]
        if not len(common):
            return {"error": "한국 ETF·선물의 동일 시각 완료 5분봉 미연결(일봉으로 잔차 대체 안 함)"}
        end = common.max()
        last_price = number(own_bars.loc[end])
    elif close.index[-1].date().isoformat() != end_day:
        return {"error": "한국 끝 종가 기준일 불일치"}
    if any(value is None or value <= 0 for value in (base_price, last_price)):
        return {"error": "한국 비교 가격 결측/범위 오류"}
    future = interval_observation(frames.get(symbol), start, end)
    if not future or pd.Timestamp(future["base_at"]) != start or pd.Timestamp(future["as_of"]) != end:
        return {"error": f"{symbol} 한국 종가 시각의 완료 봉 미연결(비동시 잔차 계산 안 함)"}
    fx = interval_observation(frames.get("USDKRW=X"), start, end)
    if not fx or pd.Timestamp(fx["base_at"]) != start or pd.Timestamp(fx["as_of"]) != end:
        fx = {}
    actual = last_price / base_price - 1
    return {"anchor": anchor, "kr_date": end_day, "base_at": start.isoformat(), "as_of": end.isoformat(),
            "actual": actual, "underlying": future["return"], "reference": future["return"],
            "proxy": symbol, "fx_return": fx.get("return"), "intraday": live,
            # Futures are not a daily-reset leveraged ETF's replicating portfolio.
            "residual_pp": (actual - future["return"]) * 100 if code != "418660" else None}


def completed_scenario_comparison(row, observations, sessions, now, *, price_frames=None, intraday_prices=None, scenario_frames=None):
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
    c = cumulative_holding_comparison(row, observations, sessions, now, price_frames,
                                     intraday_prices=intraday_prices, scenario_frames=scenario_frames)
    if c.get("error") or not c:
        return "누적 비교 보류: " + c.get("error", "동일 시각 자료 미연결") + " · " + hedge_policy_line(row)
    from stock_lab_core.report_presentation import kst_time
    fx = f"{c['fx_return'] * 100:+.2f}%" if c["fx_return"] is not None else "미연결"
    residual = (f"단순 차이 {c['residual_pp']:+.2f}%p(환율·베이시스 미조정, 추적오차 아님)"
                if c["residual_pp"] is not None else "레버리지 재설정 미반영: 배수 잔차 산출 보류")
    from stock_lab_core.report_fx import adjusted_reference
    return (f"동일 시각 비교 {kst_time(c['base_at'])}→{kst_time(c['as_of'])}: "
            f"한국 ETF 실제 {c['actual'] * 100:+.2f}% vs {c['proxy']} {c['reference'] * 100:+.2f}% · "
            f"원/달러 별도 {fx} · {residual}" + adjusted_reference(c, code) + (" · 장중·미확정" if c["intraday"] else ""))


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
