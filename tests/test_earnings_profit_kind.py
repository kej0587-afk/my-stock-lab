"""Profit row names the measure a quoted sentence states (2026-11-24 report 61: NVDA/PANW)."""
from stock_lab_core.earnings_result_sources import _prose_metrics, profit_kind
from stock_lab_core.report_calendar import _result_detail_lines

SPEC = {"ticker": "NVDA", "fiscal_period": "FY2027Q3", "source_url": "https://www.sec.gov/x.htm"}


def test_diluted_eps_sentence_is_recognised_with_both_bases():
    sentence = "GAAP and non-GAAP earnings per diluted share were $2.70 and $2.68, respectively."
    metric = _prose_metrics(["Revenue of $115.8 billion, up 103% from a year ago.", sentence], SPEC)["profit"]
    assert metric["status"] == "reported" and metric["text"] == sentence
    assert metric["profit_kind"] == {"measures": ["EPS"], "basis": "GAAP·조정"}


def test_operating_income_sentence_is_not_presented_as_eps():
    sentence = ("GAAP operating income for the fiscal first quarter 2027 was $96 million, compared with "
                "GAAP operating income of $309 million for the fiscal first quarter 2026.")
    spec = dict(SPEC, ticker="PANW", fiscal_period="FY2027Q1")
    metric = _prose_metrics([sentence], spec)["profit"]
    assert metric["profit_kind"] == {"measures": ["영업이익"], "basis": "GAAP"}
    row = {"event": "PANW earnings", "fiscal_period": "FY2027Q1", "result_metrics": {"profit": metric}}
    line = next(l for l in _result_detail_lines(row) if l.startswith("이익·EPS"))
    assert "문장에 있는 항목: 영업이익 (GAAP) · 순이익·EPS는 이 문장에 없음" in line
    assert "$96 million" in line.replace("\\$", "$")  # Source sentence still shown unchanged.


def test_basis_labels():
    assert profit_kind("Non-GAAP net income was $1 billion")["basis"] == "조정(non-GAAP)"
    assert profit_kind("Net income was $1 billion")["basis"] == "기준 미표기"
    assert profit_kind("Revenue was $1 billion")["measures"] == []
