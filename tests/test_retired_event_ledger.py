"""Retiring an optional UI must not alter gates or delete stored trades."""

import ast
from datetime import datetime
from pathlib import Path

from stock_lab_core.report_observation_panel import observation_report_lines


def test_report_keeps_gate_count_without_suggesting_event_ledger():
    lines = observation_report_lines(
        {}, [{"게이트상태": "실행가능"}, {"게이트상태": "방어우선"}], [],
        datetime.fromisoformat("2026-10-29T10:00:00+09:00"),
    )
    result = "\n".join(lines)
    assert "실행가능 1개" in result
    assert "이벤트 장부" not in result
    assert "스윙 슬롯" not in result


def test_briefing_has_no_ledger_renderer_but_storage_module_is_preserved():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app.py").read_text(encoding="utf-8-sig"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Name) and node.func.id == "render_event_swing_panel" for node in calls)
    assert (root / "stock_lab_core" / "event_swing.py").exists()
    assert (root / "docs" / "20261028_event_swing_ledger.sql").exists()
