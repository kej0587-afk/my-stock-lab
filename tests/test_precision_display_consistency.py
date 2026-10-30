"""Offline display contracts for the supplied holdings, not live valuations."""

from copy import deepcopy
import io
import json
import zipfile

import pandas as pd
import pytest

from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, GATE_WATCH_ONLY,
)
from stock_lab_core.precision_chart_view import chart_basis_rows
from stock_lab_core.precision_narrative import align_precision_narrative_display
from stock_lab_core.precision_review_export import build_precision_review_export_zip
from stock_lab_core.signal_basis import build_signal_basis
from tests.test_precision_plan_panel import display_app, held_decision


HELD_TICKERS = (
    "379810.KS", "379800.KS", "418660.KS", "0167A0.KS", "CIBR",
    "SOXL", "RAM", "BITX", "MAGS", "0025N0.KS",
)


@pytest.mark.parametrize("workflow", [None, {}, {"유형": "ETF"}, {"게이트상태": GATE_EXECUTABLE}])
def test_legacy_and_executable_narratives_remain_exactly_unchanged(workflow):
    lines = ["conclusion", "technical signal", "entry", "target 120 / stop 90 / RR 2.00"]
    before = list(lines)
    aligned, color = align_precision_narrative_display(
        lines, "#10b981", workflow, entry_hint="entry", decision_code="CORE_ETF_DCA_BUY",
    )
    assert aligned == before and color == "#10b981"
    assert aligned is not lines and lines == before


@pytest.mark.parametrize("code,entry_only", [
    ("QUALITY_PULLBACK_ENTRY", True), ("TREND_PULLBACK_EXPLORE", True), ("CORE_ETF_DCA_BUY", True),
    ("PROFIT_TAKE_SIGNAL", False), ("HOLD_QUALITY_UPTREND", False), ("REVERSE_TREND_NO_ENTRY", False),
])
def test_gate_alignment_changes_entry_permission_not_holding_exit_or_numbers(code, entry_only):
    lines = ["conclusion", "<b>📋 현재 판정</b>: original", "original hint", "target 120 / stop 90 / RR 2.00"]
    before = list(lines)
    workflow = {"게이트상태": GATE_DEFENSE, "게이트근거": "시장 <방어> & 비중"}
    aligned, color = align_precision_narrative_display(
        lines, "#10b981", workflow, entry_hint="original hint", decision_code=code,
    )
    assert "시장 &lt;방어&gt; &amp; 비중" in aligned[0] and "<방어>" not in aligned[0]
    assert aligned[1] == "<b>기술적 원신호</b>: original"
    assert (aligned[2] != before[2]) is entry_only
    assert aligned[3] == before[3] and color == "#ef4444"
    assert align_precision_narrative_display(
        aligned, color, workflow, entry_hint="original hint", decision_code=code,
    ) == (aligned, color)
    assert lines == before


def test_partial_gate_has_an_explicit_unknown_label_without_inventing_a_reason():
    lines, color = align_precision_narrative_display(["old conclusion"], "#10b981", {"게이트상태": ""})
    assert "실행 보류" in lines[0] and "미확인" in lines[0] and "실행 게이트 재확인 필요" in lines[0]
    assert color == "#d97706"


@pytest.mark.parametrize("ticker", HELD_TICKERS)
@pytest.mark.parametrize("gate", [GATE_DEFENSE, GATE_DATA_CHECK, GATE_WAIT, GATE_WATCH_ONLY, ""])
def test_held_narrative_follows_the_same_gate_as_plan_and_final_check(display_app, ticker, gate):
    app, ui = display_app
    decision = held_decision(
        dec="우량주 눌림 매수", decision_code="QUALITY_PULLBACK_ENTRY",
        current_w=1.0, target_w=5.0, buy_amt=140000,
        execution_workflow={"유형": "ETF", "게이트상태": gate, "게이트근거": "현재 실행 조건 확인"},
    )
    original = deepcopy(decision)
    checks_before, final_before = app.build_pre_buy_final_checks("Fixture", ticker, True, decision, 0, True, 95)
    plan = app.render_entry_execution_plan("Fixture", ticker, decision, has_pos=True)
    narrative = app.build_precision_narrative("Fixture", ticker, decision, 0, True, 95)
    conclusion = narrative.split("<b>오늘 결론</b>:", 1)[1].split("<br>", 1)[0]
    assert "실행 보류" in conclusion and "현재 실행 조건 확인" in conclusion
    assert "회복 후보로 볼 수 있지만" not in conclusion
    assert "<b>현재 진입 구간</b>" not in narrative
    assert "<b>기술적 원신호</b>" in narrative and decision["dec"] in narrative
    assert "<span class='highlight'>실행 보류</span>" in ui.markdowns[-1]
    assert plan["display_status"] == "실행 보류"
    assert final_before["final_label"] in {"대기", "매수 금지"}
    assert (plan["current_price"], plan["stop"], plan["target"], plan["rr_now"]) == (100, 90, 120, "2.00")
    assert (app.build_pre_buy_final_checks("Fixture", ticker, True, decision, 0, True, 95)
            == (checks_before, final_before))
    assert decision == original


@pytest.mark.parametrize("ticker", HELD_TICKERS)
def test_held_source_overlay_and_export_keep_separate_dates_without_fetching(ticker):
    source = pd.DataFrame({"Close": [100.0], "Volume": [1000]},
                          index=pd.to_datetime(["2026-10-29"]))
    chart = pd.DataFrame({"Close": [100.0, 101.0], "Volume": [1000.0, float("nan")]},
                         index=pd.to_datetime(["2026-10-29", "2026-10-30"]))
    chart.attrs["live_quote"] = {"ticker": ticker, "mfi_asof": "2026-10-29", "volume_status": "missing_live_volume"}
    before_source, before_chart = source.copy(deep=True), chart.copy(deep=True)
    basis = build_signal_basis(source, (chart, True, ""), calculated_at="2026-10-30 15:00:00 KST")
    rows = chart_basis_rows(source, chart, {}, live_applied=True)
    data = build_precision_review_export_zip(
        selected_ticker=ticker, result_ticker=ticker,
        ohlcv={"daily_source": source, "display_chart": chart}, context={"signal_basis": basis},
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        snapshot = json.loads(archive.read("snapshot.json"))
    assert basis["가격자료기준일"] == rows[0]["원자료 마지막 날짜"] == "2026-10-29"
    assert basis["지표마지막봉"] == rows[0]["차트 마지막 봉"] == "2026-10-30"
    assert "미확정" in basis["가격반영"] and "확정봉 아님" in rows[0]["가격 반영"]
    assert "2026-10-29" in basis["수급자료기준"]
    assert snapshot["sections"]["context"]["signal_basis"] == basis
    assert snapshot["manifest"]["asof"].startswith("2026-10-29")
    pd.testing.assert_frame_equal(source, before_source)
    pd.testing.assert_frame_equal(chart, before_chart)
    assert chart.attrs == before_chart.attrs
