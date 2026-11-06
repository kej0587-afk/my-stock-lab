"""Report-only split validation. Never infer a split from a large loss alone."""

import math

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import closed_daily_frame, number

register_loaded_source(__name__, __file__)

# Official effective date, not the record or distribution date. Correction also
# requires independent evidence of the historical price basis below.
VERIFIED_SPLITS = {
    "SOXX": [{"date": "2026-11-05", "ratio": 3.0,
              "source": "https://www.sec.gov/Archives/edgar/data/1100663/000119312526430480/d156277d497.htm"}],
}


def validate_report_prices(frames, quotes, now, *, etf_tickers=(), split_events=None):
    from stock_lab_core.report_quotes import regular_quote_observation

    result, notes, issues, daily_overrides = dict(frames), [], [], {}
    events = VERIFIED_SPLITS if split_events is None else split_events
    for ticker in sorted(set(etf_tickers) | set(events)):
        original = frames.get(ticker)
        closed = closed_daily_frame(original, ticker, now)
        if len(closed) < 2:
            continue
        frame = original.copy(deep=True)
        quote = regular_quote_observation(quotes.get(ticker, {}), ticker, now)
        rejection = ""
        split_quote = any(e["date"] == quote.get("date") for e in events.get(ticker, []))
        if split_quote and quote["date"] > closed.index[-1].date().isoformat():
            rejection = "분할 당일 일봉 미확보·과거 가격 단위 미확인"
        for event in events.get(ticker, []):
            day, ratio = pd.Timestamp(event["date"]).date(), number(event.get("ratio"))
            dates = list(closed.index.date)
            if not ratio or ratio <= 0 or day not in dates or dates.index(day) == 0:
                continue
            pos = dates.index(day)
            previous, current = closed.iloc[pos - 1], closed.iloc[pos]
            raw = float(previous["Close"])
            factor = None
            # A dated regular quote supplies the split-adjusted previous close.
            if quote.get("date") == day.isoformat() and quote.get("previous_date") == dates[pos - 1].isoformat():
                if math.isclose(float(current["Close"]), quote["price"], rel_tol=.001):
                    factor = quote["previous_price"] / raw
            elif "Adj Close" in closed:
                before, after = number(previous["Adj Close"]), number(current["Adj Close"])
                if before and after:
                    factor = (before / raw) / (after / float(current["Close"]))
            if factor is not None and math.isclose(factor, 1 / ratio, rel_tol=.001):
                if closed.Close.iloc[:pos].pct_change().abs().gt(.40).any():
                    rejection = "과거 이력에 큰 단위 단절 존재 · 전체 분할 보정 보류"
                    break
                mask = frame.index.date < day
                if "Adj Close" in frame:
                    before, after = number(previous["Adj Close"]), number(current["Adj Close"])
                    adj_factor = (before / raw) / (after / float(current["Close"])) if before and after else None
                    if adj_factor is not None and math.isclose(adj_factor, 1., rel_tol=.001):
                        frame.loc[mask, "Adj Close"] = pd.to_numeric(frame.loc[mask, "Adj Close"]) / ratio
                    elif adj_factor is None or not math.isclose(adj_factor, 1 / ratio, rel_tol=.001):
                        frame = frame.drop(columns="Adj Close")
                for column in ("Open", "High", "Low", "Close"):
                    if column in frame:
                        frame.loc[mask, column] = pd.to_numeric(frame.loc[mask, column]) / ratio
                if "Volume" in frame:
                    frame.loc[mask, "Volume"] = pd.to_numeric(frame.loc[mask, "Volume"]) * ratio
                note = f"{ticker}: {day} {ratio:g}:1 분할 확인 · 이전 OHLC/거래량 단위 보정 · {event['source']}"
                notes.append(note)
                frame.attrs["report_close_basis_note"] = note
                closed = closed_daily_frame(frame, ticker, now)
            elif abs(float(current["Close"]) / raw - 1) > .40 and (
                    factor is None or not math.isclose(factor, 1., rel_tol=.001)):
                rejection = "분할일 가격 단위 대조 미완료"
        move = float(closed.Close.iloc[-1] / closed.Close.iloc[-2] - 1)
        if abs(move) > .40:
            corroborated = (quote.get("date") == closed.index[-1].date().isoformat()
                            and quote.get("previous_date") == closed.index[-2].date().isoformat()
                            and math.isclose(quote["price"], float(closed.Close.iloc[-1]), rel_tol=.001)
                            and math.isclose(quote["previous_price"], float(closed.Close.iloc[-2]), rel_tol=.001))
            if not corroborated:
                rejection = f"일간 {move * 100:+.2f}% · 분할/기준가 대조 미완료"
            else:
                notes.append(f"{ticker}: ±40% 초과 일간 변동, 동일일 정규장 시세·이전 종가 대조 일치")
        if rejection:
            # Keep an independently checked daily quote without inventing the
            # missing/mixed 5D/3M history. No stale prior-session substitution.
            if split_quote:
                daily_overrides[ticker] = dict(quote, kind="확정 종가",
                    source="Yahoo 정규장 시세 · 공식 분할일 대조",
                    basis_note="일간만 확인 · 혼합/누락 이력의 중기 수익률 보류", return_5d=None)
                notes.append(f"{ticker}: 공식 분할일 정규장 시세의 일간 등락만 사용 · 중기 비교 제외")
            issues.append(f"{ticker}: {rejection} · 일봉 기반 수익률·순위 제외")
            result[ticker] = pd.DataFrame()
            continue
        result[ticker] = frame
    return result, notes, issues, daily_overrides
