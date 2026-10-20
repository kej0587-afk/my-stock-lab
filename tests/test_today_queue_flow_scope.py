"""Run the real queue calculation branch with no network or account access."""

import ast
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]


class State(dict):
    def __getattr__(self, key):
        return self[key]


def run_branch(*, full=False, fail=False):
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_render_today_queue_tab")
    branch = next(node for node in render.body if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Name) and node.test.id == "run_summary")
    calls, notes = [], []
    base = ({"ticker": "HELD"}, {"ticker": "WATCH"})
    fresh = {"fresh": True}
    summary = pd.DataFrame({"ticker": ["HELD", "WATCH"]})
    state = State(fin_score_map={})

    def refresh(**kwargs):
        calls.append("refresh")
        assert kwargs["include_theme"] and kwargs["force_theme_refresh"]
        kwargs["progress"]("test progress")
        if fail:
            raise RuntimeError("provider unavailable")
        return fresh

    def merge(items, snapshot):
        assert snapshot is fresh
        extra = ({"ticker": "NEW"},)
        return tuple(items) + extra, extra

    def compute(_scores, _mode, items):
        calls.append(tuple(item["ticker"] for item in items))
        return summary.copy()

    env = dict(
        st=SimpleNamespace(
            session_state=state, spinner=lambda *a: nullcontext(), info=notes.append,
            warning=notes.append,
            empty=lambda: SimpleNamespace(caption=notes.append, empty=lambda: None),
        ),
        measure=lambda *a: nullcontext(), logging=logging, pd=pd,
        datetime=datetime, timezone=timezone, timedelta=timedelta,
        run_summary=True, refresh_flow_candidates=full, raw_watch_items=base,
        watch_items=({"ticker": "OLD_AUTO"},), flow_auto_items=({"ticker": "OLD_AUTO"},),
        build_today_queue_items=lambda items: items,
        refresh_today_market_flow_snapshot=refresh,
        build_today_queue_items_with_flow_candidates=merge,
        build_today_queue_signature=lambda items, *a, **k: tuple(item["ticker"] for item in items),
        TODAY_QUEUE_LOGIC_VERSION="test", mode="test",
        clear_latest_price_cache=lambda: None, enable_force_live_price_refresh=lambda: None,
        cache_clear=lambda *a: None, load_price_df=None, load_price_frames_batch=None,
        get_all_summary=compute, summary_key="summary", sig_key="signature", last_key="last",
    )
    exec(compile(ast.Module(body=[branch], type_ignores=[]), str(ROOT / "app.py"), "exec"), env)
    pd.testing.assert_frame_equal(state["summary"], summary)
    return calls, state, notes


def test_default_queue_does_not_wait_for_full_market_discovery():
    calls, state, notes = run_branch()
    assert calls == [("HELD", "WATCH")]
    assert state["signature"] == ("HELD", "WATCH")
    assert any("자동발굴은 이번 계산에서 제외" in note for note in notes)


@pytest.mark.parametrize("fail", [False, True])
def test_optional_discovery_and_failure_never_resign_stale_candidates(fail):
    calls, state, notes = run_branch(full=True, fail=fail)
    expected = ("HELD", "WATCH") if fail else ("HELD", "WATCH", "NEW")
    assert calls == ["refresh", expected]
    assert state["signature"] == expected
    assert any("조회 실패" in note for note in notes) == fail


def test_discovery_checkbox_is_opt_in_and_initial_scope_matches_signature():
    source = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    render = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_render_today_queue_tab")
    checkbox = next(node.value for node in ast.walk(render) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "refresh_flow_candidates"
                            for target in node.targets))
    assert next(k.value.value for k in checkbox.keywords if k.arg == "value") is False
    prepare = next(node for node in render.body if isinstance(node, ast.With))
    assert "today_queue_refresh_flow_candidates" in ast.unparse(prepare)
    assert "build_today_queue_items(raw_watch_items)" in ast.unparse(prepare)
