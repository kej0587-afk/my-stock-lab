"""C-5 v2 (2026-11-25): display-only tech review. Clusters, strict overhead supply, type-aware overheat, leveraged
products under their own policy. It never writes back into the decision."""
import copy
import json

import pandas as pd

from stock_lab_core.tech_review import (
    CAUTION, CONFIRM, DATA_CHECK, LEVERAGE_POLICY, NEUTRAL, TECH_REVIEW_POLICY_VERSION, build_tech_review_v2,
    strict_overhead_supply, tech_review_v2_record,
)
from stock_lab_core.tech_review_view import tech_review_rows


def base(**kw):
    d = {"dec": "🔍관망: 타점 대기", "decision_code": "WATCH_WAIT_ENTRY", "decision_group": "wait",
         "cur_p": 110.0, "pct_b": 0.6, "rsi": 55.0, "ma20": 105.0, "ma50": 100.0, "vol_ratio": 1.0,
         "day_ret": 0.01, "history_days": 300, "data_state": "OK", "ext_structure": "Bullish",
         "pd_zone": "Neutral", "fvg_active": False, "fvg_type": "", "mtf_bias_label": "중립 확인"}
    d.update(kw)
    return d


def liq(rows, status="상단 매물 근접"):
    return {"ok": True, "status": status, "rows": rows}


def test_trend_weakening_signals_count_as_one_burden_but_stay_listed():
    d = base(cur_p=95.0, ma20=98.0, structure_risk=True, ext_structure="Bearish", mtf_bias_label="상위 시간대 경고")
    out = build_tech_review_v2(d)
    assert out["burden_clusters"] == ["추세약화"]
    trend = [c for c in out["clusters"] if c["묶음"] == "추세약화"][0]
    assert len(trend["개별 근거"].split(" / ")) == 4
    assert sum(1 for k, _, _ in out["reasons"] if k == "-") == 4
    assert out["verdict"] == CAUTION  # one burden, no support: same rule shape as v1


def test_overhead_supply_counts_only_zones_above_the_price():
    straddle = [{"low": 108.0, "high": 112.0, "mid": 110.5, "intensity": 1.0}]  # the old 'above' bin straddling 110
    assert strict_overhead_supply(liq(straddle), 110.0)[0] is False
    above = [{"low": 111.5, "high": 114.0, "mid": 112.7, "intensity": 0.6}]
    assert strict_overhead_supply(liq(above), 110.0)[0] is True
    weak = [{"low": 111.5, "high": 114.0, "mid": 112.7, "intensity": 0.1}]
    assert strict_overhead_supply(liq(weak), 110.0)[0] is False
    out = build_tech_review_v2(base(), liquidity_profile=liq(straddle))
    assert "매물" not in out["burden_clusters"]
    assert any(k == "·" and "기존 표시" in t for k, _, t in out["reasons"])


def test_overheat_is_reference_for_leader_and_exception_scout_only():
    hot = dict(pct_b=0.97, rsi=78.0, mtf_bias_label="정찰만 적합")
    for code in ("NEW_ENTRY_LEADER", "EXCEPTION_ENTRY"):
        out = build_tech_review_v2(base(decision_code=code, **hot))
        assert "과열" not in out["burden_clusters"] and out["type_note"]
    out = build_tech_review_v2(base(decision_code="S_PULLBACK_ENTRY", **hot))
    assert out["burden_clusters"] == ["과열"]


def test_formation_period_and_bearish_shape_are_reference_only():
    pat = {"name": "쌍봉", "direction": "bearish", "lifecycle": "관찰", "status": "관찰", "invalid_price": 130.0,
           "formation_id": ("double", "top", pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-08"))}
    out = build_tech_review_v2(base(), pattern_candidates=[pat])
    assert out["burden_clusters"] == [] and out["verdict"] == NEUTRAL
    assert any(k == "·" and "7일" in t for k, _, t in out["reasons"])
    broken = dict(pat, lifecycle="현재유효", status="이탈")
    assert "저항·하락패턴" in build_tech_review_v2(base(), pattern_candidates=[broken])["burden_clusters"]
    inv = build_tech_review_v2(base(), invalidated_patterns=[{"name": "쌍봉", "direction": "bearish"}])
    assert any("무효화" in t for _, _, t in inv["reasons"])


def test_only_essential_inputs_raise_data_check():
    assert build_tech_review_v2(base(rsi=float("nan")))["verdict"] == DATA_CHECK
    out = build_tech_review_v2(base(vol_ratio=float("nan"), mtf_bias_label=""), liquidity_profile={"ok": False, "reason": "자료 부족"})
    assert out["verdict"] != DATA_CHECK and out["unchecked"] >= 3


def test_supports_are_deduplicated_too():
    d = base(mtf_bias_label="상위 시간대 우호", is_52w_breakout=True, fvg_active=True, fvg_type="bullish")
    out = build_tech_review_v2(d, liquidity_profile=liq([], status="하단 유동성 지지 확인"))
    assert out["support_clusters"] == ["위치", "지지", "추세"] and out["verdict"] == CONFIRM


def test_leveraged_products_use_their_own_policy_and_decision_is_untouched():
    d = base(decision_code="LEVERAGED_DCA_CONDITIONAL", is_leveraged_or_inverse=True, buy_amt=300000.0,
             leveraged_l3={"status": "L3 대기", "cycle": {"active": True, "tranches_used": 1, "invested": 100.0,
                                                          "panic_latched": False}, "record": {"budget_krw": 300.0},
                           "last_bar": {"underlying_above_ma50": True, "leveraged_above_ma50": False, "recovery_passed": 4},
                           "bars_since_last_tranche": 12})
    wf = {"판정분류": "⏳눌림대기", "게이트상태": "대기/관찰", "시장실행상태": "정상"}
    before, wf_before = copy.deepcopy(d), copy.deepcopy(wf)
    model = tech_review_rows(d, wf, liquidity_profile=liq([{"low": 111.0, "high": 112.0, "mid": 111.5, "intensity": 1.0}]))
    assert d == before and wf == wf_before
    assert model["review"]["verdict"] == LEVERAGE_POLICY
    rows = {r["항목"]: r["값"] for r in model["leverage_rows"]}
    assert rows["기초지수 MA50"] == "위" and rows["레버리지 ETF MA50"] == "아래" and rows["회복체크"] == "4/6"
    assert rows["남은 회차"] == "2/3" and "12거래일 (미충족)" in rows["20거래일 cooldown"] and rows["남은 예산"] == "200원"
    assert rows["최종 실행가능 여부"] == "대기/관찰"
    assert model["reasons"]  # general reasons stay visible as reference


def test_record_is_versioned_and_json_ready():
    rec = tech_review_v2_record(build_tech_review_v2(base(cur_p=95.0)))
    assert rec["policy_version"] == TECH_REVIEW_POLICY_VERSION
    json.dumps(rec, ensure_ascii=False)
