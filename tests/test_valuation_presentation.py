"""Presentation-only cleanup: no new lookups, scores, thresholds or missing-as-zero."""

from contextlib import contextmanager
from copy import deepcopy
import socket

import pytest

from stock_lab_core.valuation_presentation import (
    MAX_ROWS, build_valuation_presentation, financial_score_display_rows, render_valuation_details,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Presentation must not perform external lookups")
    monkeypatch.setattr(socket.socket, "connect", fail)


def row(name, value="10.0", verdict="참고", **extra):
    return {"항목": name, "값": value, "판정": verdict, **extra}


def sections(result):
    return {section["id"]: section for section in result["sections"]}


def test_existing_rows_are_separated_without_modifying_values_scores_or_inputs():
    names = ["목표가 업사이드", "PER", "PBR", "PSR", "PEG", "연매출", "영업이익", "순이익",
             "매출 성장", "이익 성장", "순이익률", "영업이익률"]
    value = {"headline": "조건부 적정", "rows": [row(name) for name in names], "forward_pe": 10,
             "valuation_data_count": 5, "quality_data_count": 4, "data_count": 9}
    meta = {"final_score": 0, "notes": {"ok": True, "weighted_scores": {"selected_score": 0}}}
    before = deepcopy((value, meta))
    result = build_valuation_presentation(value, fin_meta=meta)
    groups = sections(result)
    assert [item["항목"] for item in groups["actual"]["rows"]] == names[5:]
    assert groups["consensus"]["rows"][0]["항목"] == "목표가 업사이드"
    assert [item["항목"] for item in groups["valuation"]["rows"]] == ["선행 PER(예상 이익)", "PBR", "PSR", "PEG"]
    assert all(item["값"] == "10.0" and item["판정"] == "참고" for group in result["sections"] for item in group["rows"])
    assert groups["guidance"]["rows"] == [] and "원문 미연결" in groups["guidance"]["missing"]
    assert (value, meta) == before
    assert not {"headline", "score", "valuation_score", "final_score"} & result.keys()


@pytest.mark.parametrize("forward,trailing,label", [
    (20, 15, "선행 PER(예상 이익)"), (0, 15, "선행 PER(예상 이익)"),
    (None, 15, "후행 PER(과거 이익)"), (float("nan"), 15, "후행 PER(과거 이익)"),
    (None, None, "PER(기준 미확인)"),
])
def test_per_label_matches_existing_forward_first_selection_without_recomputing(forward, trailing, label):
    result = build_valuation_presentation({"forward_pe": forward, "trailing_pe": trailing, "rows": [row("PER", "-")]})
    assert result["per_label"] == label
    assert sections(result)["valuation"]["rows"][0]["값"] == "-"


def test_exact_duplicates_only_conflicts_stay_visible_and_periods_do_not_collapse():
    first = row("PER", "10x")
    conflict = row("PER", "11x")
    annual = row("연매출", "100", 기간="2025")
    later = row("연매출", "100", 기간="2026")
    result = build_valuation_presentation({"rows": [first, dict(first), conflict, annual, later]})
    assert result["duplicate_rows_removed"] == 1
    assert len(sections(result)["valuation"]["rows"]) == 2
    assert len(sections(result)["actual"]["rows"]) == 2
    assert len(result["diagnostics"]) == 1 and "불일치" in result["diagnostics"][0]


def test_missing_zero_and_negative_actual_results_remain_distinct():
    result = build_valuation_presentation({"rows": [row("연매출", None), row("영업이익", 0), row("순이익", "-25")]})
    assert [item["값"] for item in sections(result)["actual"]["rows"]] == ["미연결", "0", "-25"]


def test_partial_success_does_not_hide_lookup_failures_or_echo_private_errors():
    snapshot = {"ok": True, "reason": "Yahoo 조회 실패: Timeout PRIVATE_KEY", "data": {"forwardPE": 20}}
    analyst = {"ok": False, "status": "rate_limited", "reason": "https://host/?apikey=PRIVATE_KEY",
        "provider_attempts": [{"source": "yfinance.get_info", "status": "error"},
                              {"source": "PRIVATE_KEY", "status": "error"}]}
    before = deepcopy((snapshot, analyst))
    result = build_valuation_presentation({"rows": [row("PER", "20x")]}, snapshot=snapshot, analyst_snapshot=analyst)
    assert any("밸류 조회: 일부 조회 실패" in note for note in result["diagnostics"])
    assert any("컨센서스 조회: 조회 제한" in note for note in result["diagnostics"])
    assert any("yfinance.get_info: 조회 실패" in note for note in result["diagnostics"])
    assert "PRIVATE_KEY" not in str(result)
    assert len(sections(result)["valuation"]["rows"]) == 1
    assert (snapshot, analyst) == before


def test_stale_consensus_and_failed_financial_fallback_are_explicit_without_overriding_scores():
    meta = {"final_score": 3, "notes": {"ok": False, "mode": "Naver간이추정"}}
    result = build_valuation_presentation({"rows": [row("목표가 업사이드", "5%")], "headline": "중립"},
        analyst_snapshot={"ok": False, "status": "stale", "stale": True}, fin_meta=meta)
    assert any("이전 자료" in item for item in result["diagnostics"])
    assert any("실적 부진 판정 아님" in item for item in result["diagnostics"])
    assert meta["final_score"] == 3
    assert sections(result)["consensus"]["rows"][0]["값"] == "5%"


@pytest.mark.parametrize("status,failed", [("failed", True), (None, False), ("available", False), (True, False)])
def test_enrichment_failure_status_is_separate_from_original_financial_meta(status, failed):
    meta = {"final_score": 0, "manual_score": 0, "source": "saved", "metrics": {},
            "notes": {"messages": ["Existing notes"]}, "valuation_lookup_status": status}
    before = deepcopy(meta)
    result = build_valuation_presentation({"rows": []}, fin_meta=meta)
    assert any("밸류 보강용 재무 조회 실패" in note for note in result["diagnostics"]) is failed
    assert meta == before
    assert all(not section["rows"] for section in result["sections"])


def test_unknown_rows_are_not_lost_or_assigned_to_guidance():
    result = build_valuation_presentation({"rows": [row("unknown", "123")]})
    assert sections(result)["unclassified"]["rows"][0]["값"] == "123"
    assert not sections(result)["guidance"]["rows"]


def test_empty_and_malformed_inputs_do_not_invent_financial_data():
    for value in (None, [], {}, {"rows": None}, {"rows": [None, {}, row("", 42)]}):
        result = build_valuation_presentation(value, snapshot={"ok": False})
        assert all(not group["rows"] and group["missing"] for group in result["sections"])
        assert result["diagnostics"]


def test_row_and_attempt_processing_are_bounded():
    result = build_valuation_presentation({"rows": [row(f"item{i}") for i in range(MAX_ROWS + 20)]},
        analyst_snapshot={"ok": True, "provider_attempts": [{"source": "FnGuide", "status": "error"}] * 1000})
    assert sum(len(group["rows"]) for group in result["sections"]) == MAX_ROWS
    assert len(result["diagnostics"]) == 2


def test_financial_score_rows_preserve_actual_zero_missing_and_negative_weighted_scores():
    meta = {"source": "SEC", "mode": "saved", "auto_score": 0, "manual_score": None, "final_score": 0}
    weighted = {"weighted_net_score": -2, "s_sum": 0, "a_sum": 0, "b_sum": None, "danger_count": 0,
                "generic_score": 0, "order_score": float("nan"), "middle_score": True}
    before = deepcopy((meta, weighted))
    result = financial_score_display_rows(meta, weighted)
    display = {item["항목"]: item["값"] for item in result["meta_rows"] + result["weighted_rows"]}
    assert display["auto_score"] == display["final_score"] == display["S_sum"] == display["danger_count"] == "0"
    assert display["manual_score"] == display["B_sum"] == display["수주판단"] == display["중간형판단"] == "-"
    assert display["weighted score"] == "-2"
    assert meta == before[0] and weighted["weighted_net_score"] == before[1]["weighted_net_score"]


def test_renderer_exposes_failures_before_collapsed_details_and_renders_each_section_once():
    class UI:
        def __init__(self):
            self.log = []
        def caption(self, text):
            self.log.append(("caption", text))
        @contextmanager
        def expander(self, label, **kwargs):
            self.log.append(("expander", label))
            assert kwargs["expanded"] is False
            yield
        def dataframe(self, frame, **kwargs):
            self.log.append(("table", frame.to_dict("records")))
    ui = UI()
    presentation = build_valuation_presentation({"rows": [row("PER"), row("PER"), row("연매출")]},
        analyst_snapshot={"ok": False, "status": "rate_limited"})
    render_valuation_details(ui, presentation)
    assert ui.log[0][0] == "caption" and "조회 제한" in ui.log[0][1]
    assert ui.log[1][0] == "expander"
    tables = [payload for kind, payload in ui.log if kind == "table"]
    assert len(tables) == 2 and sum(map(len, tables)) == 2
