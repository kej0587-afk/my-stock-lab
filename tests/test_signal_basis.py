import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.signal_basis import build_signal_basis, quote_display_label, source_date
from stock_lab_core.precision_plan_panel import entry_plan_display


def test_basis_does_not_confuse_processing_quote_and_source_dates():
    source = pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-28"]).tz_localize("America/New_York"))
    overlay = pd.DataFrame({"Close": [99]}, index=pd.to_datetime(["2026-10-29"]))
    overlay.attrs["live_quote"] = {"mfi_asof": "2026-10-28 00:00:00"}
    before = source.copy(deep=True)
    basis = build_signal_basis(source, (overlay, True, ""), calculated_at="2026-10-29 16:00:00 KST")
    assert basis["가격자료기준일"] == "2026-10-28"
    assert basis["지표마지막봉"] == "2026-10-29"
    assert "미확정" in basis["가격반영"]
    assert "2026-10-28" in basis["수급자료기준"]
    pd.testing.assert_frame_equal(source, before)


def test_failed_rebuild_keeps_original_date_and_warning():
    source = pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-28"]))
    basis = build_signal_basis(source, (source, False, "재계산 실패"))
    assert basis["가격반영"] == "가격 이력 기준"
    assert basis["가격자료기준일"] == basis["지표마지막봉"] == "2026-10-28"
    assert basis["자료주의"] == "재계산 실패"
    assert source_date(pd.DataFrame({"Close": [100]})) == "미확인"
    assert source_date(None) == "미확인"


@pytest.mark.parametrize("applied", [True, False])
def test_quote_session_is_not_inferred_from_price_gap(applied):
    label = quote_display_label(auto_price=100, live_applied=applied)
    assert label == "조회 현재가 · 세션 미확인"
    assert "차트 미반영" in quote_display_label(manual_price=100, live_applied=False)
    assert quote_display_label() == "가격 이력 기준"


def test_precision_shares_one_indicator_context_with_chart_and_decision():
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    context_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "calc_scores_and_decision"
                     and any(k.arg == "_live_indicator_context" and isinstance(k.value, ast.Name)
                             and k.value.id == "precision_live_context" for k in n.keywords)]
    assert len(context_calls) == 1
    unpack = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Name) and n.value.id == "precision_live_context"]
    assert any(isinstance(n.targets[0], ast.Tuple) and
               [x.id for x in n.targets[0].elts] == ["chart_df", "_precision_live_ohlcv_applied", "_precision_live_issue"]
               for n in unpack)


@pytest.mark.parametrize("gate", ["방어우선", "대기/관찰", "데이터확인", "", None])
def test_export_plan_headline_matches_restricted_panel_without_changing_raw_plan(gate):
    plan = {"status": "추가 정찰만", "status_note": "원래 조건", "current_price": 100}
    display = entry_plan_display(plan, {"게이트상태": gate, "게이트근거": "시장방어"})
    assert display["display_status"] == "실행 보류"
    assert display["display_note"] == "시장방어"
    assert plan == {"status": "추가 정찰만", "status_note": "원래 조건", "current_price": 100}


def test_executable_plan_keeps_its_original_headline():
    result = entry_plan_display({"status": "분할 진입 가능", "status_note": "원래 조건"}, {"게이트상태": "실행가능"})
    assert result["display_status"] == "분할 진입 가능"
    assert result["display_note"] == "원래 조건"


def test_review_flags_compare_displayed_plan_not_conditional_raw_grade():
    from stock_lab_core.precision_review_export import _conflict_flags

    sections = {
        "main_decision": {}, "execution_workflow": {"게이트상태": "방어우선"},
        "final_check": {"summary": {"final_label": "대기"}},
        "entry_plan": {"status": "추가 정찰만", "display_status": "실행 보류"},
        "hold_or_cut": {},
    }
    assert "entry_plan_vs_final_check" not in {x["code"] for x in _conflict_flags(sections)}
    del sections["entry_plan"]["display_status"]
    assert "entry_plan_vs_final_check" in {x["code"] for x in _conflict_flags(sections)}
