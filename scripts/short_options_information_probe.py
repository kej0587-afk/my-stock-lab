"""Isolated public-data research; stdout only, no operational policy changes.

Current-vintage archive experiment, NOT a point-in-time trading backtest.
Fixed public benchmark SPY is unrelated to account/watchlist inputs.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stock_lab_core.money_flow import _compute_ticker_metrics

BASE = ["돈흐름점수", "1개월수익률", "3개월수익률", "6개월수익률",
        "가속도", "거래량증가", "가격수준"]


def get(url, **kwargs):
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}, **kwargs)
    r.raise_for_status()
    return r


def fit_predict(train, test, cols, target="target"):
    mu, sd = train[cols].mean(), train[cols].std().replace(0, 1)
    x = np.column_stack([np.ones(len(train)), (train[cols] - mu) / sd])
    z = np.column_stack([np.ones(len(test)), (test[cols] - mu) / sd])
    return z @ np.linalg.lstsq(x, train[target].to_numpy(), rcond=None)[0]


def make_panel(px, ratios, lag=1, *, sessions):
    """Signal d uses ratio d-lag, outcome open[d+2]/open[d+1]-1.

    Lag counts explicit exchange sessions, never compressed price/ratio rows.
    Missing values stay NaN. The caller supplies a complete exchange calendar.
    """
    if not isinstance(lag, int) or lag < 1:
        raise ValueError("Published ratios require at least one assumed session of lag")
    sessions = pd.DatetimeIndex(sessions)
    if sessions.has_duplicates or not sessions.is_monotonic_increasing or px.index.has_duplicates:
        raise ValueError("Unique ordered exchange sessions and price dates are required")
    px = px.reindex(sessions)
    rows = []
    for day in px.index[px.index >= "2013-01-01"]:
        window = px.loc[(px.index > day - pd.DateOffset(years=1)) & (px.index <= day)]
        if len(window) >= 127 and window[["Open", "High", "Low", "Close", "Volume"]].notna().all().all():
            rows.append({"date": day, **_compute_ticker_metrics(window)})
    panel = pd.DataFrame(rows).set_index("date")
    outcome_open = px.get("OutcomeOpen", px.Open)
    panel["target"] = outcome_open.shift(-2) / outcome_open.shift(-1) - 1
    panel["exit_date"] = pd.Series(px.index, index=px.index).shift(-2)
    for name, series in ratios.items():
        panel[name] = series.reindex(px.index).shift(lag)
    return panel.loc[panel.index <= "2019-10-04", BASE + list(ratios) + ["target", "exit_date"]]


def compare(panel, name):
    # Both specifications use exactly the same complete observations.
    common = panel.dropna(subset=BASE + [name, "target", "exit_date"])
    train = common.loc[(common.index < "2017-01-01") & (common.exit_date < "2017-01-01")]
    test = common.loc[common.index >= "2017-01-01"]
    base = fit_predict(train, test, BASE)
    extra = fit_predict(train, test, BASE + [name])
    y = test.target.to_numpy()
    base_mse, extra_mse = np.mean((y-base)**2), np.mean((y-extra)**2)
    annual = {}
    for year in sorted(set(test.index.year)):
        mask = test.index.year == year
        annual[str(year)] = float(1 - np.mean((y[mask]-extra[mask])**2) / np.mean((y[mask]-base[mask])**2))
    return {"train_n": len(train), "test_n": len(test),
            "train_range": [str(train.index.min().date()), str(train.index.max().date())],
            "test_range": [str(test.index.min().date()), str(test.index.max().date())],
            "corr_ratio_flow_test": float(test[name].corr(test["돈흐름점수"])),
            "rmse_base_bp": float(np.sqrt(base_mse)*10000),
            "rmse_plus_bp": float(np.sqrt(extra_mse)*10000),
            "relative_mse_improvement": float(1-extra_mse/base_mse),
            "relative_mse_improvement_by_year": annual}


def main():
    result = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "point_in_time_vintages_verified": False, "manifest": {}}
    ratios = {}
    for name in ("equitypc", "indexpc"):
        url = f"https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/{name}.csv"
        r = get(url)
        frame = pd.read_csv(io.StringIO(r.text), skiprows=2)
        dates = pd.to_datetime(frame.DATE.str.strip(), format="%m/%d/%Y")
        assert not dates.duplicated().any()
        ratios[name] = pd.Series(frame["P/C Ratio"].to_numpy(), index=dates).sort_index()
        result["manifest"][name] = {"url": url, "sha256": hashlib.sha256(r.content).hexdigest(),
                                  "rows": len(frame), "first": str(dates.min().date()), "last": str(dates.max().date())}
    params = {"period1": int(pd.Timestamp("2012-01-01", tz="UTC").timestamp()),
              "period2": int(pd.Timestamp("2019-10-10", tz="UTC").timestamp()),
              "interval": "1d", "events": "div,splits"}
    r = get("https://query1.finance.yahoo.com/v8/finance/chart/SPY", params=params)
    j = r.json()["chart"]["result"][0]
    dates = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    px = pd.DataFrame(j["indicators"]["quote"][0], index=dates).rename(columns=str.title)
    adjustment = np.array(j["indicators"]["adjclose"][0]["adjclose"]) / px.Close
    # Radar downloads auto_adjust=False; preserve raw OHLC for its features.
    # Use adjusted open only as a vendor total-return proxy for the outcome.
    px["OutcomeOpen"] = px.Open * adjustment
    assert px.index.is_unique and px.index.is_monotonic_increasing
    assert px[["Open", "High", "Low", "Close", "Volume", "OutcomeOpen"]].notna().all().all()
    result["manifest"]["prices"] = {"url": r.url, "sha256": hashlib.sha256(r.content).hexdigest(),
                                     "rows": len(px), "adjustment": "raw OHLC features; current-vintage adjclose/close on outcome open only"}
    import exchange_calendars as calendars
    sessions = calendars.get_calendar("XNYS", start="2012-01-01", end="2019-10-09").sessions.tz_localize(None)
    if len(px.index.difference(sessions)):
        raise ValueError("Unexpected price dates outside exchange calendar")
    result["manifest"]["sessions"] = {"calendar": "XNYS", "version": calendars.__version__,
        "expected": len(sessions), "missing_price_rows": len(sessions.difference(px.index))}
    result["comparisons"] = {}
    for lag in (1, 2):
        panel = make_panel(px, ratios, lag, sessions=sessions)
        result["comparisons"][f"ratio_lag_{lag}_price_sessions"] = {name: compare(panel, name) for name in ratios}
    result["finra_format_probe_only"] = []
    for date in ("20191002", "20191003", "20191004"):
        url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
        r = get(url)
        frame = pd.read_csv(io.StringIO(r.text), sep="|")
        row = frame.loc[frame.Symbol.eq("SPY")].iloc[0]
        short, exempt, total = (int(row[k]) for k in ("ShortVolume", "ShortExemptVolume", "TotalVolume"))
        assert 0 <= exempt <= short <= total
        result["finra_format_probe_only"].append({"date": date, "symbol": "SPY", "short": short,
            "exempt_subset": exempt, "total_same_scope": total, "ratio": short/total,
            "url": url, "sha256": hashlib.sha256(r.content).hexdigest()})
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
