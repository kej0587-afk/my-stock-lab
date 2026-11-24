"""Decision-system audit (2026-11-24): fixed-input cross-screen cases.

Read-only. No source file is changed. Network helpers (RS, benchmark, leveraged
watch rows, MTF bias) are replaced in this process only with fixed values so the
same input can be fed to each screen's code path. Prints one JSON document.
Run: python -X utf8 scripts/decision_audit_cases.py
Record: docs/maintenance/20261124_decision_system_audit.md
"""
import os, sys, math, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); os.environ["STOCK_LAB_FORCE_AUTH_MODE"]="public_demo"
import logging; logging.disable(logging.CRITICAL)
import app
from tests.fixtures_price import make_price_df
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.hold_judgement import build_hold_decision
from stock_lab_core.final_check_rows import build_portfolio_check_rows
from stock_lab_core import decision_engine as de

def fix(rs=(1,"➖보통"), slope=(0.0,"➡️RS횡보",0)):
    app.get_rs_score = lambda t,a: rs
    app.get_rs_slope = lambda t,a: slope
    app.get_auto_benchmark_info = lambda t,n,a,e: {"market_bench":"QQQM","sector_bench":"","sector_label":"-","underlying_bench":"","underlying_asset":"-","sector_rs_label":"-"}
BASE = dict(user_total_asset=10_000_000, _macro_penalty=0.0, _total_eval=10_000_000, _cash_available=0.0, _reserve_available=0.0)
def run(price, **kw):
    df = make_price_df(**price)
    args = {**BASE, **kw}
    return app.calc_scores_and_decision(df=df, **args)
def gate(name, tkr, c, is_etf, has_pos):
    w = build_decision_workflow(name, tkr, c, is_etf=is_etf, has_pos=has_pos)
    return {k: w.get(k) for k in ("🔥기술적 타점","📌후보등급","최종읽기","판정분류","게이트상태","게이트근거","실행메모","R/R")}
def brief(c):
    return {k: (round(c[k],3) if isinstance(c.get(k), float) else c.get(k)) for k in ("dec","decision_code","decision_group","grade","t_score","tech_total","safety_state","macro_state","dd","rr_ratio","buy_amt","core_dca_rate","core_dca_amt","target_w","current_w","sizing_hint") if k in c}
R = {}

# Case A: unheld stock, account path (Today) vs free-input path (precision, unheld free input)
fix(rs=(2,"🚀강함"), slope=(5.0,"📈RS상승중",1))
for fin, fmr in [(1,1.0),(4,5.0)]:
    k = f"A_fin{fin}_macro{fmr}"
    common = dict(name="고정테스트주", ticker="TSTA.KS", is_etf=False, asset_class="kr_stock", my_price=0.0, has_pos=False,
                  fin_score=fin, app_mode="개인모드", user_curr_w=0.0, user_targ_w=10.0, _final_macro_risk=fmr)
    acc = run(dict(daily_drift=0.0015, daily_vol=0.012, seed=1), is_free=False, **common)
    free = run(dict(daily_drift=0.0015, daily_vol=0.012, seed=1), is_free=True, **common)
    R[k] = {"account_path(Today)": brief(acc), "gate_account": gate("고정테스트주","TSTA.KS",acc,False,False),
            "free_path(precision free input, unheld)": brief(free), "gate_free": gate("고정테스트주","TSTA.KS",free,False,False)}

# Case B: two hold panels on the same precision screen + engine verdict (held stock, fin=1)
fix(rs=(2,"🚀강함"), slope=(5.0,"📈RS상승중",1))
held = run(dict(daily_drift=0.0015, daily_vol=0.012, seed=1), name="보유F종목", ticker="TSTB.KS", is_etf=False, asset_class="kr_stock",
           my_price=100.0, has_pos=True, fin_score=1, is_free=False, app_mode="개인모드", user_curr_w=5.0, user_targ_w=10.0, _final_macro_risk=1.0)
hj = build_hold_decision("TSTB.KS","보유F종목",False,1,held,100.0,True)
app.st.session_state["_app_final_macro_risk"] = 1.0
app.detect_fin_trend_direction = lambda meta: {"score":0,"signals":[],"label":"-","has_data":False}
hc = app.render_hold_or_cut_panel("보유F종목","TSTB.KS",False,1,{},held,100.0,True)
R["B_hold_panels_fin1"] = {"engine": brief(held), "hold_judgement.build_hold_decision": {"decision": hj.decision.value, "score": hj.score},
    "app.render_hold_or_cut_panel": {"decision": hc.get("decision"), "total_score": hc.get("total_score")}, "cur_p": round(held["cur_p"],2)}
# B2: same c with structure_risk and macro 5.0 (only one of the two panels reads each)
c2 = dict(held); c2.update(structure_risk=True)
hj2 = build_hold_decision("TSTB.KS","보유종목",False,4,c2,100.0,True)
app.st.session_state["_app_final_macro_risk"] = 5.0
hc2 = app.render_hold_or_cut_panel("보유종목","TSTB.KS",False,4,{},c2,100.0,True)
R["B2_hold_panels_fin4_structure_macro5"] = {"hold_judgement": {"decision": hj2.decision.value, "score": hj2.score, "fund":hj2.fundamental_score,"tech":hj2.technical_score,"risk":hj2.risk_score},
    "render_hold_or_cut_panel": {"decision": hc2.get("decision"), "total_score": hc2.get("total_score")}}
# B3: missing macro
app.st.session_state.pop("_app_final_macro_risk", None)
hc3 = app.render_hold_or_cut_panel("보유종목","TSTB.KS",False,4,{},held,100.0,True)
R["B3_hold_or_cut_missing_macro"] = {"macro_risk_used": hc3.get("macro_risk"), "decision": hc3.get("decision")}

# Case C: core ETF deep drawdown — engine vs Today gate vs monthly rebalance multiplier
fix()
for shock, label in [(-0.62,"m60"),(-0.47,"m45"),(-0.35,"m33")]:
    c = run(dict(daily_drift=0.0005, daily_vol=0.012, seed=6, tail_shock=shock, tail_shock_days=15),
            name="코덱스200", ticker="069500.KS", is_etf=True, asset_class="kr_etf", my_price=0.0, has_pos=True, fin_score=0,
            is_free=False, app_mode="자유모드", user_curr_w=3.0, user_targ_w=9.0, _final_macro_risk=1.0)
    R[f"C_core_{label}"] = {"engine": brief(c), "today_gate": gate("코덱스200","069500.KS",c,True,True),
        "monthly_rebalance_multiplier(core)": app._rebcalc_signal_multiplier(c["dec"], "core")}

# Case D: US broad-index core ETF in perfect storm — engine vs Today gate vs precision final-check macro row
fix()
c = run(dict(daily_drift=0.0005, daily_vol=0.012, seed=5), name="S&P500 ETF", ticker="VOO", is_etf=True, asset_class="us_etf_sp",
        my_price=0.0, has_pos=True, fin_score=0, is_free=False, app_mode="자유모드", user_curr_w=3.0, user_targ_w=9.0, _final_macro_risk=5.0)
R["D_core_storm"] = {"engine": brief(c), "today_gate": gate("S&P500 ETF","VOO",c,True,True),
    "final_check_portfolio_rows(macro 5.0)": build_portfolio_check_rows(has_pos=True, target_w=9.0, curr_w=3.0, weight_gap=6.0, macro_risk=5.0, trend=c["trend"], rs_label=c["rs_label"], price_vs_avg=float("nan")),
    "monthly_rebalance_multiplier(core)": app._rebcalc_signal_multiplier(c["dec"], "core")}

# Case E: higher-timeframe guard applied in Today/precision but not on the asset page
fix(rs=(2,"🚀강함"), slope=(5.0,"📈RS상승중",1))
c = run(dict(daily_drift=0.0013, daily_vol=0.012, seed=6), name="눌림주", ticker="TSTE.KS", is_etf=False, asset_class="kr_stock",
        my_price=0.0, has_pos=False, fin_score=4, is_free=False, app_mode="개인모드", user_curr_w=0.0, user_targ_w=10.0, _final_macro_risk=1.0)
orig = app.get_precision_mtf_bias
out = {"asset_page_raw(기술적타점)": c["dec"], "raw_code": c["decision_code"],
       "monthly_rebalance_multiplier(swing)": app._rebcalc_signal_multiplier(c["dec"], "swing")}
for bias in ["상위 시간대 경고", "정찰만 적합"]:
    app.get_precision_mtf_bias = lambda pack, cc, b=bias: {"label": b, "text": "고정 입력", "color": "#000"}
    g = app.apply_precision_mtf_decision_guard(c, {"x": 1}, has_pos=False)
    out[f"today/precision after MTF='{bias}'"] = {"dec": g["dec"], "code": g["decision_code"], "gate": gate("눌림주","TSTE.KS",g,False,False)["게이트상태"]}
app.get_precision_mtf_bias = orig
R["E_mtf_guard"] = out

# Case F: leveraged ETF — engine label (asset page) vs leveraged override (Today/precision) vs rebalance multiplier
fix()
app.build_leveraged_precision_watch_rows = lambda key, comparison_ticker="": []   # underlying 1W = unknown
for shock, avg in [(-0.30, 140.0), (-0.12, 100.0)]:
    c = run(dict(daily_drift=0.0005, daily_vol=0.02, seed=7, tail_shock=shock, tail_shock_days=15), name="TQQQ", ticker="TQQQ", is_etf=True,
            asset_class="us_etf_nasdaq", my_price=avg, has_pos=True, fin_score=0, is_free=False, app_mode="개인모드",
            user_curr_w=3.0, user_targ_w=9.0, _final_macro_risk=1.0)
    ov = app.apply_leveraged_precision_decision_override(app.apply_leveraged_dca_dashboard_override(c), "TQQQ", "TQQQ", True, avg)
    R[f"F_lev_shock{shock}_avg{avg}"] = {"engine(asset page 기술적타점)": brief(c), "pnl": round(c["cur_p"]/avg-1,3),
        "today/precision override": {"dec": ov["dec"], "code": ov["decision_code"], "stage": ov.get("leveraged_dca_stage"), "recovery": ov.get("leveraged_recovery_label")},
        "rebalance_multiplier(leverage) on engine label": app._rebcalc_signal_multiplier(c["dec"], "leverage"),
        "rebalance_multiplier(leverage) on override label": app._rebcalc_signal_multiplier(ov["dec"], "leverage"),
        "today_gate(after override)": gate("TQQQ","TQQQ",ov,True,True)["게이트상태"]}

# Case G: missing macro (NaN) vs known low macro — engine flags
from stock_lab_core.decision_signals import build_entry_signal_context
base = dict(is_etf=True, has_pos=True, my_price=100, cur_p=100, targ_w=10, weight_gap=5, price_vs_avg=0.0, trend="🚀정배열(상승)",
            rs_label="➖보통", rs_slope_label="➡️RS횡보", macd_state="📈추세유지(상승중)", last_macd=1.0, prev_macd=0.9, fin_score=0,
            adj_tech_score=3.0, mfi_now=55, rsi_now=55, pct_b_now=0.6, vol_ratio=1.0, current_dd=-0.05, ret_1m=0.02, ret_3m=0.05,
            ret_6m=0.08, short_history=False, is_single_day_breakdown=False, ma20_now=98, ma50_now=95, ma120_now=90, ma5_raw=99,
            low_now=99, below_ma20=False, below_ma50=False, day_ret=0.0, fvg_info={"type":"","top":None,"bottom":None,"active":False},
            is_leveraged_or_inverse=False)
G = {}
for fmr in [1.0, float("nan"), 5.0]:
    s = build_entry_signal_context(**base, macro_risk_value=fmr)
    G[str(fmr)] = {"macro_state": de.classify_macro_state(fmr), "is_etf_accumulation_ok": s["is_etf_accumulation_ok"],
                   "portfolio_guard_storm": app.select_portfolio_guard_decision(_fmr=fmr, core_dca_context={"core_dca_label":""}, core_dca_rate=0.0, curr_w=5, fin_score=0, is_core_dca_allowed=False, is_etf=True, is_zero_target_holding=False, short_history=False, targ_w=10) is not None}
R["G_macro_missing"] = G

# Case H: group of codes absent from DECISION_GROUP_BY_CODE (inferred from label words)
H = {}
for label, code in [("⚠️실시간 급락: 정규장 확인대기","LIVE_GAP_SHOCK_WAIT"),("⚡레버리지 급락권: 회복조건 확인","LEVERAGED_RECOVERY_DCA_BLOCK"),
                    ("⚡레버리지 패닉권: DCA 보류","LEVERAGED_RECOVERY_DCA_BLOCK"),("💣코어 패닉(-50%↓): 최종투입","PANIC_FINAL_DEPLOY"),
                    ("🆕신규ETF 보유: 눌림 대기", None),("🧯안전관리자 RED: 신규진입 보류","SAFETY_RED_NO_NEW_ENTRY")]:
    o = de.build_decision_outcome(label, "#000", code)
    H[label] = {"code": o.code, "group": o.group, "in_group_map": o.code in de.DECISION_GROUP_BY_CODE}
R["H_group_inference"] = H

# --- second batch: clean free-input case and a leveraged conditional case ---
fix(rs=(2,"🚀강함"), slope=(5.0,"📈RS상승중",1))
for fin, fmr in [(1,1.0),(4,5.0)]:
    common = dict(name="고정테스트주", ticker="TSTA.KS", is_etf=False, asset_class="kr_stock", my_price=0.0, has_pos=False,
                  fin_score=fin, app_mode="개인모드", user_curr_w=0.0, user_targ_w=10.0, _final_macro_risk=fmr)
    pr = dict(daily_drift=0.0013, daily_vol=0.012, seed=6)
    acc = run(pr, is_free=False, **common); free = run(pr, is_free=True, **common)
    R[f"A2_fin{fin}_macro{fmr}"] = {"account(Today)": [acc["dec"], acc["decision_code"], acc["grade"], acc["sizing_hint"]],
        "gate_account": gate("고정테스트주","TSTA.KS",acc,False,False)["게이트상태"],
        "free(precision unheld free input)": [free["dec"], free["decision_code"], free["grade"], free["sizing_hint"]],
        "gate_free": gate("고정테스트주","TSTA.KS",free,False,False)["게이트상태"], "rr": round(free["rr_ratio"] or 0,2),
        "final_check_fin_row": "차단 (fin<3)" if fin < 3 else "통과/주의", 
        "final_check_macro_row": build_portfolio_check_rows(has_pos=False, target_w=10, curr_w=0, weight_gap=10, macro_risk=fmr, trend=free["trend"], rs_label=free["rs_label"], price_vs_avg=float("nan"))[1]["상태"]}
fix()
app.build_leveraged_precision_watch_rows = lambda key, comparison_ticker="": []
found = None
for seed in range(1, 60):
    for shock in (-0.10, -0.15, -0.20):
        df = make_price_df(daily_drift=0.0015, daily_vol=0.02, seed=seed, tail_shock=shock, tail_shock_days=10)
        cur = float(df["Close"].iloc[-1]); avg = cur * 1.08
        c = app.calc_scores_and_decision(df=df, **{**BASE, "name":"TQQQ","ticker":"TQQQ","is_etf":True,"asset_class":"us_etf_nasdaq","my_price":avg,
             "has_pos":True,"fin_score":0,"is_free":False,"app_mode":"개인모드","user_curr_w":3.0,"user_targ_w":9.0,"_final_macro_risk":1.0})
        if c["decision_code"] == "LEVERAGED_DCA_CONDITIONAL":
            found = (seed, shock, avg, c); break
    if found: break
if found:
    seed, shock, avg, c = found
    ov = app.apply_leveraged_precision_decision_override(app.apply_leveraged_dca_dashboard_override(c), "TQQQ", "TQQQ", True, avg)
    R["F2_leveraged_conditional"] = {"price_input": dict(daily_drift=0.0015, daily_vol=0.02, seed=seed, tail_shock=shock, tail_shock_days=10), "avg_price": round(avg,2),
        "cur_p": round(c["cur_p"],2), "dd": round(c["dd"],3), "pct_b": round(c["pct_b"],2), "trend": c["trend"],
        "engine(asset page)": [c["dec"], c["decision_code"]], "rebalance_mult(engine label)": app._rebcalc_signal_multiplier(c["dec"], "leverage"),
        "override(Today/precision)": [ov["dec"], ov["decision_code"], ov.get("leveraged_dca_stage"), ov.get("leveraged_dca_multiple"), ov.get("leveraged_recovery_label")],
        "rebalance_mult(override label)": app._rebcalc_signal_multiplier(ov["dec"], "leverage"),
        "today_gate(override)": gate("TQQQ","TQQQ",ov,True,True)["게이트상태"]}

print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
