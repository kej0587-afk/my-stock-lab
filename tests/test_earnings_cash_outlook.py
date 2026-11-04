"""Synthetic amounts; source identity/period validation remains upstream."""

from copy import deepcopy
from datetime import datetime, timezone

from lxml import html
import pytest

from stock_lab_core.earnings_cash_outlook import explicit_quarter_fcf, qualitative_outlook, pdf_outlook_column
from stock_lab_core.earnings_result_sources import _PROFILES, _table_grid, _prose_metrics


SPEC = dict(_PROFILES["SNDK"])


def cash_table(value="(123)"):
    return f'''<main><table><caption>Reconciliation (in millions; unaudited)</caption>
    <tr><th></th><th colspan="3">Three Months Ended</th></tr>
    <tr><th></th><th>October 2, 2026</th><th>July 3, 2026</th><th>October 3, 2025</th></tr>
    <tr><td>Operating cash flow</td><td>1000</td><td>2000</td><td>3000</td></tr>
    <tr><td>Free cash flow</td><td>{value}</td><td>222</td><td>333</td></tr>
    <tr><td>Adjusted free cash flow</td><td>999</td><td>888</td><td>777</td></tr></table></main>'''


def test_explicit_fcf_preserves_sign_period_and_definition():
    metric = explicit_quarter_fcf(html.fromstring(cash_table()), SPEC, _table_grid)
    assert metric["source_value"] == "(123)"
    assert metric["period_scope"] == "FY2027Q1"
    assert metric["column"] == "October 2, 2026"
    assert metric["unit"] == "USD millions"
    assert "999" not in metric["text"]


def test_verified_release_uses_table_only_for_missing_fcf():
    from stock_lab_core.earnings_result_sources import parse_earnings_result, _HEADINGS
    body = cash_table().removeprefix("<main>").removesuffix("</main>")
    doc = f'<main><h1>{_HEADINGS["SNDK"]}</h1><p>October 29, 2026 - Sandisk today announced financial results for the first quarter of fiscal year 2027.</p>{body}</main>'
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    metric = parse_earnings_result(doc.encode(), "SNDK", now)["metrics"]["free_cash_flow"]
    assert metric["source_value"] == "(123)"
    doc = doc.replace(body, '<p>Free cash flow was $7 million.</p>' + body)
    assert parse_earnings_result(doc.encode(), "SNDK", now)["metrics"]["free_cash_flow"]["text"] == "Free cash flow was $7 million."


@pytest.mark.parametrize("change", [
    lambda x: x.replace("Three Months", "Nine Months"),
    lambda x: x.replace("October 2, 2026", "October 2, 2025"),
    lambda x: x.replace("in millions", "unit missing"),
    lambda x: x.replace("Free cash flow</td>", "Adjusted free cash flow</td>"),
    lambda x: x.replace("(123)", "-"),
    lambda x: x.replace("July 3, 2026", "October 2, 2026"),
    lambda x: x.replace("</main>", x + "</main>"),
])
def test_ambiguous_table_never_computes_or_guesses_fcf(change):
    assert explicit_quarter_fcf(html.fromstring(change(cash_table())), SPEC, _table_grid) is None


def test_currency_and_fiscal_end_cannot_be_guessed():
    for key in ("reporting_currency", "period_end_label"):
        spec = {k: v for k, v in SPEC.items() if k != key}
        assert explicit_quarter_fcf(html.fromstring(cash_table()), spec, _table_grid) is None


def test_qualitative_outlook_is_not_an_actual_or_numeric_forecast():
    blocks = ["The company expects memory demand to grow next year.",
              "The business plans to expand capacity in the fourth quarter."]
    metrics = _prose_metrics(blocks, SPEC)
    assert metrics["guidance"]["evidence_kind"] == "qualitative"
    assert "next year" in metrics["guidance"]["text"]
    assert all(metrics[k]["status"] == "missing" for k in ("capex", "free_cash_flow", "revenue", "profit"))


@pytest.mark.parametrize("sentence", [
    "Forward-looking statements about revenue will involve risks and uncertainties.",
    "We will discuss the revenue outlook on the conference call.",
    "The company had expected demand to grow last year.",
    "The company plans a dividend equal to 50% of free cash flow.",
    "Analysts expect demand growth next year.",
    "The company posted cash of $100 billion.",
])
def test_disclaimer_deferred_policy_and_cash_balance_are_not_outlook_or_fcf(sentence):
    assert qualitative_outlook([sentence], SPEC) is None
    assert _prose_metrics([sentence], SPEC)["free_cash_flow"]["status"] == "missing"


def test_existing_numeric_and_deferred_guidance_preserved():
    numeric = "We expect revenue of $10 billion next quarter."
    qualitative = "The company expects demand to grow."
    assert _prose_metrics([qualitative, numeric], SPEC)["guidance"]["text"] == numeric
    deferred = "We will discuss guidance on the conference call."
    assert _prose_metrics([qualitative, deferred], SPEC)["guidance"]["status"] == "deferred"


def pdf_column():
    return "\n".join(["Memory", "Results".ljust(80) + "Outlook",
                      "3Q 2026 Results".ljust(80) + "4Q 2026",
                      "Actual revenue 999".ljust(80) + "Demand is expected to grow.",
                      "Actual profit 888".ljust(80) + "Expand production capacity.",
                      "".ljust(80) + "2027", "".ljust(80) + "Later guidance"])


def test_pdf_outlook_column_excludes_actuals_and_next_year():
    value = pdf_outlook_column(pdf_column(), SPEC, heading="Memory", horizon="4Q 2026", next_horizon="2027", page=7)
    assert "Demand is expected" in value["text"]
    assert "999" not in value["text"] and "888" not in value["text"] and "Later" not in value["text"]
    assert value["evidence_kind"] == "qualitative" and value["source_page"] == 7
    for change in (lambda x: x.replace("4Q 2026", "3Q 2026"), lambda x: x.replace("2027", ""),
                   lambda x: " ".join(x.split()), lambda x: x.replace("Memory", "Other")):
        assert pdf_outlook_column(change(pdf_column()), SPEC, heading="Memory", horizon="4Q 2026", next_horizon="2027", page=7) is None


@pytest.mark.parametrize("fund,issuer", [("RAM", "SNDK"), ("MAGS", "META"), ("0167A0.KS", "005930.KS"), ("CIBR", "MSFT")])
def test_common_verified_membership_bridge_keeps_forecasts_separate(fund, issuer):
    from stock_lab_core.portfolio_market_review import holding_market_review
    from stock_lab_core.holding_evidence_commentary import build_holding_evidence_commentary
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    metric = qualitative_outlook(["The company expects demand to grow next year."], _PROFILES[issuer])
    packet = dict(ticker=issuer, name=issuer, date="2026-10-29", fiscal_period="2026Q3", official=True,
                  metrics={"guidance": metric}, stages={"guidance": "확인"})
    state = {"etf_constituents_" + fund: dict(status="ok", holdings_basis="provider_reported", observed_at=now.isoformat(),
             as_of="2026-11-04", source_url="https://example.com/holdings", rows=[dict(ticker=issuer, reviewable=True, kind="security")])}
    data = dict(earnings=[packet], sessions={}, prices={})
    original = deepcopy(data)
    review = holding_market_review(fund, data, state, now=now)
    synthesis = build_holding_evidence_commentary(fund, review)
    assert synthesis["evidence"][0]["구분"] == "회사 전망 · 실제치 아님"
    assert "정성" in synthesis["evidence"][0]["자료 범위"]
    assert "FCF" in synthesis["company"] and data == original
