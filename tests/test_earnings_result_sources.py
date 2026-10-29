"""Synthetic source fixtures: no financial amounts are embedded in production."""

from copy import deepcopy
from datetime import datetime, timedelta
import json
import threading
import time

import pytest
import requests

from stock_lab_core import earnings_result_sources as results


NOW = datetime.fromisoformat("2026-10-29T12:00:00+09:00")


def event(ticker, **overrides):
    spec = results._PROFILES[results._canonical(ticker)]
    return dict(dict(ticker=ticker, fiscal_period=spec["fiscal_period"], date=spec["release_date"]), **overrides)


def reconciliation(*, current_capex="(73,155)", current_fcf="(12,965)", ttm="999,999"):
    return f'''<div>Reconciliation from GAAP Net Cash Provided by Operating Activities to Non-GAAP Free Cash Flow (in millions; unaudited):</div>
    <table><tr><th rowspan="2">Measure</th><th colspan="4">Quarter Ended</th><th>TTM</th></tr>
    <tr><th>Q4 2025</th><th>Q1 2026</th><th>Q2 2026</th><th>Q3 2026</th><th>Q3 2026</th></tr>
    <tr><td>Net cash provided by operating activities</td><td>$ 10</td><td>20</td><td>30</td><td>60,190</td><td>{ttm}</td></tr>
    <tr><td>Less: purchases of property and equipment</td><td>(1)</td><td>(2)</td><td>(3)</td><td>{current_capex}</td><td>{ttm}</td></tr>
    <tr><td>Free cash flow</td><td>$ 9</td><td>18</td><td>27</td><td>{current_fcf}</td><td>{ttm}</td></tr></table>'''


def page(ticker="GOOGL", *, body=None, metadata="", title=None, release_date=None):
    spec = results._PROFILES[ticker]
    title = title or results._HEADINGS[ticker]
    day = datetime.fromisoformat(release_date or spec["release_date"]).strftime("%B %d, %Y")
    intro = f"{day} - {spec['name']} today announced financial results for the quarter ended September 30, 2026."
    period = "<p>First quarter of fiscal year 2027.</p>" if ticker == "MSFT" else ""
    if body is None:
        body = '<div><span>Revenue was $12.3 billion and increased 19%.</span></div><div><span>Operating income was $4.9 billion and increased 21%.</span></div>'
        body += reconciliation() if ticker == "GOOGL" else ""
        if ticker == "MSFT":
            body += '<p>Microsoft will provide forward-looking guidance in connection with this quarterly earnings announcement on its earnings conference call and webcast.</p>'
    heading = f"<div>{title}</div>" if ticker == "GOOGL" else f"<h1>{title}</h1>"
    return f"<html><head>{metadata}</head><body><main>{heading}<p>{intro}</p>{period}{body}</main></body></html>".encode()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    results.clear_earnings_result_cache()
    monkeypatch.setattr(results.requests, "get", lambda *a, **k: pytest.fail("unexpected network"))
    yield
    results.clear_earnings_result_cache()


@pytest.fixture
def provider(monkeypatch):
    state = dict(calls=[], closed=[], status=200, error=None, bodies={}, active=0, max_active=0, delay=0)
    urls = {spec["source_url"]: ticker for ticker, spec in results._PROFILES.items() if spec["source_url"]}
    lock = threading.Lock()
    class Response:
        def __init__(self, url):
            self.url, self.status_code = state.get("response_url", url), state["status"]
            self.data = state["bodies"].get(urls[url], page(urls[url]))
        def iter_content(self, chunk_size):
            assert chunk_size == 64 * 1024
            yield self.data
        def close(self):
            state["closed"].append(self.url)
            with lock:
                state["active"] -= 1
    def get(url, **kwargs):
        assert kwargs["timeout"] == (2, 4) and kwargs["allow_redirects"] is False and kwargs["stream"] is True
        state["calls"].append(url)
        if state["error"]:
            raise state["error"]
        with lock:
            state["active"] += 1
            state["max_active"] = max(state["active"], state["max_active"])
        time.sleep(state["delay"])
        return Response(url)
    monkeypatch.setattr(results.requests, "get", get)
    return state


def test_seven_issuer_scope_six_requests_future_nvda_and_alias_dedup(provider):
    provider["delay"] = .01
    payload = results.load_earnings_results([event(t) for t in results._PROFILES] + [event("GOOG"), event("005935.KS")], NOW)
    assert len(payload["results"]) == len(provider["calls"]) == len(provider["closed"]) == 6
    assert len(set(provider["calls"])) == 6 and provider["max_active"] <= 3
    assert next(s for s in payload["sources"] if s["ticker"] == "NVDA")["reason"] == "future_event"
    assert all(row["status"] == "official_result" and not row["stale"] for row in payload["results"])
    assert all(set(row["metrics"]) == {"revenue", "profit", "capex", "free_cash_flow", "guidance"} for row in payload["results"])


def test_sec_styled_div_metrics_and_exact_current_column():
    row = results.parse_earnings_result(page(), "GOOGL", NOW)
    assert row["metrics"]["revenue"]["text"] == "Revenue was $12.3 billion and increased 19%."
    assert row["metrics"]["profit"]["text"] == "Operating income was $4.9 billion and increased 21%."
    for key, value in [("capex", "(73,155)"), ("free_cash_flow", "(12,965)")]:
        metric = row["metrics"][key]
        assert metric["status"] == "reported" and metric["source_value"] == value
        assert metric["column"] == "Q3 2026" and metric["unit"] == "USD millions"
        assert "999,999" not in metric["text"]
    assert row["metrics"]["guidance"]["status"] == "missing"


@pytest.mark.parametrize("table", [
    reconciliation().replace("Q3 2026", "Q3 2025"),
    reconciliation().replace("Quarter Ended", "Nine Months Ended"),
    reconciliation().replace("in millions", "unit omitted"),
    reconciliation() + reconciliation(current_fcf="888,888"),
    '<table><tr><td>Free cash flow</td><td>2025</td><td>2026</td></tr><tr><td>90</td><td>100</td></tr></table>',
])
def test_ambiguous_or_wrong_period_reconciliation_is_missing(table):
    row = results.parse_earnings_result(page(body=table), "GOOGL", NOW)
    assert row["metrics"]["capex"]["status"] == row["metrics"]["free_cash_flow"]["status"] == "missing"


def test_guidance_deferred_is_distinct_from_missing_and_reported_forecast():
    row = results.parse_earnings_result(page("MSFT"), "MSFT", NOW)
    assert row["metrics"]["guidance"]["status"] == "deferred"
    assert row["metrics"]["capex"]["status"] == row["metrics"]["free_cash_flow"]["status"] == "missing"
    forecast = results.parse_earnings_result(page("MSFT", body='<p>We expect revenue in the next quarter to be between $20 billion and $21 billion.</p>'), "MSFT", NOW)
    assert forecast["metrics"]["guidance"]["status"] == "reported"
    assert forecast["metrics"]["guidance"]["period_scope"] == "management_outlook"
    assert forecast["metrics"]["revenue"]["status"] == "missing"


def test_samsung_company_totals_not_first_segment_and_capex_not_full_year_plan():
    body = '''<p>The DS Division posted KRW 9 trillion in consolidated revenue and KRW 3 trillion in operating profit.</p>
    <p>The Company posted KRW 20 trillion in consolidated revenue, another quarterly high.</p>
    <p>Operating profit reached KRW 5 trillion.</p>
    <p>Full-year capital expenditure is expected to reach KRW 8 trillion.</p>
    <p>In the third quarter, Samsung Electronics capital expenditure reached KRW 2 trillion.</p>'''
    row = results.parse_earnings_result(page("005930.KS", body=body), "005930.KS", NOW)
    assert "KRW 20 trillion" in row["metrics"]["revenue"]["text"]
    assert "KRW 5 trillion" in row["metrics"]["profit"]["text"]
    assert "KRW 2 trillion" in row["metrics"]["capex"]["text"]
    assert "KRW 8 trillion" in row["metrics"]["guidance"]["text"]


@pytest.mark.parametrize("old_period", ["Q1 FY2026", "Q2 FY2027", "FY2026Q1", "first quarter of fiscal year 2026"])
def test_msft_rejects_old_or_wrong_fiscal_period_before_current_revenue(old_period):
    body = f'<p>In {old_period}, revenue was $10 billion.</p><p>In Q1 FY2027, revenue was $20 billion.</p>'
    row = results.parse_earnings_result(page("MSFT", body=body), "MSFT", NOW)
    assert row["metrics"]["revenue"]["text"] == "In Q1 FY2027, revenue was $20 billion."
    old_only = results.parse_earnings_result(page("MSFT", body=f'<p>In {old_period}, revenue was $10 billion.</p>'), "MSFT", NOW)
    assert old_only["metrics"]["revenue"]["status"] == "missing"


@pytest.mark.parametrize("cumulative", ["nine-month", "nine months", "9 months", "year-to-date", "YTD", "cumulative"])
def test_samsung_quarterly_capex_does_not_use_first_cumulative_amount(cumulative):
    body = f'<p>Samsung {cumulative} capital expenditure reached KRW 20 trillion.</p><p>In the third quarter 2026, capital expenditure reached KRW 2 trillion.</p>'
    row = results.parse_earnings_result(page("005930.KS", body=body), "005930.KS", NOW)
    assert row["metrics"]["capex"]["text"] == "In the third quarter 2026, capital expenditure reached KRW 2 trillion."


@pytest.mark.parametrize("ticker,modified", [
    ("MSFT", "2026-10-30"), ("MSFT", "2026-10-30T12:00:00"),
    ("MSFT", "2026-10-28T23:01:00"), ("005930.KS", "2026-10-29T12:00:01"),
])
def test_naive_modified_date_and_datetime_cannot_pass_future_cutoff(ticker, modified):
    metadata = f'<meta property="article:modified_time" content="{modified}">'
    with pytest.raises(ValueError, match="page_version_after_cutoff"):
        results.parse_earnings_result(page(ticker, metadata=metadata), ticker, NOW)


def test_date_only_same_day_uses_observed_at_without_release_minute():
    row = results.parse_earnings_result(page("005930.KS"), "005930.KS", NOW)
    assert row["release_date"] == "2026-10-29" and row["release_precision"] == "date"
    assert row["release_at"] is None
    assert datetime.fromisoformat(row["observed_at"]) == NOW
    assert row["provenance"]["timing_basis"] == "date_only_observed_at"


def test_precise_publication_and_modified_dates_are_source_bound():
    meta = '<meta property="article:published_time" content="2026-10-28T16:05:00-04:00"><meta property="article:modified_time" content="2026-10-28T17:00:00-04:00">'
    row = results.parse_earnings_result(page(metadata=meta), "GOOGL", NOW)
    assert row["release_precision"] == "datetime" and row["release_at"] == "2026-10-28T20:05:00+00:00"


def test_same_date_conflicting_minutes_downgrade_not_invent_publication_time():
    meta = '<meta property="article:published_time" content="2026-10-28T16:05:00-04:00"><script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-10-28T16:10:00-04:00"}</script>'
    row = results.parse_earnings_result(page("MSFT", metadata=meta), "MSFT", NOW)
    assert row["release_precision"] == "date" and row["release_at"] is None
    assert row["provenance"]["publication_time_status"] == "conflicting_minutes_date_only"
    assert row["metrics"]["guidance"]["status"] == "deferred"


def test_utf8_source_fragment_preserves_punctuation():
    body = '<p>Revenue \u2013 Revenue was $12.3 billion.</p>'
    row = results.parse_earnings_result(page("META", body=body), "META", NOW)
    assert row["metrics"]["revenue"]["text"] == "Revenue \u2013 Revenue was $12.3 billion."


@pytest.mark.parametrize("change,reason", [
    (dict(title="Alphabet Announces Second Quarter 2026 Results"), "result_identity_or_period_mismatch"),
    (dict(title="Tesla Releases Third Quarter 2026 Financial Results"), "result_identity_or_period_mismatch"),
    (dict(release_date="2026-10-27"), "release_date_not_in_body"),
    (dict(metadata='<meta property="article:published_time" content="2026-10-27T16:05:00-04:00">'), "publication_date_mismatch"),
    (dict(metadata='<meta property="article:modified_time" content="2026-10-30T00:00:00Z">'), "page_version_after_cutoff"),
    (dict(metadata='<meta property="article:modified_time" content="2026-10-30">'), "page_version_after_cutoff"),
    (dict(release_date="2026-10-27", body='<p>The conference call is October 28, 2026.</p>'), "release_date_not_in_body"),
])
def test_wrong_identity_period_date_or_future_version_rejected(change, reason):
    with pytest.raises(ValueError, match=reason):
        results.parse_earnings_result(page(**change), "GOOGL", NOW)


def test_script_only_identity_schedule_and_wrong_period_related_link_do_not_pass():
    data = page().replace(b'<div>Alphabet Announces Third Quarter 2026 Results</div>', b'<script>Alphabet Announces Third Quarter 2026 Results</script>')
    with pytest.raises(ValueError):
        results.parse_earnings_result(data, "GOOGL", NOW)
    schedule = page("MSFT").replace(b'<h1>Microsoft announces first quarter results</h1>', b'<h1>Microsoft earnings release date</h1><h2>Microsoft announces first quarter results</h2>')
    with pytest.raises(ValueError, match="schedule_or_preview"):
        results.parse_earnings_result(schedule, "MSFT", NOW)
    old = page("META").replace(b'<h1>Meta Reports Third Quarter 2026 Results</h1>', b'<h1>Meta Reports Second Quarter 2026 Results</h1><h2>Meta Reports Third Quarter 2026 Results</h2>')
    with pytest.raises(ValueError, match="result_identity_or_period_mismatch"):
        results.parse_earnings_result(old, "META", NOW)


def test_future_same_day_timestamp_and_unknown_next_nvda_result(provider):
    now = datetime.fromisoformat("2026-10-28T15:00:00-04:00")
    provider["bodies"]["GOOGL"] = page(metadata='<meta property="article:published_time" content="2026-10-28T16:05:00-04:00">')
    payload = results.load_earnings_results([event("GOOGL")], now)
    assert not payload["results"] and payload["sources"][0]["reason"] == "publication_after_cutoff"
    assert not results.load_earnings_results([event("NVDA")], NOW.replace(month=11, day=18))["results"]
    assert len(provider["calls"]) == 1


def test_input_validation_and_urls_never_trigger_arbitrary_requests(provider):
    events = [event("GOOGL", fiscal_period="2026Q4"), event("MSFT", date="2026-10-29"),
              dict(ticker="UNKNOWN", fiscal_period="2026Q3", date="2026-10-28", source_url="http://127.0.0.1/secret")]
    assert not results.load_earnings_results(events, NOW)["results"]
    assert not provider["calls"]
    payload = results.load_earnings_results([event("GOOGL", source_url="http://127.0.0.1/secret")], NOW)
    assert payload["results"] and provider["calls"] == [results._PROFILES["GOOGL"]["source_url"]]
    assert not results.is_official_result_url("MSFT", results._PROFILES["GOOGL"]["source_url"])
    for suffix in ["?token=secret", "#fake", "/other"]:
        assert not results.is_official_result_url("GOOGL", results._PROFILES["GOOGL"]["source_url"] + suffix)
    assert results.is_official_result_url("GOOG", results._PROFILES["GOOGL"]["source_url"])


def test_success_cache_expiry_isolation_and_cutoff(provider, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(results.time, "monotonic", lambda: clock[0])
    first = results.load_earnings_results([event("GOOGL")], NOW)
    first["results"][0]["metrics"]["revenue"]["text"] = "mutated"
    second = results.load_earnings_results([event("GOOGL")], NOW + timedelta(minutes=5))
    assert second["results"][0]["collection_reason"] == "success_cache"
    assert second["results"][0]["metrics"]["revenue"]["text"] != "mutated" and len(provider["calls"]) == 1
    before = results.load_earnings_results([event("GOOGL")], NOW - timedelta(minutes=1))
    assert not before["results"] and before["sources"][0]["reason"] == "cached_observation_after_cutoff"
    assert len(provider["calls"]) == 1
    clock[0] += results.SUCCESS_TTL + 1
    results.load_earnings_results([event("GOOGL")], NOW + timedelta(hours=7))
    assert len(provider["calls"]) == 2


def test_last_success_failure_cooldown_expiry_and_secret_safe_diagnostics(provider, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(results.time, "monotonic", lambda: clock[0])
    first = results.load_earnings_results([event("MSFT")], NOW)["results"][0]
    clock[0] += results.SUCCESS_TTL + 1
    provider["error"] = requests.ReadTimeout("token=never-print-this")
    later = NOW + timedelta(hours=7)
    fallback = results.load_earnings_results([event("MSFT")], later)
    row = fallback["results"][0]
    assert row["stale"] and row["collection_reason"] == "last_success:request_failed:ReadTimeout"
    assert row["checked_at"] == first["checked_at"] and fallback["sources"][0]["fallback_used"]
    assert "never-print-this" not in json.dumps(fallback) + str(results._CACHE)
    results.load_earnings_results([event("MSFT")], later + timedelta(seconds=1))
    assert len(provider["calls"]) == 2
    clock[0] += results.FAILURE_TTL + 1
    provider["error"] = None
    assert not results.load_earnings_results([event("MSFT")], later + timedelta(minutes=2))["results"][0]["stale"]
    assert len(provider["calls"]) == 3
    expired = results.load_earnings_results([event("MSFT")], later + timedelta(days=8), refresh=False)
    assert not expired["results"]


def test_changed_page_invalidates_last_success_not_transport_fallback(provider, monkeypatch):
    results.load_earnings_results([event("GOOGL")], NOW)
    provider["bodies"]["GOOGL"] = page(title="Alphabet Announces Second Quarter 2026 Results")
    changed = results.load_earnings_results([event("GOOGL")], NOW + timedelta(hours=7))
    assert not changed["results"]
    assert not results.load_earnings_results([event("GOOGL")], NOW + timedelta(hours=8), refresh=False)["results"]


@pytest.mark.parametrize("status,reason", [(302, "http_302"), (403, "http_403"), (500, "http_500")])
def test_http_failure_no_redirect_or_retry(provider, status, reason):
    provider["status"] = status
    payload = results.load_earnings_results([event("META")], NOW)
    assert not payload["results"] and payload["sources"][0]["reason"] == reason
    assert len(provider["calls"]) == len(provider["closed"]) == 1


def test_response_size_and_redirected_url_are_rejected_and_closed(provider):
    provider["bodies"]["META"] = b"x" * (results.MAX_BYTES + 1)
    assert results.load_earnings_results([event("META")], NOW)["sources"][0]["reason"] == "page_too_large"
    provider["response_url"] = "https://example.com/not-official"
    assert results.load_earnings_results([event("TSLA")], NOW)["sources"][0]["reason"] == "response_url_not_allowed"
    assert len(provider["closed"]) == 2


def test_refresh_false_collection_cap_and_input_preservation(provider):
    events = [event("GOOGL"), event("MSFT")]
    before = deepcopy(events)
    assert not results.load_earnings_results(events, NOW, refresh=False)["results"]
    assert events == before and not provider["calls"]
    many = (dict(ticker=f"UNKNOWN{n}") for n in range(10_000))
    payload = results.load_earnings_results(many, NOW)
    assert len(payload["sources"]) == results.MAX_EVENTS + 1 and payload["sources"][-1]["reason"] == "event_limit"
    with pytest.raises(ValueError, match="offset-aware"):
        results.load_earnings_results(events, "2026-10-29")


@pytest.mark.parametrize("ticker,failure", [("GOOGL", 403), ("005930.KS", requests.ReadTimeout("private"))])
def test_transport_failure_uses_only_verified_pdf_and_caches_success(monkeypatch, ticker, failure):
    from stock_lab_core import earnings_result_pdf
    calls, closed = [], []
    primary = results._PROFILES[ticker]["source_url"]
    alternate = results._ALTERNATE_PDFS[ticker]
    expected = results.parse_earnings_result(page(ticker), ticker, NOW)
    expected["source_url"] = alternate
    # The transport contract is tested here; table/period parsing has separate fixtures.
    def parse(data, requested_ticker, spec, now):
        assert data == b"%PDF-fixture" and requested_ticker == ticker
        assert spec["source_url"] == alternate and now == NOW
        return deepcopy(expected)
    monkeypatch.setattr(earnings_result_pdf, "parse_official_result_pdf", parse)
    class Response:
        def __init__(self, url, status):
            self.url, self.status_code = url, status
        def iter_content(self, chunk_size):
            yield b"%PDF-fixture"
        def close(self):
            closed.append(self.url)
    def get(url, **kwargs):
        calls.append(url)
        assert not kwargs["allow_redirects"] and kwargs["timeout"] == results.REQUEST_TIMEOUT
        if url == primary:
            if isinstance(failure, Exception):
                raise failure
            return Response(url, failure)
        assert url == alternate and kwargs["headers"]["Accept"] == "application/pdf"
        return Response(url, 200)
    monkeypatch.setattr(results.requests, "get", get)
    payload = results.load_earnings_results([event(ticker)], NOW)
    row, diagnostic = payload["results"][0], payload["sources"][0]
    assert calls == [primary, alternate] and closed[-1] == alternate
    assert row["source_url"] == alternate and row["stale"] is False
    assert diagnostic["status"] == "connected" and diagnostic["alternate_used"]
    assert len(diagnostic["attempts"]) == 2 and diagnostic["attempts"][0]["status"] == "unavailable"
    assert "private" not in json.dumps(payload)
    again = results.load_earnings_results([event(ticker)], NOW + timedelta(minutes=1))
    assert again["sources"][0]["from_cache"] and len(calls) == 2


def test_pdf_allowlist_is_issuer_path_and_scheme_bound():
    for ticker, url in results._ALTERNATE_PDFS.items():
        assert results.is_official_result_url(ticker, url)
        assert not results.is_official_result_url("MSFT", url)
        for bad in (url.replace("https:", "http:"), url + "?download=1", url + "/other",
                    url.replace("2026", "2025"), url.replace("https://", "https://user@")):
            assert not results.is_official_result_url(ticker, bad)


def test_alternate_failure_is_bounded_and_does_not_confirm_result(monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        raise requests.ReadTimeout("private-response")
    monkeypatch.setattr(results.requests, "get", get)
    payload = results.load_earnings_results([event("GOOGL")], NOW)
    assert not payload["results"] and len(calls) == 2
    assert payload["sources"][0]["fallback_allowed"]
    assert len(payload["sources"][0]["attempts"]) == 2
    assert "private-response" not in json.dumps(payload)
    results.load_earnings_results([event("GOOGL")], NOW + timedelta(seconds=1))
    assert len(calls) == 2


def test_changed_primary_evidence_cannot_be_hidden_by_alternate(provider):
    provider["bodies"]["GOOGL"] = page(title="Alphabet Announces Second Quarter 2026 Results")
    payload = results.load_earnings_results([event("GOOGL")], NOW)
    assert not payload["results"] and len(provider["calls"]) == 1
    assert payload["sources"][0]["reason"] == "result_identity_or_period_mismatch"
