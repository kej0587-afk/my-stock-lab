"""Synthetic outlooks keep future plans out of actual earnings and decisions."""

from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest
import requests

from stock_lab_core.official_outlook import discover_oracle_outlook, official_oracle_url, parse_oracle_outlook
from stock_lab_core.report_outlook import official_outlook_lines
from stock_lab_core import outlook_sources as sources

NOW = datetime.fromisoformat("2026-10-29T13:00:00+09:00")
URL = "https://investor.oracle.com/investor-news/news-details/2026/Oracle-Investor-Day-2026-Test/default.aspx"
TITLE = "Oracle Investor Day 2026: Test Outlook"
BODY = """Oracle Corporation (NYSE: ORCL) today hosted an Investor Day.
Defined timeline to positive free cash flow during the second half of FY30 and set free cash flow target of $42 billion+ for FY31.
Following a period of peak capex in FY29-FY30, capital expenditures are expected to step-down in FY31.
Oracle committed to limiting additional funding to be raised in the capital markets for its FY29-FY32 investment cycle to $24 billion, currently expected to be $11 billion in equity and $13 billion in gross debt.
This incremental funding requirement excludes refinancing of existing debt. This is in addition to the $17 billion at-the-market equity raise completed in the first quarter of fiscal 2029.
Vendor financing, customer-provided hardware and customer prepayments are expected to reduce upfront cash requirements.
"""


def feed(*, title=TITLE, day="10/28/2026 14:21:00", url=URL):
    return {"GetPressReleaseListResult": [dict(Headline=title, PressReleaseDate=day, LinkToDetailPage=url)]}


def page(body=BODY, *, title=TITLE, day="October 28, 2026"):
    return f'<h3 class="evergreen-news-title">{title}</h3><span class="evergreen-news-date-text">{day}</span><div class="evergreen-news-body">{body}</div>'.encode()


def parsed(body=BODY):
    return parse_oracle_outlook(page(body), discover_oracle_outlook(feed(), NOW), NOW)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    sources.clear_outlook_cache()
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: pytest.fail("unexpected HTTP"))
    yield
    sources.clear_outlook_cache()


def test_schema_and_dynamic_values_not_quarterly_actuals():
    result = parsed()
    assert result["event_kind"] == "investor_day" and result["evidence_kind"] == "company_outlook"
    assert result["status"] == "confirmed" and "fiscal_period" not in result and "actual" not in result
    m = result["metrics"]
    assert "FY29~FY30" in m["capex"]["text"] and "FY31" in m["capex"]["text"]
    assert "42 billion" in m["free_cash_flow"]["text"] and "목표" in m["free_cash_flow"]["text"]
    assert "24 billion" in m["funding"]["text"] and "11 / 총부채 13" in m["funding"]["text"]
    assert "차환 제외" in m["funding_scope"]["text"] and "17 billion" in m["funding_scope"]["text"]
    assert m["funding_scope"]["evidence_kind"] == "reported_scope_and_completed_funding"
    assert m["capex"]["source_url"] == URL and m["capex"]["evidence"] in BODY


@pytest.mark.parametrize("url", [URL.replace("investor.oracle.com", "evil.test"), URL + "?redirect=x", URL + "#x",
    URL.replace("https:", "http:"), URL.replace("investor.oracle.com", "user@investor.oracle.com"),
    URL.replace("investor.oracle.com", "investor.oracle.com:443"), URL.replace("/2026/", "/../"), None])
def test_exact_official_origin_and_path(url):
    assert not official_oracle_url(url)


@pytest.mark.parametrize("patch", [dict(title="Oracle Announces Quarterly Results"),
    dict(title="Oracle Investor Day Meeting to be held October 28, 2026"),
    dict(day="10/30/2026 10:00:00"), dict(day="06/01/2026 10:00:00"), dict(day="unknown")])
def test_discovery_rejects_quarterly_schedule_future_old_and_unknown(patch):
    assert discover_oracle_outlook(feed(**patch), NOW) is None


def test_discovery_latest_no_old_fallback_and_relative_links():
    data = feed(day="10/27/2026 10:00:00")
    data["GetPressReleaseListResult"] += feed(url=URL.replace("https://investor.oracle.com", ""))["GetPressReleaseListResult"]
    assert discover_oracle_outlook(data, NOW)["date"] == "2026-10-28"
    assert discover_oracle_outlook(data, NOW)["source_url"] == URL


@pytest.mark.parametrize("kwargs", [dict(day="October 27, 2026"), dict(title="Oracle Investor Day 2026 Revised"),
    dict(body=BODY.replace("today hosted", "plans to host")), dict(body=BODY.replace("Oracle Corporation", "Another Corporation"))])
def test_body_must_match_list_and_completed_event(kwargs):
    with pytest.raises(ValueError):
        parse_oracle_outlook(page(**kwargs), discover_oracle_outlook(feed(), NOW), NOW)


def test_missing_values_never_filled_by_older_guidance_or_risk_boilerplate():
    body = "Oracle Corporation today hosted an Investor Day. Safe Harbor Statement " + BODY
    result = parsed(body)
    assert result["status"] == "partial"
    assert all(m["status"] == "missing" for m in result["metrics"].values())
    assert all("evidence" not in m for m in result["metrics"].values())


def test_funding_without_exclusions_does_not_claim_ceiling():
    result = parsed(BODY.replace("excludes refinancing", "includes refinancing"))
    assert result["metrics"]["funding"]["status"] == "missing"
    assert "24 billion" not in result["metrics"]["funding"]["text"]


def test_conflicting_or_duplicated_matches_are_not_guessed():
    result = parsed(BODY + BODY[BODY.index("Following"):BODY.index("Oracle committed")].replace("FY31", "FY32"))
    assert result["metrics"]["capex"]["status"] == "missing"


@pytest.mark.parametrize("key, old, new", [
    ("capex", "step-down in FY31.", "step-down in FY31 only if customer prepayments reach the agreed threshold."),
    ("free_cash_flow", "$42 billion+ for FY31.", "$42 billion+ for FY31 subject to financing approval."),
    ("cash_mechanism", "upfront cash requirements.", "upfront cash requirements provided that suppliers agree."),
])
def test_unrecognized_conditions_are_not_silently_discarded(key, old, new):
    assert parsed(BODY.replace(old, new))["metrics"][key]["status"] == "missing"


def test_previous_cycle_scope_cannot_validate_current_funding():
    result = parsed(BODY.replace("This incremental funding", "For the previous FY25-FY28 investment cycle only: This incremental funding"))
    assert result["metrics"]["funding"]["status"] == result["metrics"]["funding_scope"]["status"] == "missing"


@pytest.fixture
def provider(monkeypatch):
    state = dict(calls=[], closed=[], error=None, bad_article=False)
    class Response:
        status_code = 200
        def __init__(self, url):
            self.url = url
        def iter_content(self, chunk_size):
            yield (json.dumps(feed()).encode() if "/feed/" in self.url else b"" if state["bad_article"] else page())
        def close(self):
            state["closed"].append(self.url)
    def get(url, **kwargs):
        state["calls"].append(url)
        assert kwargs["stream"] and kwargs["allow_redirects"] is False and kwargs["timeout"] == (2, 3)
        if state["error"]:
            raise state["error"]
        return Response(url)
    monkeypatch.setattr(sources.requests, "get", get)
    return state


def test_collection_two_requests_cache_isolated_and_no_time_travel(provider):
    result = sources.load_official_outlooks(NOW)
    assert len(provider["calls"]) == len(provider["closed"]) == 2
    assert result["events"][0]["metrics"]["free_cash_flow"]["status"] == "confirmed"
    result["events"].clear()
    again = sources.load_official_outlooks(NOW + timedelta(hours=1))
    assert again["events"] and again["sources"][0]["from_cache"]
    assert len(provider["calls"]) == 2
    sources.load_official_outlooks(NOW - timedelta(hours=1))
    assert len(provider["calls"]) == 4


def test_failed_transport_short_cache_and_no_fabricated_event(provider, monkeypatch):
    provider["error"] = requests.Timeout()
    result = sources.load_official_outlooks(NOW)
    assert not result["events"] and result["sources"][0]["reason"] == "request_failed:Timeout"
    sources.load_official_outlooks(NOW + timedelta(seconds=10))
    assert len(provider["calls"]) == 1
    cached_at = sources._CACHE["ORCL"][0]
    monkeypatch.setattr(sources.time, "monotonic", lambda: cached_at + 61)
    sources.load_official_outlooks(NOW + timedelta(seconds=61))
    assert len(provider["calls"]) == 2


def test_empty_html_is_unavailable_not_app_crash(provider):
    provider["bad_article"] = True
    result = sources.load_official_outlooks(NOW)
    assert not result["events"] and result["sources"][0]["status"] == "unavailable"


def test_concurrent_call_does_not_wait_on_network_or_duplicate(provider):
    with sources._LOCK:
        result = sources.load_official_outlooks(NOW)
    assert result["sources"][0]["reason"] == "collection_in_progress" and not provider["calls"]


def test_presentation_is_pure_and_keeps_interpretation_conditional():
    context = dict(official_outlooks=dict(events=[parsed()], sources=[]), decision_code="KEEP", final_read="unchanged")
    original = deepcopy(context)
    rendered = "\n".join(official_outlook_lines(context, NOW))
    assert "분기 실적(실현값)과 별도" in rendered and "조건부 해석" in rendered
    assert "수요 감소를 확정하지 않습니다" in rendered and "반증·확인" in rendered
    assert "42 billion" in rendered and "매수" not in rendered and context == original
    assert official_outlook_lines({}, NOW) == []


@pytest.mark.parametrize("when", [NOW - timedelta(seconds=1), NOW + timedelta(days=2)])
def test_future_or_stale_collected_context_cannot_render_current_guidance(when):
    rendered = "\n".join(official_outlook_lines(dict(official_outlooks=dict(events=[parsed()], sources=[])), when))
    assert "미연결" in rendered and "42 billion" not in rendered
