"""Display routing only: selected report surfaces precede holdings detail."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import report_latest


@pytest.fixture(scope="module")
def app_tree():
    return ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig"))


@pytest.fixture
def surface(app_tree, monkeypatch):
    node = next(n for n in app_tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "_render_briefing_report_surface")
    ui = SimpleNamespace(session_state={"preserve": "value"}, warning=Mock(), info=Mock())
    calls = {key: Mock() for key in ("persist_last_report", "keep_last_complete", "kept_notice", "restored_notice")}
    calls["keep_last_complete"].return_value = None
    calls["restored_notice"].return_value = None
    for key, value in calls.items():
        monkeypatch.setattr(report_latest, key, value)
    env = {"st": ui, "pd": pd, "render_today_action_news_panel": Mock(),
           "render_kiwoom_market_evidence": Mock(), "render_today_market_memo_panel": Mock()}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), env)
    return env["_render_briefing_report_surface"], env, calls


@pytest.mark.parametrize("view", ["보유관리", "시장"])
def test_holdings_and_market_return_to_existing_detail(surface, view):
    render, env, calls = surface
    assert render(view, pd.DataFrame(), "owner", ["ISA"], "store") is False
    for call in calls.values():
        call.assert_not_called()
    for name in ("render_today_action_news_panel", "render_kiwoom_market_evidence", "render_today_market_memo_panel"):
        env[name].assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_report_preserves_frame_owner_scope_and_completed_report_lifecycle(surface, empty):
    render, env, calls = surface
    frame = pd.DataFrame() if empty else pd.DataFrame([{"티커": "SOXL", "판정": "방어우선", "금액": 0}])
    before = frame.copy(deep=True)
    calls["keep_last_complete"].return_value = {"kept": True}
    calls["kept_notice"].return_value = "kept notice"
    calls["restored_notice"].return_value = "restored notice"
    assert render("시황", frame, "owner", ["ISA"], "store") is True
    assert env["render_today_market_memo_panel"].call_args.args[0] is frame
    pd.testing.assert_frame_equal(before, frame)
    assert calls["persist_last_report"].call_count == 2
    for call in calls["persist_last_report"].call_args_list:
        assert call.kwargs == {"owner_scope": "owner", "accounts": ["ISA"], "store": "store"}
    assert env["st"].session_state == {"preserve": "value"}
    assert env["st"].warning.call_count == (2 if empty else 1)
    env["st"].info.assert_called_once_with("restored notice")


@pytest.mark.parametrize("view,callee,arg", [("뉴스", "render_today_action_news_panel", None),
                                             ("키움", "render_kiwoom_market_evidence", "today_kiwoom")])
def test_other_explicit_surfaces_do_not_render_holdings_or_generate_report(surface, view, callee, arg):
    render, env, calls = surface
    frame = pd.DataFrame()
    assert render(view, frame, "owner", [], None) is True
    assert env[callee].call_args.args[0] is frame if arg is None else env[callee].call_args.args == (arg,)
    env["render_today_market_memo_panel"].assert_not_called()
    calls["persist_last_report"].assert_not_called()


def test_navigation_and_report_dispatch_precede_holdings_detail(app_tree):
    panel = next(n for n in app_tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "render_today_unified_briefing_panel")
    assert [ast.unparse(n) for n in panel.decorator_list] == ["timed_call('phase', 'briefing_render')"]
    calls = [n for n in ast.walk(panel) if isinstance(n, ast.Call)]
    def line(name):
        return next(n.lineno for n in calls if
                    (isinstance(n.func, ast.Name) and n.func.id == name) or
                    (isinstance(n.func, ast.Attribute) and n.func.attr == name))
    assert line("restore_last_report") < line("segmented_control") < line("_render_briefing_report_surface")
    assert line("_render_briefing_report_surface") < line("render_history_changes")
    assert line("_render_briefing_report_surface") < line("render_frame_decision_brief")
    selector = next(n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "segmented_control")
    assert {k.arg: ast.unparse(k.value) for k in selector.keywords}["key"] == "VIEW_KEY"
