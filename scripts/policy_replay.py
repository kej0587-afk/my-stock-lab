"""Policy validation replay (2026-11-24): re-run the current decision engine on past dates.

Read-only. No decision rule is changed; this only calls the existing engine on history.
- Prices: daily OHLCV CSVs (Date,Open,High,Low,Close,Volume) in --px, one file per ticker
  (Yahoo chart API, split-adjusted, not dividend-adjusted, like yfinance auto_adjust=False).
  Price files are not committed.
- app.load_price_df is replaced in this process by a reader that cuts the CSV at the replay
  date, so RS, RS slope and benchmark lookups use only data up to that date. Network fetchers
  are replaced by a function that raises, so a missing file can never pull today's data.
- Live-quote helpers return the replay-date close. Investor-flow history (KR) and display-name
  lookups are not replayed; they fail closed or only affect names.
- Fixed assumptions (not history): fin_score 4, unheld candidate (stocks), macro 1.0 /
  penalty 0 unless a macro variant is named, no chart-pattern input (pattern detection is not
  part of calc_scores_and_decision), market guard 정상 for leveraged gates unless noted.
Run:
  python -X utf8 scripts/policy_replay.py stocks   --px DIR --out DIR
  python -X utf8 scripts/policy_replay.py leverage --px DIR --out DIR
  python -X utf8 scripts/policy_replay.py parity   --px DIR --out DIR --step 20   # B-stage identity check
  python -X utf8 scripts/policy_replay.py rr_gate  --px DIR --out DIR --stocks-csv DIR/stocks.csv
Record: docs/maintenance/20261124_decision_policy_validation_plan.md
"""
import argparse
import math
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["STOCK_LAB_FORCE_AUTH_MODE"] = "public_demo"
import logging

logging.disable(logging.CRITICAL)
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

PX = ""
ASOF = {"d": None}
_CACHE = {}
PERIOD_ROWS = {"5d": 5, "1mo": 22, "3mo": 64, "6mo": 126, "1y": 252, "2y": 504, "5y": 1260, "10y": 2520, "max": 99999}

US_STOCKS = ["NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX", "COST", "LLY", "PLTR",
             "CRWD", "ANET", "INTC", "BA", "NKE", "PYPL", "DIS", "PFE"]
KR_STOCKS = ["005930.KS", "000660.KS", "035420.KS", "005380.KS", "051910.KS", "035720.KS", "068270.KS", "207940.KS",
             "012450.KS", "042700.KS", "000270.KS", "105560.KS"]
LEVERAGED = {"TQQQ": "us_etf_nasdaq", "QLD": "us_etf_nasdaq", "SOXL": "us_etf_nasdaq"}

# Setup families for the R/R study, by current decision_code (codes unchanged).
FAMILY = {
    "NEW_ENTRY_LEADER": "대장주", "LEADER_MA5_PULLBACK_ENTRY": "MA5 예외(대장주 눌림)",
    "LEADER_MA5_FAST_PULLBACK_ENTRY": "MA5 예외(대장주 눌림)", "EXCEPTION_ENTRY": "예외승인(FVG·%B)",
    "BREAKOUT_52W_ENTRY": "52주 신고가 돌파", "QUALITY_RECOVERY_SCOUT": "우량주 회복",
    "QUALITY_RECOVERY_CANDIDATE": "우량주 회복", "QUALITY_RECOVERY_WATCH": "우량주 회복(관찰)",
    "S_PULLBACK_ENTRY": "일반 눌림", "QUALITY_PULLBACK_ENTRY": "일반 눌림", "TREND_PULLBACK_EXPLORE": "일반 눌림",
    "EARLY_ENTRY": "선진입·반전초입", "EARLY_REVERSAL_ENTRY": "선진입·반전초입",
    "OVERSOLD_NEW_ENTRY": "과매도 진입", "A_GRADE_TECH_REBOUND": "A급 기술적 반등",
}


def local_price(ticker, period="1y"):
    path = os.path.join(PX, f"{ticker}.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    if ticker not in _CACHE:
        _CACHE[ticker] = pd.read_csv(path, index_col=0, parse_dates=True)
    df = _CACHE[ticker]
    df = df[df.index <= ASOF["d"]]
    return df.tail(PERIOD_ROWS.get(period, 252)).copy()


def _no_network(*args, **kwargs):
    raise RuntimeError("network disabled in replay")


def setup_app():
    import app
    from stock_lab_core import prices

    prices._fetch_yfinance_ohlcv = _no_network
    prices._fetch_pykrx_ohlcv = _no_network
    app.load_price_df = local_price
    # Live quotes (leveraged comparison rows use them) must be the replay-date close, never today's quote.
    app.load_display_live_price = _replay_close
    app.load_latest_price = _replay_close
    prices.load_latest_price = _replay_close
    return app


def _replay_close(ticker, *args, **kwargs):
    df = local_price(str(ticker), "5d")
    return float(df["Close"].iloc[-1]) if not df.empty else 0.0


def gate_of(c, name, ticker, is_etf, has_pos, guard=None):
    from stock_lab_core.decision_workflow import build_decision_workflow, attach_market_execution_context
    from stock_lab_core.execution_gate import build_execution_gate

    w = build_decision_workflow(name, ticker, c, is_etf=is_etf, has_pos=has_pos,
                                pattern_timing="-", pattern_bucket="", pattern_reason="")
    if guard is not None:
        w = attach_market_execution_context(pd.DataFrame([w]), guard).iloc[0].to_dict()
    g = build_execution_gate(w)
    return g["게이트상태"], g["게이트근거"]


# ── alternative targets (computed from data up to the replay date only) ──────────────
def hvn_target(hist, cur):
    h = hist.tail(120)
    lo, hi = float(h["Low"].min()), float(h["High"].max())
    if not (hi > lo > 0):
        return float("nan")
    bins = np.linspace(lo, hi, 25)
    typical = ((h["High"] + h["Low"] + h["Close"]) / 3).to_numpy()
    vol, _ = np.histogram(typical, bins=bins, weights=h["Volume"].fillna(0).to_numpy())
    centers = (bins[:-1] + bins[1:]) / 2
    cut = np.percentile(vol, 70)
    above = [c for c, v in zip(centers, vol) if c > cur * 1.01 and v >= cut]
    return float(min(above)) if above else float("nan")  # nan = no overhead high-volume node


def measured_move_target(hist, cur):
    h = hist.tail(61).iloc[:-1]
    if len(h) < 40:
        return float("nan")
    height = float(h["High"].max() - h["Low"].min())
    return max(cur, float(h["High"].max())) + height


def structure_target(hist, cur):
    yr_high = float(hist.tail(252)["High"].max())
    return yr_high if yr_high >= cur * 1.03 else measured_move_target(hist, cur)


def forward_outcome(fut, cur, stop, target, horizon=120):
    """First touch of stop or target within horizon; else mark-to-market. Returns R multiple."""
    risk = cur - stop
    if not (risk > 0) or not math.isfinite(target) or target <= cur:
        return float("nan"), "n/a"
    f = fut.head(horizon)
    for _, r in f.iterrows():
        if r["Low"] <= stop:
            return -1.0, "stop"
        if r["High"] >= target:
            return (target - cur) / risk, "target"
    if f.empty:
        return float("nan"), "n/a"
    return (float(f["Close"].iloc[-1]) - cur) / risk, "open"


def trend_exit(fut, cur, stop, atr, horizon=120):
    """Initial stop cur-2ATR, then 3ATR chandelier from the highest close; exit on close below."""
    risk = cur - stop
    if not (risk > 0):
        return float("nan"), 0
    best, days = cur, 0
    for _, r in fut.head(horizon).iterrows():
        days += 1
        if r["Low"] <= stop:
            return (stop - cur) / risk, days
        best = max(best, float(r["Close"]))
        stop = max(stop, best - 3 * atr)
        if r["Close"] < stop:
            return (float(r["Close"]) - cur) / risk, days
    if days == 0:
        return float("nan"), 0
    return (float(fut.head(horizon)["Close"].iloc[-1]) - cur) / risk, days


MACRO_VARIANTS = {  # name: (final_macro_risk seen by conditions, adj penalty)
    "cur_3.0": (3.0, 1.5), "cur_3.8": (3.8, 1.5), "cur_4.2": (4.2, 2.0),
    "pen_only_3.0": (1.0, 1.5), "pen_only_3.8": (1.0, 1.5), "pen_only_4.2": (1.0, 2.0),
}


def replay_stock(args):
    ticker, start, end, step = args
    app = setup_app()
    from stock_lab_core.ta_engine import build_indicators

    full = pd.read_csv(os.path.join(PX, f"{ticker}.csv"), index_col=0, parse_dates=True)
    ac = "kr_stock" if ticker.endswith(".KS") else "us_stock"
    dates = full.index[(full.index >= start) & (full.index <= end)][::step]
    out = []
    for d in dates:
        ASOF["d"] = d
        hist = full[full.index <= d]
        if len(hist) < 260:
            continue
        df = build_indicators(hist.tail(252).copy())
        base = dict(user_total_asset=1e7, user_curr_w=0.0, user_targ_w=10.0, _total_eval=1e7,
                    _cash_available=0.0, _reserve_available=0.0)
        try:
            c = app.calc_scores_and_decision(ticker, ticker, False, ac, df, 0.0, False, 4,
                                             _macro_penalty=0.0, _final_macro_risk=1.0, **base)
        except Exception as e:  # keep the row so failures are counted, not hidden
            out.append({"ticker": ticker, "date": d.date(), "error": repr(e)[:120]})
            continue
        cur = float(c["cur_p"])
        atr = float(c.get("atr") or float("nan"))
        stop = float(c.get("rr_stop") or float("nan"))
        fut = full[full.index > d]
        gate, gate_why = gate_of(c, ticker, ticker, False, False)
        row = {"ticker": ticker, "date": d.date(), "code": c["decision_code"], "group": c.get("decision_group"),
               "family": FAMILY.get(c["decision_code"], ""), "grade": str(c.get("grade", ""))[:3],
               "is_52w_breakout": bool(c.get("is_52w_breakout")), "cur": cur, "atr": atr, "stop": stop,
               "rr": c.get("rr_ratio"), "rr_target": c.get("rr_target"), "rr_src": c.get("rr_target_source"),
               "rr_proj": bool(c.get("rr_target_is_projection")), "gate": gate, "gate_why": gate_why}
        for k in (20, 60, 120):
            row[f"ret{k}"] = float(fut["Close"].iloc[k - 1] / cur - 1) if len(fut) >= k else float("nan")
        f60 = fut.head(60)
        row["mfe60"] = float(f60["High"].max() / cur - 1) if len(f60) else float("nan")
        row["mae60"] = float(f60["Low"].min() / cur - 1) if len(f60) else float("nan")
        if row["family"]:
            targets = {"pivot": float(c.get("rr_target") or float("nan")), "hvn": hvn_target(hist, cur),
                       "mm": measured_move_target(hist, cur), "struct": structure_target(hist, cur)}
            for name, t in targets.items():
                risk = cur - stop
                row[f"t_{name}"] = t
                row[f"rr_{name}"] = (t - cur) / risk if risk > 0 and math.isfinite(t) else float("nan")
                row[f"R_{name}"], row[f"hit_{name}"] = forward_outcome(fut, cur, stop, t)
            row["R_trend"], row["days_trend"] = trend_exit(fut, cur, stop, atr)
            for name, (fmr, pen) in MACRO_VARIANTS.items():
                try:
                    v = app.calc_scores_and_decision(ticker, ticker, False, ac, df, 0.0, False, 4,
                                                     _macro_penalty=pen, _final_macro_risk=fmr, **base)
                    row[f"m_{name}"] = v["decision_code"]
                    row[f"mg_{name}"] = gate_of(v, ticker, ticker, False, False)[0]
                except Exception as e:
                    row[f"m_{name}"] = "ERR"
        out.append(row)
    return out


def replay_rr_gate(args):
    """Counterfactual gate: same engine result, R/R target swapped for an alternative.

    Only the R/R fields handed to the gate change (rr_ratio, rr_target, projection flag);
    the decision code, stop and every other field stay as the engine produced them.
    """
    ticker, rows = args
    app = setup_app()
    from stock_lab_core.ta_engine import build_indicators

    full = pd.read_csv(os.path.join(PX, f"{ticker}.csv"), index_col=0, parse_dates=True)
    ac = "kr_stock" if ticker.endswith(".KS") else "us_stock"
    out = []
    for r in rows:
        d = pd.Timestamp(r["date"])
        ASOF["d"] = d
        hist = full[full.index <= d]
        df = build_indicators(hist.tail(252).copy())
        c = app.calc_scores_and_decision(ticker, ticker, False, ac, df, 0.0, False, 4, user_total_asset=1e7,
                                         user_curr_w=0.0, user_targ_w=10.0, _macro_penalty=0.0,
                                         _final_macro_risk=1.0, _total_eval=1e7, _cash_available=0.0,
                                         _reserve_available=0.0)
        res = {"ticker": ticker, "date": r["date"], "code": c["decision_code"],
               "gate_pivot": gate_of(c, ticker, ticker, False, False)[0]}
        cur, stop = float(c["cur_p"]), float(c.get("rr_stop") or float("nan"))
        for name in ("hvn", "mm", "struct"):
            t = r.get(f"t_{name}")
            if not (isinstance(t, float) and math.isfinite(t) and t > cur and cur > stop):
                res[f"gate_{name}"] = "목표없음"
                continue
            alt = dict(c, rr_ratio=(t - cur) / (cur - stop), rr_target=t, rr_target_is_projection=False,
                       rr_target_source=name, rr_tp1=t)
            g, why = gate_of(alt, ticker, ticker, False, False)
            res[f"gate_{name}"], res[f"why_{name}"] = g, why
        # trend-following exit has no price target: treat R/R as not limiting (rr fixed at 1.0)
        alt = dict(c, rr_ratio=1.0, rr_target_is_projection=False, rr_target_source="trend")
        res["gate_trend"], res["why_trend"] = gate_of(alt, ticker, ticker, False, False)
        out.append(res)
    return out


GUARDS = {"정상": {"mode": "정상", "us_stats": {"mode": "정상"}, "kr_stats": {"mode": "정상"}},
          "미국 방어": {"mode": "주의", "us_stats": {"mode": "방어"}, "kr_stats": {"mode": "정상"}}}


def replay_leverage(args):
    ticker, start, end, step = args
    app = setup_app()
    from stock_lab_core.ta_engine import build_indicators

    full = pd.read_csv(os.path.join(PX, f"{ticker}.csv"), index_col=0, parse_dates=True)
    ac = LEVERAGED[ticker]
    dates = full.index[(full.index >= start) & (full.index <= end)][::step]
    out = []
    for d in dates:
        ASOF["d"] = d
        hist = full[full.index <= d]
        if len(hist) < 260:
            continue
        df = build_indicators(hist.tail(252).copy())
        cur_close = float(hist["Close"].iloc[-1])
        fut = full[full.index > d]
        for avg_mult in (1.0, 1.15, 1.35, 1.6, 2.0):
            avg = cur_close * avg_mult
            try:
                c = app.calc_scores_and_decision(ticker, ticker, True, ac, df, avg, True, 0, user_total_asset=1e7,
                                                 user_curr_w=3.0, user_targ_w=9.0, _macro_penalty=0.0,
                                                 _final_macro_risk=1.0, _total_eval=1e7, _cash_available=0.0,
                                                 _reserve_available=0.0)
                ov = app.apply_leveraged_precision_decision_override(
                    app.apply_leveraged_dca_dashboard_override(dict(c)), ticker, ticker, True, avg)
            except Exception as e:
                out.append({"ticker": ticker, "date": d.date(), "avg_mult": avg_mult, "error": repr(e)[:120]})
                continue
            row = {"ticker": ticker, "date": d.date(), "avg_mult": avg_mult, "pnl": cur_close / avg - 1,
                   "dd": c.get("dd"), "trend": c.get("trend"), "rsi": c.get("rsi"), "pct_b": c.get("pct_b"),
                   "engine_code": c["decision_code"], "engine_dec": c["dec"],
                   "reb_mult": app._rebcalc_signal_multiplier(c["dec"], "leverage"),
                   "today_code": ov["decision_code"], "today_dec": ov["dec"],
                   "stage": ov.get("leveraged_dca_stage"), "recovery": ov.get("leveraged_recovery_label")}
            for gname, guard in GUARDS.items():
                row[f"gate_today_{gname}"], row[f"why_today_{gname}"] = gate_of(ov, ticker, ticker, True, True, guard)
                row[f"gate_engine_{gname}"] = gate_of(c, ticker, ticker, True, True, guard)[0]
            for k in (20, 60, 120, 250):
                row[f"ret{k}"] = float(fut["Close"].iloc[k - 1] / cur_close - 1) if len(fut) >= k else float("nan")
            out.append(row)
    return out


# ── parity: B-stage "results must be identical" check ─────────────────────────────────
PARITY_ETFS = {"QQQ": "us_etf_nasdaq", "SPY": "us_etf_sp", "SOXX": "us_etf_nasdaq", "XLK": "us_etf_sp",
               "069500.KS": "kr_etf", "091160.KS": "kr_etf"}


def _multiplier(app, c, bucket, dip_level):
    """Rebalance multiplier through whatever entry point the app currently uses."""
    fn = getattr(app, "rebalance_signal_multiplier_for_decision", None)
    if fn is not None:
        return fn(c, bucket, dip_level=dip_level)
    return app._rebcalc_signal_multiplier(c["dec"], bucket, dip_level=dip_level)


def _parity_row(app, c, name, ticker, is_etf, has_pos, my_price, chart_df, guard=None):
    from stock_lab_core.decision_workflow import build_decision_workflow, attach_market_execution_context
    from stock_lab_core.execution_gate import build_execution_gate

    row = {"code": c["decision_code"], "dec": c["dec"], "group": c.get("decision_group"),
           "buy_amt": c.get("buy_amt"), "core_dca_rate": c.get("core_dca_rate"), "core_dca_amt": c.get("core_dca_amt"),
           "sizing_hint": c.get("sizing_hint"), "grade": c.get("grade"), "safety": c.get("safety_state")}
    for bucket in ("core", "swing", "leverage"):
        for dip in (0, 2):
            row[f"mult_{bucket}_{dip}"] = _multiplier(app, c, bucket, dip)
    # Today chain: MTF guard (weekly/monthly) → dashboard override → precision override → pattern → gate
    try:
        mtf = app.build_precision_multi_timeframe_pack(ticker, chart_df, _include_daily_snapshot=False)
        t = app.apply_precision_mtf_decision_guard(c, mtf, has_pos=has_pos, ticker=ticker)
    except Exception as e:
        t = dict(c, mtf_bias_label="자료부족", data_state="상위시간대 조회 실패")
    t = app.apply_leveraged_dca_dashboard_override(t)
    t = app.apply_leveraged_precision_decision_override(t, name, ticker, has_pos, my_price)
    try:
        timing, reason, bucket_ = app.summarize_chart_pattern_for_dashboard(app.detect_chart_pattern_candidates(chart_df), t)
    except Exception:
        timing, reason, bucket_ = "-", "", ""
    w = build_decision_workflow(name, ticker, t, is_etf=is_etf, has_pos=has_pos,
                                pattern_timing=timing, pattern_bucket=bucket_, pattern_reason=reason)
    if guard is not None:
        w = attach_market_execution_context(pd.DataFrame([w]), guard).iloc[0].to_dict()
    g = build_execution_gate(w)
    row.update({"t_code": t.get("decision_code"), "t_dec": t.get("dec"), "t_group": t.get("decision_group"),
                "t_mtf": t.get("mtf_bias_label"), "t_buy_amt": t.get("buy_amt"), "t_sizing": t.get("sizing_hint"),
                "pattern": timing, "w_group": w.get("판정분류"), "w_read": w.get("최종읽기"),
                "gate": g["게이트상태"], "gate_why": g["게이트근거"]})
    for bucket in ("core", "swing", "leverage"):
        row[f"t_mult_{bucket}"] = _multiplier(app, t, bucket, 2)
    # Precision chain: MTF guard (with daily snapshot) → precision override → non-core panic scope
    shared = getattr(app, "apply_precision_post_decision", None)  # B-7 helper when present
    try:
        mtf_p = app.build_precision_multi_timeframe_pack(ticker, chart_df)
    except Exception:
        mtf_p = None
    if shared is not None and mtf_p is not None:
        p = shared(c, mtf_p, name=name, ticker=ticker, has_pos=has_pos, my_price=my_price,
                   non_core_panic_scope=True, is_etf=is_etf)
    else:
        try:
            p = app.apply_precision_mtf_decision_guard(c, mtf_p, has_pos=has_pos, ticker=ticker) if mtf_p is not None else dict(c)
        except Exception:
            p = dict(c)
        p = app.apply_leveraged_precision_decision_override(p, name, ticker, has_pos, my_price)
        p = app.enforce_non_core_panic_scope_on_result(p, is_core_dca_allowed=float(p.get("core_dca_rate") or 0) > 0, is_etf=is_etf)
    row.update({"p_code": p.get("decision_code"), "p_dec": p.get("dec"), "p_group": p.get("decision_group"),
                "p_buy_amt": p.get("buy_amt"), "p_sizing": p.get("sizing_hint")})
    return row


def replay_parity(args):
    kind, ticker, start, end, step = args
    app = setup_app()
    from stock_lab_core.ta_engine import build_indicators

    full = pd.read_csv(os.path.join(PX, f"{ticker}.csv"), index_col=0, parse_dates=True)
    dates = full.index[(full.index >= start) & (full.index <= end)][::step]
    out = []
    for d in dates:
        ASOF["d"] = d
        hist = full[full.index <= d]
        if len(hist) < 260:
            continue
        df = build_indicators(hist.tail(252).copy())
        close = float(hist["Close"].iloc[-1])
        if kind == "stock":
            ac = "kr_stock" if ticker.endswith(".KS") else "us_stock"
            cases = [(False, 0.0, 1.0, 0.0, 0.0, 10.0)] + [(True, close * m, 1.0, 0.0, 5.0, 10.0) for m in (0.85, 1.2)]
            is_etf = False
        elif kind == "etf":
            ac = PARITY_ETFS[ticker]
            cases = [(True, close * m, fmr, pen, 5.0, 15.0) for m in (0.9, 1.25) for fmr, pen in ((1.0, 0.0), (3.0, 1.5), (4.6, 2.0))]
            is_etf = True
        else:
            ac = LEVERAGED[ticker]
            cases = [(True, close * m, 1.0, 0.0, 3.0, 9.0) for m in (1.0, 1.15, 1.35, 1.6, 2.0)]
            is_etf = True
        for has_pos, my_price, fmr, pen, cw, tw in cases:
            key = {"kind": kind, "ticker": ticker, "date": str(d.date()), "has_pos": has_pos,
                   "avg_mult": round(my_price / close, 2) if my_price else 0.0, "macro": fmr}
            try:
                c = app.calc_scores_and_decision(ticker, ticker, is_etf, ac, df, my_price, has_pos, 0 if is_etf else 4,
                                                 user_total_asset=1e7, user_curr_w=cw, user_targ_w=tw,
                                                 _macro_penalty=pen, _final_macro_risk=fmr, _total_eval=1e7,
                                                 _cash_available=2e6, _reserve_available=1e6)
                key.update(_parity_row(app, c, ticker, ticker, is_etf, has_pos, my_price, df,
                                       guard=GUARDS["정상"] if kind == "leverage" else None))
            except Exception as e:
                key["error"] = repr(e)[:160]
            out.append(key)
    return out


def init_worker(px):
    global PX
    PX = px


def main():
    global PX
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["stocks", "leverage", "rr_gate", "parity"])
    ap.add_argument("--stocks-csv", default="")
    ap.add_argument("--px", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-05-29")
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tickers", default="")
    a = ap.parse_args()
    PX = a.px
    os.makedirs(a.out, exist_ok=True)
    if a.mode == "parity":
        jobs = [("stock", t, pd.Timestamp(a.start), pd.Timestamp(a.end), a.step) for t in US_STOCKS + KR_STOCKS]
        jobs += [("etf", t, pd.Timestamp(a.start), pd.Timestamp(a.end), a.step) for t in PARITY_ETFS]
        jobs += [("leverage", t, pd.Timestamp(a.start), pd.Timestamp(a.end), a.step) for t in LEVERAGED]
        if a.tickers:
            keep = set(a.tickers.split(","))
            jobs = [j for j in jobs if j[1] in keep]
        with Pool(a.workers, initializer=init_worker, initargs=(a.px,)) as pool:
            rows = [r for part in pool.imap_unordered(replay_parity, jobs) for r in part]
        frame = pd.DataFrame(rows).sort_values(["kind", "ticker", "date", "has_pos", "avg_mult", "macro"])
        path = os.path.join(a.out, "parity.csv")
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        print(path, len(frame), "errors", int(frame["error"].notna().sum()) if "error" in frame else 0)
        return
    if a.mode == "rr_gate":
        src = pd.read_csv(a.stocks_csv)
        src = src[src["family"].notna()]
        jobs = [(t, g.to_dict("records")) for t, g in src.groupby("ticker")]
        with Pool(a.workers, initializer=init_worker, initargs=(a.px,)) as pool:
            rows = [r for part in pool.imap_unordered(replay_rr_gate, jobs) for r in part]
        path = os.path.join(a.out, "rr_gate.csv")
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
        print(path, len(rows))
        return
    if a.mode == "stocks":
        tickers = a.tickers.split(",") if a.tickers else US_STOCKS + KR_STOCKS
        fn = replay_stock
    else:
        tickers = a.tickers.split(",") if a.tickers else list(LEVERAGED)
        fn = replay_leverage
    jobs = [(t, pd.Timestamp(a.start), pd.Timestamp(a.end), a.step) for t in tickers]
    with Pool(a.workers, initializer=init_worker, initargs=(a.px,)) as pool:
        rows = [r for part in pool.imap_unordered(fn, jobs) for r in part]
    path = os.path.join(a.out, f"{a.mode}.csv")
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    print(path, len(rows))


if __name__ == "__main__":
    main()
