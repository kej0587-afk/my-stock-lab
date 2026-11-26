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
    lines = _result_detail_lines(row)
    op = next(l for l in lines if l.startswith("영업이익"))
    assert "(GAAP)" in op and "$96 million" in op.replace("\\$", "$")  # Source sentence still shown unchanged.
    for name in ("순이익", "GAAP EPS", "조정 EPS"):
        assert "확인한 원문에 이 항목 없음" in next(l for l in lines if l.startswith(name))


def test_basis_labels():
    assert profit_kind("Non-GAAP net income was $1 billion")["basis"] == "조정(non-GAAP) 포함"
    intel = "EPS attributable to Intel was $0.60; non-GAAP EPS attributable to Intel was $0.52."
    assert profit_kind(intel)["basis"] == "조정(non-GAAP) 포함"
    assert profit_kind("Net income was $1 billion")["basis"] == "기준 미표기"
    assert profit_kind("Revenue was $1 billion")["measures"] == []


# ── 2026-11-26: 영업이익 · 순이익 · GAAP EPS · 조정 EPS as separate rows ─────────────────────────────────
from stock_lab_core.earnings_profit_rows import classify_sentence, profit_rows  # noqa: E402


def test_four_profit_rows_each_take_their_own_sentence():
    blocks = ["Revenue was $10.0 billion, up 20% year over year.",
              "Operating income was $3.1 billion.",
              "Net income was $2.5 billion.",
              "GAAP and non-GAAP earnings per diluted share were $2.70 and $2.68, respectively."]
    metric = _prose_metrics(blocks, SPEC)["profit"]
    rows = profit_rows(metric)
    assert rows["영업이익"]["text"] == blocks[1] and rows["순이익"]["text"] == blocks[2]
    assert rows["GAAP EPS"]["text"] == rows["조정 EPS"]["text"] == blocks[3]
    lines = _result_detail_lines({"event": "X", "fiscal_period": "FY2027Q3", "result_metrics": {"profit": metric}})
    assert [l.split(" | ")[0] for l in lines if l.split(" | ")[0] in ("영업이익", "순이익", "GAAP EPS", "조정 EPS")] == \
        ["영업이익", "순이익", "GAAP EPS", "조정 EPS"]
    assert not any(l.startswith("이익·EPS") for l in lines)


def test_unlabelled_eps_is_never_moved_into_the_gaap_row():
    intel = "EPS attributable to Intel was $0.60; non-GAAP EPS attributable to Intel was $0.52."
    found = classify_sentence(intel)
    assert found == {"EPS(회계기준 미표기)": "기준 미표기", "조정 EPS": "조정"}
    rows = profit_rows({"status": "reported", "text": intel, "source_url": "https://www.intc.com/x"})
    assert "GAAP EPS" not in rows and rows["조정 EPS"]["basis"] == "조정"
    lines = _result_detail_lines({"event": "INTC", "fiscal_period": "2026Q3",
                                  "result_metrics": {"profit": {"status": "reported", "text": intel,
                                                                "source_url": "https://www.intc.com/x"}}})
    assert any(l.startswith("EPS(회계기준 미표기)") for l in lines)
    assert "확인한 원문에 이 항목 없음" in next(l for l in lines if l.startswith("GAAP EPS"))


def test_dart_components_and_pdf_rows_map_without_new_numbers():
    dart = {"status": "reported", "source_url": "https://dart.fss.or.kr/x", "text": "a / b",
            "components": [{"status": "reported", "label": "영업이익", "text": "영업이익 · 연결 · 분기(3개월) 1 KRW"},
                           {"status": "reported", "label": "당기순이익", "text": "당기순이익 · 연결 · 분기(3개월) 2 KRW"}]}
    rows = profit_rows(dart)
    assert set(rows) == {"영업이익", "순이익"} and rows["순이익"]["basis"] == "공시 재무제표"
    pdf = {"status": "reported", "source_label": "연결 영업이익", "text": "2026년 3분기 | 연결 영업이익: 12.1 조원",
           "source_url": "https://images.samsung.com/x.pdf"}
    assert set(profit_rows(pdf)) == {"영업이익"}
    assert profit_rows({"status": "missing"}) == {}
