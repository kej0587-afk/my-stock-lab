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


# ── D: core regular-DCA trend-damage exception (user decision 2026-11-26 12:59 KST) ──────────────────────────
from stock_lab_core.monthly_execution import (CORE_MTF_EXCEPTION_CODES, CORE_MTF_EXCEPTION_TEXT,  # noqa: E402
                                              core_dca_gate_without_mtf_damage)
from stock_lab_core.execution_gate import build_execution_gate  # noqa: E402


def _row(code, **extra):
    row = {"티커": "QQQ", "판정코드": code, "상위시간대상태": "상위 시간대 경고", "시장실행상태": "정상",
           "데이터상태": "OK", "매크로상태": "OK", "최종읽기": "", "🔥기술적 타점": "", "RSI": 40.0, "MFI": 40.0,
           "볼린저 %B": 0.3, "RR값": 1.5, "판정분류": "buyish"}
    row.update(extra)
    return row


def test_trend_damage_alone_blocks_today_but_not_core_dca_for_allowed_codes():
    for code in CORE_MTF_EXCEPTION_CODES:
        row = _row(code)
        assert build_execution_gate(row)["게이트근거"] == "상위 시간대 추세훼손"  # Today gate unchanged
        d = core_dca_gate_without_mtf_damage(row)
        assert d["state"] == "실행가능" and d["mtf_exception"] is True, code
        allowed, text = monthly_gate(TYPE_CORE_ETF, "방어우선", "상위 시간대 추세훼손", d)
        assert allowed is True and text.startswith(CORE_MTF_EXCEPTION_TEXT)


def test_exception_never_bypasses_other_safety_blocks():
    cases = {
        "market": dict(시장실행상태="시장방어: 신규매수 중단"),
        "data": dict(데이터상태="가격 기준일 확인 필요"),
        "macro_unknown": dict(매크로상태="UNKNOWN", 매크로누락="VIX"),
        "weight": dict(최종읽기="비중 초과: 추매 금지"),
        "target_zero": dict(최종읽기="TARGET_ZERO 추가 제외"),
        "defense": dict(최종읽기="급락방어 우선"),
        "indicator": dict(RSI=float("nan")),
    }
    for name, extra in cases.items():
        d = core_dca_gate_without_mtf_damage(_row("CORE_DRAWDOWN_DCA", **extra))
        assert d["state"] in ("방어우선", "데이터확인"), (name, d)
        allowed, text = monthly_gate(TYPE_CORE_ETF, "방어우선", "상위 시간대 추세훼손", d)
        assert allowed is False and "다른 차단 유지" in text, name


def test_exception_excludes_storm_panic_hard_blocks_and_rows_without_damage():
    for code in ("CORE_STORM_DCA", "PANIC_CASH_DEPLOY", "PANIC_FINAL_DEPLOY", "MACRO_STORM_HOLDING_CAUTION",
                 "HARD_BLOCK_MACRO_STORM", "HARD_BLOCK_OVERWEIGHT", "TARGET_ZERO_NO_ADD", "S_PULLBACK_ENTRY"):
        assert core_dca_gate_without_mtf_damage(_row(code)) is None, code
    assert core_dca_gate_without_mtf_damage(_row("CORE_CRASH_DCA", 상위시간대상태="중립 확인")) is None
    # Without an exception the core ETF gate is the C2 rule from step 3.
    assert monthly_gate(TYPE_CORE_ETF, "방어우선", "상위 시간대 추세훼손", None)[0] is False


def test_exception_is_ignored_for_stock_swing_and_leverage():
    d = {"state": "실행가능", "reason": "", "mtf_exception": True}
    for htype in (TYPE_STOCK, TYPE_SWING, TYPE_LEVERAGE):
        assert monthly_gate(htype, "방어우선", "상위 시간대 추세훼손", d)[0] is False


# ── step 5: L3 reads the unexecuted rest of the confirmed plan (same scope, KST month) ───────────────────────
from stock_lab_core.monthly_execution import confirmed_plan_remaining  # noqa: E402
from stock_lab_core import leverage_l3_policy as l3  # noqa: E402


def test_l3_monthly_planned_is_confirmed_plan_minus_executed():
    plans = [{"account_scope": "A", "month_key": "2026-11", "ticker": "TQQQ", "plan_version": 1, "plan_krw": 300000},
             {"account_scope": "A", "month_key": "2026-11", "ticker": "TQQQ", "plan_version": 2, "plan_krw": 200000},
             {"account_scope": "B", "month_key": "2026-11", "ticker": "TQQQ", "plan_version": 9, "plan_krw": 900000}]
    execs = [{"account_scope": "A", "month_key": "2026-11", "ticker": "TQQQ", "amount_krw": 50000},
             {"account_scope": "A", "month_key": "2026-10", "ticker": "TQQQ", "amount_krw": 70000}]
    kw = dict(account_scope="A", month_key="2026-11")
    assert confirmed_plan_remaining(plans, "ok", execs, "ok", ticker="tqqq", **kw) == 150000.0
    assert confirmed_plan_remaining(plans, "ok", execs, "ok", ticker="QLD", **kw) == 0.0  # confirmed month, no plan
    assert confirmed_plan_remaining([], "ok", [], "ok", ticker="TQQQ", **kw) is None  # no confirmed plan: candidate
    assert confirmed_plan_remaining(plans, "table_missing", [], "ok", ticker="TQQQ", **kw) is None
    assert confirmed_plan_remaining(plans, "ok", [], "error", ticker="TQQQ", **kw) is None
    over = execs + [{"account_scope": "A", "month_key": "2026-11", "ticker": "TQQQ", "amount_krw": 500000}]
    assert confirmed_plan_remaining(plans, "ok", over, "ok", ticker="TQQQ", **kw) == 0.0


def test_l3_tranche_rule_is_unchanged_and_uses_the_remaining_plan():
    # Same tranche formula: min(budget/3, budget − invested, shortfall − monthly remaining).
    assert l3.tranche_amount(900000, 0, 1000000, 150000) == 300000
    assert l3.tranche_amount(900000, 0, 400000, 150000) == 250000
    assert l3.tranche_amount(900000, 0, 400000, None) == 300000


# ── Standard names (user decision 2026-11-26 16:37 KST) ─────────────────────────────────────────────────────
from stock_lab_core.monthly_execution import (STD_APP_RATE, STD_EXCESS, STD_EXECUTED, STD_OPEN,  # noqa: E402
                                              STD_PLAN, STD_TODAY, STD_WAIT, execution_rate, standard_amounts)


def _std(plan, executed, *, shortfall=1_000_000.0, allowed=True, sizing="1차 정찰대: 목표비중의 1/3",
         cash=1_000_000.0, status="ok", src="임시(미확정)", gate_text="실행가능"):
    a = four_amounts(plan_krw=plan, executed_krw=executed, shortfall_krw=shortfall, gate_allowed=allowed,
                     sizing=sizing, cash_krw=cash)
    return standard_amounts(dict(a, plan_src=src, gate_text=gate_text), executed_status=status)


def test_standard_example_before_and_after_a_recorded_buy():
    before = _std(300000.0, 0.0)
    assert (before["_open"], before[STD_TODAY], before["_wait"]) == (300000.0, "100,000원 (상한: 1차 정찰 1/3)", 200000.0)
    assert before[STD_PLAN] == "300,000원 · 임시 계획" and before[STD_EXECUTED] == "0원 · 기록 없음"
    after = _std(300000.0, 60000.0, src="확정 v2")
    assert after[STD_PLAN] == "300,000원 · 확정 계획 v2" and after[STD_EXECUTED] == "60,000원"
    assert (after["_open"], after[STD_TODAY], after["_wait"]) == (240000.0, "40,000원 (상한: 1차 정찰 1/3)", 200000.0)
    assert after[STD_APP_RATE] == "20.0%" and after[STD_EXCESS] == "-"


def test_open_equals_today_plus_wait_and_excess_is_separate():
    r = _std(300000.0, 350000.0, sizing=None)
    assert r[STD_OPEN] == "0원" and r[STD_EXCESS] == "50,000원" and r["_wait"] == 0.0
    for plan, done in ((300000.0, 0.0), (300000.0, 60000.0), (300000.0, 299000.0)):
        r = _std(plan, done, cash=50000.0)
        today = float(r[STD_TODAY].split("원")[0].replace(",", ""))
        assert r["_open"] == today + r["_wait"]


def test_zero_versus_unknown():
    blocked = _std(300000.0, 0.0, allowed=False, gate_text="방어우선: 상위 시간대 추세훼손")
    assert blocked[STD_TODAY] == "0원 · 차단: 방어우선: 상위 시간대 추세훼손" and blocked[STD_WAIT] == "300,000원"
    gate_unknown = _std(300000.0, 0.0, allowed=None)
    assert gate_unknown[STD_TODAY] == "미확인 · 게이트 미확인" and gate_unknown[STD_WAIT] == "미확인"
    no_cash = _std(300000.0, 0.0, cash=None)
    assert no_cash[STD_TODAY] == "미확인 · 가용 현금 미확인"
    unread = _std(300000.0, None, status="error")
    assert unread[STD_EXECUTED].startswith("미확인") and unread[STD_APP_RATE] == "미확인" and unread[STD_OPEN] == "미확인"


def test_plan_zero_rates_are_no_target():
    r = _std(0.0, 0.0)
    assert r[STD_APP_RATE] == "대상 없음" and r[STD_TODAY].startswith("0원 · 이번 달 계획 0원")
    assert execution_rate(10.0, 0.0) == "대상 없음" and execution_rate(None, 100.0) == "미확인"
