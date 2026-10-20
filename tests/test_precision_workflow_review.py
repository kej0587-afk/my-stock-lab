"""Offline regressions for the MSFT precision review's displayed contradictions."""

from copy import deepcopy
import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from stock_lab_core.decision_workflow import (
    align_precision_entry_plan_rows,
    align_precision_final_check_rows,
    attach_market_execution_context,
    build_decision_workflow,
    format_precision_take_profit_condition,
    partition_today_queue,
)
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    GATE_WATCH_ONLY,
    apply_execution_gate_columns,
)
from stock_lab_core.precision_review_export import build_precision_review_export_zip
from stock_lab_core.today_queue import today_queue_reason_bucket


@pytest.fixture
def msft_review():
    decision = {
        "cur_p": 531.0900268554688, "rr_stop": 508.5072, "rr_target": 551.1500244140625,
        "rr_ratio": 0.89, "atr": 11.291429792131696, "ma20": 523.4714767456055,
        "grade": "✅A급 (분할 매수)", "t_score": 8, "tech_total": 4, "fin_score": 4,
        "dec": "🎯S급 눌림목: 탑승 찬스", "decision_code": "S_PULLBACK_ENTRY",
        "decision_group": "buyish", "data_state": "OK", "mtf_bias_label": "상위 시간대 우호",
        "rsi": 57.80208419413462, "mfi": 52.75672393388274, "pct_b": 0.6469483237780042,
        "trend": "🚀정배열(상승)", "rs_label": "🚀강함", "dd": -0.04086893203241393,
    }
    workflow = {
        "티커": "MSFT", "게이트상태": GATE_DEFENSE, "게이트근거": "시장방어: 신규매수 중단",
    }
    decision["execution_workflow"] = workflow
    return {
        "selected_ticker": "MSFT", "result_ticker": "MSFT", "decision": decision,
        "final_check": {
            "ticker": "MSFT",
            "rows": [
                {"점검항목": "시스템 타점", "상태": "차단", "해석": workflow["게이트근거"]},
                {"점검항목": "재무/상품", "상태": "통과", "해석": "재무 4점"},
                {"점검항목": "밸류/가격", "상태": "통과", "해석": "조건부 적정. 목표가 업사이드 12.8%."},
                {"점검항목": "구조/추세", "상태": "통과", "해석": "정배열 / RS강함"},
                {"점검항목": "상위 시간대", "상태": "통과", "해석": "상위 시간대 우호"},
                {"점검항목": "과열", "상태": "통과", "해석": "RSI 57.8, MFI 52.8, %B 0.65"},
                {"점검항목": "횡보/눌림 품질", "상태": "주의", "해석": "손익비 별도 확인"},
                {"점검항목": "손익비", "상태": "차단", "해석": "현재가 기준 R/R 0.89"},
                {"점검항목": "비중", "상태": "주의", "해석": "목표비중 미설정"},
                {"점검항목": "매크로", "상태": "통과", "해석": "매크로 리스크 1.5"},
                {"점검항목": "보유상태", "상태": "통과", "해석": "신규 진입. 추세/RS가 양호해 정찰 비중으로 시작 가능합니다."},
            ],
            "summary": {"final_label": "매수 금지", "pass_count": 7, "caution_count": 2, "block_count": 2},
        },
        "entry_plan": {
            "ticker": "MSFT", "status": "현재가 보류 / 눌림 대기", "rr_now": "0.89",
            "current_price": decision["cur_p"], "stop": decision["rr_stop"], "target": decision["rr_target"],
            "rows": [
                {"단계": "총 추가 필요", "가격": "$531.09", "금액/수량": "-", "조건": "목표비중 기준 추가 필요 없음"},
                {"단계": "1차 진입 (30%)", "가격": "$531.09", "금액/수량": "-", "조건": "현재가 부근 1차 정찰"},
                {"단계": "2차 추가", "가격": "$523.47", "금액/수량": "-", "조건": "MA20 근처에서 반등 확인"},
                {"단계": "3차 예비", "가격": "$519.80", "금액/수량": "-", "조건": "1ATR 눌림 근처, 손절가 이탈 전까지만"},
                {"단계": "1차 익절", "가격": "$551.15", "금액/수량": "보유분 30~50%", "조건": "1R 도달 시 일부 회수, 잔여 손절은 본전 근처로 상향"},
                {"단계": "최종 익절", "가격": "$551.15", "금액/수량": "잔여분", "조건": "구조 목표가 도달 또는 MFI/%B 과열 동반 시"},
                {"단계": "손절", "가격": "$508.51", "금액/수량": "전량 또는 계획분", "조건": "종가 기준 이탈 시 신규진입 시나리오 무효"},
            ],
        },
    }


def _export(snapshot):
    with zipfile.ZipFile(io.BytesIO(build_precision_review_export_zip(**snapshot))) as archive:
        return json.loads(archive.read("snapshot.json"))


def test_msft_review_detects_row_conflicts_without_changing_captured_evidence(msft_review):
    original = deepcopy(msft_review)
    exported = _export(msft_review)
    flags = {flag["code"]: flag for flag in exported["conflict_flags"]}
    assert {
        "final_check_row_vs_execution_gate", "entry_plan_row_vs_execution_gate",
        "entry_plan_take_profit_below_1r",
    } <= flags.keys()
    assert "final_check.rows[10].해석" in flags["final_check_row_vs_execution_gate"]["note"]
    assert "entry_plan.rows[1].조건" in flags["entry_plan_row_vs_execution_gate"]["note"]
    assert "intentional" in flags["candidate_quality_vs_gate"]["note"]
    assert "execution_gate_vs_final_check" not in flags
    assert exported["sections"]["final_check"] == original["final_check"]
    assert exported["sections"]["entry_plan"] == original["entry_plan"]
    assert msft_review == original


@pytest.mark.parametrize("gate", [GATE_WAIT, GATE_DEFENSE, GATE_DATA_CHECK, GATE_WATCH_ONLY, ""])
def test_precision_prose_respects_every_restricted_gate_without_rescoring(msft_review, gate):
    original = deepcopy(msft_review)
    workflow = {"게이트상태": gate, "게이트근거": "현재 실행 조건 확인"}
    checks = align_precision_final_check_rows(msft_review["final_check"]["rows"], workflow)
    plan_rows = align_precision_entry_plan_rows(msft_review["entry_plan"]["rows"], workflow)
    assert "보류" in checks[-1]["해석"]
    assert "시작 가능" not in checks[-1]["해석"]
    assert [row["상태"] for row in checks] == [row["상태"] for row in original["final_check"]["rows"]]
    for index in (1, 2, 3):
        assert plan_rows[index]["조건"].startswith("실행 보류 · 현재 실행 조건 확인")
        assert {k: v for k, v in plan_rows[index].items() if k != "조건"} == {
            k: v for k, v in original["entry_plan"]["rows"][index].items() if k != "조건"
        }
    for index in (0, 4, 5, 6):
        assert plan_rows[index] == original["entry_plan"]["rows"][index]
    assert align_precision_entry_plan_rows(plan_rows, workflow) == plan_rows
    assert msft_review == original


def test_corrected_msft_text_leaves_only_the_intentional_axis_differences(msft_review):
    decision = msft_review["decision"]
    workflow = decision["execution_workflow"]
    msft_review["final_check"]["rows"] = align_precision_final_check_rows(msft_review["final_check"]["rows"], workflow)
    rows = align_precision_entry_plan_rows(msft_review["entry_plan"]["rows"], workflow)
    rows[4]["조건"] = format_precision_take_profit_condition(decision["cur_p"], decision["rr_stop"], decision["rr_target"])
    msft_review["entry_plan"]["rows"] = rows
    flags = {flag["code"] for flag in _export(msft_review)["conflict_flags"]}
    assert flags == {"candidate_quality_vs_gate", "different_conclusion_labels"}
    assert msft_review["final_check"]["summary"] == {
        "final_label": "매수 금지", "pass_count": 7, "caution_count": 2, "block_count": 2,
    }


def test_executable_or_held_checks_keep_the_existing_prose(msft_review):
    checks = msft_review["final_check"]["rows"]
    rows = msft_review["entry_plan"]["rows"]
    assert align_precision_final_check_rows(checks, {"게이트상태": GATE_EXECUTABLE}) == checks
    assert align_precision_entry_plan_rows(rows, {"게이트상태": GATE_EXECUTABLE}) == rows
    held = [{"점검항목": "보유상태", "상태": "통과", "해석": "평단 대비 5.0%. 보유 관리 범위 안에서 판단 가능합니다."}]
    assert align_precision_final_check_rows(held, {"게이트상태": GATE_DEFENSE}) == held


@pytest.mark.parametrize("target,expected", [(108.9, "1R 미만의 구조 목표가"), (110, "1R 도달"), (120, "1R 도달")])
def test_first_profit_condition_matches_the_existing_capped_price(target, expected):
    assert format_precision_take_profit_condition(100, 90, target).startswith(expected)


def test_msft_today_detail_keeps_quality_timing_and_market_defense_as_separate_axes(msft_review):
    decision = msft_review["decision"]
    row = build_decision_workflow("Microsoft", "MSFT", decision)
    frame = attach_market_execution_context(pd.DataFrame([row]), {"action": "신규매수 중단"})
    frame = apply_execution_gate_columns(frame)
    masks = partition_today_queue(frame, frame.apply(today_queue_reason_bucket, axis=1))
    result = frame.iloc[0]
    assert result["후보품질"] == decision["grade"] and result["후보점수"] == 8
    assert result["판정코드"] == "S_PULLBACK_ENTRY"
    assert result["게이트상태"] == GATE_DEFENSE
    assert result["게이트근거"] == "시장방어: 신규매수 중단"
    assert result["최종읽기"] == "방어우선: 추가매수 보류"
    assert masks["market_defense"].iloc[0] and not masks["execution"].iloc[0]


def test_overweight_gate_takes_precedence_over_an_earlier_leveraged_market_bucket():
    frame = pd.DataFrame([
        {"티커": "418660.KS", "게이트상태": GATE_DEFENSE, "게이트근거": "목표비중/비중초과 우선", "판정코드": "HARD_BLOCK_OVERWEIGHT"},
        {"티커": "RAM", "게이트상태": GATE_DEFENSE, "게이트근거": "목표비중/비중초과 우선", "판정코드": "HARD_BLOCK_OVERWEIGHT"},
        {"티커": "MSFT", "게이트상태": GATE_DEFENSE, "게이트근거": "시장방어: 신규매수 중단", "판정코드": "S_PULLBACK_ENTRY"},
    ], index=[2, 4, 8])
    frame["시장실행상태"] = "시장방어: 신규매수 중단"
    original = frame.copy(deep=True)
    masks = partition_today_queue(frame, pd.Series("시장방어", index=frame.index))
    assert masks["overweight"].tolist() == [True, True, False]
    assert masks["market_defense"].tolist() == [False, False, True]
    assert pd.DataFrame(masks).sum(axis=1).eq(1).all()
    pd.testing.assert_frame_equal(frame, original)


def test_actual_precision_calls_align_displayed_and_exported_rows_before_rendering():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    final_check = functions["build_pre_buy_final_checks"]
    alignment = next(node for node in ast.walk(final_check) if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Call)
                     and ast.unparse(node.value.func) == "align_precision_final_check_rows")
    counts = next(node for node in ast.walk(final_check) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "status_counts" for target in node.targets))
    assert ast.unparse(alignment.targets[0]) == "rows" and alignment.lineno < counts.lineno
    plan = functions["render_entry_execution_plan"]
    alignment = next(node for node in ast.walk(plan) if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Call)
                     and ast.unparse(node.value.func) == "align_precision_entry_plan_rows")
    render = next(node for node in ast.walk(plan) if isinstance(node, ast.Call)
                  and ast.unparse(node.func) == "st.dataframe")
    assert ast.unparse(alignment.targets[0]) == "rows" and alignment.lineno < render.lineno
    assert any(isinstance(node, ast.Call) and ast.unparse(node.func) == "format_precision_take_profit_condition"
               for node in ast.walk(plan))
    assert "'rows': rows" in ast.unparse(next(node for node in ast.walk(plan)
                                             if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)
                                             and any(isinstance(key, ast.Constant) and key.value == "rows" for key in node.value.keys)))


def test_actual_final_check_preserves_msft_verdict_and_counts(app_module, monkeypatch, msft_review):
    monkeypatch.setattr(app_module, "st", SimpleNamespace(session_state={"_app_final_macro_risk": 1.5}))
    monkeypatch.setattr(app_module, "build_leveraged_precision_state", lambda *args: {})
    monkeypatch.setattr(app_module, "get_valuation_headline_for_final_check", lambda *args, **kwargs: ("조건부 적정", "기업 체력 양호", 12.83873537378386))
    rows, summary = app_module.build_pre_buy_final_checks("Microsoft", "MSFT", False, msft_review["decision"], 4, False, 0)
    holding = next(row for row in rows if row["점검항목"] == "보유상태")
    assert "보류" in holding["해석"] and "시작 가능" not in holding["해석"]
    assert {key: summary[key] for key in msft_review["final_check"]["summary"]} == msft_review["final_check"]["summary"]


@pytest.mark.parametrize("rows", [None, {}, [None, {}, {"조건": None}]])
def test_row_diagnostics_tolerate_partial_checkpoints(msft_review, rows):
    msft_review["final_check"]["rows"] = rows
    msft_review["entry_plan"]["rows"] = rows
    flags = {flag["code"] for flag in _export(msft_review)["conflict_flags"]}
    assert flags == {"candidate_quality_vs_gate", "different_conclusion_labels"}
