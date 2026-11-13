"""Shared research across US/KR stocks and ETFs, without changing investment gates."""

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import short_trade_research as engine
from stock_lab_core import short_trade_evidence as evidence
from stock_lab_core import short_trade_data as data
from stock_lab_core.soxl_short_observation import completed_hour_grid, HOUR
from tests.test_soxl_short_observation import UI, schedule


def frame_fixture(market="US"):
    sched = schedule(days=35)
    if market == "KR":
        sched = sched - pd.Timedelta(hours=14, minutes=30)
    now = sched.market_close.iloc[-1]
    grid = pd.DatetimeIndex(engine.execution_grid(sched, now).start)
    wave = 100 + np.sin(np.arange(len(grid)) * .3) * 5 + np.arange(len(grid)) * .03
    frame = pd.DataFrame(dict(Open=wave, High=wave+3, Low=wave-3, Close=wave+.3), index=grid)
    return sched, now, frame


@pytest.mark.parametrize("ticker,market", [("MSFT","US"),("RAM","US"),("BITX","US"),
                                         ("QLD","US"),("005930.KS","KR"),("418660.KS","KR")])
def test_profiles_use_own_prices_not_inferred_three_times_or_cross_market(ticker,market):
    profile = data.research_profile(ticker)
    assert profile["market"] == market and profile["reference"] == ticker
    assert data.research_profile("SOXL")["reference"] == "SOXX"


@pytest.mark.parametrize("ticker", ["BTC-USD","NQ=F","^SOX","", "../../secrets", "ABC.LONDON"])
def test_unsupported_non_equity_sessions_are_not_silently_us(ticker):
    assert data.research_profile(ticker) is None


def test_same_inputs_us_kr_have_same_arithmetic_no_symbol_or_market_leakage(monkeypatch):
    def channel(prefix):
        close = float(prefix.Close.iloc[-1])
        return dict(lower=[close-2], upper=[close+10], known_at=prefix.index[-1],
                    formation_id=str(prefix.index[-1]))
    monkeypatch.setattr(engine, "build_parallel_channel", channel)
    outputs = []
    for ticker,market in (("MSFT","US"),("005930.KS","KR")):
        sched,now,frame = frame_fixture(market)
        report = evidence.build_report({ticker:frame},sched,now,data.research_profile(ticker))
        assert not report["issue"] and report["missing"] == {ticker:0}
        assert report["policies"]["day"]["stats"]["n"] > 0
        outputs.append(report["policies"])
    for policy in ("day","overnight"):
        assert outputs[0][policy]["stats"] == outputs[1][policy]["stats"]


def test_current_validity_missing_latest_and_future_prices(monkeypatch):
    sched,now,frame = frame_fixture()
    profile=data.research_profile("MSFT")
    def channel(prefix):
        return dict(lower=[float(prefix.Close.iloc[-1])-1], upper=[float(prefix.Close.iloc[-1])+10],
                    known_at=prefix.index[-1],formation_id="fixed")
    monkeypatch.setattr(evidence,"build_parallel_channel",channel)
    current=evidence.current_context({"MSFT":frame},sched,now,profile)
    assert current["setup"] and current["plan"] and current["cohort"]
    future=frame.iloc[-1:].copy()
    future.index=pd.DatetimeIndex([now+HOUR])
    future *= 10
    after=evidence.current_context({"MSFT":pd.concat([frame,future])},sched,now,profile)
    assert after == current
    grid=completed_hour_grid(sched,now)
    missing=frame.drop(grid[-1])
    assert not evidence.current_context({"MSFT":missing},sched,now,profile)["setup"]
    malformed=frame.copy()
    malformed.loc[grid[-1],"High"]=1
    assert not evidence.current_context({"MSFT":malformed},sched,now,profile)["plan"]


def test_cohort_only_uses_signal_information_and_no_future_trade_outcomes():
    _,now,frame=frame_fixture()
    at=frame.index[20]
    before=evidence.cohort_at(frame,frame,at)
    changed=frame.copy()
    changed.loc[changed.index>at, "Close"]=1
    assert evidence.cohort_at(changed,changed,at) == before
    current=dict(setup=True,cohort=before,as_of=now)
    trades=[dict(cohort=before,exit_time=now-HOUR,net_pct=1.,mae_bound_pct=-1.),
            dict(cohort=before,exit_time=now+HOUR,net_pct=100.,mae_bound_pct=0.),
            dict(cohort="other",exit_time=now-HOUR,net_pct=100.,mae_bound_pct=0.)]
    stats=evidence.comparable_history(dict(trades=trades),current)
    assert stats["n"] == 1 and stats["mean_pct"] == 1
    assert evidence.comparable_history(dict(trades=trades),dict(current,setup=False))["win_pct"] is None


def test_validation_is_not_winrate_optimization_or_buy_permission():
    good=engine.summarize([dict(net_pct=1.,mae_bound_pct=-1.)]*40)
    small=engine.summarize([dict(net_pct=1.,mae_bound_pct=-1.)]*2)
    bad=engine.summarize([dict(net_pct=-1.,mae_bound_pct=-1.)]*40)
    policy=dict(stats=good,early=good,late=good,cost20=good)
    assert evidence.validation_state(policy)[0] == "전진검증 후보"
    assert evidence.validation_state(dict(policy,stats=small))[0] == "표본 부족"
    assert evidence.validation_state(dict(policy,late=bad))[0] == "안정성 미확인"
    assert evidence.validation_state(dict(policy,stats=bad))[0] == "우위 미확인"
    assert evidence.validation_state(dict(policy,stats=engine.summarize([])))[0] == "검증 불가"


def test_loader_is_symbol_scoped_regular_adjusted_and_failure_explicit(monkeypatch):
    import yfinance
    _,_,frame=frame_fixture()
    calls=[]
    def download(tickers,**kw):
        calls.append((tickers,kw))
        assert not kw["prepost"] and kw["auto_adjust"] and not kw["ignore_tz"]
        assert kw["interval"] == "60m" and kw["timeout"] == 10
        return pd.concat({t:frame for t in tickers},axis=1)
    monkeypatch.setattr(yfinance,"download",download)
    assert data.load_history.__wrapped__("MSFT")["ok"]
    assert calls[-1][0] == ["MSFT"]
    assert data.load_current.__wrapped__("418660.KS")["ok"]
    assert calls[-1][0] == ["418660.KS"]
    monkeypatch.setattr(yfinance,"download",lambda *a,**kw: frame)
    assert data.load_history.__wrapped__("MSFT")["ok"]
    assert not data.load_history.__wrapped__("SOXL")["ok"]
    def fail(*a,**kw): raise TimeoutError("test")
    monkeypatch.setattr(yfinance,"download",fail)
    result=data.load_history.__wrapped__("RAM")
    assert not result["ok"] and "TimeoutError" in result["issue"]


def test_fingerprint_is_reproducible_and_not_account_dependent():
    _,_,frame=frame_fixture()
    first=evidence.input_fingerprint({"MSFT":frame})
    assert first == evidence.input_fingerprint({"MSFT":frame.copy()})
    changed=frame.copy()
    changed.iloc[-1,3] += .1
    assert first != evidence.input_fingerprint({"MSFT":changed})


def test_rerender_no_fetch_and_decision_unchanged(monkeypatch):
    from stock_lab_core import short_trade_view as view
    def fail(*a,**kw): raise AssertionError("unexpected download")
    monkeypatch.setattr(view,"load_history",fail)
    monkeypatch.setattr(view,"load_current",fail)
    decision={"execution_workflow":{"게이트상태":"방어우선","게이트근거":"시장방어"}}
    before=deepcopy(decision)
    for ticker in ("MSFT","RAM","BITX","418660.KS"):
        ui=UI()
        view.render_symbol_research(ui,ticker,decision)
        assert not ui.session_state and "과거 검증 미실행" in " ".join(ui.text)
    assert decision == before


def test_ui_all_missing_has_no_zero_percent_or_false_success():
    from stock_lab_core.short_trade_view import render_evidence
    ui=UI()
    render_evidence(ui,{"issue":"시간봉 미확보","policies":{}},{},data.research_profile("MSFT"),"test")
    assert "미확보" in " ".join(ui.text) and not ui.tables


def test_changed_cost_hides_stale_result_and_ticker_state_isolated(monkeypatch):
    from stock_lab_core import short_trade_view as view
    def fail(*a, **kw): raise AssertionError("rerender must not download")
    monkeypatch.setattr(view, "load_history", fail)
    monkeypatch.setattr(view, "load_current", fail)
    ui = UI()
    ui.session_state["short_evidence_v1_MSFT"] = {"cost": 20., "report": {"policies": {}}}
    before = deepcopy(ui.session_state)
    view.render_symbol_research(ui, "MSFT")
    assert "비용 가정 변경" in " ".join(ui.text)
    ui.text.clear()
    view.render_symbol_research(ui, "RAM")
    assert "과거 검증 미실행" in " ".join(ui.text)
    assert ui.session_state == before


def test_frequency_does_not_look_like_positive_return():
    from stock_lab_core.short_trade_view import _frequency
    assert _frequency(35.1) == "35.1%"
    assert _frequency(None) == "미산출"


def test_new_panel_is_only_precision_display_not_score_function():
    import ast
    from pathlib import Path
    tree=ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
           and n.func.id == "render_symbol_research"]
    assert len(calls) == 1
    for func in (n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))):
        assert not any(call in list(ast.walk(func)) for call in calls)
