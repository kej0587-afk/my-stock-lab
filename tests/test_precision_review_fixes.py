"""Regressions for the three reviewed precision-plan defects."""

from copy import deepcopy

import pytest

from stock_lab_core.chart_execution import build_chart_execution_guide


@pytest.mark.parametrize("label,passed", [
    (None, False), ("", False), (float("nan"), False),
    ("⏳RS기울기부족", False), ("미확인", False),
    ("📉RS하락중", False), ("➡️RS횡보", True), ("📈RS상승중", True),
])
def test_missing_rs_is_not_recovery(app_module, monkeypatch, label, passed):
    monkeypatch.setattr(app_module, "get_leveraged_etf_precision_profile",
                        lambda *a: ("SOXL", {"leverage": 3}))
    monkeypatch.setattr(app_module, "build_leveraged_precision_watch_rows", lambda *a, **k: [])
    monkeypatch.setattr(app_module, "_classify_leveraged_dca_stage", lambda *a: ("", "", "", 0))
    state = app_module.build_leveraged_precision_state("Test", "SOXL", {"rs_slope_label": label}, False, 0)
    check = next(row for row in state["recovery_checks"] if row[0] == "RS 기울기")
    assert check[1] is passed
    if label not in ("📉RS하락중", "➡️RS횡보", "📈RS상승중"):
        assert "미확인" in check[2]


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("missing", ["underlying", "rr", "both"])
@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_missing_timing_evidence_cannot_pass(app_module, held, missing, value):
    context = dict(cur_p=100, ma20=95, ma50=90, rsi=55, mfi=50, pct_b=.5,
                   day_ret=0, target_w=5, current_w=1 if held else 0, rr_ratio=2)
    state = dict(profile_key="SOXL", recovery_passed=5, recovery_total=6,
                 recovery_state="회복 우세", underlying_1w_avg=2,
                 dca_stage="중하락 DCA 후보" if held else "미보유 관찰",
                 dca_multiple="×1.0" if held else "×0")
    if missing in ("underlying", "both"):
        state["underlying_1w_avg"] = value
    if missing in ("rr", "both"):
        context["rr_ratio"] = value
    before = deepcopy((context, state))
    result = app_module.build_leveraged_dca_timing_state(context, state)
    assert not result["allow_current"]
    assert not result["technical_entry_ready"] and not result["technical_entry_watch"]
    assert result["tranche_weights"] == [0, 0, 0]
    assert "자료 확인" in result["status"]
    assert "미확인" in result["condition_summary"]
    assert context.keys() == before[0].keys() and state.keys() == before[1].keys()


@pytest.mark.parametrize("rr,expected", [(0.79, False), (0.8, True), (1.49, True), (1.5, True), (2, True)])
def test_available_timing_keeps_existing_thresholds(app_module, rr, expected):
    context = dict(cur_p=100, ma20=95, ma50=90, rsi=55, mfi=50, pct_b=.5,
                   day_ret=0, target_w=5, current_w=1, rr_ratio=rr)
    state = dict(profile_key="SOXL", recovery_passed=5, recovery_total=6,
                 underlying_1w_avg=0, dca_stage="中", dca_multiple="×1.0")
    result = app_module.build_leveraged_dca_timing_state(context, state)
    assert result["allow_current"] is expected
    assert result["technical_entry_ready"] is (rr >= 1.5)


@pytest.mark.parametrize("current", [164.23, 183.62])
def test_broken_channel_is_recovery_level_not_pullback_support(current):
    guides = [{"kind": "support", "y1": 183.63, "direction": "상승",
               "source": "parallel_channel", "channel_state": "하단 이탈"}]
    before = deepcopy(guides)
    html = build_chart_execution_guide([], guides, {}, None, "NVDA", current)
    assert "이탈선 회복" in html and "$183.63" in html
    assert "채널 하단 $183.63 부근에서 하락 멈춤" not in html
    assert guides == before


@pytest.mark.parametrize("current", [183.63, 190])
def test_intact_channel_support_is_unchanged(current):
    guides = [{"kind": "support", "y1": 183.63, "direction": "상승",
               "source": "parallel_channel", "channel_state": "채널 내부"}]
    html = build_chart_execution_guide([], guides, {}, None, "NVDA", current)
    assert "채널 하단 $183.63 부근에서 하락 멈춤" in html
    assert "이탈선 회복" not in html
