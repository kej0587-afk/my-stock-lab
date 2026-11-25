"""C-3 leveraged L3 policy (2026-11-25, user decision)."""
import numpy as np
import pandas as pd
import pytest

from stock_lab_core import leverage_l3_policy as L
from stock_lab_core.leverage_stage import resolve_leverage_stage


def bar(date, dd, pnl, *, ok=True, defense=False, regime="상승", n6=5, new_high=False, has_pos=True, blocks=()):
    return L.Bar(date=date, close=100.0, dd52=dd, new_52w_high=new_high, pnl=pnl, market_defense=defense,
                 underlying_above_ma50=ok, leveraged_above_ma50=ok, recovery_passed=n6,
                 underlying_regime=regime, has_pos=has_pos, blocks=tuple(blocks))


def run(bars, **kw):
    kw.setdefault("budget", 90.0)
    kw.setdefault("shortfall_fn", 1000.0)
    return L.replay(bars, execute=True, **kw)


def executed(reads):
    return [r for r in reads if r["status"] == L.STATUS_EXECUTABLE]


def test_l2_then_recovery_executes_even_after_loss_shrinks_above_minus_12():
    bars = [bar("d0", -0.15, -0.05, ok=False), bar("d1", -0.30, -0.20, ok=False),  # L2 qualified here
            bar("d2", -0.18, -0.03)]                                               # recovered: -3% vs avg
    cyc, reads = run(bars)
    assert reads[1]["cycle"]["l2_qualified"] and reads[1]["cycle"]["l2_stage"] == "약하락"
    assert reads[2]["status"] == L.STATUS_EXECUTABLE and reads[2]["tranche"] == 1
    assert cyc.invested == pytest.approx(30.0)


def test_no_l3_without_l2_qualification():
    bars = [bar("d0", -0.15, -0.05), bar("d1", -0.20, -0.08), bar("d2", -0.12, -0.02)]
    _, reads = run(bars)
    assert not executed(reads)
    assert "L2 자격 없음" in reads[-1]["reasons"]


def test_max_three_tranches_twenty_trading_days_apart_and_budget_cap():
    bars = [bar("d0", -0.30, -0.20, ok=False)] + [bar(f"d{i}", -0.20, -0.05) for i in range(1, 70)]
    cyc, reads = run(bars)
    ex = executed(reads)
    assert [r["tranche"] for r in ex] == [1, 2, 3]
    assert [r["date"] for r in ex] == ["d1", "d21", "d41"]  # 20 completed bars after each recorded tranche
    assert cyc.invested == pytest.approx(90.0) and cyc.tranches_used == 3
    assert "3회차 소진" in reads[-1]["reasons"]
    assert any("20거래일 미만" in x for x in reads[10]["reasons"])


def test_cooldown_survives_conditions_disappearing():
    bars = ([bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05)]
            + [bar(f"x{i}", -0.25, -0.10, ok=False) for i in range(5)]       # conditions gone
            + [bar(f"y{i}", -0.20, -0.05) for i in range(20)])               # back again
    _, reads = run(bars)
    ex = executed(reads)
    assert [r["date"] for r in ex] == ["d1", "y14"]  # bar 21 = 20 bars after d1, not restarted by the gap


def test_shortfall_and_monthly_plan_cap_the_tranche():
    assert L.tranche_amount(90, 0, 1000) == pytest.approx(30)
    assert L.tranche_amount(90, 80, 1000) == pytest.approx(10)          # remaining budget
    assert L.tranche_amount(90, 0, 12) == pytest.approx(12)             # target shortfall
    assert L.tranche_amount(90, 0, 25, monthly_planned=20) == pytest.approx(5)  # monthly plan fills first
    assert L.tranche_amount(90, 0, 15, monthly_planned=20) == 0.0
    assert L.tranche_amount(300, 0, 70, monthly_planned=30) == pytest.approx(40)  # the user's example (만원)
    assert L.tranche_amount(None, 0, 100) is None
    assert L.tranche_amount(90, 0, float("nan")) is None


def test_no_budget_is_candidate_not_executable():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05)]
    _, reads = run(bars, budget=None)
    assert reads[-1]["status"] == L.STATUS_CANDIDATE
    assert reads[-1]["reasons"] == ["레버리지 DCA 예산 미설정"]


def test_market_defense_blocks_l3():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05, defense=True)]
    _, reads = run(bars)
    assert reads[-1]["status"] == L.STATUS_WAIT and "시장방어" in reads[-1]["reasons"]


@pytest.mark.parametrize("block", ["급락일", "과열", "목표비중 없음·충족", "매크로", "데이터"])
def test_existing_blocks_stay(block):
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05, blocks=(block,))]
    _, reads = run(bars)
    assert reads[-1]["status"] == L.STATUS_WAIT and block in reads[-1]["reasons"]


@pytest.mark.parametrize("n6", [3, None])
def test_recovery_four_of_six_required(n6):
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05, n6=n6)]
    _, reads = run(bars)
    assert reads[-1]["status"] == L.STATUS_WAIT


def test_panic_latch_not_released_by_52w_high_roll_off():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.55, -0.50, ok=False),   # latch
            # the old peak leaves the window: dd52 back to -20%, recovery conditions met, but regime not 상승
            bar("d2", -0.20, -0.48, regime="횡보"), bar("d3", -0.15, -0.47, regime="하락"),
            bar("d4", -0.12, -0.46, regime="미확인")]
    cyc, reads = run(bars)
    assert all(r["status"] != L.STATUS_EXECUTABLE for r in reads)
    assert cyc.panic_latched and all("패닉 latch" in r["reasons"] for r in reads[2:])


def test_panic_latch_released_only_by_uptrend_ma50_and_recovery():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.55, -0.50, ok=False),
            bar("d2", -0.40, -0.45, regime="상승", n6=3),     # 3/6: still latched
            bar("d3", -0.38, -0.44, regime="상승", n6=4)]     # release + L3 on the same bar
    cyc, reads = run(bars)
    assert reads[2]["cycle"]["panic_latched"]
    assert not reads[3]["cycle"]["panic_latched"] and reads[3]["cycle"]["unlatch_date"] == "d3"
    assert reads[3]["status"] == L.STATUS_EXECUTABLE


def test_current_panic_bar_relatches():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.51, -0.40, regime="상승", n6=4)]
    _, reads = run(bars)
    assert reads[-1]["cycle"]["panic_latched"] and reads[-1]["status"] == L.STATUS_WAIT


def test_cycle_end_and_resets():
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05),   # tranche 1
            bar("d2", 0.0, 0.10, new_high=True),                         # cycle over
            bar("d3", -0.05, 0.05)]
    cyc, reads = run(bars)
    assert reads[2]["status"] == L.STATUS_NO_CYCLE and not cyc.active and cyc.tranches_used == 0
    # a new 52-week high does not end a latched cycle
    bars2 = [bar("d0", -0.55, -0.50, ok=False), bar("d1", 0.0, -0.40, new_high=True, regime="횡보")]
    cyc2, _ = run(bars2)
    assert cyc2.active and cyc2.panic_latched
    # closing the position clears the cycle
    bars3 = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.30, None, has_pos=False)]
    cyc3, reads3 = run(bars3)
    assert not cyc3.active and not cyc3.l2_qualified and "포지션 종료" in reads3[-1]["events"][0]


def test_target_filled_blocks_but_keeps_cycle_state():
    filled = ("목표비중 없음·충족",)
    bars = ([bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05)]
            + [bar(f"f{k}", -0.20, -0.05, blocks=filled) for k in range(2, 21)] + [bar("d21", -0.20, -0.05)])
    cyc, reads = run(bars)
    assert reads[2]["status"] == L.STATUS_WAIT and reads[2]["cycle"]["tranches_used"] == 1
    assert all(r["status"] == L.STATUS_WAIT for r in reads[2:21])
    assert reads[21]["status"] == L.STATUS_EXECUTABLE and reads[21]["tranche"] == 2


def test_missing_values_stay_unknown():
    b = L.Bar(date="d", close=None, dd52=None)
    cyc = L.LeverageDcaCycle()
    assert L.step(cyc, b, 0)["status"] == L.STATUS_NO_CYCLE
    assert L.l2_stage_for(None) == "" and L.l2_stage_for(float("nan")) == ""


def _series(values, start="2022-01-03"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def _history():
    n = 400
    lev = _series(np.r_[np.linspace(50, 100, 200), np.linspace(100, 60, 100), np.linspace(60, 75, 100)])
    axis = _series(np.r_[np.linspace(80, 120, 200), np.linspace(120, 100, 100), np.linspace(100, 118, 100)])
    bench = _series(np.linspace(300, 400, n))
    return L.build_history_bars(lev, axis, bench, avg_cost=80.0)


OVER = {"market_defense": False, "leveraged_above_ma50": True, "underlying_above_ma50": True,
        "recovery_passed": 5, "blocks": ()}


def test_history_bars_and_read_current_record_rules():
    bars = _history()
    assert len(bars) == 400 and bars[-1].pnl == pytest.approx(75 / 80 - 1)
    read = L.read_current(bars, OVER, ticker="TQQQ", shortfall=1_000_000)
    cyc = read["cycle"]
    assert cyc["active"] and cyc["l2_qualified"] and read["cycle_id"] == f"TQQQ-{cyc['start']}"
    assert read["status"] == L.STATUS_CANDIDATE and read["reasons"] == ["레버리지 DCA 예산 미설정"]
    rec = {"cycle_id": read["cycle_id"], "budget_krw": 900_000, "tranches": []}
    no_monthly = L.read_current(bars, OVER, ticker="TQQQ", record=rec, shortfall=1_000_000)
    assert no_monthly["status"] == L.STATUS_CANDIDATE and "월적립" in no_monthly["reasons"][0]
    ok = L.read_current(bars, OVER, ticker="TQQQ", record=rec, shortfall=1_000_000, monthly_planned=200_000)
    assert ok["status"] == L.STATUS_EXECUTABLE and ok["tranche"] == 1
    assert ok["amount"] == pytest.approx(300_000)
    capped = L.read_current(bars, OVER, ticker="TQQQ", record=rec, shortfall=700_000, monthly_planned=300_000)
    assert capped["amount"] == pytest.approx(300_000) and capped["planned"] == pytest.approx(300_000)
    # recorded tranche 5 bars ago -> cooldown; a record for another cycle is ignored
    rec1 = {**rec, "tranches": [{"tranche_no": 1, "exec_date": bars[-6].date, "actual_krw": 300_000}]}
    cool = L.read_current(bars, OVER, ticker="TQQQ", record=rec1, shortfall=1_000_000, monthly_planned=0.0)
    assert cool["status"] == L.STATUS_WAIT and any("20거래일 미만" in x for x in cool["reasons"])
    rec_old = {**rec1, "tranches": [{"tranche_no": 1, "exec_date": bars[-25].date, "actual_krw": 300_000}]}
    second = L.read_current(bars, OVER, ticker="TQQQ", record=rec_old, shortfall=1_000_000, monthly_planned=0.0)
    assert second["status"] == L.STATUS_EXECUTABLE and second["tranche"] == 2
    full = {**rec, "tranches": [{"tranche_no": k, "exec_date": bars[-100 + 25 * k].date, "actual_krw": 300_000}
                                for k in (1, 2, 3)]}
    done = L.read_current(bars, OVER, ticker="TQQQ", record=full, shortfall=1_000_000, monthly_planned=0.0)
    assert done["status"] == L.STATUS_WAIT and "3회차 소진" in done["reasons"]
    other = L.read_current(bars, OVER, ticker="TQQQ", record={**rec, "cycle_id": "TQQQ-1999-01-01"},
                           shortfall=1_000_000, monthly_planned=0.0)
    assert other["status"] == L.STATUS_CANDIDATE and other["record"] == {}
    defended = L.read_current(bars, {**OVER, "market_defense": True}, ticker="TQQQ", record=rec,
                              shortfall=1_000_000, monthly_planned=0.0)
    assert defended["status"] == L.STATUS_WAIT
    partial = L.read_current(bars, OVER, ticker="TQQQ", record=rec, shortfall=1_000_000, monthly_planned=0.0,
                             history_complete=False)
    assert partial["status"] == L.STATUS_CANDIDATE
    assert L.summary_text(ok).startswith("L3 실행가능")
    assert any(r["항목"] == "사전 예산" for r in L.l3_panel_rows(ok))


def test_tranche_record_payload_validation():
    bars = _history()
    base = L.read_current(bars, OVER, ticker="TQQQ", shortfall=1_000_000)
    rec = {"cycle_id": base["cycle_id"], "budget_krw": 900_000, "tranches": []}
    ok = L.read_current(bars, OVER, ticker="TQQQ", record=rec, shortfall=1_000_000, monthly_planned=0.0)
    payload, err = L.tranche_record_payload(ok, 250_000, ticker="tqqq")
    assert err == "" and payload["tranche_no"] == 1 and payload["ticker"] == "TQQQ"
    assert payload["exec_date"] == bars[-1].date and payload["planned_krw"] == pytest.approx(300_000)
    assert payload["cycle_id"] == base["cycle_id"] and payload["policy_version"] == L.POLICY_VERSION
    assert L.tranche_record_payload(ok, 400_000, ticker="TQQQ")[0] is None      # over the cap
    assert L.tranche_record_payload(ok, 0, ticker="TQQQ")[0] is None
    assert L.tranche_record_payload(base, 100_000, ticker="TQQQ")[0] is None    # candidate, not executable


def test_history_too_short_is_no_cycle():
    assert L.build_history_bars(_series([1.0] * 10), None) == []
    assert L.read_current([])["status"] == L.STATUS_NO_CYCLE


def test_leverage_stage_reports_l3_read():
    d = {"decision_code": "LEVERAGED_RECOVERY_DCA_CONDITIONAL",
         "leveraged_l3": {"status": L.STATUS_CANDIDATE, "reasons": ["레버리지 DCA 예산 미설정"]}}
    st = resolve_leverage_stage(d, gate_state="대기")
    assert st["stage"] == "L2" and st["l3_status"] == L.STATUS_CANDIDATE
    assert st["l3_reasons"] == ["레버리지 DCA 예산 미설정"] and st["executable"] is False
    assert resolve_leverage_stage({"decision_code": "LEVERAGED_DCA_CONDITIONAL"})["l3_status"] is None


@pytest.mark.parametrize("l3_status,code", [(L.STATUS_CANDIDATE, "LEVERAGED_RECOVERY_DCA_CONDITIONAL"),
                                            (L.STATUS_WAIT, "LEVERAGED_RECOVERY_DCA_BLOCK")])
def test_app_override_shows_l3_candidate_as_conditional_wait(app_module, monkeypatch, l3_status, code):
    from stock_lab_core.decision_workflow import build_decision_workflow
    from stock_lab_core.execution_gate import build_execution_gate, GATE_EXECUTABLE
    state = {"profile_key": "TQQQ", "profile": {}, "dca_stage": "관망", "dca_multiple": "×0", "dca_note": "",
             "recovery_label": "5/6", "recovery_state": "회복 우세", "recovery_passed": 5,
             "recovery_total": 6, "recovery_checks": [], "underlying_1w_avg": 1.0}
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *a: state)
    read = {"status": l3_status, "reasons": ["레버리지 DCA 예산 미설정"] if l3_status == L.STATUS_CANDIDATE else ["과열"],
            "cycle": {"active": True, "start": "2022-01-03", "l2_qualified": True, "l2_date": "2022-02-01",
                      "l2_stage": "중하락"}, "events": []}
    monkeypatch.setattr(app_module, "build_leveraged_l3_read", lambda *a: read)
    c = {"cur_p": 50.0, "ma20": 48.0, "ma50": 45.0, "rsi": 55.0, "mfi": 50.0, "pct_b": 0.6, "rr_ratio": 2.0, "rr_stop": 45.0, "rr_target": 60.0,
         "target_w": 9.0, "current_w": 3.0, "buy_amt": 500000.0, "decision_code": "WATCH_WAIT_ENTRY", "dec": "관망",
         "decision_group": "caution", "is_leveraged_or_inverse": True}
    out = app_module.apply_leveraged_precision_decision_override(c, "TQQQ", "TQQQ", True, 52.0)
    assert out["decision_code"] == code
    assert out["leveraged_l3"]["status"] == l3_status
    assert any(str(r).startswith("L3") for r in out["decision_reasons"])
    if l3_status == L.STATUS_CANDIDATE:
        assert "조건부" in out["dec"] and "L3 후보" in out["dec"]
    w = build_decision_workflow("TQQQ", "TQQQ", out, is_etf=True, has_pos=True,
                                pattern_timing="-", pattern_bucket="", pattern_reason="")
    assert build_execution_gate(w)["게이트상태"] != GATE_EXECUTABLE


def test_app_override_keeps_existing_conditional_label(app_module, monkeypatch):
    state = {"profile_key": "TQQQ", "profile": {}, "dca_stage": "약하락 DCA 후보", "dca_multiple": "×0.75", "dca_note": "",
             "recovery_label": "5/6", "recovery_state": "회복 우세", "recovery_passed": 5,
             "recovery_total": 6, "recovery_checks": [], "underlying_1w_avg": float("nan")}
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *a: state)
    monkeypatch.setattr(app_module, "build_leveraged_l3_read", lambda *a: {
        "status": L.STATUS_CANDIDATE, "reasons": ["레버리지 DCA 예산 미설정"], "cycle": {}, "events": []})
    c = {"cur_p": 50.0, "ma20": 48.0, "ma50": 45.0, "rsi": 55.0, "mfi": 50.0, "pct_b": 0.6, "rr_ratio": 2.0, "rr_stop": 45.0, "rr_target": 60.0,
         "target_w": 9.0, "current_w": 3.0, "buy_amt": 500000.0, "decision_code": "WATCH_WAIT_ENTRY", "dec": "관망",
         "decision_group": "caution", "is_leveraged_or_inverse": True}
    out = app_module.apply_leveraged_precision_decision_override(c, "TQQQ", "TQQQ", True, 60.0)
    assert out["decision_code"] == "LEVERAGED_RECOVERY_DCA_CONDITIONAL"
    assert "L3 후보" not in out["dec"]           # e.g. the data-check timing label stays visible
    assert out["leveraged_l3"]["status"] == L.STATUS_CANDIDATE


def test_app_override_executable_l3(app_module, monkeypatch):
    from stock_lab_core.decision_workflow import build_decision_workflow
    from stock_lab_core.execution_gate import build_execution_gate, GATE_EXECUTABLE
    state = {"profile_key": "TQQQ", "profile": {}, "dca_stage": "관망", "dca_multiple": "×0", "dca_note": "",
             "recovery_label": "5/6", "recovery_state": "회복 우세", "recovery_passed": 5,
             "recovery_total": 6, "recovery_checks": [], "underlying_1w_avg": 1.0}
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *a: state)
    monkeypatch.setattr(app_module, "build_leveraged_l3_read", lambda *a: {
        "status": L.STATUS_EXECUTABLE, "reasons": [], "tranche": 2, "amount": 300000.0, "events": [],
        "cycle": {"active": True, "start": "2022-01-03", "l2_qualified": True}})
    c = {"cur_p": 50.0, "ma20": 48.0, "ma50": 45.0, "rsi": 55.0, "mfi": 50.0, "pct_b": 0.6, "rr_ratio": 2.0, "rr_stop": 45.0, "rr_target": 60.0,
         "target_w": 9.0, "current_w": 3.0, "buy_amt": 900000.0, "decision_code": "WATCH_WAIT_ENTRY", "dec": "관망",
         "decision_group": "caution", "is_leveraged_or_inverse": True}
    out = app_module.apply_leveraged_precision_decision_override(c, "TQQQ", "TQQQ", True, 52.0)
    assert out["decision_code"] == "LEVERAGED_L3_RECOVERY_DCA" and out["buy_amt"] == 300000.0
    w = build_decision_workflow("TQQQ", "TQQQ", out, is_etf=True, has_pos=True,
                                pattern_timing="-", pattern_bucket="", pattern_reason="")
    g = build_execution_gate(w)
    assert g["게이트상태"] == GATE_EXECUTABLE and "L3 회복 DCA 2/3회차" in g["게이트근거"]
    from stock_lab_core.decision_workflow import attach_market_execution_context
    guarded = attach_market_execution_context(pd.DataFrame([w]), {"mode": "정상", "us_stats": {"mode": "방어"}})
    assert build_execution_gate(guarded.iloc[0].to_dict())["게이트상태"] != GATE_EXECUTABLE
