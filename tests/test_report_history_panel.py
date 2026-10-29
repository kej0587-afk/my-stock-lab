"""Offline comparison parity and compact rendering contracts, without a browser."""

from contextlib import contextmanager
from copy import deepcopy
from itertools import product
import socket

import pandas as pd
import pytest

from stock_lab_core.report_comparison import history_comparison_lines
from stock_lab_core.report_evidence import _cell
from stock_lab_core.report_history_panel import build_history_change_view, render_history_changes


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("History presentation must not fetch data")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def row(ticker, *, name="", held=False, verdict="관망", gate="대기", reasons=("개별 위험사유 없음",), origin="등록"):
    return {"티커": ticker, "종목명": name or ticker, "보유여부": held, "최종읽기": verdict,
            "게이트상태": gate, "저장사유": list(reasons), "입력출처": origin}


def baseline(previous, **kwargs):
    return dict(previous=previous, previous_date="2026-10-27/2026-10-28",
                current_date="2026-10-28/2026-10-29", **kwargs)


class FakeUI:
    def __init__(self):
        self.events = []
        self.path = []

    def markdown(self, value):
        self.events.append(("markdown", tuple(self.path), value))

    def caption(self, value):
        self.events.append(("caption", tuple(self.path), value))

    def dataframe(self, value, **kwargs):
        assert kwargs["hide_index"] and kwargs["width"] == "stretch"
        assert kwargs["row_height"] == 64 and kwargs["height"] <= 420
        self.events.append(("table", tuple(self.path), value.copy(deep=True)))

    @contextmanager
    def expander(self, label, *, expanded):
        assert expanded is False
        self.events.append(("expander", tuple(self.path), label))
        self.path.append(label)
        try:
            yield self
        finally:
            self.path.pop()


@pytest.mark.parametrize("held,before,after,old_gate,new_gate,reason_changed", [
    (held, before, after, old_gate, new_gate, reason_changed)
    for held, (before, after), (old_gate, new_gate), reason_changed in product(
        (False, True), (("관망", "관망"), ("관망", "정밀확인"), ("", "관망")),
        (("대기", "대기"), ("대기", "방어우선")), (False, True))
])
def test_counts_and_individual_fields_match_existing_comparison(held, before, after, old_gate, new_gate, reason_changed):
    prior = row("TEST", held=held, verdict=before, gate=old_gate)
    current = row("TEST", held=held, verdict=after, gate=new_gate,
                  reasons=("가격급락",) if reason_changed else ("개별 위험사유 없음",))
    baselines = [baseline([prior])]
    original = deepcopy(([current], baselines))
    view = build_history_change_view([current], baselines)
    legacy = history_comparison_lines([current], baselines)
    assert view["full_lines"] == legacy
    for count in view["summary"]:
        expected = (count["reference"], count["basis"],
                    f"{'보유' if count['held'] else '관심·미보유'} {count['total']}개",
                    count["compared"], count["uncompared"],
                    f"{count['changed']}개" if count["changed"] is not None else "비교 불가")
        assert " | ".join(_cell(value) for value in expected) in legacy
    expected_fields = 0
    for change in view["changes"]:
        for field, old, new in change["fields"]:
            expected_fields += 1
            assert " | ".join(_cell(value) for value in
                              (change["name"], field, old, new, " · ".join(change["references"]))) in legacy
    legacy_fields = sum(line.startswith("TEST(종목명 미저장) |") for line in legacy)
    assert expected_fields == legacy_fields
    assert ([current], baselines) == original


def test_gate_embedded_in_verdict_is_not_counted_twice():
    prior = row("T", verdict="대기: 관찰", gate="대기")
    current = row("T", verdict="방어우선: 추가매수 보류", gate="방어우선")
    view = build_history_change_view([current], [baseline([prior])])
    assert view["changes"][0]["fields"] == [("판정·게이트", "대기: 관찰", "방어우선: 추가매수 보류")]
    assert view["summary"][1]["changed"] == 1


def test_reason_order_and_duplicates_are_not_changes():
    prior = row("T", reasons=("비중초과", "가격급락", "가격급락"))
    current = row("T", reasons=("가격급락", "비중초과"))
    assert build_history_change_view([current], [baseline([prior])])["changes"] == []


def test_identical_baseline_transitions_merge_but_counts_remain_separate():
    current = [row("H", name="보유", held=True, reasons=("가격급락",)), row("W", reasons=("추세훼손",))]
    prior = [row("H", held=True), row("W")]
    baselines = [baseline(prior), dict(previous=prior, previous_date="2026-10-28/2026-10-29",
        current_date="2026-10-28/2026-10-29", same_session=True, previous_run_at="2026-10-29T00:15:00+00:00")]
    view = build_history_change_view(current, baselines)
    assert len(view["summary"]) == 4 and len(view["changes"]) == 2
    assert all(r["changed"] == 1 for r in view["summary"])
    assert view["summary"][2]["basis"] == "2026-10-29 09:15 KST"
    assert view["changes"][0]["held"]
    assert view["changes"][0]["references"] == ["이전 저장 기준일", "같은 거래일 직전 생성"]


def test_same_ticker_different_transitions_keep_both_baselines():
    current = [row("T")]
    baselines = [baseline([row("T", reasons=("가격급락",))]),
                 dict(previous=[row("T", reasons=("추세훼손",))], previous_date="2026-10-29",
                      current_date="2026-10-29", same_session=True)]
    assert len(build_history_change_view(current, baselines)["changes"]) == 2


@pytest.mark.parametrize("previous,current,same", [
    ("", "2026-10-29", False), ("2026-10-29", "2026-10-29", False),
    ("2026-10-28", "2026-10-29", True), ("2026-10-30", "2026-10-29", False),
    ("2026-10-27/2026-10-30", "2026-10-28/2026-10-29", False),
    ("2026-10-27", "2026-10-28/2026-10-29", False),
    ("2026-02-30", "2026-10-29", False), ("20261028", "2026-10-29", False),
])
def test_invalid_or_incompatible_baselines_do_not_create_changes(previous, current, same):
    view = build_history_change_view([row("NEW")], [dict(previous=[row("OLD")],
        previous_date=previous, current_date=current, same_session=same)])
    assert view["summary"] == view["changes"] == view["membership"] == []
    assert "비교 없음" in "\n".join(view["full_lines"])


def test_membership_keeps_registered_auto_unknown_and_does_not_infer_sales():
    unknown = dict(row("UNKNOWN", origin=""), source="registered", provider="automatic")
    current = [row("REG", held=True), row("AUTO", origin="자동"), unknown]
    view = build_history_change_view(current, [baseline([row("OLD", origin="자동")])])
    origins = {r["ticker"]: r["origin"] for r in view["membership"]}
    assert origins == {"REG": "등록", "AUTO": "자동", "UNKNOWN": "미확인", "OLD": "자동"}
    assert view["changes"] == []
    assert all(count["changed"] is None for count in view["summary"])
    assert "삭제 여부는 미확인" in "\n".join(view["full_lines"])


def test_name_fallback_and_no_ticker_or_snapshot_mutation():
    frame = pd.DataFrame([row("005930.KS", reasons=("가격급락",))])
    prior = [row("005930.KS", name="삼성전자")]
    original = frame.copy(deep=True)
    view = build_history_change_view(frame, [baseline(prior)])
    assert view["changes"][0]["name"] == "삼성전자(005930.KS)"
    pd.testing.assert_frame_equal(frame, original)
    unmatched = build_history_change_view([row("005930")], [baseline(prior)])
    assert {r["action"] for r in unmatched["membership"]} == {"추가", "이탈"}


def test_quantity_zero_overrides_held_flag_like_existing_comparison():
    current = [dict(row("T", held=True, reasons=("가격급락",)), 보유량=0)]
    view = build_history_change_view(current, [baseline([row("T", held=True)])])
    assert not view["changes"][0]["held"]
    assert view["summary"][0]["total"] == 0 and view["summary"][1]["compared"] == 1


def test_holdings_first_with_all_overflow_and_watch_rows_collapsed():
    current = [row(f"W{i}", name=f"관심{i}", reasons=("가격급락",)) for i in range(25)]
    current += [row(f"H{i}", name=f"보유{i}", held=True, reasons=("추세훼손",)) for i in range(9)]
    prior = [dict(r, 저장사유=["개별 위험사유 없음"]) for r in current]
    ui = FakeUI()
    view = render_history_changes(ui, current, baselines=[baseline(prior)], holding_limit=6)
    tables = [(path, value) for kind, path, value in ui.events if kind == "table"]
    public_changes = [value for path, value in tables if not path and "종목" in value]
    assert len(public_changes) == 1 and len(public_changes[0]) == 6
    assert public_changes[0]["종목"].str.startswith("보유").all()
    assert list(public_changes[0]) == ["종목", "이전 → 현재", "주요 사유"]
    assert sum(len(value) for path, value in tables if path and "추가 보유" in path[0]) == 3
    assert sum(len(value) for path, value in tables if path and "관심·미보유" in path[0]) == 25
    assert len(view["changes"]) == 34
    assert all(" | " not in value for kind, _, value in ui.events if kind == "caption")
    original = next(value for kind, path, value in ui.events if kind == "markdown" and path == ("비교 기준·판정·사유 원문",))
    assert original == "\n".join(history_comparison_lines(current, [baseline(prior)]))


def test_compact_reason_keeps_full_before_after_in_collapsed_original():
    long_reason = "전체 사유 원문 " * 35
    current = [row("T", name="이름|파이프 <b>문자</b>", held=True, reasons=(long_reason,))]
    prior = [row("T", held=True)]
    ui = FakeUI()
    view = render_history_changes(ui, current, baselines=[baseline(prior)])
    compact = next(value for kind, path, value in ui.events if kind == "table" and not path and "종목" in value)
    assert len(compact.iloc[0]["주요 사유"]) <= 80
    assert compact.iloc[0]["주요 사유"].endswith("…")
    assert compact.iloc[0]["이전 → 현재"] == "판정 유지: 관망"
    assert view["changes"][0]["fields"][0][2] == long_reason.strip()
    assert "이름|파이프 <b>문자</b>" in compact.iloc[0]["종목"]


def test_single_baseline_api_registered_auto_counts_and_held_addition_visibility():
    ui = FakeUI()
    current = [row("H", name="새 보유", held=True), row("A", origin="자동")]
    view = render_history_changes(ui, current, [row("OLD")], previous_date="2026-10-28", current_date="2026-10-29")
    outside = [value for kind, path, value in ui.events if kind == "table" and not path]
    shown = next(value for value in outside if "종목" in value)
    assert shown.iloc[0]["종목"] == "새 보유(H)"
    counts = next(value for value in outside if "출처" in value).set_index("출처")
    assert counts.loc["등록", ["추가", "이탈"]].tolist() == [1, 1]
    assert counts.loc["자동", ["추가", "이탈"]].tolist() == [1, 0]
    assert not view["changes"]


def test_no_history_is_distinct_from_no_change_and_empty_current_keeps_removals():
    ui = FakeUI()
    render_history_changes(ui, [row("T")], [], current_date="2026-10-29")
    assert ("caption", (), "비교 가능한 저장 이력 없음") in ui.events
    assert not any(kind == "table" for kind, _, _ in ui.events)
    view = render_history_changes(FakeUI(), [], [row("OLD", held=True)],
                                  previous_date="2026-10-28", current_date="2026-10-29")
    assert view["membership"][0]["action"] == "이탈"


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_visible_limit_rejected(limit):
    with pytest.raises(ValueError, match="positive integer"):
        render_history_changes(FakeUI(), [], holding_limit=limit)
