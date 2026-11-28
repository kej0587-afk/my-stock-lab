"""Shared per-render flags produce the same download; no persistent cache."""
import ast
import io
from pathlib import Path
from unittest.mock import MagicMock
import zipfile

import pandas as pd
import pytest


@pytest.mark.parametrize("kind", ["normal", "duplicate", "changed_input", "empty"])
def test_shared_flags_and_fallback_export_have_identical_csv(app_module, monkeypatch, kind):
    app = app_module
    summary = pd.DataFrame([{"티커": "MSFT", "종목명": "Example", "게이트상태": "방어우선",
                             "게이트근거": "시장방어", "판정분류": "caution", "R/R": .5, "목표비중": 10.}])
    if kind == "duplicate":
        summary = pd.concat([summary, summary], ignore_index=True)
    if kind == "changed_input":
        summary["목표비중"] = 30.
    holdings = pd.DataFrame([{"티커": "MSFT", "자산명": "Example", "목표비중": 10.}])
    flow = pd.DataFrame() if kind == "empty" else pd.DataFrame([{"Ticker": "OTHER", "종목명": "Other"}])
    before = summary.copy(deep=True)
    flags = app.build_today_review_flags_df(summary, holdings, flow)
    ui = MagicMock()
    monkeypatch.setattr(app, "st", ui)
    builder = MagicMock(wraps=app.build_today_review_flags_df)
    monkeypatch.setattr(app, "build_today_review_flags_df", builder)
    archives = []
    for provided in (None, flags):
        app.render_today_review_export_download(summary, flow, holdings, review_flags_df=provided)
        archives.append(zipfile.ZipFile(io.BytesIO(ui.download_button.call_args.kwargs["data"])))
    assert builder.call_count == 1
    assert archives[0].namelist() == archives[1].namelist()
    for name in archives[0].namelist():
        if name != "_manifest.csv":  # export creation timestamp, not calculation input
            assert archives[0].read(name) == archives[1].read(name)
    pd.testing.assert_frame_equal(summary, before)


def test_queue_shares_only_its_local_frames_without_session_storage():
    tree = ast.parse(Path("app.py").read_text(encoding="utf-8-sig"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_render_today_queue_tab")
    produced = next(n for n in node.body if isinstance(n, ast.Assign)
                    and ast.unparse(n.targets[0]) == "briefing_flags")
    assert ast.unparse(produced.value.func) == "render_today_unified_briefing_panel"
    assert ast.unparse(produced.value.args[0]) == "summary_df"
    assert next(ast.unparse(k.value) for k in produced.value.keywords if k.arg == "flow_shortlist_df") == "flow_shortlist_df"
    detail = next(n for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == "render_today_queue_details")
    export = next(k.value for k in detail.keywords if k.arg == "render_today_review_export_download")
    assert ast.unparse(export) == "partial(render_today_review_export_download, review_flags_df=briefing_flags) if isinstance(briefing_flags, pd.DataFrame) else render_today_review_export_download"
    uses = [n for n in ast.walk(node) if isinstance(n, ast.Name) and n.id == "briefing_flags"]
    assert len(uses) == 3  # local assignment, type check and partial only
