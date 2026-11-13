"""Connected research desk: chronology, gaps, missing data, sizing and unchanged gates."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import soxl_trade_research as research
from stock_lab_core.soxl_trade_plan import price_plan, size_scenario, paired_five, build_price_context
from stock_lab_core.soxl_short_observation import completed_hour_grid, HOUR
from stock_lab_core.soxl_five_observation import build_five_observation
from tests.test_soxl_short_observation import schedule, UI


def sample():
    sched = schedule(days=2)
    now = sched.market_close.iloc[-1]
    slots = research.execution_grid(sched, now)
    index = pd.DatetimeIndex(slots.start)
    xx = pd.DataFrame(dict(Open=100., High=102., Low=98., Close=100.), index=index)
    xl = pd.DataFrame(dict(Open=60., High=61., Low=59., Close=60.), index=index)
    signals = [dict(time=index[1], formation="a", soxx_stop=95., soxx_upper=120.)]
    return sched, now, slots, xx, xl, signals


def test_plan_has_one_entry_r_basis_not_three_times_proxy():
    plan = price_plan(60, 58)
    assert plan["target"] == 62 and plan["risk_pct"] == pytest.approx(100*2/60)
    assert price_plan(62, 58)["target"] == 66
    for entry, stop in ((58,58),(57,58),(np.nan,50),(60,np.inf),(0,1)):
        assert price_plan(entry,stop) == {}


def test_zero_cash_unset_equity_and_finite_budget():
    plan = price_plan(60,58)
    assert size_scenario(plan,10000,0,.5,2)["shares"] == 0
    assert size_scenario(plan,0,1000,.5,2) == {}
    assert size_scenario(plan,10000,1000,.5,np.nan) == {}
    assert size_scenario(plan,10000,1000,.5,-1) == {}
    normal = size_scenario(plan,10000,1000,.5,0)
    stress = size_scenario(plan,10000,1000,.5,5)
    assert stress["shares"] < normal["shares"]
    assert normal["amount"] <= 1000 and normal["loss"] <= 50
    assert stress["loss"] <= 50


@pytest.mark.parametrize("kind", ["target", "stop", "both", "gap"])
def test_next_open_actual_soxl_basis_and_conservative_exit(kind):
    _, _, slots, xx, xl, signals = sample()
    at = signals[0]["time"]
    if kind == "target": xl.loc[at, ["High", "Low"]] = [65, 59.5]
    if kind in ("stop", "both"): xl.loc[at, "Low"] = 58
    if kind == "both": xl.loc[at, "High"] = 65
    if kind == "gap":
        xl.loc[at, "Low"] = 59.5
        xl.loc[slots.start.iloc[2], ["Open", "Low", "High", "Close"]] = [55,54,56,55]
    trades, _ = research.simulate(signals,xx,xl,slots)
    trade = trades[0]
    assert trade["entry"] == 60 and trade["stop"] == 59 and trade["target"] == 61
    assert trade["exit"] == ({"target":61, "stop":59, "both":59, "gap":61}[kind])
    if kind == "both": assert trade["ambiguous"]
    assert trade["exit_time"] > trade["signal_time"]


def test_gap_stop_and_soxx_close_delay():
    _, _, slots, xx, xl, signals = sample()
    xl.loc[:, "High"] = 60.5
    xl.loc[:, "Low"] = 59.5
    xl.loc[slots.start.iloc[0], "Low"] = 59
    xl.loc[slots.start.iloc[2], ["Open", "Low", "High", "Close"]] = [55,54,56,55]
    trades, _ = research.simulate(signals,xx,xl,slots)
    assert trades[0]["exit"] == 55 and trades[0]["reason"] == "gap_stop"
    xx.loc[slots.start.iloc[1], "Close"] = 94
    trades, _ = research.simulate(signals,xx,xl,slots)
    assert trades[0]["exit"] == 55 and trades[0]["reason"] == "soxx_stop_next_open"
    assert trades[0]["exit_time"] == slots.start.iloc[2]


def test_flat_close_and_overnight_are_distinct_without_market_gate_override():
    sched, _, slots, xx, xl, signals = sample()
    xl.loc[:, "High"] = 60.5
    xl.loc[:, "Low"] = 59.5
    xl.loc[slots.start.iloc[0], "Low"] = 58
    xl.loc[slots.start.iloc[7], ["Open", "Low", "High", "Close"]] = [50,49,51,50]
    day,_ = research.simulate(signals,xx,xl,slots)
    night,_ = research.simulate(signals,xx,xl,slots,same_day=False)
    assert day[0]["exit_time"] == sched.market_close.iloc[0]
    assert day[0]["reason"] == "session_close_proxy"
    assert night[0]["overnight"] and night[0]["exit"] == 50
    blocked,rejected = research.simulate(signals,xx,xl,slots,gates={})
    assert not blocked and rejected["gate_blocked_or_unknown"] == 1


def test_missing_never_fills_or_counts_as_loss_or_win():
    _, _, slots, xx, xl, signals = sample()
    xl.loc[signals[0]["time"],"High"] = np.nan
    trades,rejected = research.simulate(signals,xx,xl,slots)
    assert not trades and rejected["path_missing"] == 1
    assert research.summarize(trades)["win_pct"] is None
    xl = xl.drop(signals[0]["time"])
    assert not research.simulate(signals,xx,xl,slots)[0]


def test_no_double_entry_and_entry_outside_reference_rejected():
    _, _, slots, xx, xl, signals = sample()
    again = dict(signals[0], time=slots.start.iloc[3])
    trades, _ = research.simulate([*signals, again],xx,xl,slots)
    assert len(trades) == 1
    xx.loc[signals[0]["time"], "Open"] = 130
    trades, rejected = research.simulate(signals,xx,xl,slots)
    assert not trades and rejected["entry_outside_soxx_plan"] == 1


def test_early_close_partial_executes_but_never_signals():
    sched = schedule(days=1,early=True)
    now = sched.market_close.iloc[-1]
    slots = research.execution_grid(sched,now)
    assert len(slots) == 4 and slots.end.iloc[-1] - slots.start.iloc[-1] == pd.Timedelta(minutes=30)
    assert len(completed_hour_grid(sched,now)) == 3


def test_completed_hour_and_five_prices_ignore_future_changes():
    sched,now,_,xx,xl,_ = sample()
    at = sched.market_open.iloc[0]
    frame = xx.iloc[:1].copy()
    frame.index = pd.DatetimeIndex([at])
    future = frame.copy()
    future.index = pd.DatetimeIndex([at+pd.Timedelta(minutes=5)])
    future *= 10
    both = pd.concat([frame,future])
    result = paired_five({"SOXX":both,"SOXL":both},sched,at+pd.Timedelta(minutes=6))
    assert result["end"] == at+pd.Timedelta(minutes=5)
    assert all(row["close"] == 100 for row in result["rows"])


def test_interval_is_not_point_probability_and_policy_pair_is_by_entry():
    trades = [dict(net_pct=2.,mae_bound_pct=-1.,entry_time="a"),dict(net_pct=-1.,mae_bound_pct=-2.,entry_time="b")]
    stats = research.summarize(trades)
    assert stats["n"] == 2 and stats["win_pct"] == 50
    assert stats["interval"][0] < 50 < stats["interval"][1]
    paired = research.compare_policies(trades,[dict(entry_time="a",net_pct=5.)])
    assert paired["paired"] == 1 and paired["max_forgone_pp"] == 3 and paired["unpaired"] == 1


def test_signal_uses_prefix_never_future_pivots(monkeypatch):
    sched = schedule(days=25)
    grid = completed_hour_grid(sched, sched.market_close.iloc[-1])
    frame = pd.DataFrame(dict(Open=100.,High=103.,Low=94.,Close=101.), index=grid)
    seen = []
    def channel(prefix):
        seen.append(prefix.index[-1])
        return dict(lower=[95],upper=[120],known_at=prefix.index[-1],formation_id=str(prefix.index[-1]))
    monkeypatch.setattr(research,"build_parallel_channel",channel)
    before = research.signal_rows(frame)
    changed = frame.copy()
    changed.loc[grid[-1], "Close"] = 200
    after = research.signal_rows(changed)
    assert before[:-1] == after and all(t <= grid[-1] for t in seen)


def test_pair_does_not_fall_back_to_previous_missing_or_afterhours_bar():
    sched, _, _, xx, _, _ = sample()
    at = sched.market_open.iloc[0]
    frame = xx.iloc[:1].copy()
    frame.index = pd.DatetimeIndex([at])
    result = paired_five({"SOXX":frame,"SOXL":frame},sched,at+pd.Timedelta(minutes=5))
    assert not result["issue"] and all(r["close"] == 100 for r in result["rows"])
    result = paired_five({"SOXX":frame,"SOXL":frame},sched,at+pd.Timedelta(minutes=10))
    assert result["issue"] and all(r["close"] is None for r in result["rows"])


def test_outside_channel_is_unmet_not_data_outage():
    sched,now,_,_,_,_ = sample()
    hourly = dict(plan={},as_of=now,expected_end=now,channel={"lower":[90]},status="상단 돌파")
    result = build_five_observation(pd.DataFrame(),hourly,sched,now)
    assert result["status"] == "타점 조건 미충족"


def test_context_price_scenario_still_exists_outside_soxx_channel():
    sched,now,_,_,xl,_ = sample()
    grid = completed_hour_grid(sched,now)
    xx = pd.DataFrame(dict(Open=100.,High=103.,Low=99.,Close=102.),index=grid)
    hourly = dict(frame=xx,channel={"lower":[90],"upper":[95]},plan={},status="상단 돌파",
                  as_of=grid[-1]+HOUR,expected_end=grid[-1]+HOUR)
    context = build_price_context({"SOXL":xl},hourly,sched,now)
    assert context["plan"]["entry"] == 60 and not context["signal"]
    assert not context["session_active"]


def test_ui_no_trade_permission_and_budget_inputs_do_not_mutate_decision(monkeypatch):
    from stock_lab_core.soxl_trade_view import render_trade_desk, render_stats
    sched,now,_,xx,xl,_ = sample()
    grid = completed_hour_grid(sched,now)
    hourly = dict(frame=xx.reindex(grid),channel={},plan={},status="채널 미형성",
                  as_of=grid[-1]+HOUR,expected_end=grid[-1]+HOUR)
    decision = {"execution_workflow":{"게이트상태":"방어우선","게이트근거":"시장방어"},"buy_amt":0}
    before = deepcopy(decision)
    ui=UI()
    render_trade_desk(ui,dict(frames={"SOXL":xl},five_minute={}),hourly,sched,now,decision,str)
    assert decision == before and "시장방어" in str(ui.tables)
    assert "과거 검증 미실행" in " ".join(ui.text)
    empty = research.summarize([])
    policy = dict(stats=empty,early=empty,late=empty,cost20=empty,trades=[],rejected={})
    render_stats(ui,dict(rule="test",policies={"day":policy,"overnight":policy},first=now,last=now,missing={}),str)
    assert "미산출" in str(ui.tables) and "0.0%" not in str(ui.tables)


def test_manual_entry_below_reference_explains_numbers_without_widening_stop(monkeypatch):
    from stock_lab_core.soxl_trade_view import render_trade_desk
    sched, now, _, xx, xl, _ = sample()
    xl = xl.copy()
    xl.loc[:, "Open"] = 65.
    xl.loc[:, "Close"] = 65.53
    xl.loc[:, "High"] = 66.
    xl.loc[:, "Low"] = 64.41
    grid = completed_hour_grid(sched, now)
    hourly = dict(frame=xx.reindex(grid), channel={}, plan={}, status="채널 미형성",
                  as_of=grid[-1]+HOUR, expected_end=grid[-1]+HOUR)
    decision = {"execution_workflow": {"게이트상태": "방어우선", "게이트근거": "시장방어"}, "buy_amt": 0}
    before = deepcopy(decision)
    ui = UI()
    ui.number_input = lambda label, **kw: 64. if kw["key"] == "soxl_scenario_entry_v1" else kw.get("value", 0.)
    render_trade_desk(ui, dict(frames={"SOXL": xl}, five_minute={}), hourly, sched, now, decision, str)
    text = " ".join(ui.text)
    assert "$64.00" in text and "$64.41" in text and "손절선은 자동으로 낮아지지" in text
    assert not any("1R 익절 참고선" in str(table) for table in ui.tables)
    assert all(row["수량"] == "미산출" for table in ui.tables for row in table if "손실예산" in row)
    assert decision == before
