"""Offline scorecard evidence contracts; never execute app startup or auth."""

import ast
from contextlib import nullcontext
from copy import deepcopy
import csv
from datetime import datetime, timezone
import inspect
import io
import json
import logging
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock, call
import urllib.request
import zipfile

import numpy as np
import pandas as pd
import pytest
import requests

from stock_lab_core import chart_scorecard
from stock_lab_core.decision_workflow import (
    align_precision_final_check_rows,
    build_decision_workflow,
)
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK,
    GATE_DEFENSE,
    GATE_EXECUTABLE,
    GATE_WAIT,
    GATE_WATCH_ONLY,
)
from stock_lab_core.financial_freshness import financial_basis
from stock_lab_core.formatters import clean_float, finite_num, format_rr_ratio, is_kr_listed
from stock_lab_core.precision_chart_view import frame_last_date
from stock_lab_core.precision_review_export import build_precision_review_export_zip
from stock_lab_core.scorecard_review import build_scorecard_review, scorecard_decision_context


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    blocked = Mock(side_effect=AssertionError("Scorecard tests must stay offline"))
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    yield
    blocked.assert_not_called()


class ScorecardUI:
    def __init__(self):
        self.frames = []
        self.captions = []
        self.session_state = {"_app_final_macro_risk": 0.0}
        self.column_config = SimpleNamespace(TextColumn=Mock(), ProgressColumn=Mock())

    def markdown(self, *args, **kwargs):
        pass

    def caption(self, text):
        self.captions.append(text)

    def dataframe(self, frame, **kwargs):
        self.frames.append(frame.copy(deep=True))

    def expander(self, *args, **kwargs):
        return nullcontext()


@pytest.fixture(scope="module")
def app_definitions():
    names = {
        "get_fin_meta_parts", "get_fin_latest_record", "_valuation_missing",
        "_merge_missing_valuation_fields", "build_valuation_fields_from_fin_meta",
        "render_precision_scorecard", "build_pre_buy_final_checks",
    }
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    return compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec")


@pytest.fixture
def offline_app(app_definitions):
    app = SimpleNamespace(
        st=ScorecardUI(), pd=pd, np=np, inspect=inspect, logging=logging,
        clean_float=clean_float, finite_num=finite_num, format_rr_ratio=format_rr_ratio,
        financial_basis=financial_basis, frame_last_date=frame_last_date,
        is_kr_listed=is_kr_listed,
        fetch_valuation_snapshot=Mock(return_value=None),
        load_price_df=Mock(return_value=pd.DataFrame()),
        get_rs_benchmark=Mock(return_value="SPY"),
        build_decision_workflow=build_decision_workflow,
        align_precision_final_check_rows=align_precision_final_check_rows,
        is_leveraged_or_inverse_product=Mock(return_value=False),
        build_leveraged_precision_state=Mock(return_value={}),
        build_sideways_quality_state=Mock(return_value={}),
        get_valuation_headline_for_final_check=Mock(return_value=("가격매력 우수", "", 20.0)),
        GATE_DATA_CHECK=GATE_DATA_CHECK, GATE_DEFENSE=GATE_DEFENSE,
        GATE_EXECUTABLE=GATE_EXECUTABLE, GATE_WAIT=GATE_WAIT, GATE_WATCH_ONLY=GATE_WATCH_ONLY,
    )
    exec(app_definitions, app.__dict__)
    return app


def bars(count=300):
    close = np.linspace(100.0, 140.0, count)
    return pd.DataFrame({
        "Open": close - 1, "High": close + 2, "Low": close - 2,
        "Close": close, "Volume": np.arange(count, dtype=float) + 1000,
    }, index=pd.bdate_range(end="2026-10-30", periods=count))


def stored_financial():
    return {
        "source": "saved synthetic statements", "auto_score": 4, "manual_score": 0, "final_score": 0,
        "metrics": {
            "annual_latest": {"date": "2025-12-31", "roe": 25.0, "net_margin": 0.0},
            "derived": {"rev_growth": 15.0},
        },
    }


def strong_scorecard():
    rows = [{"축": axis, "점수": score} for axis, score in (("품질", 100), ("가치", 95), ("모멘텀", 90))]
    factors = [{"축": row["축"], "항목": f"factor {i}", "값": 1, "점수": row["점수"]}
               for row in rows for i in range(2)]
    return {
        "rows": rows, "factors": factors, "review": build_scorecard_review(rows, factors),
        "source": "saved synthetic statements", "price_asof": "2026-10-30",
        "financial_basis": {"재무자료기간": "연간 2025-12-31"},
    }


@pytest.mark.parametrize("missing", [None, "", "invalid", True, False, float("nan"), float("inf"), -float("inf")])
def test_review_missing_factor_is_not_zero_or_a_known_score(missing):
    rows = [{"축": "품질", "점수": 99}]
    factors = [{"축": "품질", "항목": "ROE", "값": missing, "점수": missing}]
    before = deepcopy((rows, factors))
    review = build_scorecard_review(rows, factors)
    axis = review["axes"][0]
    assert axis["점수"] is None and axis["확인"] == 0 and axis["전체"] == 1
    assert axis["자료상태"] == "미수집"
    assert review["missing_axes"] == ["품질"] and review["partial_axes"] == []
    assert review["strongest"] is None and review["weakest"] is None
    assert review["mode"] == "evidence_only"
    assert review["score_added"] == 0 and review["thresholds_changed"] is False
    assert (rows, factors) == before


@pytest.mark.parametrize("zero", [0, 0.0, "0"])
def test_review_actual_zero_remains_known_and_is_not_missing(zero):
    rows = [{"축": "품질", "점수": zero}]
    factors = [{"축": "품질", "항목": "ROE", "값": zero, "점수": zero}]
    before = deepcopy((rows, factors))
    review = build_scorecard_review(rows, factors)
    assert review["axes"][0] == {
        "축": "품질", "점수": 0.0, "확인": 1, "전체": 1, "자료상태": "충족", "근거": "",
    }
    assert review["missing_axes"] == review["partial_axes"] == []
    assert (rows, factors) == before


def test_review_ranks_only_sufficiently_covered_financial_axes():
    inputs = [
        ("품질", 100, [100, None, None, None]),
        ("가치", 99, [99, 99, None, None, None]),
        ("성장", 70, [70, 70]),
        ("재무건전성", 20, [20, 20, None, None]),
        ("주주환원", 85, [85]),
        ("모멘텀", 100, [100, 100, 100, 100, 100, 100]),
    ]
    rows = [{"축": axis, "점수": score} for axis, score, _ in inputs]
    factors = [{"축": axis, "항목": str(i), "점수": score}
               for axis, _, scores in inputs for i, score in enumerate(scores)]
    before = deepcopy((rows, factors))
    review = build_scorecard_review(rows, factors)
    assert review["strongest"]["축"] == "성장"
    assert review["weakest"]["축"] == "재무건전성"
    assert review["partial_axes"] == ["품질", "가치", "재무건전성"]
    assert (rows, factors) == before


def test_negative_metrics_are_warned_and_nonpositive_pe_is_not_cheap():
    info = {"returnOnEquity": -0.1, "revenueGrowth": -0.2, "earningsGrowth": -0.3,
            "operatingCashflow": -100, "freeCashflow": -10, "trailingPE": -5, "forwardPE": 0}
    before = deepcopy(info)
    rows, factors = chart_scorecard.build_chart_scorecard(info, pd.DataFrame())
    review = build_scorecard_review(rows, factors)
    by_name = {item["항목"]: item for item in factors}
    assert by_name["ROE"]["점수"] == 0
    assert by_name["후행 PER"]["점수"] is None
    assert by_name["선행 PER"]["점수"] is None
    assert set(review["warnings"]) == {
        "ROE 음수", "매출 성장 음수", "이익 성장 음수", "영업현금흐름 음수", "잉여현금흐름 음수",
        "후행 PER 0 이하: 저평가로 간주하지 않음", "선행 PER 0 이하: 저평가로 간주하지 않음",
    }
    assert info == before


def test_etf_review_discards_corporate_axes_even_if_supplied():
    scorecard = strong_scorecard()
    before = deepcopy(scorecard)
    review = build_scorecard_review(scorecard["rows"], scorecard["factors"], is_etf=True)
    assert [axis["축"] for axis in review["axes"]] == ["모멘텀"]
    assert review["strongest"] is None and review["weakest"] is None
    assert review["missing_axes"] == review["partial_axes"] == []
    assert scorecard == before


@pytest.mark.parametrize("wrapped", [False, True], ids=["raw", "snapshot"])
@pytest.mark.parametrize("currencies,fcf,cap,expected", [
    pytest.param({"currency": "USD", "financialCurrency": "USD"}, 8, 100, 8.0, id="same-currency"),
    pytest.param({"currency": "USD", "financialCurrency": "EUR"}, 8, 100, None, id="different-currency"),
    pytest.param({"currency": "GBp", "financialCurrency": "GBP"}, 8, 100, None, id="pence-vs-pounds"),
    pytest.param({}, 8, 100, None, id="both-currencies-unknown"),
    pytest.param({"financialCurrency": "USD"}, 8, 100, None, id="quote-currency-unknown"),
    pytest.param({"currency": "USD"}, 8, 100, None, id="financial-currency-unknown"),
    pytest.param({"currency": "USD", "financialCurrency": "USD"}, 0, 100, 0.0, id="known-zero-fcf"),
    pytest.param({"currency": "USD", "financialCurrency": "USD"}, None, 100, None, id="missing-fcf"),
    pytest.param({"currency": "USD", "financialCurrency": "USD"}, 8, 0, None, id="zero-market-cap"),
    pytest.param({"currency": "USD", "financialCurrency": "USD"}, 8, -100, None, id="negative-market-cap"),
])
def test_fcf_yield_requires_known_matching_currency_and_positive_cap(wrapped, currencies, fcf, cap, expected):
    data = {**currencies, "freeCashflow": fcf, "marketCap": cap}
    info = {"data": data, "sources": ["synthetic"]} if wrapped else data
    before = deepcopy(info)
    _, factors = chart_scorecard.build_chart_scorecard(info, pd.DataFrame())
    factor = next(item for item in factors if item["항목"] == "FCF 수익률")
    if expected is None:
        assert factor["값"] is None and factor["점수"] is None
    else:
        assert factor["값"] == pytest.approx(expected)
        assert factor["점수"] == (0 if expected == 0 else 100)
    assert info == before


@pytest.mark.parametrize("is_etf", [False, True])
def test_chart_render_returns_review_and_displays_coverage_without_mutation(is_etf):
    ui, frame, benchmark = ScorecardUI(), bars(), bars()
    info = {"returnOnEquity": 0, "trailingAnnualDividendYield": 0}
    before_info, before_frame, before_benchmark = deepcopy(info), frame.copy(deep=True), benchmark.copy(deep=True)
    result = chart_scorecard.render_chart_scorecard(ui, frame, info=info, ticker="TEST",
                                                  is_etf=is_etf, benchmark=benchmark, source="synthetic")
    assert set(result) == {"rows", "factors", "review"}
    assert result["review"] == build_scorecard_review(result["rows"], result["factors"], is_etf=is_etf)
    shown = ui.frames[0]
    assert list(shown.columns) == ["축", "점수", "자료"]
    assert shown["축"].tolist() == [item["축"] for item in result["review"]["axes"]]
    assert shown["자료"].tolist() == [f"{item['확인']}/{item['전체']} · {item['자료상태']}"
                                     for item in result["review"]["axes"]]
    if is_etf:
        assert shown["축"].tolist() == ["모멘텀"]
        assert {item["축"] for item in result["factors"]} == {"모멘텀"}
    else:
        assert shown.set_index("축").loc["품질", "점수"] == 0
        assert pd.isna(shown.set_index("축").loc["가치", "점수"])
    assert info == before_info
    pd.testing.assert_frame_equal(frame, before_frame)
    pd.testing.assert_frame_equal(benchmark, before_benchmark)


@pytest.mark.parametrize("snapshot", [None, {"data": None}, {"data": []}, "invalid",
                                     RuntimeError("PRIVATE_PROVIDER_DETAIL")],
                         ids=["none", "data-none", "data-invalid", "snapshot-invalid", "fetch-error"])
def test_precision_render_survives_unusable_snapshot_using_saved_data(offline_app, snapshot, caplog):
    app, meta, frame = offline_app, stored_financial(), bars()
    before_meta, before_frame = deepcopy(meta), frame.copy(deep=True)
    before_snapshot = deepcopy(snapshot)
    if isinstance(snapshot, Exception):
        app.fetch_valuation_snapshot.side_effect = snapshot
    else:
        app.fetch_valuation_snapshot.return_value = snapshot
    result = app.render_precision_scorecard(frame, "MSFT", meta, False)
    assert result["data"] == {"profitMargins": 0.0, "returnOnEquity": 0.25, "revenueGrowth": 0.15}
    assert "저장 재무 보완" in result["source"]
    assert result["price_asof"] == "2026-10-30"
    assert result["financial_basis"] == financial_basis(meta)
    assert result["review"]["mode"] == "evidence_only"
    app.fetch_valuation_snapshot.assert_called_once_with("MSFT")
    assert app.load_price_df.call_args_list == [call("MSFT", "2y"), call("SPY", "2y")]
    assert meta == before_meta
    if not isinstance(snapshot, Exception):
        assert snapshot == before_snapshot
    else:
        assert "조회 실패" in result["source"]
        assert "PRIVATE_PROVIDER_DETAIL" not in str(app.st.captions) + caplog.text + result["source"]
    pd.testing.assert_frame_equal(frame, before_frame)


@pytest.mark.parametrize("is_etf", [False, True])
def test_precision_render_accepts_none_fin_meta_and_etf_skips_financial_fetch(offline_app, is_etf):
    app = offline_app
    result = app.render_precision_scorecard(bars(), "SPY" if is_etf else "MSFT", None, is_etf)
    assert result["data"] == {}
    assert result["financial_basis"] == financial_basis({}, is_etf=is_etf)
    if is_etf:
        app.fetch_valuation_snapshot.assert_not_called()
        assert [axis["축"] for axis in result["review"]["axes"]] == ["모멘텀"]
    else:
        app.fetch_valuation_snapshot.assert_called_once_with("MSFT")
        assert set(result["review"]["missing_axes"]) == {"품질", "가치", "성장", "재무건전성", "주주환원"}


@pytest.mark.parametrize("scorecard", [None, {}, {"review": None}, {"review": []}])
def test_unlinked_scorecard_has_no_added_vote(scorecard):
    assert scorecard_decision_context(scorecard, None, 0) == {
        "status": "unavailable", "summary": "성적표 자료 미연결", "score_added": 0,
    }


@pytest.mark.parametrize("is_etf", [False, True])
@pytest.mark.parametrize("state", [GATE_DATA_CHECK, GATE_DEFENSE, GATE_WAIT, GATE_WATCH_ONLY, GATE_EXECUTABLE])
def test_strong_scorecard_cannot_change_final_counts_verdict_or_gate(offline_app, state, is_etf):
    app, scorecard = offline_app, strong_scorecard()
    if is_etf:
        scorecard["review"] = build_scorecard_review(scorecard["rows"], scorecard["factors"], is_etf=True)
    workflow = {"게이트상태": state, "게이트근거": "synthetic gate", "RR값": 2.0}
    decision = {
        "dec": "신규 진입", "grade": "A급", "t_score": 8, "fin_score": 4, "cur_p": 100,
        "trend": "상승", "rs_label": "강함", "mfi": 55, "rsi": 55, "pct_b": 0.5,
        "dd": -0.05, "day_ret": 0.01, "target_w": 5, "current_w": 0,
        "execution_workflow": workflow,
    }
    meta = stored_financial()
    before = deepcopy((decision, meta, scorecard))
    rows_before, summary_before = app.build_pre_buy_final_checks("Test", "MSFT", is_etf, decision, 4, False, 0, fin_meta=meta)
    linked = {**deepcopy(decision), "chart_scorecard": scorecard}
    before_linked = deepcopy(linked)
    rows_after, summary_after = app.build_pre_buy_final_checks("Test", "MSFT", is_etf, linked, 4, False, 0, fin_meta=meta)
    assert rows_after == rows_before
    assert {key: value for key, value in summary_after.items() if key != "scorecard_evidence"} == {
        key: value for key, value in summary_before.items() if key != "scorecard_evidence"
    }
    evidence = summary_after["scorecard_evidence"]
    assert summary_before["scorecard_evidence"]["status"] == "unavailable"
    assert evidence["status"] == "linked" and evidence["score_added"] == 0
    assert evidence["thresholds_changed"] is False
    assert evidence["stored_financial_score"] == (None if is_etf else 4)
    assert evidence["source"] == scorecard["source"]
    assert evidence["price_asof"] == scorecard["price_asof"]
    assert evidence["financial_basis"] == scorecard["financial_basis"]
    assert evidence["review"] == scorecard["review"]
    if state == GATE_EXECUTABLE:
        assert summary_after["execution_allowed"] is True
    else:
        assert summary_after["execution_allowed"] is False
        assert "실행 제한을 해제하지 않습니다" in evidence["summary"]
    assert (decision, meta, scorecard) == before and linked == before_linked


@pytest.mark.parametrize("fin_score,expected", [(0, 0.0), (None, None), ("invalid", None)])
def test_decision_evidence_preserves_stored_zero_and_missing_score(fin_score, expected):
    scorecard, workflow = strong_scorecard(), {"게이트상태": GATE_WAIT}
    before = deepcopy((scorecard, workflow))
    result = scorecard_decision_context(scorecard, workflow, fin_score)
    assert result["stored_financial_score"] == expected
    assert result["score_added"] == 0 and result["thresholds_changed"] is False
    assert (scorecard, workflow) == before


def test_rendered_scorecard_reaches_precision_zip_without_extra_fetch_or_recalculation(offline_app, monkeypatch):
    app, meta, frame, extended, benchmark = offline_app, stored_financial(), bars(200), bars(400), bars(400)
    snapshot = {"data": {"returnOnEquity": 0, "revenueGrowth": None}, "sources": ["cached synthetic"]}
    before_snapshot, before_meta = deepcopy(snapshot), deepcopy(meta)
    before_frames = [item.copy(deep=True) for item in (frame, extended, benchmark)]
    app.fetch_valuation_snapshot.return_value = snapshot
    app.load_price_df.side_effect = [extended, benchmark]
    render = Mock(wraps=chart_scorecard.render_chart_scorecard)
    render.__signature__ = inspect.signature(chart_scorecard.render_chart_scorecard)
    monkeypatch.setattr(chart_scorecard, "render_chart_scorecard", render)
    scorecard = app.render_precision_scorecard(frame, "MSFT", meta, False)
    assert scorecard["data"]["returnOnEquity"] == 0
    assert scorecard["data"]["revenueGrowth"] == 0.15
    assert scorecard["data"]["profitMargins"] == 0
    pd.testing.assert_frame_equal(render.call_args.args[1], extended)
    assert render.call_args.kwargs["benchmark"] is benchmark
    app.fetch_valuation_snapshot.assert_called_once_with("MSFT")
    assert app.load_price_df.call_args_list == [call("MSFT", "2y"), call("SPY", "2y")]
    render.assert_called_once()
    etf_holdings = {"ticker": "MSFT", "status": "not_requested", "rows": []}
    decision = {"ticker": "MSFT", "fin_score": 4, "t_score": 8, "chart_scorecard": scorecard,
                "etf_holdings": etf_holdings,
                "execution_workflow": {"게이트상태": GATE_WAIT, "게이트근거": "synthetic gate"}}
    before_decision = deepcopy(decision)
    forbidden = Mock(side_effect=AssertionError("Export must use the already rendered scorecard"))
    app.fetch_valuation_snapshot = app.load_price_df = forbidden
    monkeypatch.setattr(chart_scorecard, "build_chart_scorecard", forbidden)
    monkeypatch.setattr(chart_scorecard, "render_chart_scorecard", forbidden)
    payload = build_precision_review_export_zip(
        selected_ticker="MSFT", result_ticker="MSFT", decision=decision,
        financial=meta, ohlcv={"daily_source": frame},
        captured_at=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc),
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        snapshot_json = json.loads(archive.read("snapshot.json"))
        manifest = json.loads(archive.read("manifest.json"))
        assert "chart_scorecard.csv" in archive.namelist()
        assert "etf_holdings.csv" in archive.namelist()
        csv_rows = list(csv.DictReader(io.StringIO(archive.read("chart_scorecard.csv").decode("utf-8-sig"))))
        assert any(row["value"] == "evidence_only" for row in csv_rows)
    assert snapshot_json["sections"]["chart_scorecard"] == scorecard
    assert snapshot_json["sections"]["etf_holdings"] == etf_holdings
    assert "chart_scorecard" not in snapshot_json["sections"]["main_decision"]
    assert "etf_holdings" not in snapshot_json["sections"]["main_decision"]
    assert snapshot_json["sections"]["main_decision"]["fin_score"] == 4
    assert snapshot_json["sections"]["main_decision"]["t_score"] == 8
    assert manifest["fetched_for_export"] is False and manifest["recalculated_for_export"] is False
    assert "chart_scorecard.csv" in manifest["files"]
    assert "etf_holdings.csv" in manifest["files"]
    forbidden.assert_not_called()
    assert decision == before_decision and meta == before_meta and snapshot == before_snapshot
    for actual, previous in zip((frame, extended, benchmark), before_frames):
        pd.testing.assert_frame_equal(actual, previous)
