"""Offline observation contracts: identical results/order, real send vs get, no IDs."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
import json
import threading
from unittest.mock import Mock

import pytest
import requests

from stock_lab_core import earnings_collection as collection
from stock_lab_core import earnings_dart_directory as directory
from stock_lab_core import earnings_discovery_performance as audit
from stock_lab_core import earnings_filing_sources as filings
from stock_lab_core import earnings_result_sources as results
from stock_lab_core import earnings_sources as schedules
from stock_lab_core import sec_rate
from stock_lab_core.performance import PerformanceTrace
from tests.test_earnings_filing_discovery import NOW, Response, dart_payload
from tests.test_earnings_discovery_performance import get_fixture
from tests.test_earnings_dart_financials import COMPANY, CORP, TICKER, payload, setup_codes
from tests.test_earnings_result_sources import NOW as IR_NOW, event, page


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for module, name in ((filings, "clear_cache"), (results, "clear_earnings_result_cache"),
                         (schedules, "clear_earnings_source_cache")):
        getattr(module, name)()
    monkeypatch.setattr(sec_rate, "_FORCED", False)
    monkeypatch.setattr(sec_rate, "limiter", sec_rate.SecLimiter())
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("Unexpected network"))
    yield
    filings.clear_cache()
    results.clear_earnings_result_cache()
    schedules.clear_earnings_source_cache()


def counts(trace):
    return trace.report()["transport_events"]


def names(trace):
    return {row["name"] for row in trace.report()["functions"]}


def test_sec_trace_on_off_identical_outputs_requests_cache_and_cutoff(monkeypatch):
    monkeypatch.setattr(filings.time, "monotonic", lambda: 100.)
    runs = []
    for enabled in (False, True):
        filings.clear_cache()
        get = get_fixture()
        trace = PerformanceTrace()
        with trace if enabled else nullcontext():
            cold = filings.collect_filing_earnings(["CYBR", "CYBR"], NOW,
                sec_user_agent="private-agent", dart_api_key="", get=get)
            warm = filings.collect_filing_earnings(["CYBR"], NOW + timedelta(seconds=1),
                sec_user_agent="private-agent", dart_api_key="", get=get)
        runs.append((cold, warm, get.call_args_list))
    assert runs[0] == runs[1]
    assert len(runs[0][2]) == 4
    events = counts(trace)
    assert events["earnings_collection.sec.get_calls"] == 4
    assert events["earnings_collection.sec.get.response.200"] == 4
    assert not events.get("earnings_collection.sec.http.attempt")  # injected get, no Session.send
    assert events["earnings_discovery.cache.sec_archive.miss"] == 2
    assert events["earnings_collection.coverage.filing.events"] == 2
    assert events["earnings_collection.coverage.filing.results"] == 2
    assert events["earnings_collection.coverage.filing.metrics.reported"] == 10
    assert {"earnings_discovery.cache.lock_wait", "earnings_discovery.cache_store",
            "earnings_discovery.archive_store", "earnings_discovery.select_sec_filing"} <= names(trace)
    encoded = json.dumps(trace.report())
    assert all(value not in encoded for value in ("CYBR", "private-agent", "sec.gov", "CIK", "https://"))


def test_dart_cfs_ofs_order_and_warm_cache_are_preserved(monkeypatch):
    setup_codes(monkeypatch)
    monkeypatch.setattr(filings.time, "monotonic", lambda: 100.)
    runs = []
    for enabled in (False, True):
        filings.clear_cache()
        get = Mock(side_effect=[Response(dart_payload()), Response(COMPANY),
                               Response({"status": "013"}), Response(payload())])
        trace = PerformanceTrace()
        with trace if enabled else nullcontext():
            cold = filings.collect_filing_earnings([TICKER], NOW, sec_user_agent="", dart_api_key="private-key", get=get)
            warm = filings.collect_filing_earnings([TICKER], NOW + timedelta(seconds=1), sec_user_agent="", dart_api_key="private-key", get=get)
        runs.append((cold, warm, get.call_args_list))
    assert runs[0] == runs[1]
    assert [call.kwargs["params"].get("fs_div") for call in runs[0][2]] == [None, None, "CFS", "OFS"]
    events = counts(trace)
    assert events["earnings_collection.dart.get_calls"] == 4
    assert events["earnings_collection.dart.api_status.000"] == 3
    assert events["earnings_collection.dart.api_status.013"] == 1
    assert events["earnings_discovery.cache.dart_accounts.hit"] == 1
    assert {"earnings_discovery.dart_setup_wait", "earnings_discovery.parse_dart_financials",
            "earnings_collection.dart_directory.snapshot_store"} <= names(trace)
    assert "private-key" not in json.dumps(trace.report()) and TICKER not in json.dumps(trace.report())


@pytest.mark.parametrize("source,url", [("dart_directory", "https://opendart.fss.or.kr/start"),
                                        ("ir_html", "https://example.test/start")])
def test_real_send_boundary_counts_redirects_without_changing_request(source, url):
    sent = []

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            sent.append((request.url, kwargs))
            response = requests.Response()
            response.status_code = 302 if request.url == url else 200
            response.url, response.request, response._content = request.url, request, b"body"
            if response.status_code == 302:
                response.headers["Location"] = "/final"
            return response

        def close(self):
            pass

    with requests.Session() as session:
        session.mount("https://", Adapter())
        with PerformanceTrace() as trace:
            response = audit.observed_get(source, session.get, url, timeout=5)
    assert response.content == b"body" and [r.status_code for r in response.history] == [302]
    assert [item[0] for item in sent] == [url, url.rsplit("/", 1)[0] + "/final"]
    events = counts(trace)
    prefix = "earnings_collection." + source
    assert events[prefix + ".get_calls"] == 1
    assert events[prefix + ".http.attempt"] == 2
    assert events[prefix + ".http.response.302"] == events[prefix + ".http.response.200"] == 1
    assert not events.get("sec.http.attempt")


def test_sec_admission_is_not_a_send_and_prepaid_slot_is_not_double_counted(monkeypatch):
    response = Mock(status_code=200, history=[])
    transport = Mock(return_value=response)
    monkeypatch.setattr(sec_rate, "_original_send", transport)
    with PerformanceTrace() as trace:
        with sec_rate.slot():
            returned = audit.observed_get("sec", requests.Session().get, "https://data.sec.gov/private")
    assert returned is response and transport.call_count == 1
    assert counts(trace)["sec.request"] == counts(trace)["sec.http.attempt"] == 1
    sec_rate.limiter.access_limited("10")
    with PerformanceTrace() as blocked:
        with pytest.raises(sec_rate.SecRateLimited):
            audit.observed_get("sec", requests.Session().get, "https://data.sec.gov/private")
    assert not counts(blocked).get("earnings_collection.sec.http.attempt")
    assert counts(blocked)["sec.blocked_by_access_limit"] == 1
    assert transport.call_count == 1


def test_transport_error_is_counted_and_context_does_not_leak(monkeypatch):
    transport = Mock(side_effect=requests.Timeout("https://secret.test/?key=private"))
    monkeypatch.setattr(sec_rate, "_original_send", transport)
    with PerformanceTrace() as trace:
        with pytest.raises(requests.Timeout):
            audit.observed_get("ir_html", requests.Session().get, "https://example.test/private")
        with pytest.raises(requests.Timeout):
            requests.Session().get("https://example.test/unrelated")
    assert counts(trace)["earnings_collection.ir_html.http.attempt"] == 1
    assert counts(trace)["earnings_collection.ir_html.http.transport_error"] == 1
    assert counts(trace)["earnings_collection.ir_html.get.transport_error"] == 1
    assert "secret.test" not in json.dumps(trace.report())


@pytest.mark.parametrize("status", [200, 503])
def test_ir_result_worker_context_and_cache_preserve_exact_output(monkeypatch, status):
    monkeypatch.setattr(results.time, "monotonic", lambda: 100.)
    runs = []
    for enabled in (False, True):
        results.clear_earnings_result_cache()
        response = Mock(status_code=status, url=results._PROFILES["MSFT"]["source_url"])
        response.iter_content = lambda **kw: iter([page("MSFT")])
        get = Mock(return_value=response)
        monkeypatch.setattr(results.requests, "get", get)
        trace = PerformanceTrace()
        with trace if enabled else nullcontext():
            cold = results.load_earnings_results([event("MSFT")], IR_NOW)
            warm = results.load_earnings_results([event("MSFT")], IR_NOW + timedelta(seconds=1))
        runs.append((cold, warm, get.call_args_list))
    assert runs[0] == runs[1] and len(runs[0][2]) == 1
    events = counts(trace)
    assert events["earnings_collection.ir_html.get_calls"] == 1
    assert events["earnings_collection.ir_result.cache.miss"] == 1
    outcome = "hit" if status == 200 else "failure_hit"
    assert events["earnings_collection.ir_result.cache." + outcome] == 1
    assert {"earnings_collection.ir_result.issuer.lock_wait", "earnings_collection.ir_result.cache_store",
            "earnings_collection.ir_result.ordered_join_wait"} <= names(trace)
    if status == 200:
        assert {"earnings_collection.ir_html.body", "earnings_collection.ir_html.transform"} <= names(trace)


def test_ir_schedule_worker_context_and_cache_preserve_output(monkeypatch):
    from tests.test_official_earnings_sources import NOW as SCHEDULE_NOW
    spec = schedules._ISSUERS["MSFT"]
    response = Mock(status_code=200, content=b"page", text=" ".join(spec["evidence"]))
    get = Mock(return_value=response)
    monkeypatch.setattr(schedules.requests, "get", get)
    with PerformanceTrace() as trace:
        cold = schedules.load_official_earnings(["MSFT"], SCHEDULE_NOW)
        warm = schedules.load_official_earnings(["MSFT"], SCHEDULE_NOW)
    assert cold["events"] == warm["events"] and get.call_count == 1
    assert counts(trace)["earnings_collection.ir_schedule.get_calls"] == 1
    assert counts(trace)["earnings_collection.ir_schedule.cache.hit"] == 1
    assert counts(trace)["earnings_collection.ir_schedule.cache.miss"] == 1
    assert counts(trace)["earnings_collection.coverage.ir_schedule.events"] == 2


def test_budget_skipped_rows_count_each_market_without_issuing_http(monkeypatch):
    setup_codes(monkeypatch)
    monkeypatch.setattr(filings.time, "monotonic", lambda: 100.)
    get = Mock(return_value=Response({"0": {"ticker": "CYBR", "cik_str": 1234}}))
    filings.collect_filing_earnings([], NOW, sec_user_agent="ua", dart_api_key="key", get=get)
    # Reuse setup only; consume the same deadline at the original before-issuer check.
    original_cached = filings._cached
    def cached(key, *args, **kwargs):
        if key[0] == "issuer_accounts_v1":
            monkeypatch.setattr(filings.time, "monotonic", lambda: 124.)
        return original_cached(key, *args, **kwargs)
    monkeypatch.setattr(filings, "_cached", cached)
    with PerformanceTrace() as trace:
        output = filings.collect_filing_earnings(["CYBR", TICKER], NOW,
            sec_user_agent="ua", dart_api_key="key", get=get)
    assert [row["ticker"] for row in output["sources"]] == ["CYBR", TICKER]
    assert all(row["reason"] == "collection_time_budget" for row in output["sources"])
    assert get.call_count == 1  # SEC directory only
    assert counts(trace)["earnings_discovery.time_budget.before_issuer"] == 2
    for market in ("KR", "US"):
        assert counts(trace)["earnings_collection.coverage.filing." + market + ".time_budget_skipped"] == 1


def test_body_budget_and_pre_request_budget_are_separate(monkeypatch):
    clock = [100.]
    monkeypatch.setattr(filings.time, "monotonic", lambda: clock[0])
    response = Response(b"body")
    def chunks(size):
        clock[0] = 125.
        yield b"body"
    response.iter_content = chunks
    get = Mock(return_value=response)
    with PerformanceTrace() as trace:
        with pytest.raises(ValueError, match="collection_time_budget"):
            filings._request("https://opendart.fss.or.kr/api/list.json", deadline=124., get=get)
        with pytest.raises(ValueError, match="collection_time_budget"):
            filings._request("https://opendart.fss.or.kr/api/list.json", deadline=124., get=get)
    assert get.call_count == 1
    assert counts(trace)["earnings_discovery.time_budget.body"] == 1
    assert counts(trace)["earnings_discovery.time_budget.before_request"] == 1


def test_directory_persisted_cache_and_retry_store_are_separate(monkeypatch):
    from stock_lab_core import dart_corporate_codes as codes, dart_corporate_snapshot as snapshot
    live = codes.CorporateCodeMap({"123456": CORP}, diagnostic={"cause": "ok"})
    failed = codes.CorporateCodeMap(diagnostic={"cause": "timeout"})
    fetch = Mock(side_effect=[failed, live])
    monkeypatch.setattr(codes, "fetch_corporate_codes", fetch)
    monkeypatch.setattr(snapshot, "fresh_corporate_codes", lambda **kw: None)
    def store(data, **kw):
        data.diagnostic["persist_status"] = "saved"
        return data
    monkeypatch.setattr(snapshot, "use_corporate_snapshot", store)
    monkeypatch.setattr(directory.time, "monotonic", lambda: 100.)
    with PerformanceTrace() as trace:
        output = directory.prepare_directory("secret-key", NOW, 124., Mock())
        monkeypatch.setattr(snapshot, "fresh_corporate_codes", lambda **kw: live)
        again = directory.prepare_directory("secret-key", NOW, 124., Mock())
    assert output[0] == again[0] == dict(live)
    assert output[1]["mapping_attempts"] == 2 and again[1]["mapping_attempts"] == 0
    assert fetch.call_count == 2 and all(call.kwargs["timeout"] == 5 for call in fetch.call_args_list)
    assert counts(trace)["earnings_collection.dart_directory.retry"] == 1
    assert counts(trace)["earnings_collection.dart_directory.store.saved"] == 1
    assert counts(trace)["earnings_collection.dart_directory.persisted_cache.hit"] == 1
    assert counts(trace)["earnings_collection.dart_directory.persisted_cache.miss"] == 1


def test_lock_timer_excludes_work_and_always_releases():
    clock = [0.]
    class Lock:
        held = False
        def acquire(self):
            clock[0] += 2
            self.held = True
        def release(self):
            self.held = False
    lock = Lock()
    with PerformanceTrace(clock=lambda: clock[0]) as trace:
        with pytest.raises(ValueError):
            with audit.observed_lock(lock, "fixed"):
                assert lock.held
                clock[0] += 10
                raise ValueError("no payload retained")
    assert not lock.held
    assert trace.report()["functions"][0]["total_seconds"] == 2
    real = threading.RLock()
    with audit.observed_lock(real, "fixed"), audit.observed_lock(real, "fixed"):
        pass


def test_collection_cap_order_and_coverage_do_not_mutate_rows(monkeypatch):
    from stock_lab_core import earnings_discovery as discovery
    rows = [dict(ticker=f"S{i}", verdict="blocked", score=7) for i in range(100)]
    before = deepcopy(rows)
    catalog = {row["ticker"]: dict(registered=True, held=i == 99) for i, row in enumerate(rows)}
    monkeypatch.setattr(discovery, "issuer_catalog", lambda rows: catalog)
    filing_call = Mock(return_value=dict(events=[], results=[], sources=[]))
    monkeypatch.setattr(filings, "collect_filing_earnings", filing_call)
    monkeypatch.setattr(schedules, "load_official_earnings", Mock(return_value=dict(events=[], sources=[])))
    monkeypatch.setattr(results, "load_earnings_results", Mock(return_value=dict(results=[], sources=[])))
    with PerformanceTrace() as trace:
        output = collection.collect_report_earnings(rows, {"events": []}, NOW)
    order = ["S99", *[f"S{i}" for i in range(95)]]
    assert filing_call.call_args.args == (order, NOW)
    assert output["earnings_collection_scope"]["submitted"] == order
    assert rows == before
    assert counts(trace)["earnings_collection.submitted"] == 96
    assert counts(trace)["earnings_collection.cap_skipped"] == 4
    assert "earnings_collection.merge_transform" in names(trace)


def test_untrusted_provider_status_and_coverage_reasons_never_become_labels():
    with PerformanceTrace() as trace:
        audit.dart_status_event("private-key")
        audit.coverage_event("private-issuer", sources=[{"ticker": "SECRET.KS", "reason": "private-url",
                             "financial_reason": "collection_time_budget", "status": "connected"}])
    assert counts(trace)["earnings_collection.dart.api_status.other"] == 1
    assert counts(trace)["earnings_collection.coverage.other.KR.time_budget_skipped"] == 1
    assert all(value not in json.dumps(trace.report()) for value in ("private", "SECRET"))
