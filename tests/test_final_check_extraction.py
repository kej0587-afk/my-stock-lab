"""Full ordered-output contracts captured before the final-check extraction."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WATCH_ONLY,
)

GOLDEN = Path(__file__).parent / "golden" / "final_check_rows_v1.json"


def cases():
    yield "normal", {}, {}
    for field, values in {
        "dd": [-0.1999, -0.2, -0.3],
        "mfi": [79.99, 80, 84.99, 85, None],
        "rsi": [69.99, 70, 74.99, 75, None],
        "pct_b": [0.9499, 0.95, 1.0199, 1.02, None],
        "rr_ratio": [None, 0, 0.99, 1, 1.49, 1.5],
        "current_w": [0, 4.999, 5, 6],
        "mtf_bias_label": ["상위 시간대 경고", "정찰만 적합", "상위 시간대 우호", "기타"],
        "cur_p": [None, 0, 92.99, 93, 110],
    }.items():
        for value in values:
            yield f"{field}={value}", {field: value}, {"has_pos": True}
    for risk in [None, 2.4999, 2.5, 4.4999, 4.5]:
        yield f"macro={risk}", {}, {"macro": risk}
    for gate in [GATE_DATA_CHECK, GATE_DEFENSE, GATE_WATCH_ONLY]:
        yield f"gate={gate}", {}, {"gate": gate}
    yield "core_drawdown_overheat", {"bucket": "core", "core_dca_rate": 0.2, "dd": -0.3, "mfi": 90}, {"is_etf": True}
    yield "core_default_label", {"bucket": "core", "core_dca_rate": 0.2, "pct_b": 1.02}, {"is_etf": True}
    yield "shock", {"live_gap_shock": True, "day_ret": -0.09}, {}
    yield "structure", {"structure_risk": True}, {}
    yield "weak", {"trend": "역배열", "rs_label": "약함"}, {}
    yield "explicit_mtf_text", {"mtf_bias_label": "상위 시간대 경고", "mtf_bias_text": "원문 유지"}, {}
    yield "held_target_zero", {"current_w": 2, "target_w": 0}, {"has_pos": True}
    yield "unheld_target_zero", {"target_w": 0}, {}
    yield "zero_cash", {"cash": 0, "available_cash": 0, "buy_amount": 0}, {"has_pos": True}
    yield "target_below_price", {"rr_target": 95, "rr_ratio": -0.5}, {}
    yield "missing", {"mfi": None, "rsi": None, "pct_b": None, "rr_ratio": None, "cur_p": None}, {"macro": None}
    yield "leveraged_fallback", {"is_leveraged_or_inverse": True, "day_ret": -0.08}, {"is_etf": True}
    for stage in ["미보유 관찰", "회복 전 DCA 보류", "과열패스", "회복 후보"]:
        yield f"leveraged_{stage}", {}, {"is_etf": True, "has_pos": True, "lev": {
            "dca_stage": stage, "dca_multiple": "×0" if stage != "회복 후보" else "×1",
            "recovery_passed": 2, "recovery_label": "2/5", "profile_key": "SOXL",
        }}


CASES = list(cases())


def run_case(app, changes, options):
    decision = {
        "dec": "신규진입 매수", "cur_p": 100.0, "rr_stop": 90, "rr_target": 116,
        "rr_ratio": 1.6, "trend": "🚀정배열(상승)", "rs_label": "🚀강함",
        "mfi": 55.0, "rsi": 55.0, "pct_b": 0.5, "dd": -0.05,
        "day_ret": 0.01, "target_w": 5.0, "current_w": 0.0,
        **changes,
    }
    decision["execution_workflow"] = {
        "게이트상태": options.get("gate", GATE_EXECUTABLE), "게이트근거": "fixed reason",
        "RR값": decision["rr_ratio"],
    }
    original = deepcopy(decision)
    with (
        patch.object(app.st, "session_state", {"_app_final_macro_risk": options.get("macro", 0)}),
        patch.object(app, "get_valuation_headline_for_final_check", return_value=("가격매력 우수", "", 20.0)),
        patch.object(app, "is_leveraged_or_inverse_product", return_value=False),
        patch.object(app, "build_leveraged_precision_state", return_value=options.get("lev", {})),
        patch.object(app, "build_leveraged_dca_timing_state", return_value={"status": "대기", "entry1_verdict": "대기"}),
        patch.object(app, "build_sideways_quality_state", return_value={}),
    ):
        result = app.build_pre_buy_final_checks(
            "Test", "TEST", options.get("is_etf", False), decision, 4,
            options.get("has_pos", False), 100.0,
        )
    assert decision == original
    return result


def digest(value):
    # Keep list order, every explanation, evidence field and final permission.
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


@pytest.mark.parametrize("case_id,changes,options", CASES, ids=[c[0] for c in CASES])
def test_full_final_check_matches_pre_extraction(app_module, case_id, changes, options):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    actual = run_case(app_module, changes, options)
    assert digest(actual) == expected[case_id], repr(actual)


@pytest.mark.parametrize("ticker,changes", [
    ("379810.KS", {"bucket": "core", "core_dca_rate": 0.2, "dd": -0.3}),
    ("SOXL", {"is_leveraged_or_inverse": True, "day_ret": -0.08}),
])
def test_final_panel_renders_held_etf_checks(app_module, ticker, changes):
    from streamlit.testing.v1 import AppTest

    rows, summary = run_case(app_module, changes, {"is_etf": True, "has_pos": True})
    payload = json.dumps([rows, summary], ensure_ascii=True)
    screen = AppTest.from_string(
        "import app, json\n"
        f"app.render_pre_buy_final_check_panel({ticker!r}, {ticker!r}, True, "
        f"{{}}, 0, True, 100, prepared_checks=json.loads({payload!r}))\n"
    ).run(timeout=20)
    assert not screen.exception
    assert screen.dataframe[0].value["점검항목"].tolist() == [r["점검항목"] for r in rows]
    assert [m.value for m in screen.metric] == [
        summary["final_label"], f"{summary['pass_count']}개",
        f"{summary['caution_count']}개", f"{summary['block_count']}개",
    ]
