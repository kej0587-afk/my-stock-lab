"""Report-only close confirmation; never modify the decision price history."""

import math

import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def pending_close_mask(frame):
    """Keep unconfirmed dates missing in every report consumer, including RS."""
    return frame.index.strftime("%Y-%m-%d") == frame.attrs.get("report_close_pending_date", "")


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def confirm_kr_close_bar(old, row, day, *, scale=1):
    """Caller verifies symbol/date/poll clock; return a copy or a rejection reason.

    An exact OHLCV match confirms the existing daily series without splicing a
    quote's conflicting previous-price basis into that series. Otherwise retain
    the strict previous-close checks before replacing a cached intraday bar.
    """
    if row.get("ms") != "CLOSE":
        return None, "종목 시세가 마감 상태가 아님"
    frame = old.copy(deep=True)
    frame.index = frame.index.tz_localize(None).normalize()
    if frame.index.has_duplicates:
        return None, "동일 거래일 일봉 중복"
    if day not in frame.index:
        return None, "당일 날짜의 일봉 없음"
    values = {col: _number(row.get(key)) for col, key in
              (("Open", "ov"), ("High", "hv"), ("Low", "lv"), ("Close", "nv"))}
    if any(v is None or v <= 0 for v in values.values()):
        return None, "마감 OHLC 결측/범위 오류"
    if not values["Low"] <= min(values["Open"], values["Close"]) <= max(values["Open"], values["Close"]) <= values["High"]:
        return None, "마감 OHLC 순서 오류"
    values = {col: value / scale for col, value in values.items()}
    volume = _number(row.get("aq"))
    sign = {"1": 1, "2": 1, "3": 0, "4": -1, "5": -1}.get(str(row.get("rf")))
    change = _number(row.get("cv"))
    previous = values["Close"] - abs(change) * sign / scale if sign is not None and change is not None else None
    supplied = _number(row.get("pcv"))
    supplied = supplied / scale if supplied is not None else None
    prior = pd.to_numeric(frame.loc[frame.index < day, "Close"], errors="coerce").sort_index()
    history_previous = _number(prior.iloc[-1]) if not prior.empty else None
    basis_matches = (previous is not None and history_previous is not None and previous > 0
                     and math.isclose(history_previous, previous, rel_tol=1e-5)
                     and (supplied is None or math.isclose(supplied, previous, rel_tol=1e-5)))
    whole_bar_matches = (volume is not None and volume > 0 and "Volume" in frame
                         and _number(frame.loc[day, "Volume"]) == volume
                         and all(col in frame and _number(frame.loc[day, col]) is not None
                                 and math.isclose(float(frame.loc[day, col]), value, rel_tol=1e-9)
                                 for col, value in values.items()))
    frame.attrs.pop("report_close_basis_note", None)
    if whole_bar_matches:
        # Preserve adjusted historical values and the caller's price definition.
        frame.attrs["report_close_verification"] = "daily_ohlcv_match"
        if not basis_matches:
            frame.attrs["report_close_basis_note"] = "마감 OHLCV 일치 · 시세 전일값 불일치/미확인, 수익률은 기존 일봉 기준 유지"
    elif basis_matches:
        for col, value in values.items():
            frame.loc[day, col] = value
        frame.loc[day, "Volume"] = volume
        frame.attrs.update(source="Naver 정규장 마감 시세(CLOSE 확인)", report_close_verification="quote_repair")
    else:
        return None, "일봉과 마감 시세의 전일가격 기준 불일치/미확인 · 당일 OHLCV 전체 일치도 미확인"
    frame.attrs.pop("report_close_pending_date", None)
    frame.attrs.pop("report_close_pending_reason", None)
    return frame.sort_index(), ""
