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


def test_max_three_tranches_one_per_new_bar_and_budget_cap():
    bars = [bar("d0", -0.30, -0.20, ok=False)] + [bar(f"d{i}", -0.20, -0.05) for i in range(1, 8)]
    cyc, reads = run(bars)
    ex = executed(reads)
    assert [r["tranche"] for r in ex] == [1, 2, 3]
    assert [r["date"] for r in ex] == ["d1", "d2", "d3"]  # one tranche per completed bar
    assert cyc.invested == pytest.approx(90.0) and cyc.tranches_used == 3
    assert "3회차 소진" in reads[-1]["reasons"]


def test_same_bar_never_spends_two_tranches():
    cyc = L.LeverageDcaCycle()
    L.step(cyc, bar("d0", -0.30, -0.20, ok=False), 0, budget=90, shortfall=1000, execute=True)
    first = L.step(cyc, bar("d1", -0.20, -0.05), 1, budget=90, shortfall=1000, execute=True)
    again = L.step(cyc, bar("d1", -0.20, -0.05), 1, budget=90, shortfall=1000, execute=True)
    assert first["status"] == L.STATUS_EXECUTABLE
    assert again["status"] == L.STATUS_WAIT and "같은 완료봉" in again["reasons"]
    assert cyc.tranches_used == 1


def test_shortfall_and_monthly_plan_cap_the_tranche():
    assert L.tranche_amount(90, 0, 1000) == pytest.approx(30)
    assert L.tranche_amount(90, 80, 1000) == pytest.approx(10)          # remaining budget
    assert L.tranche_amount(90, 0, 12) == pytest.approx(12)             # target shortfall
    assert L.tranche_amount(90, 0, 25, monthly_planned=20) == pytest.approx(5)  # monthly plan fills first
    assert L.tranche_amount(90, 0, 15, monthly_planned=20) == 0.0
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
    bars = [bar("d0", -0.30, -0.20, ok=False), bar("d1", -0.20, -0.05),
            bar("d2", -0.20, -0.05, blocks=("목표비중 없음·충족",)), bar("d3", -0.20, -0.05)]
    cyc, reads = run(bars)
    assert reads[2]["status"] == L.STATUS_WAIT and reads[2]["cycle"]["tranches_used"] == 1
    assert reads[3]["status"] == L.STATUS_EXECUTABLE and reads[3]["tranche"] == 2


def test_missing_values_stay_unknown():
    b = L.Bar(date="d", close=None, dd52=None)
    cyc = L.LeverageDcaCycle()
    assert L.step(cyc, b, 0)["status"] == L.STATUS_NO_CYCLE
    assert L.l2_stage_for(None) == "" and L.l2_stage_for(float("nan")) == ""


def _series(values, start="2022-01-03"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_history_bars_and_read_current_never_executable():
    n = 400
    up = np.linspace(50, 100, 200)
    down = np.linspace(100, 60, 100)          # -40% from the high: cycle + L2 vs avg 80
    rec = np.linspace(60, 75, 100)
    lev = _series(np.r_[up, down, rec])
    axis = _series(np.r_[np.linspace(80, 120, 200), np.linspace(120, 100, 100), np.linspace(100, 118, 100)])
    bench = _series(np.linspace(300, 400, n))
    bars = L.build_history_bars(lev, axis, bench, avg_cost=80.0)
    assert len(bars) == n and bars[-1].pnl == pytest.approx(75 / 80 - 1)
    over = {"market_defense": False, "leveraged_above_ma50": True, "recovery_passed": 5, "blocks": ()}
    read = L.read_current(bars, over, budget=None, shortfall=1_000_000)
    assert read["cycle"]["active"] and read["cycle"]["l2_qualified"]
    assert read["status"] in {L.STATUS_CANDIDATE, L.STATUS_WAIT}
    # Even with a budget, no tranche record and no monthly plan means candidate only.
    with_budget = L.read_current(bars, over, budget=900_000, shortfall=1_000_000)
    assert with_budget["status"] != L.STATUS_EXECUTABLE
    with_monthly = L.read_current(bars, over, budget=900_000, shortfall=1_000_000, monthly_planned=0.0)
    assert with_monthly["status"] != L.STATUS_EXECUTABLE
    if with_monthly["status"] == L.STATUS_CANDIDATE:
        assert with_monthly["reasons"] == ["회차 기록 미연결"]
    assert L.summary_text(read).startswith("L3")
    assert any(r["항목"] == "L2 자격" for r in L.l3_panel_rows(read))


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
    c = {"cur_p": 50.0, "ma20": 48.0, "ma50": 45.0, "rsi": 55.0, "mfi": 50.0, "pct_b": 0.6, "rr_ratio": 2.0,
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
    c = {"cur_p": 50.0, "ma20": 48.0, "ma50": 45.0, "rsi": 55.0, "mfi": 50.0, "pct_b": 0.6, "rr_ratio": 2.0,
         "target_w": 9.0, "current_w": 3.0, "buy_amt": 500000.0, "decision_code": "WATCH_WAIT_ENTRY", "dec": "관망",
         "decision_group": "caution", "is_leveraged_or_inverse": True}
    out = app_module.apply_leveraged_precision_decision_override(c, "TQQQ", "TQQQ", True, 60.0)
    assert out["decision_code"] == "LEVERAGED_RECOVERY_DCA_CONDITIONAL"
    assert "L3 후보" not in out["dec"]           # e.g. the data-check timing label stays visible
    assert out["leveraged_l3"]["status"] == L.STATUS_CANDIDATE
