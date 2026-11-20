"""Read-only synthesis of captured structure, price, duration and liquidity."""

from contextlib import nullcontext
from copy import deepcopy
import html
import math
import socket
import urllib.request

import numpy as np
import pandas as pd
import pytest
import requests

from stock_lab_core.precision_scenarios import build_precision_scenarios, render_precision_scenarios
from stock_lab_core.precision_observation import build_precision_observation_rows
from tests.test_precision_observation import evidence


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    from stock_lab_core import prices
    def forbidden(*args, **kwargs):
        pytest.fail("Read-only scenarios attempted data collection")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    for name in ("load_price_df", "load_price_frames_batch", "load_latest_price"):
        monkeypatch.setattr(prices, name, forbidden)


@pytest.fixture
def case():
    decision, context = evidence()
    dates = context["multi_timeframe"]["일봉"]["df"].index
    context["multi_timeframe"]["주봉"]["snapshot"]["state"] = "상승 유지"
    context["signal_basis"].update(가격자료기준일=str(dates[-1].date()), 가격반영="완료 일봉")
    decision.update(rr_stop=90.0, rr_target=120.0, rr_target_is_projection=False, score=7.125)
    chart = decision["chart_structure"]["일봉"]
    chart.update(provisional_last=False, expected_close=dates[-1], decision_asof=dates[-1])
    chart["channel"].update(x=[dates[0], dates[-1]], known_at=dates[-2], execution_guide_eligible=True)
    chart["events"][0]["provisional"] = False
    for tf in ("월봉", "주봉"):
        decision["chart_structure"][tf] = {"provisional_last": False}
    plan = {"ticker": "TEST", "status": "original", "current_price": 100,
            "stop": 90.0, "target": 120.0, "stop_source": "원래 손절", "target_source": "원래 목표",
            "rows": [{"단계": "1차 진입 (30%)", "가격": "$97.50123", "조건": "기존 확인봉", "금액/수량": "$30 / 0.3주"}]}
    return decision, context, plan


def assert_unchanged(actual, expected):
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_unchanged(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, b in zip(actual, expected):
            assert_unchanged(a, b)
    elif expected is None or expected is pd.NA or expected is pd.NaT:
        assert actual is expected
    elif isinstance(expected, (float, np.floating)) and math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert type(actual) is type(expected) and actual == expected


def build(case, **kwargs):
    before = deepcopy(case)
    decision, context, plan = case
    try:
        return build_precision_scenarios(decision, "TEST", context, plan, **kwargs)
    finally:
        for actual, expected in zip(case, before):
            assert_unchanged(actual, expected)


def test_four_axes_use_captured_values_and_same_timestamp_rails_without_mutation(case):
    decision, context, _ = case
    original_axes = build_precision_observation_rows(decision, "TEST", context)
    model = build(case)
    assert model["focus"].startswith("A안")
    assert model["duration_known"] and model["flow_known"]
    assert [r["축"] for r in model["axes"]] == ["구조", "가격 위치", "기간", "유동성 대용치"]
    assert model["location"]["support"] == "$95.00"
    assert model["location"]["resistance"] == "$115.00"
    assert "25.0%" in model["location"]["location"]
    assert model["axes"][2]["관측"] == original_axes[2]["관측"]
    assert model["axes"][2]["기준·제한"] == original_axes[2]["기준·제한"]
    assert "12개 관측봉" in model["axes"][2]["관측"]
    assert "1.25x (20개 유효봉)" in model["axes"][3]["관측"]
    assert "$97.50123" in model["plan"]["entry"]
    assert "확정할 수 없습니다" in model["axes"][2]["해석"]
    assert "반등 확률이 아닙니다" in model["axes"][1]["해석"]
    assert "손절 주문량" in model["axes"][3]["해석"] and "미확인" in model["axes"][3]["해석"]
    assert all(row["evidence"] for row in model["scenarios"])


@pytest.mark.parametrize("fault", ["retired", "ineligible", "stale_x", "future_x", "future_known", "none_known", "nat_known", "equal_range", "reversed_range", "missing_expected", "stale_expected", "missing_decision", "stale_decision"])
def test_invalid_or_unaligned_channels_never_supply_current_rails_or_a_focus(case, fault):
    chart = case[0]["chart_structure"]["일봉"]
    rail = chart["channel"]
    at = case[1]["multi_timeframe"]["일봉"]["df"].index[-1]
    if fault == "retired": rail["ended_at"] = at
    elif fault == "ineligible": rail["execution_guide_eligible"] = False
    elif fault == "stale_x": rail["x"][-1] = at - pd.Timedelta(days=1)
    elif fault == "future_x": rail["x"][-1] = at + pd.Timedelta(days=1)
    elif fault == "future_known": rail["known_at"] = at + pd.Timedelta(days=1)
    elif fault == "none_known": rail["known_at"] = None
    elif fault == "nat_known": rail["known_at"] = pd.NaT
    elif fault == "equal_range": rail["lower"][-1] = rail["upper"][-1]
    elif fault == "reversed_range": rail["lower"][-1] = 116
    else:
        key = "expected_close" if "expected" in fault else "decision_asof"
        chart[key] = None if fault.startswith("missing") else at - pd.Timedelta(days=1)
    model = build(case)
    assert model["focus"].startswith("C안")
    assert not model["location"]["available"]
    assert model["location"]["support"] == model["location"]["resistance"] == "미확인"
    assert "$95.00" not in str(model["axes"][1])
    assert "$95.00" not in model["scenarios"][0]["condition"]


@pytest.mark.parametrize("value", [None, True, np.bool_(True), math.nan, math.inf, -math.inf, "bad", 0])
def test_invalid_rail_numbers_never_become_optimistic_evidence(case, value):
    case[0]["chart_structure"]["일봉"]["channel"]["lower"][-1] = value
    model = build(case)
    assert model["focus"].startswith("C안") and not model["location"]["available"]
    assert model["location"]["support"] == "미확인"


@pytest.mark.parametrize("provisional", [True, None])
def test_provisional_daily_bar_never_opens_a_focus(case, provisional):
    case[0]["chart_structure"]["일봉"]["provisional_last"] = provisional
    assert build(case)["focus"].startswith("C안")


@pytest.mark.parametrize("damage", [False, True])
@pytest.mark.parametrize("missing", ["period", "period_confirmation", "current_volume"])
def test_missing_period_or_current_volume_is_c_unless_existing_damage_is_b(case, damage, missing):
    decision, context, _ = case
    chart = decision["chart_structure"]["일봉"]
    if missing == "period": chart["events"] = []
    elif missing == "period_confirmation": chart["events"][0].pop("provisional")
    else: decision["live_quote"] = {"volume_status": "missing_live_volume"}
    if damage: context["multi_timeframe"]["주봉"]["snapshot"]["state"] = "추세훼손"
    model = build(case)
    assert model["focus"].startswith("B안" if damage else "C안")
    assert "근거가 부족" in model["thesis"]


@pytest.mark.parametrize("field", ["vol_ratio", "vol_valid_count", "mfi"])
@pytest.mark.parametrize("value", [None, True, np.bool_(False), math.nan, math.inf, -math.inf, "bad"])
def test_missing_or_invalid_liquidity_never_claims_four_axis_alignment(case, field, value):
    case[0][field] = value
    model = build(case)
    assert not model["flow_known"] and model["focus"].startswith("C안")


@pytest.mark.parametrize("mfi", [0, 100])
def test_usable_observations_do_not_add_trading_thresholds(case, mfi):
    case[0].update(mfi=mfi, vol_ratio=.01, vol_valid_count=1)
    assert build(case)["focus"].startswith("A안")


@pytest.mark.parametrize("gate,veto,allowed", [("방어우선", False, False), ("실행가능", True, False), ("실행가능", False, True)])
def test_a_observation_does_not_override_market_gate_or_final_veto(case, gate, veto, allowed):
    decision = case[0]
    decision["execution_workflow"] = {"게이트상태": gate, "게이트근거": "기존 시장 제한"}
    decision["chart_final_check"] = {"execution_allowed": not veto, "block_count": int(veto),
                                     "core_missing_ids": [], "action": "최종 체크 차단" if veto else "기존 통과"}
    model = build(case)
    assert model["focus"].startswith("A안")
    assert model["ready"]["execution_allowed"] is allowed
    assert model["scenarios"][0]["new_money"] == model["execution"]
    if not allowed: assert "보류 유지" in model["execution"]


@pytest.mark.parametrize("field,value", [("ticker", "OTHER"), ("current_price", 101), ("stop", 89), ("target", 121), ("status", "unavailable")])
def test_mismatched_original_plan_withholds_all_plan_prices(case, field, value):
    case[2][field] = value
    model = build(case)
    assert not model["plan"]["valid"] and model["focus"].startswith("C안")
    assert model["plan"]["stop"] == model["plan"]["target"] == "미확인"
    assert "가격 제시 보류" in model["plan"]["entry"]
    assert "$97.50123" not in model["scenarios"][0]["prices"]


@pytest.mark.parametrize("value", [None, True, np.bool_(True), math.nan, math.inf, -math.inf])
def test_decision_plan_numbers_are_validated_not_coerced_to_zero(case, value):
    case[0]["cur_p"] = value
    assert not build(case)["plan"]["valid"]


@pytest.mark.parametrize("has_pos", [False, True])
def test_holding_and_new_money_actions_are_distinct(case, has_pos):
    model = build(case, has_pos=has_pos)
    assert model["has_pos"] is has_pos
    assert all(("미보유" in row["holding"]) is (not has_pos) for row in model["scenarios"])
    if has_pos: assert "자동 전량매도 명령 아님" in model["scenarios"][1]["holding"]
    assert "보류 유지" in model["execution"]


@pytest.mark.parametrize("fault", ["current", "historical", "future", "provisional", "future_known", "missing_expected", "stale_expected", "missing_decision", "stale_decision", "duplicate_index", "unordered_index"])
def test_sell_event_b_focus_requires_current_confirmed_session_even_when_channel_retired(case, fault):
    decision, context, _ = case
    chart = decision["chart_structure"]["일봉"]
    frame = context["multi_timeframe"]["일봉"]["df"]
    event = chart["events"][0]
    event.update(side="sell", confirmation="확인된 이탈")
    chart["channel"]["ended_at"] = frame.index[-1]
    if fault == "historical": event["time"] = frame.index[-2]
    elif fault == "future": event["time"] = frame.index[-1] + pd.Timedelta(days=1)
    elif fault == "provisional": event["provisional"] = True
    elif fault == "future_known": event["known_at"] = frame.index[-1] + pd.Timedelta(days=1)
    elif fault == "duplicate_index": frame.index = pd.DatetimeIndex([*frame.index[:-1], frame.index[-2]])
    elif fault == "unordered_index": context["multi_timeframe"]["일봉"]["df"] = frame.iloc[::-1].copy()
    elif fault != "current":
        key = "expected_close" if "expected" in fault else "decision_asof"
        chart[key] = None if fault.startswith("missing") else frame.index[-2]
    model = build(case)
    assert model["focus"].startswith("B안" if fault == "current" else "C안")
    if fault == "current": assert "확인된 이탈" in model["scenarios"][1]["evidence"]
    else: assert "이탈 신호 미확인" in model["scenarios"][1]["evidence"]


@pytest.mark.parametrize("projection", [False, True])
def test_projection_is_labelled_without_changing_original_target(case, projection):
    case[0]["rr_target_is_projection"] = projection
    model = build(case)
    assert "$120.00" in model["plan"]["target"]
    assert ("예상 확정값 아님" in model["plan"]["target"]) is projection


@pytest.mark.parametrize("tf", ["월봉", "주봉"])
@pytest.mark.parametrize("provisional", [True, None])
def test_higher_timeframe_unconfirmed_a_is_explicitly_provisional(case, tf, provisional):
    case[0]["chart_structure"][tf]["provisional_last"] = provisional
    model = build(case)
    assert model["focus"].startswith("A안") and "잠정" in model["focus"]
    assert "확정된 상태는 아닙니다" in model["thesis"]
    assert "잠정" in model["scenarios"][0]["evidence"]


class FakeUI:
    def __init__(self):
        self.markdowns, self.captions, self.tab_names = [], [], []
        self.expanders = []
    def subheader(self, value): pass
    def caption(self, value): self.captions.append(value)
    def markdown(self, value, **kwargs): self.markdowns.append((value, kwargs))
    def expander(self, *args, **kwargs):
        self.expanders.append(kwargs)
        return nullcontext()
    def tabs(self, names):
        self.tab_names = names
        return [nullcontext() for _ in names]


def test_renderer_escapes_evidence_plan_and_gate_html_without_mutating_model(case):
    payload = '<img src=x onerror="alert(1)"><script>bad()</script>&'
    case[0]["chart_final_check"]["action"] = payload
    case[0]["chart_structure"]["일봉"]["events"][0]["name"] = payload
    case[2]["rows"][0]["조건"] = payload
    case[2]["target_source"] = payload
    model = build(case)
    before = deepcopy(model)
    ui = FakeUI()
    render_precision_scenarios(ui, model)
    output = "\n".join(value for value, _ in ui.markdowns)
    assert len(ui.tab_names) == 3 and len(ui.markdowns) == 5
    assert payload not in output and "<script>" not in output and "<img " not in output
    assert html.escape(payload) in output
    assert "현재 근거·반대 근거" in output and "table-layout:fixed" in output
    assert any("승률 판정 아님" in value for value in ui.captions)
    assert_unchanged(model, before)


@pytest.mark.parametrize("focus", ["A안", "B안", "C안"])
def test_summary_scenario_opens_first_and_evidence_remains_accessible(case, focus):
    model = build(case)
    model["focus"] = focus + " · 현재 요약"
    before = deepcopy(model)
    ui = FakeUI()
    render_precision_scenarios(ui, model)
    assert ui.tab_names[0].startswith(focus)
    assert len(ui.tab_names) == 3
    assert ui.expanders == [{"expanded": False}]
    assert "구조" in ui.markdowns[1][0] and "유동성" in ui.markdowns[1][0]
    assert_unchanged(model, before)
