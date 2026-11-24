"""Regression shapes from the Nov-21 official-release audit; synthetic amounts."""
from copy import deepcopy

import pytest

from stock_lab_core.earnings_filing_evidence import parse_sec_release
from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from tests.test_earnings_filing_discovery import NOW, FILING, BASE, release


def parse(body, **kwargs):
    return parse_sec_release(body, "CYBR", "1234", FILING, BASE + "results.htm", NOW,
                             issuer_name=kwargs.get("issuer_name", "Example Cyber Inc."))


def yearless(facts):
    return release(quarter="First Quarter", facts=facts)


def test_realized_fiscal_period_in_body_recovers_yearless_heading_read_only():
    data = yearless("""<p>Revenue was $3 billion.</p>
      <p>Example Cyber returned $100 million to shareholders in the first quarter of fiscal year 2027.</p>
      <h2>Business Outlook</h2><p>We expect revenue of $4 billion in the second quarter of fiscal 2027.</p>""")
    event, result = parse(data)
    assert result["fiscal_period"] == "FY2027Q1"
    assert result["release_date"] == "2026-11-19"
    assert result["metrics"]["revenue"]["text"] == "Revenue was $3 billion."
    assert result["metrics"]["capex"]["status"] == "missing"
    assert result["metrics"]["free_cash_flow"]["status"] == "missing"
    rows = [dict(ticker="CYBR", name="Example Cyber", score=7, verdict="blocked")]
    context = dict(calendar_events=[event], earnings_results=[result])
    before = deepcopy((rows, context))
    pipeline = build_earnings_pipeline(context, rows, now=NOW)
    assert pipeline["scoring_used"] is False
    assert (rows, context) == before
    assert pipeline["packets"][0]["official"]


@pytest.mark.parametrize("facts", [
    "<p>Revenue was $3 billion for the quarter ended September 30, 2026.</p>",
    "<p>We expect revenue of $3 billion in the first quarter of fiscal 2027.</p>",
    "<p>Example Cyber returned $1 million in the second quarter of fiscal 2027.</p>",
    "<p>Example Cyber returned $1 million in the first quarter of fiscal 2026 and the first quarter of fiscal 2027.</p>",
    "<table><tr><td>Example Cyber reported revenue of $3 billion for the first quarter of fiscal 2027.</td></tr></table>",
    "<h2>Business Outlook</h2><p>Example Cyber generated $3 billion in the first quarter of fiscal 2027.</p>",
    "<p>Example Cyber reported Q1 2027 revenue of $3 billion.</p>",
    "<p>In the prior fiscal year, Example Cyber returned $1 million in the first quarter of fiscal 2026.</p>",
])
def test_fallback_never_infers_period_from_dates_forecasts_or_comparatives(facts):
    with pytest.raises(ValueError, match="explicit_fiscal_quarter_unavailable"):
        parse(yearless(facts))


def test_conflicting_dated_title_is_not_repaired_from_body():
    data = release(quarter="First Quarter Fiscal 2026 and First Quarter Fiscal 2027",
                   facts="<p>Example Cyber returned $1 million in the first quarter of fiscal 2027.</p>")
    with pytest.raises(ValueError, match="explicit_fiscal_quarter_unavailable"):
        parse(data)


def test_recovered_quarter_still_requires_real_dateline_not_filing_or_call_date():
    data = yearless("""<p>Example Cyber today announced results for its fiscal 2027 first quarter ended September 30, 2026.</p>
      <p>The financial results conference call is November 19, 2026.</p>""")
    data = data.replace(b"November 19, 2026 -- ", b"")
    with pytest.raises(ValueError, match="release_dateline_unavailable"):
        parse(data)


@pytest.mark.parametrize("issuer_name", ["Example Cyber Inc /DE", "EXAMPLE CYBER INC /DE/", "Example Cyber Inc /NEW/"])
def test_trailing_edgar_state_tag_is_ignored_but_name_still_matched(issuer_name):
    event, result = parse(release(), issuer_name=issuer_name)
    assert result["ticker"] == "CYBR"


@pytest.mark.parametrize("issuer_name", ["Other Cyber Inc /DE", "Example /DE Cyber Inc", "Example Cyber Holdings Inc /DE",
                                         "Example Cyber Inc /de"])
def test_state_tag_rule_does_not_loosen_the_name_match(issuer_name):
    with pytest.raises(ValueError, match="release_issuer_mismatch"):
        parse(release(), issuer_name=issuer_name)


def test_fallback_requires_one_explicit_heading_quarter():
    data = release(quarter="Quarterly", facts="<p>Example Cyber returned $1 million in the first quarter of fiscal 2027.</p>")
    with pytest.raises(ValueError, match="explicit_fiscal_quarter_unavailable"):
        parse(data)
