from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from stock_lab_core.memory_thesis import build_thesis_tables, STATE_KEY
from stock_lab_core.memory_thesis_sources import parse_consensus, parse_cash_pages, fetch_memory_evidence

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def snapshot_html(code="005930", eps="2000"):
    header = [{"YYMM": f"{2023+i}/12", "CD": f"VAL{i+1}", "CONSOL_TYPE": "연결", "EP_CHK": "E" if i == 3 else None} for i in range(4)]
    rows = [{"NAME": k, "VAL4": v} for k, v in [
        ("매출액", "30000"), ("영업이익(발표기준)", "9000"), ("당기순이익(지배)", "6000"), ("EPS", eps), ("BPS", "10000")]]
    block = json.dumps({"header": header, "data": rows}, ensure_ascii=False)
    return f'''<input id="cmp_cd" value="{code}"><h1 id="giName">삼성전자</h1>
    <div><h2>시세현황</h2><span class="date">[2026/11/03]</span></div>
    <table><caption>시세현황</caption><tr><th>종가/ 전일대비/수익률</th><td>20,000/ -100 / -0.5</td>
    <th>종가(NXT)</th><td>99,999</td></tr></table>
    <section>단위 : 억원, %, 배, 주<div><table id="snpFinancial"></table></div></section>
    <script>var result = {{snpFinancial: {block}, other: 1}};</script>'''


def cash_pages(code="005930"):
    if code == "005930":
        return {1: "SAMSUNG ELECTRONICS 3Q 2026 Earnings Call", 15: """Appendix 4: Cash Flow (Summary)
KRW trillion 3Q 25 2Q 26 3Q 26 Current State of Net Cash
Cash flows from operating activities 22.6 105.1 98.6 Net Cash 91.8 167.6 197.6
Purchase of PP&E (10.8) (14.1) (26.9) • Commentary 300
"""}
    return {1: "FY2026 Earnings 2026.10.28", 2: "SK hynix FY2026 Q3 preliminary results", 16: """Statement of Cash Flows
(Unit : KRW Billion) ’26 Q3 ’26 Q2 ’25 Q3
CF from Operating Activities 54,781 65,710 14,368 D&A 4,335
Acquisition of PP&E (12,670) (10,671) (5,033) F/X Effect, etc. 3,881
"""}


def test_consensus_keeps_estimates_and_close_date_separate():
    result = parse_consensus(snapshot_html(), "005930", NOW)
    assert result["close"] == 20000  # Not NXT or a target price.
    assert result["estimate_period"] == "2026/12"
    assert result["price_asof"] == "2026-11-03"
    assert result["estimate_asof"] is None
    assert result["operating_profit_100m"] == 9000


def test_provider_schema_change_is_explicit_failure():
    with pytest.raises(ValueError, match="financial_payload_schema_changed"):
        parse_consensus(snapshot_html().replace('"data": [', '"data": [null,'), "005930", NOW)


@pytest.mark.parametrize("old,new", [
    ('value="005930"', 'value="000660"'), ("삼성전자", "다른기업"),
    ("2026/11/03", "2026/11/05"), ("2026/11/03", "unknown"),
    ('"2026/12"', '"2026/09"'), ('"연결"', '"별도"'),
    ('"EP_CHK": "E"', '"EP_CHK": "P"'), ("단위 : 억원", "단위 : 백만원"),
])
def test_rejects_wrong_identity_date_period_unit(old, new):
    with pytest.raises(ValueError):
        parse_consensus(snapshot_html().replace(old, new), "005930", NOW)


@pytest.mark.parametrize("eps", [None, "-2000", "0", "NaN"])
def test_missing_or_loss_eps_never_produces_positive_per(eps):
    result = parse_consensus(snapshot_html(eps=eps), "005930", NOW)
    tables = build_thesis_tables({"005930": {"consensus": result}})
    assert tables["estimates"].iloc[0]["계산 PER(배)"] == "미확인"
    assert tables["sensitivity"].iloc[0]["EPS 20% 감소 가정"] == "미확인"
    assert "판단 보류" in tables["interpretations"].iloc[0]["저평가 가설 검토"]


@pytest.mark.parametrize("code,ocf,ppe,surplus", [
    ("005930", 98.6, 26.9, 71.7), ("000660", 54.781, 12.67, 42.111),
])
def test_cash_table_column_unit_sign_and_adjacent_chart(code, ocf, ppe, surplus):
    result = parse_cash_pages(cash_pages(code), code)
    assert result["ocf_trillion"] == pytest.approx(ocf)
    assert result["cash_ppe_trillion"] == pytest.approx(ppe)
    assert result["cash_surplus_trillion"] == pytest.approx(surplus)
    assert result["reported_fcf"] is None


@pytest.mark.parametrize("old,new", [
    ("3Q 26", "2Q 26"), ("KRW trillion", "KRW billion"),
    ("(26.9)", "26.9"), ("105.1 98.6", "98.6"),
    ("Purchase of PP&E", "Cash balance"),
])
def test_unknown_cash_layout_is_missing_not_inferred(old, new):
    pages = cash_pages()
    pages[15] = pages[15].replace(old, new)
    with pytest.raises(ValueError):
        parse_cash_pages(pages, "005930")


def test_analysis_is_read_only_and_never_invents_fair_price():
    evidence = {"005930": {"consensus": parse_consensus(snapshot_html(), "005930", NOW),
                           "cash": parse_cash_pages(cash_pages(), "005930")}}
    before = deepcopy(evidence)
    tables = build_thesis_tables(evidence)
    assert evidence == before
    assert tables["estimates"].iloc[0]["계산 PER(배)"] == "10.00"
    assert tables["estimates"].iloc[0]["예상 매출(조원)"] == "3.00"
    assert tables["sensitivity"].iloc[0]["EPS 20% 감소 가정"] == "12.50"
    assert "감소" in tables["interpretations"].iloc[0]["반대 근거 / 확인할 것"]
    assert "미확인" == tables["cash"].iloc[0]["회사 정의 FCF"]
    assert "판단 보류" in tables["interpretations"].iloc[1]["저평가 가설 검토"]


def test_fetch_failure_has_no_fabricated_numbers(monkeypatch):
    import requests
    import stock_lab_core.memory_thesis_sources as module
    fetch_memory_evidence.clear()
    def fail(*args):
        raise requests.Timeout("private response must not be exposed")
    monkeypatch.setattr(module, "_download", fail)
    result = fetch_memory_evidence("005930", "consensus")
    assert not result["ok"] and result["reason"] == "Timeout"
    assert "close" not in result
    fetch_memory_evidence.clear()


def test_streamlit_readonly_panel_renders_cached_tables_without_fetch(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import stock_lab_core.memory_thesis as module
    def forbidden(*args):
        raise AssertionError("render-only must not fetch")
    monkeypatch.setattr(module, "fetch_memory_evidence", forbidden)
    at = AppTest.from_string('''
import streamlit as st
from stock_lab_core.memory_thesis import render_memory_thesis
render_memory_thesis(st, "RAM")
''')
    at.session_state[STATE_KEY] = {"005930": {"consensus": parse_consensus(snapshot_html(), "005930", NOW),
                                           "cash": parse_cash_pages(cash_pages(), "005930")}}
    at.run(timeout=30)
    assert not at.exception
    assert list(at.dataframe[0].value.columns) == ["항목", "삼성전자", "SK하이닉스"]
    assert len(at.button) == 1
    assert "매도·추가매수 승인" in " ".join(x.value for x in at.caption)


def test_streamlit_fetch_button_then_rerun_reuses_evidence(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import stock_lab_core.memory_thesis as module
    calls = []
    def fetch(code, kind):
        calls.append((code, kind))
        return {"ok": False, "reason": "test_unavailable"}
    monkeypatch.setattr(module, "fetch_memory_evidence", fetch)
    at = AppTest.from_string('''
import streamlit as st
from stock_lab_core.memory_thesis import render_memory_thesis
render_memory_thesis(st, "0167A0")
''').run(timeout=30)
    assert calls == []
    at.button[0].click().run(timeout=30)
    assert not at.exception
    assert len(calls) == 4
    at.run(timeout=30)
    assert not at.exception
    assert len(calls) == 4
