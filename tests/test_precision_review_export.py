"""Offline review export regressions, including the real observatory call site."""

import ast
from copy import deepcopy
import csv
from datetime import datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.decision_workflow import (
    align_precision_entry_plan_rows,
    build_decision_workflow,
    format_precision_take_profit_condition,
)
from stock_lab_core.execution_gate import GATE_EXECUTABLE
from stock_lab_core.precision_review_export import (
    EXPORT_VERSION,
    PrecisionReviewDownload,
    REVIEW_NOTICE,
    build_precision_review_export_zip,
    render_precision_review_download,
)


CAPTURED = datetime(2026, 10, 20, 8, 30, tzinfo=timezone.utc)
APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _snapshot(**overrides):
    return {
        "selected_ticker": "MSFT", "result_ticker": "MSFT", "captured_at": CAPTURED,
        "decision": {
            "grade": "S급", "dec": "분할 진입 가능", "decision_code": "DISPLAYED_CODE",
            "decision_reasons": ["Displayed signal evidence"], "cur_p": 105,
            "rr_ratio": 2.0, "mtf_bias_label": "상위 시간대 경고",
            "execution_workflow": {"티커": "MSFT", "게이트상태": "실행가능", "게이트근거": "Displayed gate"},
        },
        "final_check": {
            "ticker": "MSFT",
            "rows": [{"점검항목": "밸류/가격", "상태": "차단", "해석": "Displayed lower evidence"}],
            "summary": {"final_label": "대기", "action": "Displayed action", "block_count": 1},
        },
        **overrides,
    }


def _read(**kwargs):
    archive = zipfile.ZipFile(io.BytesIO(build_precision_review_export_zip(**_snapshot(**kwargs))))
    return archive, json.loads(archive.read("snapshot.json"))


def _csv(archive, name):
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))


def test_review_keeps_display_basis_and_indicator_warning_without_private_context():
    basis = {"가격자료기준일": "2026-10-28", "지표마지막봉": "2026-10-28",
             "계산시각": "2026-10-29 16:00:00 KST", "가격반영": "가격 이력 기준"}
    _, snapshot = _read(context={"signal_basis": basis, "live_indicator_issue": "재계산 실패",
                                 "owner_email": "private@example.com", "api_key": "private-key"})
    context = snapshot["sections"]["context"]
    assert context["signal_basis"] == basis
    assert context["live_indicator_issue"] == "재계산 실패"
    assert "owner_email" not in context and "api_key" not in context


def test_archive_captures_rendered_sections_and_source_vs_display_prices_without_mutation():
    source = pd.DataFrame({
        "Open": [98.0, 100.0], "High": [101.0, 103.0], "Low": [97.0, 99.0],
        "Close": [100.0, 102.0], "Volume": [1000, 1200],
    }, index=pd.date_range("2026-10-19", periods=2, name="Date"))
    source.attrs = {"ticker": "MSFT", "source": "cached daily"}
    chart = source.copy(deep=True)
    chart.loc[chart.index[-1], "Close"] = 105.0
    mtf = {"주봉": {"snapshot": {"state": "warning", "rsi": 75}, "df": source.tail(1)}}
    args = _snapshot(
        financial={"auto_score": 4, "manual_score": 3, "final_score": 3, "metrics": {"pe": 25}},
        valuation={"ticker": "MSFT", "interpretation": {"headline": "업사이드 제한"}, "inputs": {"forwardPE": 25}},
        entry_plan={"ticker": "MSFT", "status": "분할 진입 가능", "rows": [{"단계": "1차", "가격": "$105"}]},
        signal_evidence={"patterns": [{"name": "triangle", "evidence": [1, 2]}]},
        workflow_display=pd.DataFrame([{"게이트상태": "실행가능"}]),
        multi_timeframe=mtf, ohlcv={"daily_source": source, "display_chart": chart},
        context={"name": "Microsoft", "displayed_price": 105, "manual_price": 105},
    )
    original = deepcopy(args)
    archive = zipfile.ZipFile(io.BytesIO(build_precision_review_export_zip(**args)))
    data = json.loads(archive.read("snapshot.json"))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest == data["manifest"]
    assert manifest["version"] == EXPORT_VERSION
    assert manifest["captured_at"] == CAPTURED.isoformat()
    assert manifest["scope"] == REVIEW_NOTICE
    assert manifest["selected_ticker"] == manifest["result_ticker"] == "MSFT"
    assert not manifest["recalculated_for_export"] and not manifest["fetched_for_export"]
    assert set(manifest["files"]) == set(archive.namelist())
    assert {"_manifest.csv", "candidate_grade.csv", "main_decision.csv",
            "execution_workflow.csv", "final_check.csv", "entry_plan.csv",
            "financial_inputs.csv", "valuation.csv", "multi_timeframe.csv",
            "signal_evidence.csv", "conflict_flags.csv"} <= set(archive.namelist())
    sections = data["sections"]
    assert sections["main_decision"]["decision_code"] == "DISPLAYED_CODE"
    assert sections["candidate_grade"]["grade"] == "S급"
    assert sections["final_check"] == args["final_check"]
    assert sections["entry_plan"] == args["entry_plan"]
    assert sections["valuation"] == args["valuation"]
    assert sections["financial_inputs"]["manual_score"] == 3
    assert sections["multi_timeframe"]["주봉"]["snapshot"]["rsi"] == 75
    history = manifest["ohlcv"]
    assert _csv(archive, history["daily_source"]["file"])[-1]["Close"] == "102.0"
    assert _csv(archive, history["display_chart"]["file"])[-1]["Close"] == "105.0"
    assert "2026-10-20" in _csv(archive, history["daily_source"]["file"])[-1]["_row_index"]
    assert history["timeframe_주봉"]["rows"] == 1
    assert all(row["scope"] == REVIEW_NOTICE for row in _csv(archive, "conflict_flags.csv"))
    assert "execution_gate_vs_final_check" in {flag["code"] for flag in data["conflict_flags"]}
    assert args["decision"] == original["decision"]
    assert args["final_check"] == original["final_check"]
    pd.testing.assert_frame_equal(source, original["ohlcv"]["daily_source"])
    pd.testing.assert_frame_equal(chart, original["ohlcv"]["display_chart"])


@pytest.mark.parametrize("overrides", [
    {"selected_ticker": "AAPL"},
    {"result_ticker": "AAPL"},
    {"selected_ticker": ""},
    {"result_ticker": None},
    {"selected_ticker": "private@example.com", "result_ticker": "private@example.com"},
    {"decision": {"ticker": "AAPL"}},
    {"decision": {"ticker": 5930}},
    {"decision": {"live_quote": {"ticker": "AAPL"}}},
    {"decision": {"execution_workflow": {"티커": "AAPL"}}},
    {"workflow_display": pd.DataFrame([{"ticker": "AAPL"}])},
    {"financial": {"ticker": "AAPL"}},
    {"final_check": {"ticker": "AAPL"}},
    {"entry_plan": {"ticker": "AAPL"}},
    {"hold_or_cut": {"ticker": "AAPL"}},
    {"valuation": {"ticker": "AAPL"}},
    {"valuation": {"financial_inputs": {"ticker": "AAPL"}}},
    {"multi_timeframe": {"일봉": {"snapshot": {"ticker": "AAPL"}}}},
    {"ohlcv": {"daily": pd.DataFrame({"ticker": ["MSFT", "AAPL"], "Close": [1, 2]})}},
    {"ohlcv": {"daily": pd.DataFrame([["MSFT", "AAPL", 1]], columns=["ticker", "ticker", "Close"])}},
    {"ohlcv": {"daily": pd.DataFrame([[1]], columns=pd.MultiIndex.from_tuples([("Close", "AAPL")]))}},
    {"selected_ticker": "005930.KS", "result_ticker": "005930.KQ"},
])
def test_mismatched_or_missing_tickers_are_rejected(overrides):
    with pytest.raises(ValueError, match="ticker"):
        build_precision_review_export_zip(**_snapshot(**overrides))


def test_frame_attributes_also_prevent_stale_ticker_export():
    frame = pd.DataFrame({"Close": [1]})
    frame.attrs["ticker"] = "AAPL"
    with pytest.raises(ValueError, match="ticker"):
        _read(ohlcv={"daily": frame})
    frame.attrs = {"ticker": "MSFT", "live_quote": {"ticker": "AAPL"}}
    with pytest.raises(ValueError, match="ticker"):
        _read(ohlcv={"daily": frame})


def test_case_and_whitespace_are_normalized_but_listing_is_preserved():
    _, data = _read(selected_ticker=" msft ", result_ticker="MsFt")
    assert data["manifest"]["selected_ticker"] == "MSFT"
    _, kr = _read(selected_ticker="005930.KS", result_ticker="005930.ks", decision={}, final_check=None)
    assert kr["manifest"]["result_ticker"] == "005930.KS"


def test_missing_nested_nan_and_mixed_values_are_safe():
    cycle = {}
    cycle["cycle"] = cycle
    _, data = _read(
        decision={"grade": None, "nested": [np.nan, np.inf, -np.inf, pd.NA, pd.NaT,
                                          np.int64(4), np.bool_(True), Decimal("2.5")],
                  "frame": pd.DataFrame({"mixed": [None, {"k": [1, np.nan]}]}),
                  "cycle": cycle, "opaque": object()},
        financial={"metrics": {"array": np.array([1.0, np.nan]), "scalar": np.array(3)}, "notes": [None, "saved"]},
        final_check=pd.NA, valuation=None, entry_plan=None,
        multi_timeframe={"일봉": pd.NA, "주봉": {"snapshot": None, "df": pd.DataFrame()}},
        ohlcv={"missing": None},
    )
    decision = data["sections"]["main_decision"]
    assert decision["nested"] == [None, None, None, None, None, 4, True, 2.5]
    assert decision["opaque"] is None
    assert decision["cycle"]["cycle"] is None
    assert decision["frame"]["rows"][1] == [{"k": [1, None]}]
    assert data["sections"]["financial_inputs"]["metrics"]["array"] == [1.0, None]
    assert data["sections"]["financial_inputs"]["metrics"]["scalar"] == 3
    assert {"final_check", "entry_plan", "valuation"} <= set(data["manifest"]["missing_sections"])
    assert data["conflict_flags"] == []


@pytest.mark.parametrize("value", ["=1+1", "+SUM(1,2)", "-2+3", "@SUM(A1)", " \t=1", "\ttext", "\rtext", "\ntext"])
def test_csv_formula_strings_are_escaped_while_json_keeps_original_text(value):
    archive, data = _read(decision={"dec": value, "=-field": value, "negative_number": -2.5})
    rows = _csv(archive, "main_decision.csv")
    assert next(row["value"] for row in rows if row["field"] == "dec") == "'" + value
    assert next(row["value"] for row in rows if row["field"] == "negative_number") == "-2.5"
    assert any(row["field"] == "'=-field" for row in rows)
    assert data["sections"]["main_decision"]["dec"] == value


def test_ohlcv_strings_and_indexes_are_also_formula_safe():
    archive, data = _read(ohlcv={"daily": pd.DataFrame({"Close": ["=1+1"]}, index=["@row"])})
    row = _csv(archive, data["manifest"]["ohlcv"]["daily"]["file"])[0]
    assert row["Close"] == "'=1+1"
    assert row["_row_index"] == "'@row"


def test_credentials_accounts_and_session_state_are_excluded_recursively():
    archive, data = _read(
        decision={
            "dec": "대기", "api_key": "PRIVATE_KEY_VALUE", "owner_email": "private@example.com",
            "session_state": {"anything": "ENTIRE_STATE"},
            "user_name": "PRIVATE_NAME", "user": {"id": "PRIVATE_USER"},
            "nested": {"account_id": "PRIVATE_ACCOUNT", "safe": "public",
                       "json": '{"password": "PRIVATE_PASSWORD", "roe": 5}'},
            "source_url": "https://user:PRIVATE_AUTH@example.org/path?key=PRIVATE_QUERY#PRIVATE_FRAGMENT",
        },
        financial={"owner_email": "private@example.com", "notes": {"messages": ["private@example.com"], "access_token": "PRIVATE_TOKEN"}},
        context={"name": "Microsoft", "account_id": "PRIVATE_ACCOUNT", "holdings": ["PRIVATE_HOLDINGS"]},
        ohlcv={"daily": pd.DataFrame({"Close": [100], "account": ["PRIVATE_FRAME"]})},
    )
    all_text = "\n".join(archive.read(name).decode("utf-8-sig") for name in archive.namelist())
    for forbidden in ("PRIVATE_", "ENTIRE_STATE", "private@example.com"):
        assert forbidden not in all_text
    assert data["sections"]["main_decision"]["nested"]["json"] == {"roe": 5}
    assert data["sections"]["main_decision"]["source_url"] == "https://example.org/path"
    assert data["sections"]["context"] == {"name": "Microsoft"}


def test_candidate_quality_is_not_exported_as_execution_permission():
    archive, data = _read(
        decision={"grade": "S급", "dec": "눌림 대기", "execution_workflow": {"게이트상태": "대기/관찰"}},
        final_check={"summary": {"final_label": "대기"}},
    )
    flags = {flag["code"]: flag for flag in data["conflict_flags"]}
    assert "candidate_quality_vs_gate" in flags
    assert "intentional" in flags["candidate_quality_vs_gate"]["note"]
    assert "execution_gate_vs_final_check" not in flags
    assert _csv(archive, "conflict_flags.csv")


def test_matching_labels_have_no_conflict_and_reverse_conflicts_are_preserved():
    _, aligned = _read(
        decision={"dec": "분할 가능", "execution_workflow": {"게이트상태": "실행가능"}},
        final_check={"summary": {"final_label": "분할 가능"}},
    )
    assert aligned["conflict_flags"] == []
    _, reverse = _read(
        decision={"dec": "대기", "execution_workflow": {"게이트상태": "대기/관찰"}},
        final_check={"summary": {"final_label": "분할 가능"}},
    )
    assert {"main_decision_vs_final_check", "execution_gate_vs_final_check"} <= {
        flag["code"] for flag in reverse["conflict_flags"]
    }


def test_build_provenance_includes_hashes_but_never_local_user_paths():
    archive, data = _read(source_build={
        "base_commit": "abc123", "loaded_source_sha256": "loaded-hash",
        "entrypoint": "C:/Users/PRIVATE_USER/app.py", "renderer_path": "PRIVATE_PATH",
        "restart_required": True, "stale_modules": ["stock_lab.app_entry"],
        "sources": {"stock_lab.app_entry": {
            "sha256": "old-hash", "disk_sha256": "new-hash", "path": "PRIVATE_PATH",
        }},
    })
    build = data["manifest"]["source_build"]
    assert build["base_commit"] == "abc123" and build["restart_required"]
    assert build["sources"]["stock_lab.app_entry"] == {"sha256": "old-hash", "disk_sha256": "new-hash"}
    assert "PRIVATE_" not in "\n".join(archive.read(name).decode("utf-8-sig") for name in archive.namelist())


def test_empty_export_and_empty_flags_still_have_manifest_and_csv_headers():
    archive, data = _read(decision=None, final_check=None)
    assert data["conflict_flags"] == []
    assert archive.read("conflict_flags.csv").decode("utf-8-sig").startswith("code,left,right,note,scope")
    assert _csv(archive, "_manifest.csv")
    with pytest.raises(ValueError, match="timezone"):
        _read(captured_at=datetime(2026, 10, 20))


class _UI:
    def __init__(self):
        self.session_state = {}
        self.captions = []
        self.downloads = []
        self.warnings = []
        self.frames = []
        self.markdowns = []

    def download_button(self, label, **kwargs):
        self.downloads.append((label, kwargs))

    def warning(self, text):
        self.warnings.append(text)

    def dataframe(self, frame, **kwargs):
        self.frames.append(frame.copy())

    def markdown(self, value, **kwargs):
        self.markdowns.append(value)

    def columns(self, count):
        return [self] * count

    def metric(self, *args):
        pass

    def info(self, *args):
        pass

    def caption(self, text):
        self.captions.append(text)

    def empty(self):
        return self

    def container(self):
        return self

    def expander(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_download_is_eager_snapshot_bytes_and_does_not_rerun():
    ui = _UI()
    render_precision_review_download(ui, **_snapshot())
    assert len(ui.downloads) == 1 and not ui.warnings
    _, kwargs = ui.downloads[0]
    assert kwargs["on_click"] == "ignore"
    assert kwargs["mime"] == "application/zip"
    assert kwargs["file_name"] == "precision_review_MSFT.zip"
    assert isinstance(kwargs["data"], bytes)
    assert "매매 판단은 변경하지 않습니다" in kwargs["help"]
    render_precision_review_download(ui, **_snapshot(selected_ticker="AAPL"))
    assert len(ui.downloads) == 1 and len(ui.warnings) == 1
    assert "선택 종목" in ui.warnings[0]


def _download_snapshot(ui):
    with zipfile.ZipFile(io.BytesIO(ui.downloads[-1][1]["data"])) as archive:
        return json.loads(archive.read("snapshot.json"))


def _complete_snapshot(**overrides):
    frame = pd.DataFrame({"Close": [105]}, index=pd.to_datetime(["2026-10-19"]))
    return _snapshot(
        financial={"final_score": 4}, valuation={"ticker": "MSFT", "status": "displayed"},
        entry_plan={"ticker": "MSFT", "status": "분할 진입 가능"},
        hold_or_cut={"ticker": "MSFT", "displayed": False},
        multi_timeframe={"일봉": {"snapshot": {"state": "displayed"}}},
        signal_evidence={"pattern_timing": "displayed"}, context={"name": "Microsoft"},
        ohlcv={"daily_source": frame}, **overrides,
    )


def test_top_download_is_immediately_available_then_captures_each_local_checkpoint():
    ui = _UI()
    download = PrecisionReviewDownload(ui, selected_ticker="MSFT", owner="owner-a")
    initial = _download_snapshot(ui)
    assert initial["manifest"]["selected_ticker"] == "MSFT"
    assert initial["manifest"]["completion"] == "partial"
    assert initial["manifest"]["asof"] is None
    assert "final_check" in initial["manifest"]["missing_sections"]
    assert "기준일 미확인" in ui.captions[-1] and "부분 결과" in ui.captions[-1]
    download.update(**_complete_snapshot(), completion="partial", stage="daily_decision")
    partial = _download_snapshot(ui)
    assert partial["manifest"]["completion"] == "partial"
    assert partial["manifest"]["stage"] == "daily_decision"
    assert partial["manifest"]["asof"] == "2026-10-19T00:00:00"
    assert partial["manifest"]["captured_at"] == CAPTURED.isoformat()
    before_complete = datetime.now(timezone.utc)
    download.update(completion="complete", stage="panels")
    after_complete = datetime.now(timezone.utc)
    complete = _download_snapshot(ui)
    assert complete["manifest"]["completion"] == "complete"
    assert complete["sections"]["main_decision"] == partial["sections"]["main_decision"]
    assert complete["sections"]["final_check"] == partial["sections"]["final_check"]
    assert before_complete <= datetime.fromisoformat(complete["manifest"]["captured_at"]) <= after_complete
    assert complete["manifest"]["stage"] == "panels"
    assert "완료 결과" in ui.captions[-1] and "2026-10-19" in ui.captions[-1]
    assert complete["manifest"]["captured_at"] in ui.captions[-1]
    keys = [kwargs["key"] for _, kwargs in ui.downloads]
    assert len(keys) == len(set(keys))
    assert all(kwargs["on_click"] == "ignore" for _, kwargs in ui.downloads)
    assert "owner-a" not in json.dumps(complete)


@pytest.mark.parametrize("missing", ["decision", "final_check", "entry_plan", "valuation", "multi_timeframe", "ohlcv"])
def test_incomplete_sections_cannot_be_labelled_complete(missing):
    args = _complete_snapshot()
    args[missing] = None
    with zipfile.ZipFile(io.BytesIO(build_precision_review_export_zip(**args, completion="complete"))) as archive:
        assert json.loads(archive.read("manifest.json"))["completion"] == "partial"


def test_saved_download_reappears_before_any_rebuild_and_retains_its_asof(monkeypatch):
    ui = _UI()
    download = PrecisionReviewDownload(ui, selected_ticker="MSFT", owner="Owner-A")
    download.update(**_complete_snapshot(), completion="complete")
    saved = ui.downloads[-1][1]["data"]

    def unexpected_build(**kwargs):
        raise AssertionError("Cached download must not rebuild or fetch")

    monkeypatch.setattr("stock_lab_core.precision_review_export.build_precision_review_export_zip", unexpected_build)
    PrecisionReviewDownload(ui, selected_ticker=" msft ", owner="owner-a")
    assert ui.downloads[-1][1]["data"] == saved
    assert "이전 저장 결과" in ui.captions[-1] and "완료 결과" in ui.captions[-1]
    assert "2026-10-19" in ui.captions[-1]


@pytest.mark.parametrize("ticker,owner", [("AAPL", "owner-a"), ("MSFT", "owner-b"), ("MSFT", ""), ("MSFT", None)])
def test_other_ticker_or_owner_never_reuses_a_saved_download(ticker, owner):
    ui = _UI()
    download = PrecisionReviewDownload(ui, selected_ticker="MSFT", owner="owner-a")
    download.update(**_complete_snapshot(), completion="complete")
    saved = ui.downloads[-1][1]["data"]
    PrecisionReviewDownload(ui, selected_ticker=ticker, owner=owner)
    current = _download_snapshot(ui)
    assert ui.downloads[-1][1]["data"] != saved
    assert current["manifest"]["selected_ticker"] == ticker
    assert current["manifest"]["completion"] == "partial"
    assert current["sections"]["main_decision"] == {}
    assert current["sections"]["final_check"] is None
    assert "이전 저장 결과" not in ui.captions[-1]
    if not owner:
        assert not ui.session_state


def test_listing_switch_and_failed_checkpoint_discard_stale_results():
    ui = _UI()
    PrecisionReviewDownload(ui, selected_ticker="005930.KS", owner="owner-a")
    download = PrecisionReviewDownload(ui, selected_ticker="005930.KQ", owner="owner-a")
    assert _download_snapshot(ui)["manifest"]["selected_ticker"] == "005930.KQ"
    assert "이전 저장 결과" not in ui.captions[-1]
    count = len(ui.downloads)
    download.update(decision={"ticker": "005930.KS"})
    assert len(ui.downloads) == count and ui.warnings
    assert not ui.session_state


@pytest.mark.parametrize("index,expected", [
    (pd.to_datetime(["2026-10-19"]), "2026-10-19T00:00:00"),
    (["2026-10-19"], "2026-10-19T00:00:00"),
    ([0], None), (["not a date"], None),
])
def test_asof_is_the_market_history_date_never_the_capture_date_or_numeric_index(index, expected):
    _, data = _read(ohlcv={"daily_source": pd.DataFrame({"Close": [1]}, index=index)})
    assert data["manifest"]["asof"] == expected


def test_streamlit_replaces_the_top_download_without_duplicate_widgets_on_rerun():
    from streamlit.testing.v1 import AppTest

    script = """
import io
import json
import zipfile
import pandas as pd
import streamlit as st
from stock_lab_core.precision_review_export import PrecisionReviewDownload

def saved_manifest():
    data = st.session_state["_precision_review_export_ready"]["data"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read("manifest.json"))

download = PrecisionReviewDownload(st, selected_ticker="MSFT", owner="owner-a")
st.session_state["initial_manifest"] = saved_manifest()
if st.session_state.get("reuse_only", False):
    st.stop()
download.update(financial={"ticker": "MSFT", "final_score": 4}, stage="financial")
download.update(
    decision={"ticker": "MSFT", "dec": "displayed", "execution_workflow": {"티커": "MSFT"}},
    stage="daily_decision", completion="partial",
    ohlcv={"daily_source": pd.DataFrame({"Close": [100]}, index=pd.to_datetime(["2026-10-19"]))},
)
st.session_state["partial_manifest"] = saved_manifest()
if st.session_state.get("finish", False):
    download.update(
        final_check={"ticker": "MSFT", "summary": {"final_label": "displayed"}},
        entry_plan={"ticker": "MSFT", "status": "displayed"},
        valuation={"ticker": "MSFT", "status": "displayed"},
        hold_or_cut={"ticker": "MSFT", "displayed": False},
        multi_timeframe={"day": {"snapshot": {"state": "displayed"}}},
        signal_evidence={"pattern_timing": "displayed"}, context={"name": "Microsoft"},
        completion="complete", stage="panels",
    )
st.session_state["final_manifest"] = saved_manifest()
"""
    app = AppTest.from_string(script).run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    assert "부분 결과" in app.caption[0].value
    previous_partial = dict(app.session_state["final_manifest"])
    app.session_state["reuse_only"] = True
    app.run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    assert "이전 저장 결과" in app.caption[0].value and "부분 결과" in app.caption[0].value
    assert previous_partial["captured_at"] in app.caption[0].value
    app.session_state["reuse_only"] = False
    app.session_state["finish"] = True
    app.run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    assert app.session_state["initial_manifest"] == previous_partial
    complete = app.session_state["final_manifest"]
    assert complete["completion"] == "complete" and complete["stage"] == "panels"
    assert complete["captured_at"] > app.session_state["partial_manifest"]["captured_at"]
    assert "2026-10-19" in app.caption[0].value and "완료 결과" in app.caption[0].value
    assert complete["captured_at"] in app.caption[0].value
    assert "이전 저장 결과" not in app.caption[0].value
    app.session_state["reuse_only"] = True
    app.run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    assert app.session_state["initial_manifest"] == complete
    assert "이전 저장 결과" in app.caption[0].value and "완료 결과" in app.caption[0].value
    assert complete["captured_at"] in app.caption[0].value


def _precision_download_startup():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))
    precision = next(node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "main_page == 'precision'")
    start = next(i for i, node in enumerate(precision.body) if isinstance(node, ast.ImportFrom) and any(
        alias.name == "precision_review_export" for alias in node.names
    ))
    end = next(i for i, node in enumerate(precision.body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
               and isinstance(node.value.func, ast.Name) and node.value.func.id == "render_data_basis_caption")
    return ast.Module(body=precision.body[start:end], type_ignores=[])


def test_new_app_uses_legacy_renderer_once_when_cached_module_lacks_checkpoint_class(monkeypatch):
    import stock_lab_core.precision_review_export as export_module

    monkeypatch.delattr(export_module, "PrecisionReviewDownload")
    calls = []

    def legacy_render(st, *, selected_ticker, result_ticker, decision=None, workflow_display=None,
                      final_check=None, valuation=None, financial=None, entry_plan=None,
                      signal_evidence=None, multi_timeframe=None, ohlcv=None, context=None,
                      hold_or_cut=None, source_build=None, captured_at=None, source="precision"):
        calls.append((selected_ticker, result_ticker, captured_at))

    namespace = {"st": _UI(), "render_precision_review_download": legacy_render}
    exec(compile(_precision_download_startup(), str(APP_PATH), "exec"), namespace)
    download = namespace["precision_review_download"]
    download.update(financial={"ticker": "MSFT"}, completion="partial", stage="financial")
    download.update(**_complete_snapshot(), completion="partial", stage="workflow")
    assert not calls
    download.update(**_complete_snapshot(), completion="complete", stage="panels")
    assert calls == [("MSFT", "MSFT", CAPTURED)]
    # Compile the entire entry point without running UI, auth, or DB initialization.
    compile(APP_PATH.read_text(encoding="utf-8-sig"), str(APP_PATH), "exec")


def test_streamlit_new_branch_runs_with_cached_module_missing_new_export(monkeypatch):
    import stock_lab_core.precision_review_export as export_module
    from streamlit.testing.v1 import AppTest

    monkeypatch.delattr(export_module, "PrecisionReviewDownload")
    script = """
import streamlit as st
from stock_lab_core.precision_review_export import render_precision_review_download
""" + ast.unparse(_precision_download_startup()) + """
precision_review_download.update(financial={"ticker": "MSFT"}, completion="partial", stage="financial")
precision_review_download.update(
    selected_ticker="MSFT", result_ticker="MSFT", decision={"ticker": "MSFT", "dec": "displayed"},
    completion="complete", stage="panels",
)
"""
    app = AppTest.from_string(script).run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1
    app.run(timeout=15)
    assert not app.exception
    assert len(app.get("download_button")) == 1


def _load_render_function(name, namespace):
    """Execute only the render function, never app authentication/network setup."""
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(APP_PATH), "exec"), namespace)
    return namespace[name]


def test_final_check_return_is_the_exact_rendered_result_and_builder_runs_once():
    ui = _UI()
    calls = []
    rows = [{"점검항목": "시스템 타점", "상태": "주의", "해석": "original"}]
    summary = {"final_label": "대기", "action": "same displayed action", "final_color": "#000",
               "pass_count": 0, "caution_count": 1, "block_count": 0}

    def build(*args, **kwargs):
        calls.append(args)
        return rows, summary

    render = _load_render_function("render_pre_buy_final_check_panel", {
        "st": ui, "pd": pd, "build_pre_buy_final_checks": build, "escape_html_value": str,
    })
    captured = render("Test", "MSFT", False, {}, 4, False, 0)
    assert len(calls) == 1
    assert captured["rows"] is rows and captured["summary"] is summary
    assert ui.frames[0].to_dict("records") == rows
    render_precision_review_download(ui, **_snapshot(final_check=captured))
    assert len(calls) == 1


def test_entry_plan_return_matches_rendered_rows_without_rebuilding():
    ui = _UI()
    render = _load_render_function("render_entry_execution_plan", {
        "st": ui, "pd": pd, "np": np, "clean_float": lambda value, default=0: float(value) if value is not None else default,
        "finite_num": np.isfinite, "format_currency": lambda value, ticker: f"${value:.2f}",
        "escape_html_value": str, "is_kr_listed": lambda ticker: False,
        "build_leveraged_precision_state": lambda *args: {},
        "is_leveraged_or_inverse_product": lambda *args: False,
        "align_precision_entry_plan_rows": align_precision_entry_plan_rows,
        "build_decision_workflow": build_decision_workflow,
        "format_precision_take_profit_condition": format_precision_take_profit_condition,
        "GATE_EXECUTABLE": GATE_EXECUTABLE,
    })
    decision = {
        "cur_p": 100, "rr_stop": 90, "rr_target": 120, "atr": 5, "buy_amt": 100000,
        "target_w": 5, "current_w": 0, "ma5": 98, "ma20": 95,
    }
    before = deepcopy(decision)
    captured = render("Test", "MSFT", decision)
    assert captured["status"] == "분할 진입 가능"
    assert captured["rows"] == ui.frames[0].to_dict("records")
    assert captured["status"] in ui.markdowns[0]
    assert decision == before
    missing = render("Test", "MSFT", {"buy_amt": 1})
    assert missing["status"] == "unavailable"


def test_valuation_return_reuses_the_displayed_inputs_and_interpretation():
    ui = _UI()
    calls = []
    inputs = {"forwardPE": 20}
    financial = {"final_score": 4}
    interpretation = {
        "headline": "중립", "target_upside": 5, "forward_pe": 20, "trailing_pe": 21,
        "ps": 3, "note": "displayed", "color": "#000",
        "rows": [{"항목": "PER", "값": "20.0x", "판정": "적정"}],
        "valuation_data_count": 2,
    }
    original_rows = deepcopy(interpretation["rows"])

    def fetch(ticker):
        calls.append(ticker)
        return {"ok": True, "data": inputs, "sources": ["cached"]}

    render = _load_render_function("render_valuation_price_panel", {
        "st": ui, "pd": pd, "np": np, "fetch_valuation_snapshot": fetch,
        "get_analyst_snapshot": lambda ticker: {"ok": False},
        "_valuation_missing": lambda value: value is None,
        "ensure_fin_meta_for_valuation": lambda *args: financial,
        "clean_float": lambda value, default: value, "build_valuation_interpretation": lambda *args, **kwargs: interpretation,
        "format_backtest_percent": str, "fmt_multiple": str, "finite_num": np.isfinite,
        "escape_html_value": str,
    })
    captured = render("Test", "MSFT", False, {"cur_p": 100}, 4)
    assert captured["inputs"] is inputs
    assert captured["interpretation"] is interpretation
    assert captured["financial_inputs"] is financial
    assert len(ui.frames) == 1
    displayed, = ui.frames[0].to_dict("records")
    assert displayed["항목"] == "선행 PER(예상 이익)"
    assert {key: displayed[key] for key in ("값", "판정")} == {
        key: original_rows[0][key] for key in ("값", "판정")
    }
    assert interpretation["rows"] == original_rows
    render_precision_review_download(ui, **_snapshot(valuation=captured))
    assert calls == ["MSFT"]
    assert render("Test", "MSFT", True, {}, 0)["status"] == "ETF 별도판단"


@pytest.mark.parametrize("held,leveraged", [(False, False), (True, False), (True, True)])
def test_hold_or_cut_captures_each_rendered_path_without_recalculation(held, leveraged):
    ui = _UI()
    ui.session_state = {"_app_final_macro_risk": 0}
    calls = []
    leveraged_state = {"dca_stage": "조건부 DCA 대기", "dca_note": "original leveraged note"}

    def build(*args):
        calls.append(args)
        return leveraged_state if leveraged else {}

    render = _load_render_function("render_hold_or_cut_panel", {
        "st": ui, "clean_float": lambda value, default: default if value is None else float(value),
        "finite_num": np.isfinite, "escape_html_value": str,
        "build_leveraged_precision_state": build,
        "detect_fin_trend_direction": lambda meta: {"score": 0, "label": "stable", "has_data": False},
    })
    captured = render("Test", "MSFT", False, 4, {}, {
        "cur_p": 120, "dd": -0.05, "trend": "정배열", "rs_label": "🚀강함",
    }, 100, held)
    assert captured["displayed"] is held
    if not held:
        assert not calls and not ui.markdowns
    elif leveraged:
        assert captured["leveraged_state"] is leveraged_state
        assert captured["action"] in "\n".join(ui.markdowns)
    else:
        assert captured["decision"] in "\n".join(ui.markdowns)
        assert captured["action"] in "\n".join(ui.markdowns)
        assert captured["hold_reasons"]
    archive, data = _read(hold_or_cut=captured)
    assert data["sections"]["hold_or_cut"] == captured
    assert "hold_or_cut.csv" in archive.namelist()
    assert len(calls) == int(held)
    if held and not leveraged:
        assert "holding_addition_vs_final_check" in {flag["code"] for flag in data["conflict_flags"]}


def test_real_and_demo_call_sites_use_finished_local_results_not_download_calculations():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))
    precision_branch = next(node for node in tree.body if isinstance(node, ast.If) and ast.unparse(node.test) == "main_page == 'precision'")
    updates = [
        node for node in ast.walk(precision_branch) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and ast.unparse(node.func) == "precision_review_download.update"
    ]
    real = next(node for node in updates if any(
        kw.arg == "completion" and isinstance(kw.value, ast.Constant) and kw.value.value == "complete"
        for kw in node.keywords
    ))
    render_calls = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "render_precision_review_download"
    ]
    compat_class = next(node for node in ast.walk(precision_branch) if isinstance(node, ast.ClassDef)
                        and node.name == "_PrecisionReviewDownloadCompat")
    compat_calls = [node for node in ast.walk(compat_class) if node in render_calls]
    assert len(compat_calls) == 1
    compat_call = compat_calls[0]
    assert [ast.unparse(arg) for arg in compat_call.args] == ["st"]
    assert len(compat_call.keywords) == 1
    assert compat_call.keywords[0].arg is None
    assert ast.unparse(compat_call.keywords[0].value) == "snapshot"
    compat_update = next(node for node in compat_class.body if isinstance(node, ast.FunctionDef) and node.name == "update")
    assert [arg.arg for arg in compat_update.args.kwonlyargs] == ["completion", "stage"]
    assert ast.unparse(compat_update.body[0].test) == "completion == 'complete'"
    # Every renderer call is accounted for, including the legacy adapter.
    standard_calls = [node for node in render_calls if node not in compat_calls]
    assert len(standard_calls) == 1
    exports = standard_calls + [real]
    assert len(exports) == 2
    for call in exports:
        # Only source hashing may run here, never market calculations or data fetching.
        assert not any(
            isinstance(node, (ast.Call, ast.Attribute, ast.Subscript))
            for keyword in call.keywords if keyword.arg != "source_build"
            for node in ast.walk(keyword.value)
        )
        kwargs = {keyword.arg: keyword.value for keyword in call.keywords}
        assert kwargs["source_build"].func.id == "get_report_build_info"
        assert kwargs["decision"].id == "c"
        assert kwargs["selected_ticker"].id == kwargs["result_ticker"].id == "tkr"
        assert kwargs["final_check"].id == "precision_final_check"
        prior_check = [
            node for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "render_pre_buy_final_check_panel" and node.lineno < call.lineno
        ]
        assert prior_check
    kwargs = {keyword.arg: keyword.value for keyword in real.keywords}
    assert kwargs["entry_plan"].id == "precision_entry_plan"
    assert kwargs["valuation"].id == "precision_valuation"
    assert kwargs["workflow_display"].id == "precision_workflow_display"
    assert kwargs["hold_or_cut"].id == "precision_hold_or_cut"
    success_branch = next(node for node in precision_branch.body if isinstance(node, ast.If) and ast.unparse(node.test) == "not df.empty")
    startup = next(node for node in ast.walk(precision_branch) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_precision_review_download_type")
    assert not any(
        isinstance(node, ast.ImportFrom) and any(alias.name == "PrecisionReviewDownload" for alias in node.names)
        for node in ast.walk(precision_branch)
    )
    calls_by_name = {
        node.func.id: node for node in ast.walk(precision_branch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert startup.lineno < calls_by_name["render_data_basis_caption"].lineno
    assert startup.lineno < calls_by_name["load_fin_score_meta_fast"].lineno
    stages = {next(kw.value.value for kw in node.keywords if kw.arg == "stage"): node for node in updates}
    assert stages["financial"].lineno < calls_by_name["load_precision_price_history"].lineno
    assert stages["daily_decision"].lineno < calls_by_name["build_precision_multi_timeframe_pack"].lineno
    assert stages["workflow"].lineno < calls_by_name["render_peer_comparison_panel"].lineno
    assert stages["workflow"].lineno < calls_by_name["render_personal_stock_analysis_panel"].lineno
    assert stages["workflow"].lineno < calls_by_name["render_valuation_price_panel"].lineno

    def unconditional_assignments(body):
        for node in body:
            if isinstance(node, ast.Assign) and node.lineno < real.lineno:
                for target in node.targets:
                    yield from (part.id for part in ast.walk(target) if isinstance(part, ast.Name))
            if isinstance(node, ast.With):
                yield from unconditional_assignments(node.body)
            if isinstance(node, ast.If):
                yield from set(unconditional_assignments(node.body)).intersection(unconditional_assignments(node.orelse))

    assigned = set(unconditional_assignments(precision_branch.body)) | set(unconditional_assignments(success_branch.body))
    required = {node.id for node in ast.walk(real) if isinstance(node, ast.Name) and node.id.startswith("precision_")}
    assert required | {"price_source", "price_refresh_time", "auto_cur_p", "manual_cur_p", "display_cur_p"} <= assigned
    hold_calls = [node for node in ast.walk(success_branch) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "render_hold_or_cut_panel"]
    assert len(hold_calls) == 1 and hold_calls[0].lineno < real.lineno
    # Exercise the exact real-screen export call with offline render-local data.
    namespace = {node.id: None for node in ast.walk(real) if isinstance(node, ast.Name)}
    ui = _UI()
    download = PrecisionReviewDownload(ui, selected_ticker="MSFT", owner="owner-a")
    ui.downloads.clear()
    sample = _complete_snapshot()
    namespace.update({
        "precision_review_download": download,
        "st": ui, "tkr": "MSFT", "c": sample["decision"],
        "precision_final_check": sample["final_check"], "fin_meta": {"final_score": 4},
        "precision_entry_plan": sample["entry_plan"], "precision_valuation": sample["valuation"],
        "precision_hold_or_cut": sample["hold_or_cut"],
        "df": sample["ohlcv"]["daily_source"], "chart_df": sample["ohlcv"]["daily_source"],
        "mtf_pack": sample["multi_timeframe"], "name": "Microsoft",
        "get_report_build_info": lambda path: {"base_commit": "test"}, "__file__": str(APP_PATH),
    })
    before_complete = datetime.now(timezone.utc)
    eval(compile(ast.Expression(body=real), str(APP_PATH), "eval"), namespace)
    after_complete = datetime.now(timezone.utc)
    assert len(ui.downloads) == 1 and not ui.warnings
    archive = zipfile.ZipFile(io.BytesIO(ui.downloads[0][1]["data"]))
    captured = json.loads(archive.read("snapshot.json"))
    assert captured["sections"]["final_check"] == sample["final_check"]
    assert captured["manifest"]["source"] == "precision"
    assert captured["manifest"]["completion"] == "complete"
    assert captured["manifest"]["stage"] == "panels"
    assert before_complete <= datetime.fromisoformat(captured["manifest"]["captured_at"]) <= after_complete
