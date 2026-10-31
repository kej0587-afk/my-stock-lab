"""Execute the actual app render boundaries without importing app startup."""

import ast
from contextlib import contextmanager
from copy import deepcopy
from html import escape
from pathlib import Path
import socket
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import valuation_presentation as presentation
from stock_lab_core import earnings_comparison as earnings
from stock_lab_core.financial_score import optional_float
from stock_lab_core.valuation_inputs import resolve_valuation_inputs


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def app_tree():
    return ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Presentation integration must not perform external lookups")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


class UI:
    def __init__(self):
        self.log, self.metrics, self.frames = [], [], []

    def markdown(self, text, **kwargs):
        self.log.append(("markdown", text))

    def caption(self, text):
        self.log.append(("caption", text))

    def info(self, text):
        self.log.append(("info", text))

    def write(self, *args):
        self.log.append(("write", args))

    def columns(self, count):
        return [self] * count

    def metric(self, label, value):
        self.metrics.append((label, value))

    def dataframe(self, frame, **kwargs):
        assert kwargs == {"width": "stretch", "hide_index": True}
        self.frames.append(frame.copy(deep=True))
        self.log.append(("table", len(frame)))

    @contextmanager
    def expander(self, label, *, expanded):
        self.log.append(("expander", label))
        assert expanded is False
        yield


def load_render(tree, namespace):
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == "render_valuation_price_panel"]
    assert len(nodes) == 1
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return namespace["render_valuation_price_panel"]


@pytest.fixture
def panel(app_tree, monkeypatch):
    ui = UI()
    monkeypatch.setattr(earnings, "get_earnings_comparison_snapshot", Mock(return_value={"ok": False, "status": "no_data"}))
    inputs = {"forwardPE": 20.0, "trailingPE": 21.0, "targetMeanPrice": 105.0,
              "targetMedianPrice": 104.0, "numberOfAnalystOpinions": 12,
              "recommendationKey": "hold", "currentPrice": 100.0, "regularMarketPrice": 100.0}
    snapshot = {"ok": True, "data": inputs, "sources": ["cached"], "reason": ""}
    analyst = {"ok": True, "status": "available", "data": dict(inputs)}
    financial = {"auto_score": 4, "manual_score": 0, "final_score": 0,
                 "metrics": {"original": 42}, "notes": {"ok": True}}
    valuation = {"headline": "중립", "color": "#64748b", "note": "Original interpretation",
        "forward_pe": 20.0, "trailing_pe": 21.0, "ps": 3.0, "target_upside": 5.0,
        "valuation_data_count": 3, "quality_data_count": 2, "data_count": 5,
        "rows": [{"항목": "연매출", "값": "100", "판정": "참고"},
                 {"항목": "목표가 업사이드", "값": "5.0%", "판정": "중립"},
                 {"항목": "PER", "값": "20.0x", "판정": "적정"},
                 {"항목": "PER", "값": "20.0x", "판정": "적정"}]}
    fetch = Mock(return_value=snapshot)
    analyst_fetch = Mock(return_value=analyst)
    financial_fetch = Mock(return_value=financial)
    calculate = Mock(return_value=valuation)
    build_display = Mock(wraps=presentation.build_valuation_presentation)
    render_details = Mock(wraps=presentation.render_valuation_details)
    monkeypatch.setattr(presentation, "build_valuation_presentation", build_display)
    monkeypatch.setattr(presentation, "render_valuation_details", render_details)
    namespace = {
        "st": ui, "np": np, "pd": pd, "fetch_valuation_snapshot": fetch,
        "get_analyst_snapshot": analyst_fetch, "ensure_fin_meta_for_valuation": financial_fetch,
        "build_valuation_interpretation": calculate,
        "_valuation_missing": lambda value: optional_float(value) is None,
        "clean_float": lambda value, default: optional_float(value) if optional_float(value) is not None else default,
        "finite_num": lambda value: optional_float(value) is not None,
        "fmt_multiple": lambda value: "-" if optional_float(value) is None else f"{value:.1f}x",
        "format_backtest_percent": lambda value: "" if optional_float(value) is None else f"{value:.1f}%",
        "escape_html_value": escape,
    }
    return dict(render=load_render(app_tree, namespace), ui=ui, inputs=inputs, snapshot=snapshot,
        analyst=analyst, financial=financial, valuation=valuation, fetch=fetch, analyst_fetch=analyst_fetch,
        financial_fetch=financial_fetch, calculate=calculate, build_display=build_display, render_details=render_details)


@pytest.mark.parametrize("forward,expected_label", [(20.0, "선행 PER(예상 이익)"), (None, "후행 PER(과거 이익)")])
def test_actual_panel_preserves_original_results_and_inputs_and_calls_new_details(panel, forward, expected_label):
    panel["valuation"]["forward_pe"] = forward
    keys = ("inputs", "snapshot", "analyst", "financial", "valuation")
    before = {key: deepcopy(panel[key]) for key in keys}
    calculation = {"cur_p": 100.0, "score": 0, "gate_state": "unchanged"}
    result = panel["render"]("Test", "MSFT", False, calculation, 0, fin_meta=panel["financial"])
    assert result["interpretation"] is panel["valuation"]
    expected_inputs, _ = resolve_valuation_inputs(panel["snapshot"], panel["analyst"], "MSFT", 100)
    assert result["inputs"] == expected_inputs and result["inputs"] is not panel["inputs"]
    assert result["financial_inputs"] is panel["financial"]
    assert result["sources"] is panel["snapshot"]["sources"]
    assert result["source_ok"] is True and result["source_reason"] == ""
    assert result["financial_inputs"]["final_score"] == 0
    assert all(panel[key] == before[key] for key in keys)
    assert calculation == {"cur_p": 100.0, "score": 0, "gate_state": "unchanged"}
    panel["fetch"].assert_called_once_with("MSFT")
    panel["analyst_fetch"].assert_called_once_with("MSFT")
    panel["financial_fetch"].assert_called_once_with("MSFT", False, panel["financial"])
    panel["calculate"].assert_called_once_with(expected_inputs, 100.0, "MSFT", fin_meta=panel["financial"])
    panel["build_display"].assert_called_once_with(panel["valuation"], snapshot=panel["snapshot"],
        analyst_snapshot=panel["analyst"], fin_meta=panel["financial"])
    panel["render_details"].assert_called_once()
    shown = panel["render_details"].call_args.args[1]
    assert panel["render_details"].call_args.args[0] is panel["ui"]
    assert shown["duplicate_rows_removed"] == 1
    assert sum(len(frame) for frame in panel["ui"].frames) == 4
    assert panel["ui"].metrics[2] == (expected_label, "20.0x" if forward is not None else "21.0x")
    assert any("회사 전망 원문 미연결" in str(item) for item in panel["ui"].log)
    assert len(result["interpretation"]["rows"]) == 4  # Only the presentation deduplicates.


def test_actual_panel_keeps_partial_lookup_failure_visible_outside_details(panel):
    panel["snapshot"]["reason"] = "Yahoo 조회 실패: Timeout PRIVATE_KEY"
    panel["analyst"].update(ok=False, status="rate_limited")
    result = panel["render"]("Test", "MSFT", False, {"cur_p": 100.0}, 0, fin_meta=panel["financial"])
    log = panel["ui"].log
    expander = next(i for i, (kind, _) in enumerate(log) if kind == "expander")
    visible = [text for kind, text in log[:expander] if kind == "caption"]
    assert any("밸류 조회: 일부 조회 실패" in text for text in visible)
    assert any("컨센서스 조회: 조회 제한" in text for text in visible)
    assert "PRIVATE_KEY" not in str(log)
    assert result["interpretation"] is panel["valuation"]
    assert result["source_reason"] == panel["snapshot"]["reason"]  # Preserve the export contract.


def test_actual_panel_missing_lookups_do_not_invent_values_or_bypass_new_details(panel):
    panel["snapshot"].update(ok=False, status="no_data")
    panel["analyst"].update(ok=False, status="no_target")
    panel["valuation"].update(forward_pe=None, trailing_pe=None, ps=None, target_upside=None,
                              rows=[], valuation_data_count=0, data_count=0)
    before = deepcopy(panel["inputs"])
    result = panel["render"]("Test", "MSFT", False, {"cur_p": 100.0}, 0, fin_meta=panel["financial"])
    assert result["inputs"] == {} and panel["inputs"] == before
    assert len(panel["ui"].frames) == 1
    assert panel["ui"].frames[0].iloc[0]["상태"] == "목표가 미제공"
    assert panel["ui"].metrics[2:] == [("PER(기준 미확인)", "-"), ("PSR", "-")]
    panel["render_details"].assert_called_once()
    assert any("밸류 조회: 자료 미제공" in str(item) for item in panel["ui"].log)


def test_quarterly_earnings_is_exported_as_evidence_without_entering_valuation_math(panel, monkeypatch):
    from datetime import datetime, timezone
    snapshot = {"ok": True, "status": "available", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "data": {"quoteType": {"symbol": "MSFT", "quoteType": "EQUITY"},
                 "earningsHistory": {"defaultMethodology": "gaap", "history": [{
                     "quarter": {"fmt": "2026-06-30"}, "epsActual": {"raw": 4.0},
                     "epsEstimate": {"raw": 3.0}, "currency": "USD"}]}}}
    fetch = Mock(return_value=snapshot)
    monkeypatch.setattr(earnings, "get_earnings_comparison_snapshot", fetch)
    result = panel["render"]("Test", "MSFT", False, {"cur_p": 100.0}, 0, fin_meta=panel["financial"])
    fetch.assert_called_once_with("MSFT")
    evidence = result["earnings_comparison"]
    assert evidence["actuals"][0]["difference"] == 1
    assert evidence["comparison_used_for_scoring"] is False
    assert result["interpretation"] is panel["valuation"]
    assert panel["ui"].frames[-1].iloc[0]["실제−예상"] == "1.00 USD"
    assert "earningsHistory" not in panel["calculate"].call_args.args[0]


def test_etf_returns_before_fetch_scoring_or_new_presentation(panel):
    result = panel["render"]("ETF", "SPY", True, {}, 0, fin_meta=panel["financial"])
    assert result == {"ticker": "SPY", "status": "ETF 별도판단"}
    for key in ("fetch", "analyst_fetch", "financial_fetch", "calculate", "build_display", "render_details"):
        panel[key].assert_not_called()
    earnings.get_earnings_comparison_snapshot.assert_not_called()
    assert not panel["ui"].frames and not panel["ui"].metrics
    assert any(kind == "info" for kind, _ in panel["ui"].log)


@pytest.mark.parametrize("lookup_failed", [True, False])
def test_actual_ensure_preserves_uncalculated_meta_and_exposes_enrichment_failure(app_tree, panel, lookup_failed):
    original = {"auto_score": None, "manual_score": None, "final_score": 3,
                "source": "uncalculated", "mode": "manual_or_default", "metrics": {},
                "notes": {"messages": ["자동 재무점수 미계산 상태"]}}
    before = deepcopy(original)
    fallback = {"source": "valuation_fin_fetch_failed", "metrics": {},
                "notes": {"messages": ["PRIVATE_PROVIDER_EXCEPTION"]}} if lookup_failed else {}
    fetched = Mock(return_value=fallback)
    namespace = panel["render"].__globals__
    namespace.update(fetch_fin_meta_for_valuation_fallback=fetched,
                     build_valuation_fields_from_fin_meta=Mock(return_value={}))
    nodes = [node for node in app_tree.body if isinstance(node, ast.FunctionDef)
             and node.name == "ensure_fin_meta_for_valuation"]
    assert len(nodes) == 1
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec"), namespace)

    result = panel["render"]("Test", "MSFT", False, {"cur_p": 100.0}, 3, fin_meta=original)
    fetched.assert_called_once_with("MSFT", False)
    panel["financial_fetch"].assert_not_called()  # The actual AST ensure function ran.
    assert original == before
    returned = result["financial_inputs"]
    assert returned["notes"] is original["notes"] and returned["metrics"] is original["metrics"]
    assert {key: returned[key] for key in original} == original
    assert returned["auto_score"] is None and returned["manual_score"] is None and returned["final_score"] == 3
    assert result["interpretation"] is panel["valuation"]
    expected_inputs, _ = resolve_valuation_inputs(panel["snapshot"], panel["analyst"], "MSFT", 100)
    panel["calculate"].assert_called_once_with(expected_inputs, 100.0, "MSFT", fin_meta=returned)
    shown = panel["render_details"].call_args.args[1]
    if lookup_failed:
        assert returned is not original
        assert returned == {**original, "valuation_lookup_status": "failed"}
        assert any("밸류 보강용 재무 조회 실패" in note for note in shown["diagnostics"])
        expander = next(i for i, item in enumerate(panel["ui"].log) if item[0] == "expander")
        assert any("밸류 보강용 재무 조회 실패" in str(item) for item in panel["ui"].log[:expander])
    else:
        assert returned is original and shown["diagnostics"] == []
    assert "PRIVATE_PROVIDER_EXCEPTION" not in str(returned) + str(panel["ui"].log)


@pytest.mark.parametrize("with_weighted", [True, False])
def test_actual_judgement_tab_calls_score_display_and_keeps_zero_scores(app_tree, monkeypatch, with_weighted):
    blocks = [node for node in ast.walk(app_tree) if isinstance(node, ast.With) and any(
        isinstance(item.context_expr, ast.Name) and item.context_expr.id == "judgement_tab" for item in node.items)]
    assert len(blocks) == 1
    ui = UI()
    meta = {"source": "SEC", "mode": "saved", "auto_score": 0, "manual_score": None, "final_score": 0}
    weighted = {"weighted_net_score": -2, "s_sum": 0, "a_sum": 0, "b_sum": 0,
                "danger_count": 0, "generic_score": 0, "order_score": 0, "middle_score": 0} if with_weighted else {}
    before = deepcopy((meta, weighted))
    build = Mock(wraps=presentation.financial_score_display_rows)
    monkeypatch.setattr(presentation, "financial_score_display_rows", build)
    namespace = {"st": ui, "pd": pd, "fin_meta": meta, "weighted": weighted,
                 "annual_judgements": {}, "quarter_judgements": {}, "notes": {"messages": []}}
    exec(compile(ast.Module(body=blocks[0].body, type_ignores=[]), str(APP_PATH), "exec"), namespace)
    build.assert_called_once_with(meta, weighted)
    assert (meta, weighted) == before
    assert len(ui.frames) == (2 if with_weighted else 1)
    values = dict(zip(ui.frames[0]["항목"], ui.frames[0]["값"]))
    assert values["auto_score"] == values["final_score"] == "0" and values["manual_score"] == "-"
    if with_weighted:
        values = dict(zip(ui.frames[1]["항목"], ui.frames[1]["값"]))
        assert values["weighted score"] == "-2" and values["danger_count"] == "0"
