"""C-8 crisis fund: trigger, 6-tranche schedule, guard deferral, no default amount (2026-11-26)."""
import numpy as np
import pandas as pd

from stock_lab_core import crisis_fund as cf
from stock_lab_core import crisis_fund_store as store
from stock_lab_core.crisis_fund_view import build_crisis_rows
from stock_lab_core.monthly_execution import TYPE_CORE_ETF


def _df(path, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(path))
    close = pd.Series(path, index=idx, dtype=float)
    return pd.DataFrame({"Close": close, "High": close})


def _crash():
    up = list(np.linspace(100, 120, 300))
    down = list(np.linspace(119, 66, 60))  # reaches -40% of 120 (=72) near the end
    flat = [66.0] * 150
    return _df(up + down + flat)


def test_trigger_is_first_close_at_minus_40_of_52w_high():
    df = _crash()
    start = cf.latest_episode_start(df)
    dd = cf.drawdown_52w(df)
    assert start is not None and dd.loc[start] <= -0.40
    assert (dd.loc[:start].iloc[:-1] > -0.40).all()


def test_rearm_needs_recovery_above_minus_20():
    df = _crash()
    path = list(df["Close"]) + list(np.linspace(66, 130, 80)) + list(np.linspace(129, 70, 60))
    df2 = _df(path)
    first = cf.latest_episode_start(_crash())
    second = cf.latest_episode_start(df2)
    assert second is not None and second > first


def test_schedule_six_tranches_first_trading_day_of_next_months():
    days = pd.bdate_range("2026-07-01", "2026-11-24")
    sch = cf.tranche_schedule(days, "2026-07-29")
    assert [t["no"] for t in sch] == [1, 2, 3, 4, 5, 6]
    assert str(sch[0]["date"].date()) == "2026-07-29"
    assert str(sch[1]["date"].date()) == "2026-08-03"
    assert sch[5]["date"] is None and sch[5]["month"] == "2026-12"


def _status(**kw):
    days = pd.bdate_range("2026-07-01", "2026-11-24")
    base = dict(eligible=True, episode_start=pd.Timestamp("2026-07-29"), schedule=cf.tranche_schedule(days, "2026-07-29"),
                today=pd.Timestamp("2026-07-29"), fund_total=600000, executed_nos=[], guard_market=cf.GUARD_OK,
                cash_available=10_000_000)
    base.update(kw)
    return cf.crisis_status(**base)


def test_no_fund_is_candidate_only_and_no_amount():
    s = _status(fund_total=None)
    assert s["state"] == "candidate" and s["amount"] == 0.0 and "미설정" in s["text"]
    assert _status(fund_total=0)["state"] == "candidate"


def test_executable_tranche_is_one_sixth():
    s = _status()
    assert s["state"] == "executable" and s["due_nos"] == [1] and s["amount"] == 100000


def test_guard_stop_or_unknown_defers():
    for market in (cf.GUARD_STOP, None, "시장정보 확인 필요: 한국 지수 데이터 미확인"):
        s = _status(guard_market=market)
        assert s["state"] == "deferred" and s["amount"] == 0.0


def test_one_tranche_per_day_oldest_first():
    s = _status(today=pd.Timestamp("2026-08-04"))
    assert s["state"] == "executable" and s["due_nos"] == [1] and s["amount"] == 100000 and "대기 1회차" in s["text"]
    s = _status(today=pd.Timestamp("2026-08-04"), executed_today=True, executed_nos=[1])
    assert s["state"] == "deferred" and s["due_nos"] == [2] and s["amount"] == 0.0
    s = _status(today=pd.Timestamp("2026-08-05"), executed_nos=[1])
    assert s["state"] == "executable" and s["due_nos"] == [2]
    s = _status(today=pd.Timestamp("2026-11-24"), executed_nos=[1, 2, 3, 4, 5])
    assert s["state"] == "waiting"
    s = _status(today=pd.Timestamp("2026-12-31"), executed_nos=[1, 2, 3, 4, 5, 6])
    assert s["state"] == "done" and s["amount"] == 0.0


def test_account_cash_checked():
    assert _status(cash_available=50000)["state"] == "deferred"
    assert "가용 현금 부족" in _status(cash_available=50000)["text"]
    assert "가용 현금 미확인" in _status(cash_available=None)["text"]


def test_not_eligible_or_no_episode():
    assert _status(eligible=False)["state"] == "none"
    assert _status(episode_start=None)["state"] == "none"


def test_store_helpers_versions_and_keys():
    rows = [{"ticker": "qqq", "fund_version": 1, "total_krw": 100}, {"ticker": "QQQ", "fund_version": 2, "total_krw": 200}]
    assert store.active_funds(rows)["QQQ"]["total_krw"] == 200
    tr = [{"ticker": "QQQ", "episode_start": "2026-07-29", "tranche_no": 1},
          {"ticker": "QQQ", "episode_start": "2025-01-02", "tranche_no": 2}]
    assert store.executed_tranches(tr, ticker="QQQ", episode_start="2026-07-29") == [1]
    assert store.tranche_key("A|B", "qqq", "2026-07-29", 3) == "A|B|QQQ|2026-07-29|3"


class _Fail:
    def table(self, name):
        raise RuntimeError(f'relation "{name}" does not exist')


def test_store_table_missing_and_invalid():
    assert store.load_scope(_Fail(), store.FUNDS, owner_email="o", account_scope="s") == ([], "table_missing")
    assert store.save_fund(_Fail(), owner_email="o", account_scope="s", ticker="Q", total_krw=0, existing=[]) == "invalid"
    assert store.save_fund(_Fail(), owner_email="o", account_scope="s", ticker="Q", total_krw=10, existing=[]) == "table_missing"


def test_view_rows_two_etfs_same_day_each_uses_own_fund():
    df = _crash()
    start = cf.latest_episode_start(df)
    rows = [{"ticker": "AAA", "name": "A", "type": TYPE_CORE_ETF, "shortfall": 1.0},
            {"ticker": "BBB", "name": "B", "type": TYPE_CORE_ETF, "shortfall": 1.0},
            {"ticker": "CCC", "name": "C", "type": "long_term_stock", "shortfall": 1.0},
            {"ticker": "DDD", "name": "D", "type": TYPE_CORE_ETF, "shortfall": 0.0}]
    out = build_crisis_rows(rows, price_loader=lambda t: df, gate_reader=lambda t: {"market": cf.GUARD_OK},
                            funds={"AAA": {"total_krw": 600, "fund_version": 1}, "BBB": {"total_krw": 1200, "fund_version": 1}},
                            tranche_rows=[], today=start, cash_available=1000)
    by = {r["ticker"]: r for r in out}
    assert set(by) == {"AAA", "BBB", "DDD"}
    assert by["AAA"]["status"]["amount"] == 100 and by["BBB"]["status"]["amount"] == 200
    assert by["DDD"]["status"]["state"] == "none"
    # Account cash is shared: with 250 left only the first ETF's tranche fits, the second waits.
    out = build_crisis_rows(rows[:2], price_loader=lambda t: df, gate_reader=lambda t: {"market": cf.GUARD_OK},
                            funds={"AAA": {"total_krw": 600, "fund_version": 1}, "BBB": {"total_krw": 1200, "fund_version": 1}},
                            tranche_rows=[], today=start, cash_available=250)
    assert out[0]["status"]["state"] == "executable" and out[1]["status"]["state"] == "deferred"
    # A tranche already recorded today for AAA blocks a second one today.
    tr = [{"ticker": "AAA", "episode_start": str(start.date()), "tranche_no": 1, "exec_date": str(start.date())}]
    out = build_crisis_rows(rows[:1], price_loader=lambda t: df, gate_reader=lambda t: {"market": cf.GUARD_OK},
                            funds={"AAA": {"total_krw": 600, "fund_version": 1}}, tranche_rows=tr, today=start,
                            cash_available=1000)
    assert out[0]["status"]["state"] in ("waiting", "deferred")
