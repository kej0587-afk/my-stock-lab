"""Offline SOXS hypothesis study; never imported by production.

run_study(soxs, soxx, spy, *, sessions, completed_through, adjusted_ohlc=True)
accepts date-indexed DataFrames. SOXS requires consistently adjusted OHLC;
SOXX/SPY require adjusted Close. Adjustment is a caller attestation, not inferred
from prices; no extra split/dividend adjustment is applied. Supply an authoritative
exchange-session index (including missing observations), not the price index or
a weekday approximation. completed_through must be the last *completed* session.

Signal: SOXX close < its inclusive MA20 AND SPY close < its inclusive MA50.
This is a market-defense PROXY, NOT reconstructed historical macro policy.
Enter next session's Open, exit fifth session's Close (entry day counts as one).
No overlapping lots; an exit-day signal may enter the following open. Each trade
uses up to 5% of INITIAL capital including entry costs, capped by available cash.
Profits never increase the cap; depleted hedge cash is not replenished from stocks.
30/60bp roundtrip assumptions mean 15/30bp on each side's execution notional.

Optional portfolio_returns is an anonymous noncash-sleeve daily return Series,
constructed upstream from the user's fixed-weight portfolio, in the SAME currency
as the account. cash_weight is initial cash / capital, at least 5%. The same compounded
risky sleeve appears in both hedge arms; no stocks are sold to fund the hedge.
No automatic restoration of initial account weights, interest, tax, FX conversion
fees or additional portfolio turnover costs are modeled. Optional usdkrw (Open/Close)
converts SOXS entry/exit/marks to KRW, leaving account cash in KRW. These daily FX
bars are an asynchronous conversion approximation, NOT simultaneous executable
exchange rates. No FX forward-fill. Without usdkrw all account inputs must be USD.
The first return is measured
from the initial account valuation immediately before the first supplied session.

Returns in-memory cases with daily curve, trade ledger, signal ledger, and summary.
Incomplete/missing-data trades are excluded from completed-trade statistics, NOT
retroactively erased from observed equity. Full-horizon mark_to_market accounts
separately liquidate any open lot at the final observed Close INCLUDING exit cost.
This endpoint assumption is not a five-session completed trade. No period trimming.
Missing OHLC still makes strategy return/MDD unverified; missing marks remain NaN.
No private holdings, weights, paths or input series are echoed. CLI only accepts
public price/session CSVs and prints aggregate research results; no account export.
"""

import argparse
import json

import numpy as np
import pandas as pd


NOTE = "Market-defense proxy only: SOXX<MA20 & SPY<MA50; not historical macro replay"
OHLC = ["Open", "High", "Low", "Close"]


def _dates(index):
    if not isinstance(index, pd.DatetimeIndex) or index.tz is not None:
        raise ValueError("Use timezone-naive exchange-session date indexes")
    if (index.hasnans or index.has_duplicates or not index.is_monotonic_increasing
            or not index.equals(index.normalize())):
        raise ValueError("Session dates must be unique, sorted and normalized")
    return index


def _prices(frame, columns, sessions):
    if (not isinstance(frame, pd.DataFrame) or frame.columns.has_duplicates
            or any(col not in frame for col in columns)):
        raise ValueError("Required adjusted price columns are missing")
    _dates(frame.index)
    # Ignore extra dates outside the requested interval, reject off-calendar rows within it.
    inside = frame.index[(frame.index >= sessions[0]) & (frame.index <= sessions[-1])]
    if not inside.isin(sessions).all():
        raise ValueError("Prices contain dates outside the supplied exchange calendar")
    values = frame.reindex(sessions)[columns].apply(pd.to_numeric, errors="coerce")
    return values.where(np.isfinite(values) & values.gt(0))


def _performance(series, capital, verified=True):
    if not verified or series.isna().any():
        return {"verified": False, "net_return": None, "mdd": None}
    values = np.r_[capital, series.to_numpy(dtype=float)]
    drawdown = values / np.maximum.accumulate(values) - 1
    return {"verified": True, "net_return": float(values[-1] / capital - 1),
            "mdd": float(drawdown.min())}


def _case(prices, signal, rising, signal_known, portfolio, cash_weight, capital, bps, fx):
    cost = bps / 20000.0
    budget = capital * .05
    cash = capital
    hedge_cash = capital * cash_weight if portfolio is not None else None
    position = None
    pending = None
    halted = False
    trades, signals, curves = [], [], []
    valid = prices.notna().all(axis=1) & (
        prices.High >= prices[["Open", "Low", "Close"]].max(axis=1)) & (
        prices.Low <= prices[["Open", "High", "Close"]].min(axis=1))
    for i, (day, bar) in enumerate(prices.iterrows()):
        opening = bar.Open * fx.Open.iloc[i]
        closing = bar.Close * fx.Close.iloc[i]
        if pending is not None:
            event = signals[pending]
            # Only the entry Open is known at execution; never inspect this day's
            # High/Low/Close (or the next four bars) to decide whether to enter.
            if pd.isna(opening):
                event["status"] = "excluded_missing_or_zero_open"
            elif cash <= 0:
                event["status"] = "excluded_insufficient_cash"
            else:
                allocation = min(budget, cash)
                hedge_allocation = min(budget, hedge_cash) if hedge_cash is not None else 0.0
                units = allocation / (float(opening) * (1 + cost))
                hedge_units = hedge_allocation / (float(opening) * (1 + cost))
                position = {"signal_date": event["signal_date"], "entry_date": day,
                            "entry_index": i, "exit_index": i + 4,
                            "entry_price": float(opening), "units": units,
                            "allocation": allocation, "hedge_allocation": hedge_allocation,
                            "hedge_units": hedge_units,
                            "entry_cost": units * float(opening) * cost,
                            "soxx_up_signal": event["soxx_up_signal"], "missing": False}
                cash -= allocation
                if hedge_cash is not None:
                    hedge_cash -= hedge_allocation
                event["status"] = "entered"
            pending = None
        value = 0.0
        hedge_value = 0.0
        if position is not None:
            if not valid.iloc[i] or pd.isna(closing):
                position["missing"] = True
            value = position["units"] * closing if valid.iloc[i] else np.nan
            hedge_value = position["hedge_units"] * closing if valid.iloc[i] else np.nan
            if i == position["exit_index"]:
                # An observed exit Close can settle cash even if another OHLC field
                # is missing, but the trade and performance remain unverified.
                proceeds = position["units"] * closing * (1 - cost)
                cash += proceeds
                if hedge_cash is not None:
                    hedge_cash += position["hedge_units"] * closing * (1 - cost)
                status = "excluded_missing_ohlc" if position["missing"] else "completed"
                trades.append(dict(signal_date=position["signal_date"],
                                   entry_date=position["entry_date"], exit_date=day,
                                   entry_price=position["entry_price"], exit_price=closing,
                                   holding_sessions=5, status=status,
                                   allocation=position["allocation"],
                                   hedge_allocation=position["hedge_allocation"],
                                   soxx_up_signal=position["soxx_up_signal"],
                                   net_return=float(proceeds / position["allocation"] - 1),
                                   cost_amount=float(position["entry_cost"] +
                                                     position["units"] * closing * cost)))
                halted = pd.isna(cash)
                position, value, hedge_value = None, 0.0, 0.0
        row = {"date": day, "cash": capital, "soxs_5pct": cash + value}
        if portfolio is not None:
            row.update(portfolio_cash=float(portfolio.iloc[i] + capital * cash_weight),
                       portfolio_hedge=float(portfolio.iloc[i] + hedge_cash + hedge_value))
        curves.append(row)
        if signal.iloc[i]:
            status = ("blocked_unknown_cash" if halted else "blocked_overlap" if position is not None
                      else "no_next_open" if i + 1 == len(prices) else "pending")
            signals.append({"signal_date": day, "soxx_up_signal": bool(rising.iloc[i]), "status": status})
            if status == "pending":
                pending = len(signals) - 1
    if position is not None:
        trades.append(dict(signal_date=position["signal_date"], entry_date=position["entry_date"],
                           exit_date=pd.NaT, entry_price=position["entry_price"], exit_price=np.nan,
                           holding_sessions=len(prices) - position["entry_index"],
                           allocation=position["allocation"], hedge_allocation=position["hedge_allocation"],
                           status="incomplete_end_missing_ohlc" if position["missing"] else "incomplete_end",
                           soxx_up_signal=position["soxx_up_signal"], net_return=np.nan, cost_amount=np.nan))
    curve = pd.DataFrame(curves).set_index("date")
    liquidated_curve = curve.copy()
    exit_cost = hedge_exit_cost = 0.0
    if position is not None:
        last_mark = prices.Close.iloc[-1] * fx.Close.iloc[-1]
        exit_cost = float(position["units"] * last_mark * cost)
        hedge_exit_cost = float(position["hedge_units"] * last_mark * cost)
        liquidated_curve.loc[curve.index[-1], "soxs_5pct"] -= exit_cost
        if portfolio is not None:
            liquidated_curve.loc[curve.index[-1], "portfolio_hedge"] -= hedge_exit_cost
    completed = [trade for trade in trades if trade["status"] == "completed"]
    verified = len(completed) == len(trades)
    performance = {col: _performance(curve[col], capital,
                                    col in {"cash", "portfolio_cash"} or verified) for col in curve}
    mtm_verified = all(trade["status"] in {"completed", "incomplete_end"} for trade in trades)
    mtm_performance = {col: _performance(liquidated_curve[col], capital,
                                        col in {"cash", "portfolio_cash"} or mtm_verified) for col in curve}
    grouped = {}
    for label, subset in (("all", completed), ("soxx_up_signal", [t for t in completed if t["soxx_up_signal"]])):
        returns = [t["net_return"] for t in subset]
        grouped[label] = {"completed_trades": len(subset),
                          "max_trade_loss": max(0.0, -min(returns)) if returns else None,
                          "mean_net_return": float(np.mean(returns)) if returns else None,
                          "holding_sessions": 5 if returns else None}
    counts = pd.Series([s["status"] for s in signals], dtype=object).value_counts().to_dict()
    summary = {"roundtrip_cost_bps": bps, "signal_count": int(signal.sum()),
               "soxx_up_signal_count": int((signal & rising).sum()),
               "signal_unavailable_sessions": int((~signal_known).sum()),
               "signal_status_counts": {k: int(v) for k, v in counts.items()},
               "excluded_or_incomplete_trades": len(trades) - len(completed),
               "trade_statistics": grouped, "accounts": performance,
               "mark_to_market": {
                   "assumption": "Entire period; terminal open lot liquidated at last observed Close with exit cost; not a completed five-session trade",
                   "terminal_open_position": position is not None,
                   "terminal_exit_cost": exit_cost if np.isfinite(exit_cost) else None,
                   "terminal_hedge_exit_cost": hedge_exit_cost if np.isfinite(hedge_exit_cost) else None,
                   "accounts": mtm_performance}}
    return {"curve": curve, "mark_to_market_curve": liquidated_curve, "trades": pd.DataFrame(trades),
            "signals": pd.DataFrame(signals), "summary": summary}


def run_study(soxs, soxx, spy, *, sessions, completed_through, adjusted_ohlc,
              portfolio_returns=None, cash_weight=None, capital=100_000.0, usdkrw=None,
              evaluation_start=None):
    """See module contract. Outputs contain no holdings identifiers or raw inputs."""
    if adjusted_ohlc is not True:
        raise ValueError("Explicitly confirm consistently adjusted OHLC inputs")
    sessions = _dates(sessions)
    cutoff = pd.Timestamp(completed_through)
    if pd.isna(cutoff) or cutoff.tzinfo is not None or cutoff != cutoff.normalize():
        raise ValueError("completed_through must be a completed exchange-session date")
    sessions = sessions[sessions <= cutoff]
    if sessions.empty or not np.isfinite(capital) or capital <= 0:
        raise ValueError("Nonempty completed sessions and positive capital required")
    prices = _prices(soxs, OHLC, sessions)
    sector = _prices(soxx, ["Close"], sessions).Close
    broad = _prices(spy, ["Close"], sessions).Close
    ma20, ma50 = sector.rolling(20).mean(), broad.rolling(50).mean()
    known = ma20.notna() & ma50.notna()
    signal = sector.lt(ma20) & broad.lt(ma50) & known
    rising = sector.gt(sector.shift(1))
    # Compute moving averages on the supplied warmup first; account evaluation can
    # start later, e.g. at a common inception date for a hypothetical portfolio.
    if evaluation_start is not None:
        start = pd.Timestamp(evaluation_start)
        if pd.isna(start) or start.tzinfo is not None or start != start.normalize():
            raise ValueError("evaluation_start must be a session date")
        sessions = sessions[sessions >= start]
        if sessions.empty:
            raise ValueError("No completed evaluation sessions")
        prices, signal, rising, known = (value.reindex(sessions) for value in (prices, signal, rising, known))
    if usdkrw is None:
        fx = pd.DataFrame({"Open": 1., "Close": 1.}, index=sessions)
    else:
        # FX trades on some equity holidays, so those extra source dates are valid.
        if not isinstance(usdkrw, pd.DataFrame):
            raise ValueError("Daily USD/KRW Open/Close DataFrame required")
        _dates(usdkrw.index)
        fx = _prices(usdkrw.loc[usdkrw.index.isin(sessions)], ["Open", "Close"], sessions)
    portfolio = None
    if portfolio_returns is not None:
        if not isinstance(portfolio_returns, pd.Series):
            raise ValueError("Anonymous noncash-sleeve daily return Series required")
        _dates(portfolio_returns.index)
        if cash_weight is None or not np.isfinite(cash_weight) or not .05 <= cash_weight <= 1:
            raise ValueError("Initial cash fraction must be between 0.05 and 1")
        returns = pd.to_numeric(portfolio_returns.reindex(sessions), errors="coerce")
        if not np.isfinite(returns).all() or (returns <= -1).any():
            raise ValueError("Portfolio returns must cover every completed session and exceed -1")
        portfolio = capital * (1 - cash_weight) * (1 + returns).cumprod()
    elif cash_weight is not None:
        raise ValueError("cash_weight requires anonymous portfolio returns")
    return {"note": NOTE, "allocation": "Up to 5% initial capital, capped by remaining cash; entry day is holding day 1",
            "currency": "USD" if usdkrw is None else "KRW",
            "fx_note": "none" if usdkrw is None else "Daily FX Open/Close approximation; not synchronous execution FX",
            "portfolio_note": "Hypothetical current-weight sleeve, NOT actual historical account P&L; cash fraction is a caller assumption",
            "cases": {str(bps): _case(prices, signal, rising, known, portfolio, cash_weight, capital, bps, fx)
                      for bps in (30, 60)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("soxs", "soxx", "spy", "sessions", "completed-through"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--adjusted-ohlc", action="store_true", required=True)
    parser.add_argument("--usdkrw", help="Optional public daily FX CSV; account cash then stays in KRW")
    args = parser.parse_args(argv)
    try:
        frames = [pd.read_csv(path, index_col="Date", parse_dates=["Date"])
                  for path in (args.soxs, args.soxx, args.spy)]
        sessions = pd.DatetimeIndex(pd.to_datetime(pd.read_csv(args.sessions)["Date"]))
        fx = pd.read_csv(args.usdkrw, index_col="Date", parse_dates=["Date"]) if args.usdkrw else None
        result = run_study(*frames, sessions=sessions, completed_through=args.completed_through,
                           adjusted_ohlc=args.adjusted_ohlc, usdkrw=fx)
    except (OSError, ValueError, KeyError, TypeError):
        parser.error("Invalid local research CSV/date/schema; input paths and contents are not echoed")
    print(json.dumps({"note": result["note"], "currency": result["currency"], "fx_note": result["fx_note"], "cases": {
        key: value["summary"] for key, value in result["cases"].items()}}, allow_nan=False))


if __name__ == "__main__":
    main()
