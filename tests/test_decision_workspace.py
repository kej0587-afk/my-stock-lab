"""Captured decision displays must not fetch, merge permissions, or alter inputs."""

from contextlib import nullcontext
from copy import deepcopy
import html
import socket
import urllib.request

import pandas as pd
import pytest
import requests

from stock_lab_core.decision_brief import build_decision_brief, compare_decision_briefs
from stock_lab_core import decision_workspace as workspace
from stock_lab_core.portfolio_holding_review import PRECISION_KEY
from stock_lab_core.portfolio_signal_cache import SIGNAL_SOURCES


SCOPE = "synthetic-account-a"
AT = "2026-11-20T01:00:00+00:00"


@pytest.fixture(autouse=True)
def forbid_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Decision workspace attempted an external call")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def workflow(**changes):
    row = {
        "티커": "MSFT", "종목명": "Synthetic company", "현재가": "$522.6501",
        "현재가원값": 522.6501, "가격자료기준일": "2026-11-19",
        "가격반영": "정규장 종가", "최종읽기": "기존 후보", "판정코드": "FIXTURE",
        "게이트상태": "실행가능", "게이트근거": "기존 조건 확인",
        "기술적타점": "회복 관찰", "핵심근거": "가격 관찰",
        "현재비중": 1.25, "목표비중": 5.0, "1차기준": "$510.9117",
        "1차조건": "기존 확인봉 유지", "손절가": "$499.1743", "차트목표": "$551.150024",
        "R/R": "1.2140223", "R/R출처": "기존 계산",
        "financial": {"period": "FY2027 Q1", "quarter_revenue": 123.456789,
                      "ytd_cash_flow": 456.789123, "capex": None, "unit": "USD million"},
    }
    row.update(changes)
    return row


def final_check(**changes):
    result = {"execution_allowed": True, "block_count": 0, "core_missing_ids": [],
              "final_label": "정밀확인", "action": "사용자 최종 판단"}
    result.update(changes)
    return result


def frame(rows=None, *, scope=SCOPE, at=AT):
    result = pd.DataFrame(rows if rows is not None else [workflow()])
    result.attrs.update(portfolio_signal_context=scope, portfolio_signal_at=at)
    return result


def precision_state(row=None, *, key="MSFT", scope=SCOPE, at=AT, final=None):
    return {PRECISION_KEY: {"context": scope, "reviews": {key: {
        "workflow": workflow() if row is None else row, "captured_at": at,
        "final": final_check() if final is None else final,
    }}}}


class FakeSt:
    def __init__(self, state=None, selections=None, clicked=False):
        self.session_state = {} if state is None else state
        self.selections = selections or {}
        self.clicked = clicked
        self.markdowns, self.captions, self.warnings, self.infos, self.tables = [], [], [], [], []

    def expander(self, *args, **kwargs):
        return nullcontext()

    def markdown(self, value, **kwargs):
        self.markdowns.append((value, kwargs))

    def caption(self, value):
        self.captions.append(value)

    def warning(self, value):
        self.warnings.append(value)

    def info(self, value):
        self.infos.append(value)

    def selectbox(self, label, options, *, key, **kwargs):
        return self.selections.get(key, list(options)[0])

    radio = selectbox

    def dataframe(self, value, **kwargs):
        self.tables.append(value.copy(deep=True))

    def button(self, *args, **kwargs):
        return self.clicked


def test_brief_preserves_exact_prices_quarter_values_and_nested_input_isolation():
    row, final = workflow(), final_check()
    before = deepcopy((row, final))
    brief = build_decision_brief(row, source="fixture", calculated_at=AT, final_check=final)
    assert brief["workflow"] == row
    assert brief["price"] == "$522.6501"
    assert brief["plan"] == {"1차 기준": "$510.9117", "조건": "기존 확인봉 유지",
                             "손절 참고선": "$499.1743", "차트 목표": "$551.150024",
                             "현재가 기준 R/R": "1.2140223"}
    assert brief["calculated_at"] == AT and brief["basis"] == "2026-11-19"
    assert (row, final) == before
    brief["workflow"]["financial"]["quarter_revenue"] = -1
    brief["ready"]["display_workflow"]["financial"]["capex"] = 0
    assert (row, final) == before


@pytest.mark.parametrize("missing", [None, float("nan"), pd.NA, pd.NaT, "", "-", "nan", "None", "NaT"])
def test_missing_values_are_unknown_not_zero_or_invented_prices(missing):
    row = {key: missing for key in ("현재가", "현재가원값", "현재비중", "목표비중", "1차기준",
                                    "손절가", "차트목표", "R/R", "가격자료기준일")}
    brief = build_decision_brief(row, source="fixture")
    assert brief["price"] == brief["basis"] == brief["plan"]["손절 참고선"] == "미확인"
    assert brief["plan"]["차트 목표"] == brief["plan"]["현재가 기준 R/R"] == "미확인"
    assert "현재 미확인 / 목표 미확인" in brief["layers"][-1]["확인"]
    assert not brief["ready"]["execution_allowed"]
    assert "가격 제시 보류" in brief["scenarios"][1]["대응"]
    assert "가격 제시 보류" in brief["scenarios"][2]["대응"]


@pytest.mark.parametrize("raw", [None, 0, -1, float("inf"), float("-inf"), "invalid"])
def test_invalid_raw_price_never_becomes_a_zero_quote(raw):
    assert build_decision_brief({"티커": "MSFT", "현재가원값": raw}, source="fixture")["price"] == "미확인"


def test_valid_zero_weights_remain_zero_and_numeric_fallback_is_display_only():
    row = workflow(현재가=None, 현재가원값=123.45, 현재비중=0, 목표비중=0)
    brief = build_decision_brief(row, source="fixture")
    assert brief["price"] == "$123.45"
    assert "현재 0.0% / 목표 0.0%" in brief["layers"][-1]["확인"]
    assert row["현재가"] is None and row["현재가원값"] == 123.45


@pytest.mark.parametrize("gate,final,allowed", [
    ("실행가능", None, False), ("실행가능", {}, False),
    ("실행가능", final_check(), True),
    ("방어우선", final_check(), False), ("대기", final_check(), False),
    ("실행가능", final_check(execution_allowed=False, final_label="매수 금지"), False),
    ("실행가능", final_check(block_count=1), False),
    ("실행가능", final_check(core_missing_ids=["price"]), False),
    ("실행가능", {"final_label": "긍정적", "action": "회복"}, False),
])
def test_no_scenario_overrides_original_gate_or_final_veto(gate, final, allowed):
    row = workflow(게이트상태=gate)
    original = deepcopy((row, final))
    brief = build_decision_brief(row, source="fixture", final_check=final)
    assert brief["gate"] == brief["workflow"]["게이트상태"] == gate
    assert brief["ready"]["execution_allowed"] is allowed
    assert (brief["scenarios"][0]["대응"] == "원계획 재검토") is allowed
    assert "제한은 해제되지 않음" in brief["scenarios"][0]["재확인"]
    assert (row, final) == original


def test_sources_and_calculation_times_remain_separate_without_favorable_value_merge():
    keys = list(SIGNAL_SOURCES)
    state = {keys[0]: frame([workflow(현재가="$100", 게이트상태="방어우선")]),
             keys[1]: frame([workflow(현재가="$200")], at="2026-11-20T02:00:00Z")}
    state.update(precision_state(workflow(현재가="$300"), final=final_check(execution_allowed=False)))
    original = deepcopy(state)
    briefs = workspace.collect_decision_briefs(state, SCOPE)
    assert [item["price"] for item in briefs] == ["$100", "$200", "$300"]
    assert [item["source"] for item in briefs] == [SIGNAL_SOURCES[keys[0]], SIGNAL_SOURCES[keys[1]], "정밀관측소"]
    assert [item["calculated_at"] for item in briefs] == [AT, "2026-11-20T02:00:00Z", AT]
    assert all(not item["ready"]["execution_allowed"] for item in briefs)
    comparison = compare_decision_briefs(briefs)
    assert [row["판정가"] for row in comparison] == ["$100", "$200", "$300"]
    briefs[0]["workflow"]["financial"]["period"] = "changed"
    for key in keys[:2]:
        pd.testing.assert_frame_equal(state[key], original[key])
        assert state[key].attrs == original[key].attrs
    assert state[PRECISION_KEY] == original[PRECISION_KEY]


@pytest.mark.parametrize("scope,at", [("other-account", AT), (None, AT), (SCOPE, None),
                                     (SCOPE, "invalid"), (SCOPE, ""), (SCOPE, pd.NaT)])
def test_unscoped_or_undated_sources_and_precision_are_rejected(scope, at):
    state = {key: frame(scope=scope, at=at) for key in SIGNAL_SOURCES}
    state.update(precision_state(scope=scope, at=at))
    assert workspace.collect_decision_briefs(state, SCOPE) == []
    assert workspace.collect_decision_briefs(state, "") == []


def test_precision_mismatched_ticker_rejected_and_final_envelope_veto_preserved():
    state = precision_state(key="AAPL")
    assert workspace.collect_decision_briefs(state, SCOPE) == []
    state = precision_state(final={"summary": final_check(execution_allowed=False, block_count=2)})
    briefs = workspace.collect_decision_briefs(state, SCOPE)
    assert len(briefs) == 1 and not briefs[0]["ready"]["execution_allowed"]


def test_duplicate_normalized_tickers_reject_both_rows_without_hiding_other_sources():
    keys = list(SIGNAL_SOURCES)
    state = {keys[0]: frame([workflow(티커="005930.KS"), workflow(티커="005930"),
                             workflow(티커="AAPL"), workflow(티커="")]),
             keys[1]: frame([workflow(티커="005930.KS")])}
    briefs = workspace.collect_decision_briefs(state, SCOPE)
    assert [(b["source"], b["ticker"]) for b in briefs] == [
        (SIGNAL_SOURCES[keys[0]], "AAPL"), (SIGNAL_SOURCES[keys[1]], "005930.KS")]


def test_precision_without_ticker_is_not_an_identified_capture():
    assert workspace.collect_decision_briefs(precision_state(workflow(티커=""), key=""), SCOPE) == []


def test_html_escaped_in_every_unsafe_render_and_brief_not_mutated():
    payload = '<img src=x onerror="alert(1)"><script>bad()</script>&'
    row = {key: payload for key in workflow() if key not in {"financial", "현재비중", "목표비중"}}
    brief = build_decision_brief(row, source="fixture", final_check=final_check(action=payload))
    before = deepcopy(brief)
    ui = FakeSt()
    workspace.render_decision_brief(ui, brief, expanded=True)
    unsafe = [value for value, kwargs in ui.markdowns if kwargs.get("unsafe_allow_html")]
    assert len(unsafe) == 6
    assert all(payload not in value and "<script>" not in value and "<img " not in value for value in unsafe)
    assert html.escape(payload) in "\n".join(unsafe)
    assert brief == before


@pytest.mark.parametrize("aliases", [False, True])
def test_frame_renderer_rejects_ambiguous_ticker_rows(aliases):
    rows = [workflow(티커="005930.KS"), workflow(티커="005930" if aliases else "005930.KS")]
    ui = FakeSt()
    workspace.render_frame_decision_brief(ui, frame(rows), source="fixture", key="frame-choice")
    assert ui.warnings
    assert not ui.markdowns


@pytest.mark.parametrize("clicked", [False, True])
def test_workspace_render_selects_one_source_without_fetching_mutating_or_implicit_navigation(clicked):
    state = {list(SIGNAL_SOURCES)[0]: frame()}
    state.update(precision_state(final=final_check(execution_allowed=False, final_label="매수 금지")))
    saved = deepcopy(state)
    ui = FakeSt(state, {"scenario_decision_source": "정밀관측소"}, clicked=clicked)
    navigated = []
    workspace.render_scenario_workspace(ui, context=SCOPE, open_precision=navigated.append)
    assert navigated == (["MSFT"] if clicked else [])
    assert len(ui.tables) == 1 and len(ui.tables[0]) == 2
    assert "실행 보류" in "\n".join(value for value, _ in ui.markdowns)
    assert state[PRECISION_KEY] == saved[PRECISION_KEY]
    key = list(SIGNAL_SOURCES)[0]
    pd.testing.assert_frame_equal(state[key], saved[key])
    assert state[key].attrs == saved[key].attrs


def test_empty_workspace_does_not_navigate_or_invent_a_result():
    ui = FakeSt()
    workspace.render_scenario_workspace(ui, context=SCOPE,
                                        open_precision=lambda _: pytest.fail("Unexpected navigation"))
    assert ui.infos and not ui.markdowns and not ui.tables
