"""B-2 (2026-11-24): code-based decision groups must equal the old label inference.

The old rule was ``DECISION_GROUP_BY_CODE.get(code) or classify_decision_signal(label)``
with the original 55-entry table. Every literal (label, code) pair the code base emits
must resolve to the same group through the frozen tables.
"""
import ast
import pathlib

from stock_lab_core.decision_engine import (
    DECISION_CODE_BY_LABEL,
    DECISION_GROUP_BY_CODE,
    DECISION_GROUP_BY_CODE_LABEL,
    build_decision_outcome,
    classify_decision_signal,
    resolve_decision_group,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Approved policy corrections that intentionally differ from the old label inference.
APPROVED_CHANGES = {"PROFIT_TAKE_REVIEW": "caution"}  # A-4, 2026-11-25
SOURCES = [
    "stock_lab_core/decision_policies.py", "stock_lab_core/decision_priority.py",
    "stock_lab_core/decision_followup.py", "stock_lab_core/decision_engine.py",
    "stock_lab_core/decision_finalization.py", "stock_lab_core/today_queue.py", "app.py",
]


def _original_table():
    tree = ast.parse((ROOT / "stock_lab_core/decision_engine.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DECISION_GROUP_BY_CODE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("DECISION_GROUP_BY_CODE literal not found")


def _literal(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _literal(node.body) + _literal(node.orelse)
    return []


def _emitted_pairs():
    pairs = set()
    for rel in SOURCES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in ("_set_decision", "build_decision_outcome") and len(node.args) >= 3:
                    codes = _literal(node.args[2])
                    for label in _literal(node.args[0]):
                        for code in codes:
                            if code.isupper():
                                pairs.add((code, label))
    pairs.update((code, label) for label, code in DECISION_CODE_BY_LABEL.items())
    return pairs


def test_every_emitted_label_keeps_its_old_group():
    original = _original_table()
    pairs = _emitted_pairs()
    assert len(pairs) > 100
    for code, label in pairs:
        old = APPROVED_CHANGES.get(code) or original.get(code) or classify_decision_signal(label)
        assert resolve_decision_group(code, label) == old, (code, label)
        assert build_decision_outcome(label, "#000", code).group == old, (code, label)


def test_frozen_tables_only_add_codes_and_keep_original_values():
    original = _original_table()
    for code, group in original.items():
        assert DECISION_GROUP_BY_CODE[code] == group
    assert len(DECISION_GROUP_BY_CODE) >= len(original) + 60
    assert {code for code, _ in DECISION_GROUP_BY_CODE_LABEL} == {"HARD_BLOCK_BOLLINGER_UPPER", "LEVERAGED_RECOVERY_DCA_BLOCK"}


def test_generic_codes_still_read_label_words():
    assert resolve_decision_group("BUYISH_GENERIC", "분할 매수 가능") == "buyish"
    assert resolve_decision_group("UNKNOWN_CODE", "추격금지 대기") == classify_decision_signal("추격금지 대기")


def test_a4_profit_take_review_is_caution_not_buyish():
    label = "🔔익절 타이밍: 고평가+과열+수익20%↑ (분할 매도 검토)"
    assert classify_decision_signal(label) == "buyish"  # the old word-based reading this fixes
    assert resolve_decision_group("PROFIT_TAKE_REVIEW", label) == "caution"
    assert set(APPROVED_CHANGES) == {"PROFIT_TAKE_REVIEW"}
    from stock_lab_core.decision_behavior_groups import behavior_group_label
    assert behavior_group_label("PROFIT_TAKE_REVIEW") == "5. 보유 유지·비중·익절"
