"""B-1 (2026-11-24): every decision code belongs to exactly one display behavior group."""
from stock_lab_core.decision_behavior_groups import (
    BEHAVIOR_GROUP_BY_CODE, BEHAVIOR_GROUP_CODES, BEHAVIOR_GROUP_LABELS, behavior_group_label,
)
from stock_lab_core.decision_engine import DECISION_CODE_BY_LABEL, DECISION_GROUP_BY_CODE
from tests.test_decision_group_freeze import _emitted_pairs


def test_groups_partition_the_127_emitted_codes():
    codes = [code for group in BEHAVIOR_GROUP_CODES.values() for code in group]
    assert len(codes) == len(set(codes)) == 127
    assert {k: len(v) for k, v in BEHAVIOR_GROUP_CODES.items()} == {
        "NEW_ENTRY_BASIC": 5, "NEW_ENTRY_MOMENTUM": 8, "RECOVERY_ENTRY": 3, "HOLDING_ADD": 23, "HOLDING_KEEP": 15,
        "RISK_CHECK": 27, "ETF_CORE_DCA": 20, "LEVERAGED": 8, "WAIT_OVERHEAT_DATA": 18,
    }
    assert set(BEHAVIOR_GROUP_CODES) == set(BEHAVIOR_GROUP_LABELS)


def test_every_known_code_has_a_behavior_group():
    known = {code for code, _ in _emitted_pairs()} | set(DECISION_GROUP_BY_CODE) | set(DECISION_CODE_BY_LABEL.values())
    missing = sorted(code for code in known if code not in BEHAVIOR_GROUP_BY_CODE)
    assert missing == []


def test_unknown_and_generic_codes_are_unclassified():
    assert behavior_group_label("BUYISH_GENERIC") == "미분류"
    assert behavior_group_label("") == "미분류"
    assert behavior_group_label("leveraged_dca_conditional") == "8. 레버리지 전용"
