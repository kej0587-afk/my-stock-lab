"""Offline contracts for financial fallback units, missing data and presentation."""

from copy import deepcopy
import socket

import pytest

from stock_lab_core.financial_score import (
    estimate_kr_fin_score_from_naver_snapshot,
    resolve_fin_score_source,
)
from stock_lab_core.valuation_presentation import (
    build_valuation_presentation,
    financial_score_display_rows,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Financial refresh contracts must use synthetic data only")

    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.mark.parametrize("data", [
    {"trailingPE": 30},
    {"trailingPE": 0},
    {"returnOnEquity": 0},
    {"returnOnEquity": 0.05},
    {"operatingMargins": 0.01},
    {"profitMargins": 0},
])
def test_available_indicators_do_not_use_the_missing_data_default(data):
    snapshot = {"ok": True, "data": data}
    before = deepcopy(snapshot)
    score, reason = estimate_kr_fin_score_from_naver_snapshot(snapshot)
    assert score == 1
    assert "no usable" not in reason
    assert snapshot == before


@pytest.mark.parametrize("snapshot", [
    None, {}, {"ok": False, "data": {}},
    {"data": {"trailingPE": "-", "returnOnEquity": "NaN", "profitMargins": float("inf")}},
])
def test_missing_data_keeps_the_explicit_default_and_reason(snapshot):
    score, reason = estimate_kr_fin_score_from_naver_snapshot(snapshot, default_score=2)
    assert score == 2
    assert "no usable summary indicators" in reason


@pytest.mark.parametrize("field,percent,ratio", [
    ("returnOnEquity", "0.5%", 0.005),
    ("returnOnEquity", "1%", 0.01),
    ("operatingMargins", "0.5%", 0.005),
    ("profitMargins", "1%", 0.01),
    ("returnOnEquity", "-0.5%", -0.005),
    ("operatingMargins", "15%", 0.15),
    ("profitMargins", "8%", 0.08),
])
def test_explicit_percent_matches_the_equivalent_provider_ratio(field, percent, ratio):
    assert estimate_kr_fin_score_from_naver_snapshot({field: percent}) == (
        estimate_kr_fin_score_from_naver_snapshot({field: ratio})
    )


@pytest.mark.parametrize("data,expected", [
    ({"trailingPE": 15}, 2),
    ({"trailingPE": 15.01}, 1),
    ({"returnOnEquity": 0.15}, 2),
    ({"returnOnEquity": 0.1499}, 1),
    ({"priceToBook": 1.2}, 2),
    ({"priceToBook": 1.201}, 1),
    ({"operatingMargins": 0.1}, 2),
    ({"operatingMargins": 0.0999}, 1),
    ({"profitMargins": 0.08}, 2),
    ({"profitMargins": 0.0799}, 1),
    ({"trailingPE": 10, "priceToBook": 1, "operatingMargins": 0, "debtToEquity": 250}, 3),
    ({"trailingPE": 10, "priceToBook": 1, "operatingMargins": 0, "debtToEquity": 251}, 2),
    ({"trailingPE": 10, "priceToBook": 1, "returnOnEquity": 0.2, "profitMargins": 0.2}, 3),
])
def test_existing_scoring_thresholds_and_cap_are_preserved(data, expected):
    assert estimate_kr_fin_score_from_naver_snapshot(data)[0] == expected


def test_fallback_source_and_missing_scores_stay_distinct_from_saved_manual_zero():
    meta = {"auto_score": None, "manual_score": 0, "final_score": 0,
            "source": "naver_fallback", "mode": "Naver\uac04\uc774\ucd94\uc815",
            "notes": {"ok": False, "source": "naver_fallback"}}
    before = deepcopy(meta)
    assert resolve_fin_score_source({"source": "dart/krx"}, meta["notes"]) == "naver_fallback"
    display = financial_score_display_rows(meta)
    scores = {row["\ud56d\ubaa9"]: row["\uac12"] for row in display["meta_rows"]}
    assert scores["auto_score"] == "-"
    assert scores["manual_score"] == scores["final_score"] == "0"
    assert meta == before


def test_reported_actuals_and_forward_pe_do_not_create_consensus_or_guidance():
    valuation = {"forward_pe": 20, "rows": [
        {"\ud56d\ubaa9": "\uc5f0\ub9e4\ucd9c", "\uac12": "100", "\ud310\uc815": "\ucc38\uace0",
         "\uae30\uac04": "2025-12-31", "\ucd9c\ucc98": "FMP"},
        {"\ud56d\ubaa9": "\uc5f0\ub9e4\ucd9c", "\uac12": "100", "\ud310\uc815": "\ucc38\uace0",
         "\uae30\uac04": "2026-03-31", "\ucd9c\ucc98": "FMP"},
        {"\ud56d\ubaa9": "PER", "\uac12": "20x", "\ud310\uc815": "\ub0ae\uc74c"},
    ]}
    before = deepcopy(valuation)
    result = build_valuation_presentation(valuation)
    groups = {section["id"]: section for section in result["sections"]}
    assert len(groups["actual"]["rows"]) == 2
    assert result["duplicate_rows_removed"] == 0
    assert not groups["consensus"]["rows"] and not groups["guidance"]["rows"]
    assert valuation == before
