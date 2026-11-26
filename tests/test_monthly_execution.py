"""C-6/C-11 step 3 (2026-11-26): four monthly amounts, per-type monthly gate, scout cap, storage scope and records."""
from datetime import datetime, timezone

import pandas as pd

from stock_lab_core import monthly_store
from stock_lab_core.monthly_execution import (TYPE_CORE_ETF, TYPE_LEVERAGE, TYPE_STOCK, TYPE_SWING,
                                              active_confirmed_plan, executed_by_ticker, execution_key, four_amounts,
                                              holding_type, kst_month_key, monthly_gate)
from stock_lab_core.monthly_execution_view import build_execution_rows


def test_kst_month_key_uses_korea_time():
    assert kst_month_key(datetime(2026, 11, 30, 15, 30, tzinfo=timezone.utc)) == "2026-12"
    assert kst_month_key(datetime(2026, 11, 30, 14, 59, tzinfo=timezone.utc)) == "2026-11"


def test_holding_types():
    assert holding_type("core", True) == TYPE_CORE_ETF
    assert holding_type("core", False) == TYPE_STOCK
    assert holding_type("swing", True) == TYPE_SWING
    assert holding_type("leverage", True) == TYPE_LEVERAGE


def test_monthly_gate_c2_for_core_etf_only_and_c1_elsewhere():
    timing = "R/R 1.2 · 과열/추격금지"
    assert monthly_gate(TYPE_CORE_ETF, "대기/관찰", timing)[0] is True
    for htype in (TYPE_STOCK, TYPE_SWING, TYPE_LEVERAGE):
        assert monthly_gate(htype, "대기/관찰", timing)[0] is False
        assert monthly_gate(htype, "실행가능", "")[0] is True
    # Safety blocks, MTF damage (D not active), leveraged conditional and mixed reasons block core ETF too.
    for state, reason in (("방어우선", "상위 시간대 추세훼손"), ("데이터확인", "매크로 미확인"),
                          ("대기/관찰", "레버리지 조건부 DCA"), ("대기/관찰", "R/R 1.2 · 실행 신호 아님")):
        assert monthly_gate(TYPE_CORE_ETF, state, reason)[0] is False
    assert monthly_gate(TYPE_CORE_ETF, None, None)[0] is None


def test_four_amounts_take_the_smallest_limit():
    base = dict(plan_krw=300000.0, executed_krw=100000.0, shortfall_krw=1e9, gate_allowed=True, cash_krw=1e9)
    a = four_amounts(**base)
    assert (a["plan"], a["executed"], a["executable"], a["remaining"], a["limit"]) == (300000.0, 100000.0, 200000.0, 0.0, "월 계획 잔액")
    assert four_amounts(**dict(base, shortfall_krw=50000.0))["executable"] == 50000.0
    assert four_amounts(**dict(base, cash_krw=30000.0))["executable"] == 30000.0
    blocked = four_amounts(**dict(base, gate_allowed=False))
    assert blocked["executable"] == 0.0 and blocked["remaining"] == 200000.0


def test_scout_cap_is_never_exceeded_by_repeated_execution():
    first = four_amounts(plan_krw=300000.0, executed_krw=0.0, shortfall_krw=1e9, gate_allowed=True,
                         sizing="1차 정찰대: 목표비중의 1/3", cash_krw=1e9)
    assert first["executable"] == 100000.0
    again = four_amounts(plan_krw=300000.0, executed_krw=100000.0, shortfall_krw=1e9, gate_allowed=True,
                         sizing="1차 정찰대: 목표비중의 1/3", cash_krw=1e9)
    assert again["executable"] == 0.0


def test_missing_inputs_stay_unknown():
    assert four_amounts(plan_krw=None, executed_krw=0.0, shortfall_krw=1.0, gate_allowed=True, cash_krw=1.0)["executable"] is None
    assert four_amounts(plan_krw=1.0, executed_krw=None, shortfall_krw=1.0, gate_allowed=True, cash_krw=1.0)["executable"] is None
    assert four_amounts(plan_krw=1.0, executed_krw=0.0, shortfall_krw=1.0, gate_allowed=None, cash_krw=1.0)["executable"] is None
    assert four_amounts(plan_krw=1.0, executed_krw=0.0, shortfall_krw=None, gate_allowed=True, cash_krw=1.0)["executable"] is None
    assert four_amounts(plan_krw=1.0, executed_krw=0.0, shortfall_krw=1.0, gate_allowed=True, cash_krw=None)["executable"] is None


def test_holdings_and_log_are_not_subtracted_twice():
    # After a 100k buy, holdings show a smaller shortfall AND the log shows 100k executed: min() keeps one deduction.
    a = four_amounts(plan_krw=300000.0, executed_krw=100000.0, shortfall_krw=400000.0, gate_allowed=True, cash_krw=1e9)
    assert a["executable"] == 200000.0


def test_other_scope_or_month_records_are_ignored_and_latest_plan_version_wins():
    rows = [{"account_scope": "A|B", "month_key": "2026-11", "ticker": "qqq", "amount_krw": 1000},
            {"account_scope": "A", "month_key": "2026-11", "ticker": "QQQ", "amount_krw": 5000},
            {"account_scope": "A|B", "month_key": "2026-10", "ticker": "QQQ", "amount_krw": 7000}]
    assert executed_by_ticker(rows, account_scope="A|B", month_key="2026-11") == {"QQQ": 1000.0}
    plans = [{"account_scope": "A|B", "month_key": "2026-11", "ticker": "QQQ", "plan_version": 1, "plan_krw": 1},
             {"account_scope": "A|B", "month_key": "2026-11", "ticker": "QQQ", "plan_version": 2, "plan_krw": 2}]
    assert active_confirmed_plan(plans, account_scope="A|B", month_key="2026-11")["QQQ"]["plan_krw"] == 2


def test_storage_scope_is_the_account_set_and_execution_key_is_stable():
    assert monthly_store.storage_scope(["일반", "ISA", "ISA"]) == "ISA|일반"
    assert monthly_store.storage_scope([]) == "미확인"
    k = execution_key(account_scope="ISA|일반", month_key="2026-11", ticker="qqq", exec_date="2026-11-26", signal_key="s1")
    assert k == execution_key(account_scope="ISA|일반", month_key="2026-11", ticker="QQQ", exec_date="2026-11-26", signal_key="s1")


class _Table:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.payload = db, name, [], None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def insert(self, payload):
        self.payload = payload if isinstance(payload, list) else [payload]
        return self

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        if self.payload is None:
            return type("R", (), {"data": [r for r in rows if all(r.get(k) == v for k, v in self.filters)]})()
        for row in self.payload:
            if self.name == monthly_store.EXECUTIONS and any(
                    r["exec_key"] == row["exec_key"] and r["owner_email"] == row["owner_email"] for r in rows):
                raise RuntimeError("duplicate key value violates unique constraint (23505)")
        rows.extend(self.payload)
        return type("R", (), {"data": self.payload})()


class _Client:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return _Table(self.db, name)


def test_confirm_adds_versions_and_duplicate_execution_is_refused():
    client = _Client()
    rows = [{"ticker": "QQQ", "final_alloc": 300000.0, "multiplier": 1.0, "tap_raw": "x"},
            {"ticker": "TQQQ", "final_alloc": 0.0, "signal_unknown": True}]
    n, status = monthly_store.confirm_plan(client, owner_email="o", account_scope="A", month_key="2026-11", rows=rows, existing=[])
    assert (n, status) == (1, "ok")  # unknown-signal rows are never confirmed
    existing, _ = monthly_store.load_month(client, monthly_store.PLANS, owner_email="o", account_scope="A", month_key="2026-11")
    monthly_store.confirm_plan(client, owner_email="o", account_scope="A", month_key="2026-11", rows=rows, existing=existing)
    assert [r["plan_version"] for r in client.db[monthly_store.PLANS]] == [1, 2]
    kw = dict(owner_email="o", account_scope="A", month_key="2026-11", ticker="QQQ", exec_date="2026-11-26",
              amount_krw=100000.0, plan_version=2, exec_key="k1", conditions={})
    assert monthly_store.record_execution(client, **kw) == "ok"
    assert monthly_store.record_execution(client, **kw) == "duplicate"
    assert monthly_store.record_execution(client, **dict(kw, amount_krw=0)) == "invalid"


def test_missing_table_is_reported_not_zero():
    class Broken:
        def table(self, name):
            raise RuntimeError("relation \"monthly_dca_plans\" does not exist")
    assert monthly_store.load_month(Broken(), monthly_store.PLANS, owner_email="o", account_scope="A", month_key="2026-11") == ([], "table_missing")


def test_execution_rows_keep_confirmed_plan_when_signal_is_lost_and_share_cash():
    holdings = pd.DataFrame([{"티커": "QQQ", "목표비중": 50, "현재비중": 10},
                             {"티커": "SPY", "목표비중": 50, "현재비중": 10}])
    calc = [{"ticker": "QQQ", "name": "QQQ", "bucket": "core", "is_etf": True, "final_alloc": 0.0, "signal_unknown": True},
            {"ticker": "SPY", "name": "SPY", "bucket": "core", "is_etf": True, "final_alloc": 200000.0}]
    gate = {"QQQ": {"state": "실행가능"}, "SPY": {"state": "실행가능"}}
    rows = build_execution_rows(calc, holdings, total_asset=10_000_000, cash_krw=250000.0, gate_reader=gate.get,
                                decisions={}, confirmed={"QQQ": {"plan_krw": 300000.0, "plan_version": 1}},
                                executed={}, executed_status="ok")
    qqq, spy = rows
    assert qqq["plan"] == 300000.0 and qqq["executable"] == 0.0 and qqq["plan_src"] == "확정 v1"
    assert spy["plan"] == 200000.0 and spy["executable"] == 200000.0
    no_store = build_execution_rows(calc, holdings, total_asset=10_000_000, cash_krw=250000.0, gate_reader=gate.get,
                                    decisions={}, confirmed={}, executed={}, executed_status="no_client")
    assert no_store[0]["plan"] is None and no_store[1]["executed"] is None and no_store[1]["executable"] is None
