"""Synthetic, distinct values ensure current-quarter columns are selected."""

from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace

import pytest

from stock_lab_core import earnings_result_pdf as pdf
from stock_lab_core.earnings_result_sources import _PROFILES, _ALTERNATE_PDFS

NOW = datetime.fromisoformat("2026-10-29T13:00:00+09:00")
ALPHABET = """Alphabet Announces Third Quarter 2026 Results
MOUNTAIN VIEW - October 28, 2026 - Alphabet today announced financial results for the quarter ended September 30, 2026.
Financial Highlights (in millions, except for per share information and percentages).
Quarter Ended September 30,
2025 2026
Revenues $ 100,000 $ 123,456
Operating income $ 10,000 $ 25,678
Revenues and GAAP Percentage Change in Revenues
"""
CASH = """Reconciliation from GAAP Net Cash Provided by Operating Activities to Non-GAAP Free Cash Flow (in millions; unaudited):
Quarter Ended TTM
Q4 2025 Q1 2026 Q2 2026 Q3 2026 Q3 2026
Net cash provided by operating activities $ 11 $ 22 $ 33 $ 55,000 $ 555,555
Less: purchases of property and equipment (1) (2) (3) (66,000) (666,666)
Free cash flow $ 10 $ 20 $ 30 $ (11,000) $ 777,777
"""
SAMSUNG = """3Q 2026 Results
Based on consolidated financial statements
Revenue Operating Profit R&D Investment
KRW 123.4T KRW 56.7T KRW 8.9T
"""
SAMSUNG_CASH = """Appendix 4: Cash Flow (Summary)
KRW trillion 3Q 25 2Q 26 3Q 26 Current State of Net Cash
Cash flows from operating activities 10.0 20.0 30.0 Net Cash 100 200 300
Purchase of PP&E (1.1) (2.2) (3.3) • A separate shareholder return figure 999 trillion
"""


@pytest.fixture
def reader(monkeypatch):
    state = dict(texts={1: ALPHABET, 8: CASH}, pages=16, encrypted=False,
                 created=NOW - timedelta(days=1), modified=NOW - timedelta(hours=1), calls=[])
    class Page:
        def __init__(self, index):
            self.index = index
        def extract_text(self, **kwargs):
            assert kwargs == {"extraction_mode": "layout"}
            state["calls"].append(self.index)
            return state["texts"].get(self.index, "")
    def fake_reader(stream):
        return SimpleNamespace(is_encrypted=state["encrypted"], pages=[Page(i + 1) for i in range(state["pages"])],
                               metadata=SimpleNamespace(creation_date=state["created"], modification_date=state["modified"]))
    monkeypatch.setattr("pypdf.PdfReader", fake_reader)
    return state


def parse(ticker="GOOGL", **kwargs):
    spec = dict(_PROFILES[ticker], source_url=_ALTERNATE_PDFS[ticker])
    return pdf.parse_official_result_pdf(kwargs.get("data", b"%PDF-fixture"), ticker, kwargs.get("spec", spec), kwargs.get("now", NOW))


def test_alphabet_current_quarter_not_ttm_and_signed_fcf(reader):
    result = parse()
    metrics = result["metrics"]
    assert metrics["revenue"]["source_value"] == "123,456"
    assert metrics["profit"]["source_value"] == "25,678"
    assert metrics["capex"]["source_value"] == "(66,000)"
    assert metrics["free_cash_flow"]["source_value"] == "(11,000)"
    assert metrics["free_cash_flow"]["source_page"] == 8
    assert metrics["free_cash_flow"]["column"] == "Q3 2026"
    assert "777,777" not in str(metrics)
    assert metrics["guidance"]["status"] == "missing"
    assert result["release_at"] is None and result["release_precision"] == "date"
    assert reader["calls"] == [1, 8]


@pytest.mark.parametrize("change", [
    lambda t: t.replace("Quarter Ended", "Nine Months Ended"),
    lambda t: t.replace("Q3 2026 Q3 2026", "Q2 2026 Q3 2026"),
    lambda t: t.replace("in millions; unaudited", "units unspecified"),
    lambda t: t + "Free cash flow $ 1 $ 2 $ 3 $ 4 $ 5\n",
])
def test_unknown_ambiguous_or_ytd_table_stays_missing(reader, change):
    reader["texts"][8] = change(CASH)
    assert parse()["metrics"]["free_cash_flow"]["status"] == "missing"


@pytest.mark.parametrize("header", ["Nine Months Ended September 30,", "Year Ended December 31,", "Quarter Ended June 30,"])
def test_quarter_header_does_not_authorize_next_period_table(reader, header):
    reader["texts"][1] = ALPHABET.replace("Revenues $", header + "\n2025 2026\nRevenues $")
    metrics = parse()["metrics"]
    assert metrics["revenue"]["status"] == metrics["profit"]["status"] == "missing"
    reader["texts"][8] = CASH.replace("Free cash flow $", header + "\nFree cash flow $")
    assert parse()["metrics"]["free_cash_flow"]["status"] == "missing"


def test_samsung_ppe_not_total_capex_and_no_computed_fcf(reader):
    reader["texts"] = {1: "SAMSUNG ELECTRONICS\n3Q 2026 Earnings Call", 5: SAMSUNG, 15: SAMSUNG_CASH}
    result = parse("005930.KS")
    metrics = result["metrics"]
    assert metrics["revenue"]["source_value"] == "123.4" and metrics["profit"]["source_value"] == "56.7"
    assert metrics["capex"]["source_value"] == "(3.3)" and metrics["capex"]["source_page"] == 15
    assert "회사 총 CAPEX와 별도" in metrics["capex"]["text"]
    assert metrics["free_cash_flow"]["status"] == "missing" and not metrics["free_cash_flow"]["text"]
    assert metrics["free_cash_flow"]["reason"] == "not_reported_in_supported_pdf"
    assert metrics["guidance"]["status"] == "missing"
    assert result["provenance"]["release_date_basis"] == "verified_issuer_calendar"
    assert result["release_at"] is None and reader["calls"] == [1, 5, 15]


@pytest.mark.parametrize("bad", ["Alphabet Announces Second Quarter 2026 Results", "Other Announces Third Quarter 2026 Results"])
def test_wrong_issuer_or_period_is_rejected(reader, bad):
    reader["texts"][1] = ALPHABET.replace("Alphabet Announces Third Quarter 2026 Results", bad)
    with pytest.raises(ValueError, match="identity_or_period"):
        parse()


def test_publication_day_must_match_source_body(reader):
    reader["texts"][1] = ALPHABET.replace("October 28, 2026", "October 27, 2026")
    with pytest.raises(ValueError, match="release_date_not_in_body"):
        parse()


@pytest.mark.parametrize("key", ["created", "modified"])
def test_future_pdf_metadata_is_rejected(reader, key):
    reader[key] = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError, match="page_version_after_cutoff"):
        parse()


def test_naive_metadata_uses_issuer_zone_for_cutoff_not_release_time(reader):
    reader["modified"] = datetime(2026, 10, 29, 0, 1)  # New York 04:01 UTC > cutoff 04:00 UTC.
    with pytest.raises(ValueError, match="page_version_after_cutoff"):
        parse()


@pytest.mark.parametrize("pages,encrypted", [(1, False), (25, False), (16, True)])
def test_page_and_encryption_bounds(reader, pages, encrypted):
    reader.update(pages=pages, encrypted=encrypted)
    with pytest.raises(ValueError, match="invalid_pdf_pages"):
        parse()


def test_size_magic_future_and_unsupported_period_fail_closed(reader):
    for data in (b"<html>not pdf</html>", b"%PDF-" + b"x" * pdf.MAX_BYTES):
        with pytest.raises(ValueError, match="invalid_document_size"):
            parse(data=data)
    with pytest.raises(ValueError, match="future_result"):
        parse(now=NOW - timedelta(days=3))
    with pytest.raises(ValueError, match="unsupported_result"):
        parse(spec=dict(_PROFILES["GOOGL"], fiscal_period="2026Q4"))


def test_missing_pdf_dependency_and_corruption_are_bounded(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(ValueError, match="pdf_reader_unavailable"):
        parse()


def test_real_pdf_reader_rejects_corruption():
    with pytest.raises(ValueError, match="invalid_pdf_document"):
        parse(data=b"%PDF-corrupt")
