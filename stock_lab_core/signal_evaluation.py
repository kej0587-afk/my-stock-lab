"""Price-only event studies, not a replay of historical portfolio decisions."""

import math

import pandas as pd


def next_open_outcomes(df, signal_index, horizons=(5, 20, 60)):
    """Enter next bar's open, exit the Nth held bar's close (entry day is day 1).

    Missing opens never fall back to the signal close. Incomplete horizons stay
    unscored. Low prices measure adverse excursion, not a simulated stop fill.
    Fees, spreads, news, weights and historical macro are not reconstructed.
    """
    entry_index = signal_index + 1
    result = {"진입일": "", "진입가": math.nan, "체결가정": "다음 봉 시가", "검증범위": "가격조건 사건연구 (실전판정 재현 아님)"}
    for horizon in horizons:
        result[f"{horizon}일후"] = math.nan
        result[f"{horizon}일최대낙폭"] = math.nan
    if entry_index >= len(df) or "Open" not in df:
        return result
    price = pd.to_numeric(pd.Series([df["Open"].iloc[entry_index]]), errors="coerce").iloc[0]
    if not math.isfinite(price) or price <= 0:
        return result
    result.update(진입일=str(df.index[entry_index])[:10], 진입가=float(price))
    for horizon in horizons:
        exit_index = entry_index + horizon - 1
        if exit_index >= len(df):
            continue
        window = df.iloc[entry_index:exit_index + 1]
        closes = pd.to_numeric(window["Close"], errors="coerce")
        lows = pd.to_numeric(window.get("Low", pd.Series(math.nan, index=window.index)), errors="coerce")
        if (closes.gt(0) & closes.lt(math.inf)).all():
            result[f"{horizon}일후"] = (float(closes.iloc[-1]) / price - 1) * 100
        if (lows.gt(0) & lows.lt(math.inf)).all():
            result[f"{horizon}일최대낙폭"] = min(0.0, (float(lows.min()) / price - 1) * 100)
    return result
