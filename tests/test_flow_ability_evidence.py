"""Offline regressions for duplicated and misattributed sector-card evidence."""

from copy import deepcopy
from itertools import permutations
import math

import pytest

from stock_lab_core.flow_ability_evidence import (
    deduplicate_evidence,
    select_card_action,
    sorted_representatives,
    source_quality,
)


ACTION_RANK = {"관망/제외": 1, "관심등록": 2, "추격금지": 3, "눌림대기": 4, "정밀관측": 5}


def normalize(action):
    return {"진입검토": "정밀관측"}.get(action, action if action in ACTION_RANK else "관망/제외")


def select(items):
    return select_card_action(items, normalize, ACTION_RANK.get)


def evidence(key="ticker:CIBR", source="ETF", **values):
    return {"observation_key": key, "source": source, "score": 28.0,
            "short": 0.04, "mid": 0.08, "action": "관심등록", **values}


def test_duplicate_observations_do_not_raise_evidence_or_valid_counts():
    row = evidence()
    single = deduplicate_evidence([row])
    assert deduplicate_evidence([row, dict(row), row]) == single
    assert source_quality([row] * 3) == source_quality([row])
    assert source_quality([row] * 3)["evidence_count"] == 1
    assert source_quality([row] * 3)["valid_counts"]["short"] == 1


def test_execution_attaches_action_and_representative_without_replacing_observation():
    observation = evidence(action="진입검토", representative="Raw representative")
    command = evidence(source="실행", score=90.0, short=0.9, mid=0.7,
                       action="눌림대기", representative="Final representative")
    before = deepcopy((observation, command))
    for ordered in permutations([observation, command, dict(command)]):
        merged, = deduplicate_evidence(ordered)
        assert (merged["source"], merged["score"], merged["short"], merged["mid"]) == (
            "ETF", 28.0, 0.04, 0.08
        )
        assert merged["action"] == "진입검토"
        assert merged["observation_actions"] == ["진입검토"]
        assert merged["execution_actions"] == ["눌림대기"]
        assert merged["representative"] == "Final representative"
        assert select([merged]) == "눌림대기"
        assert source_quality([merged])["execution_count"] == 1
    assert (observation, command) == before


def test_raw_source_precedence_and_missing_primary_values_are_preserved():
    rows = [evidence(source="실행", score=99.0),
            evidence(source="테마", score=40.0), evidence(score=None, mid=None)]
    for ordered in permutations(rows):
        merged, = deduplicate_evidence(ordered)
        assert merged["source"] == "ETF" and merged["score"] is None
        assert merged["mid"] is None
    assert deduplicate_evidence(rows[:2])[0]["score"] == 40.0


def test_duplicate_conflicts_are_deterministic_and_actions_are_conservative():
    rows = [evidence(score=42.0), evidence(score=28.0),
            evidence(source="실행", action="정밀관측"),
            evidence(source="실행", action="추격금지"),
            evidence(source="실행", action="관망/제외")]
    expected = deduplicate_evidence(rows)
    for ordered in permutations(rows):
        assert deduplicate_evidence(ordered) == expected
        assert select(ordered) == "관망/제외"
        assert select(deduplicate_evidence(ordered)) == "관망/제외"
    assert set(expected[0]["execution_actions"]) == {"정밀관측", "추격금지", "관망/제외"}


def test_deduplication_is_idempotent_and_retains_finalized_actions():
    rows = [evidence(), evidence(source="실행", action="눌림대기", representative="Moderna"),
            evidence(source="실행", action="정밀관측", representative="Moderna")]
    merged = deduplicate_evidence(rows)
    assert merged[0]["source"] == "ETF"
    assert set(merged[0]["execution_actions"]) == {"눌림대기", "정밀관측"}
    assert deduplicate_evidence(merged) == merged
    assert select(merged) == "눌림대기"
    assert select(deduplicate_evidence(merged)) == "눌림대기"


def test_best_finalized_action_wins_across_distinct_observations():
    rows = [evidence("ticker:GOOD", action="관망/제외"),
            evidence("ticker:GOOD", "실행", action="정밀관측"),
            evidence("ticker:BAD", "실행", action="관망/제외")]
    for ordered in permutations(rows):
        merged = deduplicate_evidence(ordered)
        assert select(ordered) == "정밀관측"
        assert select(merged) == "정밀관측"
        assert select(deduplicate_evidence(merged)) == "정밀관측"


def test_same_key_conflicts_resolve_before_best_distinct_action_and_rep_sort():
    rows = [evidence("ticker:CONFLICT", representative="Conflicted", short=0.9),
            evidence("ticker:CONFLICT", "실행", action="정밀관측", representative="Conflicted"),
            evidence("ticker:CONFLICT", "실행", action="관망/제외", representative="Conflicted"),
            evidence("ticker:VALID", "실행", action="눌림대기", representative="Valid", short=-0.1)]
    for ordered in permutations(rows):
        merged = deduplicate_evidence(ordered)
        assert select(ordered) == "눌림대기"
        assert select(merged) == "눌림대기"
        assert sorted_representatives(ordered) == ["Valid", "Conflicted"]
        assert sorted_representatives(deduplicate_evidence(merged)) == ["Valid", "Conflicted"]


def test_command_action_wins_over_raw_precision_even_with_different_keys():
    rows = [evidence(action="정밀관측"),
            evidence("ticker:MRNA", "테마", action="진입검토"),
            evidence("command:MRNA", "실행", action="눌림대기")]
    assert select(rows) == "눌림대기"


@pytest.mark.parametrize("action", ["", None, "unknown", "추격금지", "관망/제외"])
def test_command_veto_or_unknown_action_cannot_inherit_raw_precision(action):
    rows = [evidence(action="정밀관측"), evidence(source="실행", action=action)]
    assert select(rows) == normalize(action)
    assert select(deduplicate_evidence(rows)) == normalize(action)


def test_etf_only_defense_signal_does_not_authorize_individual_stock_precision():
    rows = [evidence("ticker:SHLD", action="진입검토")]
    assert select(rows) == "관망/제외"
    assert deduplicate_evidence(rows)[0]["observation_actions"] == ["진입검토"]
    assert deduplicate_evidence(rows)[0]["execution_actions"] == []
    assert select([]) == "관망/제외"


def test_representatives_are_sorted_by_execution_then_numeric_short_and_score():
    rows = [evidence("theme:weak", "테마", representative="Weak", short=-0.2),
            evidence("theme:flat", "테마", representative="Flat", short=0.0),
            evidence("theme:strong", "테마", representative="Strong", short=0.2),
            evidence("command:ready", "실행", representative="Final", short=0.01)]
    for ordered in permutations(rows):
        assert sorted_representatives(ordered) == ["Final", "Strong", "Flat", "Weak"]


def test_representative_canonical_final_action_precedes_short_and_score():
    actions = ["정밀관측", "눌림대기", "추격금지", "관심등록", "관망/제외"]
    rows = [evidence("ticker:" + action, "실행", representative=action,
                     action=action, short=index / 10, score=index * 10)
            for index, action in enumerate(actions)]
    rows.append(evidence("theme:raw", "테마", action="정밀관측", representative="Raw", short=9, score=999))
    assert sorted_representatives(rows) == actions + ["Raw"]
    assert sorted_representatives(list(reversed(rows))) == actions + ["Raw"]


def test_representative_ties_use_score_then_name_and_missing_numbers_sort_last():
    rows = [evidence("ticker:B", representative="Beta", score=5, short=0.1),
            evidence("ticker:A", representative="Alpha", score=5, short=0.1),
            evidence("ticker:C", representative="Higher score", score=6, short=0.1),
            evidence("ticker:D", representative="Missing", score=None, short=math.nan)]
    assert sorted_representatives(rows) == ["Higher score", "Alpha", "Beta", "Missing"]
    assert sorted_representatives(list(reversed(rows))) == sorted_representatives(rows)


def test_explicit_etf_representatives_are_excluded_and_labels_are_unique():
    rows = [evidence(representative="SOXX", is_etf_representative=True),
            evidence("ticker:A", representative="Stock"),
            evidence("ticker:B", representative="Stock"),
            evidence("ticker:C", representative="-"),
            evidence("ticker:D", representative=None)]
    assert sorted_representatives(rows) == ["Stock"]
    assert source_quality(rows)["evidence_count"] == 5


def test_attached_command_preserves_representative_type_and_execution_priority():
    rows = [evidence("ticker:A", representative="ETF alias", is_etf_representative=True),
            evidence("ticker:A", "실행", representative="Final stock", is_etf_representative=False),
            evidence("ticker:B", representative="Raw leader", short=0.9)]
    assert sorted_representatives(rows) == ["Final stock", "Raw leader"]
    rows[1]["is_etf_representative"] = True
    assert sorted_representatives(rows) == ["Raw leader"]


def test_source_quality_counts_finite_values_including_zero_without_imputation():
    rows = [evidence(score=0, short=-0.01, mid=None, r1d=math.nan, r5d=math.inf),
            evidence("theme:missing", "테마", score=None, short=None, mid=0, price_level=False),
            evidence("command:only", "실행", score=4, short=None, mid=None)]
    quality = source_quality(rows + [rows[0]])
    assert quality["evidence_count"] == 3
    assert quality["observation_count"] == 2 and quality["execution_count"] == 1
    assert quality["valid_counts"] == {
        "score": 2, "short": 1, "r1d": 0, "r5d": 0, "mid": 1, "long": 0, "price_level": 0
    }
    assert source_quality(rows, fields=("mid",))["valid_counts"] == {"mid": 1}
    assert source_quality([])["evidence_count"] == 0


@pytest.mark.parametrize("key", [None, ""])
def test_missing_observation_identity_is_rejected(key):
    with pytest.raises(ValueError, match="observation_key"):
        deduplicate_evidence([evidence(key)])
