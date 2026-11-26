"""C-6/C-11 step 1 (2026-11-26): shared decision record and shared monthly plan call keep results unchanged."""
import copy

import pandas as pd

from stock_lab_core import decision_record as dr
from stock_lab_core.monthly_rebalance import build_rebalance_plan, compute_monthly_plan, prepare_rebalance_holdings
from stock_lab_core.rebalance_multiplier import decision_signal_multiplier

ENGINE = {"decision_code": "CORE_PULLBACK_DCA", "dec": "🧱코어 눌림: 눌림 100% 적립", "core_dca_label": "눌림 100% 적립",
          "core_dca_rate": 1.0, "buy_amt": 500000.0, "grade": "A", "adj": 5.0, "current_w": 5.0, "target_w": 15.0,
          "macro_missing_components": ("VIX",)}
POST = dict(ENGINE, decision_code="MTF_DAMAGE_NO_ADD", dec="상위 시간대 추세훼손", mtf_bias_label="추세훼손")


def _record(**kw):
    base = dict(ticker="qqq", source=dr.SOURCE_PRECISION, engine=ENGINE, post=POST,
                workflow={"게이트상태": "방어우선", "게이트근거": "상위 시간대 추세훼손"}, account_scope="scope-a",
                has_pos=True, price_asof="2026-11-25", macro_status={"macro_data_status": "complete", "as_of": {"VIX": "2026-11-25"}})
    base.update(kw)
    return dr.build_decision_record(**base)


def test_record_keeps_engine_and_post_apart_without_mutating_inputs():
    engine, post = copy.deepcopy(ENGINE), copy.deepcopy(POST)
    rec = _record(engine=engine, post=post)
    assert engine == ENGINE and post == POST
    assert rec["engine"]["decision_code"] == "CORE_PULLBACK_DCA"
    assert rec["post"]["decision_code"] == "MTF_DAMAGE_NO_ADD"
    assert rec["gate"]["state"] == "방어우선"
    assert rec["ticker"] == "QQQ"
    assert rec["policy_versions"]["record"] == dr.RECORD_VERSION


def test_manual_price_is_a_separate_source_and_never_replaces_the_normal_record():
    state = {}
    normal = _record()
    manual = _record(manual_price=True)
    assert manual["source"] == dr.SOURCE_PRECISION_MANUAL
    dr.store_record(state, normal)
    dr.store_record(state, manual)
    assert dr.read_record(state, "QQQ", dr.SOURCE_PRECISION)["as_of"]["manual_price"] is False
    assert dr.read_record(state, "QQQ", dr.SOURCE_PRECISION_MANUAL)["as_of"]["manual_price"] is True


def test_cache_key_reflects_scope_holding_price_macro_and_version():
    base = _record()["cache_key"]
    assert _record(account_scope="scope-b")["cache_key"] != base
    assert _record(has_pos=False)["cache_key"] != base
    assert _record(price_asof="2026-11-24")["cache_key"] != base
    assert _record(macro_status={"macro_data_status": "complete", "as_of": {"VIX": "2026-11-24"}})["cache_key"] != base
    assert _record(extra_versions={"gate": "x"})["cache_key"] != base
    assert _record()["cache_key"] == base


def test_out_of_scope_record_is_not_returned():
    state = {}
    dr.store_record(state, _record())
    assert dr.read_record(state, "QQQ", dr.SOURCE_PRECISION, account_scope="scope-a") is not None
    assert dr.read_record(state, "QQQ", dr.SOURCE_PRECISION, account_scope="scope-b") is None


def test_monthly_multiplier_reads_the_raw_engine_code_only():
    for bucket in ("core", "swing", "leverage"):
        assert dr.engine_monthly_multiplier(ENGINE, bucket) == decision_signal_multiplier(ENGINE, bucket)
    # The post-processing code is never the source of the monthly multiplier.
    rec = _record()
    assert dr.engine_monthly_multiplier(rec["engine"], "core") == 1.0


def _holdings():
    return pd.DataFrame([
        {"티커": "QQQ", "자산명": "QQQ", "목표비중": 40, "bucket": "core", "asset_class": "us_etf_nasdaq", "현재가": 500.0,
         "매입가": 450.0, "보유량": 3, "is_etf": True, "운용대상": True},
        {"티커": "TQQQ", "자산명": "TQQQ", "목표비중": 10, "bucket": "leverage", "asset_class": "us_etf_nasdaq",
         "현재가": 60.0, "매입가": 80.0, "보유량": 5, "is_etf": True, "운용대상": True},
        {"티커": "005930.KS", "자산명": "삼성전자", "목표비중": 30, "bucket": "core", "asset_class": "kr_stock",
         "현재가": 70000.0, "매입가": 65000.0, "보유량": 10, "is_etf": False, "운용대상": True},
        {"티커": "NVDA", "자산명": "NVDA", "목표비중": 20, "bucket": "swing", "asset_class": "us_stock",
         "현재가": 150.0, "매입가": 120.0, "보유량": 2, "is_etf": False, "운용대상": True},
    ])


def _multiplier(tap, bucket, dip_level=0, decision=None):
    if isinstance(decision, dict) and str(decision.get("dec", "")).strip() == str(tap).strip():
        return decision_signal_multiplier(decision, bucket, dip_level=dip_level)
    from stock_lab_core.rebalance_multiplier import legacy_label_multiplier
    return legacy_label_multiplier(tap, bucket, dip_level=dip_level)


def test_shared_monthly_plan_equals_the_calculator_rows():
    holdings = _holdings()
    signals = {"QQQ": ENGINE["dec"], "TQQQ": "⚡레버리지 조건부 DCA", "005930.KS": "-", "NVDA": "🟢눌림 매수"}
    decisions = {"QQQ": ENGINE}
    for redistribute in (True, False):
        for always in (set(), {"005930.KS"}):
            eligible = prepare_rebalance_holdings(holdings)
            expected = build_rebalance_plan(eligible, float(eligible["목표비중"].sum()), 1_000_000, 1400.0, signals,
                                            always, redistribute, {"NVDA": 30000.0}, _multiplier, signal_decisions=decisions)
            plan = compute_monthly_plan(holdings, total_invest=1_000_000, usdkrw=1400.0, signal_cache=signals,
                                        signal_decisions=decisions, always_invest_set=always,
                                        redistribute_mode=redistribute, accumulated={"NVDA": 30000.0},
                                        signal_multiplier=_multiplier, month="2026-11")
            assert plan["status"] == "ok"
            assert plan["rows"] == expected
            assert plan["alloc"] == {r["ticker"].upper(): float(r["final_alloc"]) for r in expected}


def test_shared_monthly_plan_reports_empty_inputs():
    assert compute_monthly_plan(pd.DataFrame(), total_invest=1, usdkrw=1400.0, signal_cache={}, signal_decisions={},
                                always_invest_set=set(), redistribute_mode=True, accumulated={},
                                signal_multiplier=_multiplier, month="2026-11")["status"] == "no_input"
    zero = _holdings().assign(목표비중=0)
    assert compute_monthly_plan(zero, total_invest=1, usdkrw=1400.0, signal_cache={}, signal_decisions={},
                                always_invest_set=set(), redistribute_mode=True, accumulated={},
                                signal_multiplier=_multiplier, month="2026-11")["status"] == "no_eligible"
