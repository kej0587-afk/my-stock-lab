"""Observation prose uses captured facts, not new thresholds or provider calls."""

from copy import deepcopy
from html.parser import HTMLParser
import math

import pandas as pd
import pytest

from stock_lab_core.precision_narrative import build_precision_narrative
from stock_lab_core.precision_observation import build_precision_observation_rows, render_precision_observation
from stock_lab_core.precision_chart_view import prepare_channel_display
from tests.test_channel_display_lifecycle import fixture as channel_fixture
from tests.test_precision_narrative import app_functions


def evidence():
    dates = pd.bdate_range("2026-10-01", "2026-10-21")
    frame = pd.DataFrame({"Close": 100.0}, index=dates)
    decision = {
        "dec": "눌림 후보", "cur_p": 100, "vol_ratio": 1.25, "vol_valid_count": 20, "mfi": 55,
        "execution_workflow": {"게이트상태": "실행가능", "게이트근거": "선별 통과"},
        "chart_final_check": {"execution_allowed": False, "block_count": 0,
                              "core_missing_ids": ["overheat"], "action": "과열 자료 확인"},
        "chart_structure": {"일봉": {
            "patterns": [{"name": "쌍봉", "lifecycle": "현재유효", "age": 5, "known_at": dates[-2]}],
            "events": [{"name": "쌍봉", "formation_start": dates[0], "formation_end": dates[-4],
                        "known_at": dates[-2], "time": dates[-1]}],
            "channel": {"state": "채널 내부", "lower": [90, 95], "upper": [110, 115]},
        }},
    }
    context = {
        "multi_timeframe": {
            "월봉": {"source_asof": "2026-10-20", "snapshot": {"state": "상승 유지"}},
            "주봉": {"source_asof": "2026-10-20", "snapshot": {"state": "혼조 확인"}},
            "일봉": {"df": frame, "snapshot": {"state": "상승추세 내 조정", "ma20_gap": -2, "pct_b": .3}},
        },
        "signal_basis": {"가격자료기준일": "2026-10-20", "가격반영": "조회 현재가 보정 · 미확정", "수급자료기준": "가격·거래량 원자료"},
        "liquidity_profile": {"ok": True, "poc": {"low": 98, "high": 102}},
    }
    return decision, context


def test_four_axes_keep_exact_values_dates_units_and_original_inputs():
    decision, context = evidence()
    before_decision, before_context = deepcopy(decision), deepcopy(context)
    rows = build_precision_observation_rows(decision, "TEST", context)
    assert [row["축"] for row in rows] == ["구조", "가격 위치", "기간", "유동성 대용치"]
    assert rows[0]["관측"].startswith("월봉 상승 유지 / 주봉 혼조 확인 / 일봉 상승추세 내 조정")
    assert "일봉 쌍봉 · 현재유효" in rows[0]["관측"]
    assert "MA20 이격 -2.0%" in rows[1]["관측"] and "%B 0.30" in rows[1]["관측"]
    assert "하단 $95.00 / 상단 $115.00" in rows[1]["관측"]
    assert "12개 관측봉" in rows[2]["관측"]
    assert "피벗 확인 2026-10-20 · 확인봉 2026-10-21" == rows[2]["기준·제한"]
    assert "1.25x (20개 유효봉)" in rows[3]["관측"]
    assert "MFI 55.0" in rows[3]["관측"] and "$98.00~$102.00" in rows[3]["관측"]
    assert "실제 순유입·호가 잔량 아님" in rows[3]["기준·제한"]
    html = render_precision_observation(decision, "TEST", context)
    assert "데이터확인" in html and "과열 자료 확인" in html and "선별 통과" not in html
    assert "기술적 원신호" in html and "눌림 후보" in html
    assert all(word not in html for word in ("에너지", "성공확률", "손절", "정찰", "추매"))
    assert decision == before_decision
    pd.testing.assert_frame_equal(context["multi_timeframe"]["일봉"]["df"], before_context["multi_timeframe"]["일봉"]["df"])
    for label in ("월봉", "주봉"):
        assert context["multi_timeframe"][label] == before_context["multi_timeframe"][label]
    assert context["signal_basis"] == before_context["signal_basis"]
    assert context["liquidity_profile"] == before_context["liquidity_profile"]


@pytest.mark.parametrize("missing", [None, math.nan, math.inf, -math.inf, "", "bad", True])
def test_missing_values_never_become_zero_or_optimistic_evidence(missing):
    decision, context = evidence()
    decision.update(cur_p=missing, mfi=missing, vol_ratio=missing, vol_valid_count=missing)
    decision["chart_structure"] = {}
    context["multi_timeframe"] = {"일봉": {"snapshot": {"ma20_gap": missing, "pct_b": missing}}}
    context["liquidity_profile"] = {"ok": True, "poc": {"low": missing, "high": missing}}
    rows = build_precision_observation_rows(decision, "TEST", context)
    assert rows[0]["관측"] == "월봉 미확인 / 주봉 미확인 / 일봉 미확인"
    assert "판정가 미확인" in rows[1]["관측"] and "%B 미확인" in rows[1]["관측"]
    assert "기간 미확인" in rows[2]["관측"]
    assert "기준비 미확인" in rows[3]["관측"] and "MFI 미확인" in rows[3]["관측"]
    assert "추정 매물대 미확인" in rows[3]["관측"]
    assert all(word not in str(rows) for word in ("nan", "inf", "$0.00", "0.00x"))


@pytest.mark.parametrize("context", [None, {}, {"multi_timeframe": None, "liquidity_profile": None, "signal_basis": None}])
def test_empty_context_still_has_four_unknown_axes(context):
    rows = build_precision_observation_rows({}, "TEST", context)
    assert len(rows) == 4 and all("미확인" in row["관측"] for row in rows)
    assert "실행가능" not in render_precision_observation({}, "TEST", context)


@pytest.mark.parametrize("provisional", [False, True])
def test_retired_or_unconfirmed_channel_never_supplies_current_rails(provisional):
    decision, context = evidence()
    frame, channel = channel_fixture()
    frame.iloc[-1, 0] = channel["lower"][-1] - 1
    displayed = prepare_channel_display(frame, channel, provisional_last=provisional)
    before = deepcopy(displayed)
    decision["chart_structure"]["일봉"]["channel"] = displayed
    row = build_precision_observation_rows(decision, "TEST", context)[1]
    assert "현재 가격 비교 제외" in row["관측"]
    assert "미확정 봉" in row["관측"] if provisional else "과거 채널" in row["관측"]
    assert "하단 $" not in row["관측"] and "상단 $" not in row["관측"]
    assert displayed == before


def test_no_future_bucket_as_source_or_missing_volume_as_current_flow():
    decision, context = evidence()
    context["multi_timeframe"]["월봉"].update(source_asof=None, df=pd.DataFrame(index=pd.to_datetime(["2026-10-31"])))
    context["multi_timeframe"]["주봉"].update(source_kind="daily_fallback", source_asof="")
    decision["chart_structure"]["월봉"] = {"provisional_last": True}
    decision["live_quote"] = {"volume_status": "missing_live_volume", "mfi_asof": "2026-10-19T12:00:00"}
    rows = build_precision_observation_rows(decision, "TEST", context)
    assert "월봉 미확인" in rows[0]["기준·제한"] and "주봉 2026-10-20" in rows[0]["기준·제한"]
    assert "미확정 봉 포함" in rows[0]["관측"] and "2026-10-31" not in str(rows)
    assert "최신 거래량 미확인 · MFI 기준 2026-10-19" in rows[3]["기준·제한"]


def test_candidate_age_is_bars_since_formation_not_days_or_confirmation_age():
    decision, context = evidence()
    decision["chart_structure"]["일봉"]["events"] = []
    row = build_precision_observation_rows(decision, "TEST", context)[2]
    assert "형성 말단 이후 5봉" in row["관측"] and "5일" not in row["관측"]
    assert "확인봉 자료 없음" in row["기준·제한"]


def test_missing_or_out_of_window_formation_dates_do_not_invent_bar_count():
    decision, context = evidence()
    event = decision["chart_structure"]["일봉"]["events"][0]
    event.update(formation_start="2025-01-01", formation_end=None, known_at=None, provisional=True)
    row = build_precision_observation_rows(decision, "TEST", context)[2]
    assert "관측봉 수 미확인" in row["관측"] and "미확정 관측" in row["기준·제한"]
    assert "피벗 확인 미확인" in row["기준·제한"]


def test_html_escapes_evidence_and_uses_a_bounded_wrapping_table():
    decision, context = evidence()
    decision["dec"] = "<script>alert(1)</script>"
    context["multi_timeframe"]["월봉"]["snapshot"]["state"] = "<b>untrusted</b>"
    html = render_precision_observation(decision, "TEST", context)
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;untrusted" in html
    assert html.count("<tr>") == 4 and "table-layout:fixed" in html and "overflow-wrap:anywhere" in html
    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = 0
        def handle_starttag(self, tag, attrs):
            self.tables += tag == "table"
    tags = Tags()
    tags.feed(html)
    assert tags.tables == 1


def test_opt_in_narrative_and_app_wrapper_never_call_old_scoring_callbacks():
    decision, context = evidence()
    def forbidden(*args, **kwargs):
        pytest.fail("Observation-only narrative must not recompute indicators or scores")
    expected = build_precision_narrative("Test", "TEST", decision, 4, False, 0,
                                         observation_context=context, describe_fvg_plain=forbidden,
                                         build_sideways_quality_state=forbidden)
    namespace = app_functions()
    namespace.update(describe_fvg_plain=forbidden, build_sideways_quality_state=forbidden)
    assert namespace["build_precision_narrative"]("Test", "TEST", decision, 4, False, 0,
                                                  observation_context=context) == expected
