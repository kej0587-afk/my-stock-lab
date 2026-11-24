"""Decision policy proposal (2026-11-24): fixed-input evidence cases.

Read-only. No source file is changed. Like scripts/decision_audit_cases.py, network
helpers (RS, benchmark, leveraged watch rows) are replaced in this process only.
Prices are seeded synthetic data from tests.fixtures_price, not real quotes, so the
numbers show code paths, not market facts. Prints one JSON document.
Run: python -X utf8 scripts/decision_policy_cases.py
Record: docs/maintenance/20261124_decision_policy_proposal.md
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["STOCK_LAB_FORCE_AUTH_MODE"] = "public_demo"
import logging

logging.disable(logging.CRITICAL)
import pandas as pd

import app
from tests.fixtures_price import make_price_df
from stock_lab_core.decision_workflow import build_decision_workflow, attach_market_execution_context
from stock_lab_core.execution_gate import build_execution_gate
from stock_lab_core.final_check_rows import build_portfolio_check_rows


def fix(rs=(1, "➖보통"), slope=(0.0, "➡️RS횡보", 0)):
    app.get_rs_score = lambda t, a: rs
    app.get_rs_slope = lambda t, a: slope
    app.get_auto_benchmark_info = lambda t, n, a, e: {
        "market_bench": "QQQM", "sector_bench": "", "sector_label": "-", "underlying_bench": "",
        "underlying_asset": "-", "sector_rs_label": "-"}


def macro_penalty(fmr):
    # Same ladder as app.get_macro_analysis (app.py:15581); passed explicitly because
    # calc_scores_and_decision receives the penalty from its caller.
    if not math.isfinite(fmr):
        return 0.0
    return 2.0 if fmr >= 4 else 1.5 if fmr >= 2.5 else 0.5 if fmr >= 1.5 else 0.0


def run(price, **kw):
    base = dict(user_total_asset=10_000_000, _total_eval=10_000_000, _cash_available=0.0, _reserve_available=0.0)
    return app.calc_scores_and_decision(df=make_price_df(**price), **{**base, **kw})


def gate_row(name, tkr, c, is_etf, has_pos, guard=None, **pattern):
    w = build_decision_workflow(name, tkr, c, is_etf=is_etf, has_pos=has_pos, **pattern)
    if guard is not None:
        w = attach_market_execution_context(pd.DataFrame([w]), guard).iloc[0].to_dict()
    g = build_execution_gate(w)
    return {"판정분류": w.get("판정분류"), "최종읽기": w.get("최종읽기"), "시장실행상태": w.get("시장실행상태", ""),
            "게이트": g["게이트상태"], "게이트근거": g["게이트근거"]}


R = {}

# P: a chart pattern changes the Today group/gate of an existing decision.
base = dict(dec="🎯A급: 기술적 반등", decision_code="A_GRADE_TECH_REBOUND", decision_group="neutral", grade="A급",
            t_score=7, rr_ratio=1.8, rr_kind="구조 목표", rr_stop=96.0, rr_target=107.2, rsi=50, mfi=50, pct_b=0.5,
            macro_state="NORMAL", mtf_bias_label="중립 확인", data_state="OK", cur_p=100, my_price=105, has_pos=True,
            buy_amount=300000, target_weight=10, current_weight=5, ma20=99, ma50=95, ma120=90, atr=2.0,
            decision_reasons=("고정 입력",), sizing_hint="", trend="🚀정배열(상승)", rs_label="🚀강함", dd=-0.05, day_ret=0.0)
P = {}
for timing, bucket in [("-", ""), ("✅패턴유효: 정밀확인", "interest"), ("👀패턴관찰: 돌파대기", "interest"), ("🛑하락패턴 유효", "risk")]:
    P[timing] = gate_row("고정", "AAA", dict(base), False, True,
                         pattern_timing=timing, pattern_bucket=bucket, pattern_reason="")
R["P_pattern_changes_gate(A_GRADE_TECH_REBOUND, R/R 1.8)"] = P

# M: unheld stock candidates at several macro values: which layers react.
fix(rs=(2, "🚀강함"), slope=(5.0, "📈RS상승중", 1))
M = {}
inputs = {"S_PULLBACK_ENTRY": (6, 0.0013), "NEW_ENTRY_LEADER": (2, 0.002), "EXCEPTION_ENTRY": (5, 0.0013),
          "EARLY_REVERSAL_ENTRY": (27, 0.0013), "QUALITY_RECOVERY_SCOUT": (1, 0.002)}
for start_code, (seed, drift) in inputs.items():
    ladder = {}
    for fmr in [1.0, 2.0, 3.0, 3.6, 4.6, float("nan")]:
        c = run(dict(daily_drift=drift, daily_vol=0.012, seed=seed), name="후보주", ticker="TSTE.KS", is_etf=False,
                asset_class="kr_stock", my_price=0.0, has_pos=False, fin_score=4, is_free=False, app_mode="개인모드",
                user_curr_w=0.0, user_targ_w=10.0, _final_macro_risk=fmr, _macro_penalty=macro_penalty(fmr))
        rows = build_portfolio_check_rows(has_pos=False, target_w=10.0, curr_w=0.0, weight_gap=10.0, macro_risk=fmr,
                                          trend=c["trend"], rs_label=c["rs_label"], price_vs_avg=float("nan"))
        macro_row = next((r["상태"] for r in rows if r["점검항목"] == "매크로"), "-")
        ladder[str(fmr)] = {"penalty": macro_penalty(fmr), "adj": round(float(c.get("adj", float("nan"))), 2),
                            "code": c["decision_code"], "gate": gate_row("후보주", "TSTE.KS", c, False, False)["게이트"],
                            "final_check_macro": macro_row,
                            "guard_points_from_risk": 2 if math.isfinite(fmr) and fmr >= 4.5 else 1 if math.isfinite(fmr) and fmr >= 3.5 else 0}
    M[f"{start_code}(seed{seed})"] = ladder
R["M_macro_layers_unheld_stock"] = M

# L: leveraged ETF drawdown, engine vs Today override vs market guard defense.
fix()
app.build_leveraged_precision_watch_rows = lambda key, comparison_ticker="": []
L = {}
guards = {"정상": {"mode": "정상", "us_stats": {"mode": "정상"}, "kr_stats": {"mode": "정상"}},
          "미국 방어": {"mode": "주의", "us_stats": {"mode": "방어"}, "kr_stats": {"mode": "정상"}}}
cases = [("F2 조건부(시드2)", dict(daily_drift=0.0015, daily_vol=0.02, seed=2, tail_shock=-0.10, tail_shock_days=10), 1.08),
         ("급락 역배열(시드7)", dict(daily_drift=0.0005, daily_vol=0.02, seed=7, tail_shock=-0.30, tail_shock_days=15), 1.40)]
for label, price, avg_mult in cases:
    df = make_price_df(**price)
    avg = float(df["Close"].iloc[-1]) * avg_mult
    c = run(price, name="TQQQ", ticker="TQQQ", is_etf=True, asset_class="us_etf_nasdaq", my_price=avg, has_pos=True,
            fin_score=0, is_free=False, app_mode="개인모드", user_curr_w=3.0, user_targ_w=9.0,
            _final_macro_risk=1.0, _macro_penalty=0.0)
    ov = app.apply_leveraged_precision_decision_override(app.apply_leveraged_dca_dashboard_override(c), "TQQQ", "TQQQ", True, avg)
    L[label] = {
        "dd": round(c.get("dd", float("nan")), 3), "pnl": round(c["cur_p"] / avg - 1, 3), "trend": c.get("trend"),
        "engine": {"code": c["decision_code"], "dec": c["dec"]},
        "rebalance_multiplier(engine label)": app._rebcalc_signal_multiplier(c["dec"], "leverage"),
        "today_override": {"code": ov["decision_code"], "dec": ov["dec"], "stage": ov.get("leveraged_dca_stage"),
                           "recovery": ov.get("leveraged_recovery_label")},
        **{f"gate(override, market {k})": gate_row("TQQQ", "TQQQ", ov, True, True, guard=g) for k, g in guards.items()},
        **{f"gate(engine label, market {k})": gate_row("TQQQ", "TQQQ", c, True, True, guard=g) for k, g in guards.items()},
    }
R["L_leveraged_drawdown"] = L

print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
