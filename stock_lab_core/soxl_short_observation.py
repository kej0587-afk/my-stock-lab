"""Read-only SOXX hourly observation, isolated from investment decisions."""

import numpy as np
import pandas as pd

from stock_lab_core.chart_structure import build_parallel_channel
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

SYMBOLS = ("SOXX", "^SOX", "SMH", "QQQ")
ROLES = {"SOXX": "타점 기준 · 동일 지수 1배 ETF", "^SOX": "참고 · 별도 반도체 지수",
         "SMH": "참고 · 다른 반도체 구성", "QQQ": "참고 · 나스닥100 환경"}
VERSION = 1
HOUR = pd.Timedelta(hours=1)


def completed_hour_grid(schedule, now):
    """NYSE open-anchored full hours only; exclude the final partial hour."""
    clock = pd.Timestamp(now)
    if clock.tzinfo is None:
        raise ValueError("timezone_required")
    starts = []
    for row in schedule.itertuples():
        opening, closing = pd.Timestamp(row.market_open), pd.Timestamp(row.market_close)
        if opening.tzinfo is None or closing.tzinfo is None or closing <= opening:
            raise ValueError("invalid_exchange_schedule")
        if opening + HOUR <= closing:
            starts.extend(pd.date_range(opening, closing - HOUR, freq="1h").tolist())
    grid = pd.DatetimeIndex(starts, tz="UTC").sort_values().unique()
    return grid[grid + HOUR <= clock]


def completed_hour_frame(raw, grid):
    required = ["Open", "High", "Low", "Close"]
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame(), "시간봉 미수집"
    if (not isinstance(raw.index, pd.DatetimeIndex) or raw.index.tz is None
            or not raw.index.is_unique or raw.columns.has_duplicates
            or not set(required).issubset(raw.columns)):
        return pd.DataFrame(), "시각·OHLC 형식 확인 필요"
    frame = raw.copy(deep=True)
    frame.index = frame.index.tz_convert("UTC")
    frame = frame.reindex(grid).loc[lambda f: f.index >= raw.index.min()]
    values = frame[required].apply(pd.to_numeric, errors="coerce")
    valid = (np.isfinite(values).all(axis=1) & values.gt(0).all(axis=1)
             & values.High.ge(values[["Open", "Close", "Low"]].max(axis=1))
             & values.Low.le(values[["Open", "Close", "High"]].min(axis=1)))
    frame[required] = values
    # Preserve gaps as NaN: do not compress time or manufacture candle continuity.
    frame.loc[~valid, required] = np.nan
    return frame, ""


def channel_plan(frame, channel):
    """One frozen observation basis, not a buy permission or SOXL price forecast."""
    if frame.empty or not channel:
        return {}, "확정 피벗 채널 미형성"
    entry = float(frame.Close.iloc[-1])
    stop, target = float(channel["lower"][-1]), float(channel["upper"][-1])
    if not all(np.isfinite(v) and v > 0 for v in (entry, stop, target)):
        return {}, "채널 가격 확인 필요"
    if not stop < entry < target:
        side = "하단 이탈/접촉" if entry <= stop else "상단 돌파/접촉"
        return {}, side + " · 재진입/새 저항 확인 전 계획 보류"
    risk = entry - stop
    return {"entry": entry, "stop": stop, "target": target,
            "one_r": entry + risk, "one_r_before_target": entry + risk <= target,
            "rr": (target - entry) / risk, "risk_pct": risk / entry * 100,
            "support_reaction": bool(frame.Low.iloc[-1] <= stop < entry)}, "채널 내부 관찰"


def build_short_observation(frames, schedule, now):
    grid = completed_hour_grid(schedule, now)
    result = {"status": "자료 확인", "plan": {}, "channel": {}, "rows": [],
              "frame": pd.DataFrame(), "as_of": None, "expected_end": None}
    if len(grid) < 2:
        result["status"] = "완료 1시간봉 부족"
        return result
    result["expected_end"] = grid[-1] + HOUR
    for ticker in SYMBOLS:
        frame, issue = completed_hour_frame(frames.get(ticker), grid)
        row = {"ticker": ticker, "role": ROLES[ticker], "close": None,
               "change_pct": None, "end": None, "status": issue}
        valid = frame.dropna(subset=["Open", "High", "Low", "Close"]) if not frame.empty else frame
        if not valid.empty:
            row.update(close=float(valid.Close.iloc[-1]), end=valid.index[-1] + HOUR)
            fresh = valid.index[-1] == grid[-1]
            row["status"] = "동일 완료봉" if fresh else "최신 완료봉 미연결 · 과거값"
            if fresh and len(frame) >= 2 and pd.notna(frame.Close.iloc[-2]):
                row["change_pct"] = (float(frame.Close.iloc[-1] / frame.Close.iloc[-2]) - 1) * 100
            if ticker == "SOXX":
                result.update(frame=frame.tail(140), as_of=row["end"])
                if not fresh:
                    result["status"] = row["status"]
                elif len(frame) < 24 or frame.tail(140)[["Open", "High", "Low", "Close"]].isna().any().any():
                    result["status"] = "SOXX 시간봉 부족·구간 결측 · 계획 보류"
                else:
                    channel = build_parallel_channel(frame.tail(140))
                    plan, state = channel_plan(frame, channel)
                    result.update(channel=channel, plan=plan, status=state)
        elif ticker == "SOXX":
            result["status"] = issue or "SOXX 유효 시간봉 미수집"
        result["rows"].append(row)
    return result
