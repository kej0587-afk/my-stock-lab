"""Measurements must not cache responses, expose credentials or alter outputs."""

from copy import deepcopy
from datetime import timedelta
import json
from unittest.mock import Mock

import pytest
import requests

from stock_lab_core import earnings_discovery_performance as profiling
from stock_lab_core import earnings_filing_sources as sources
from stock_lab_core.performance import PerformanceTrace, submit_with_context
from tests.test_earnings_filing_discovery import NOW, Response, submissions, release


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    sources.clear_cache()
    from stock_lab_core import sec_rate
    monkeypatch.setattr(sources.sec_rate, "limiter", sec_rate.SecLimiter())  # fresh app-wide SEC window
    yield
    sources.clear_cache()


def get_fixture():
    return Mock(side_effect=[Response({"0": dict(ticker="CYBR", cik_str=1234)}),
        Response(submissions()),
        Response(b'<table><tr><td>99.1</td><td><a href="results.htm">release</a></td></tr></table>'),
        Response(release())])


def test_rejection_counts_only_actual_validation_and_hides_unknown_exception_text(monkeypatch):
    args = dict(sec_user_agent="Research private@example.test", dart_api_key="", get=get_fixture())
    def refuse(*a, **k):
        raise ValueError("release_dateline_unavailable")
    monkeypatch.setattr(sources, "parse_sec_release", refuse)
    with PerformanceTrace() as first:
        result = sources.collect_filing_earnings(["CYBR"], NOW, **args)
    with PerformanceTrace() as cached:
        again = sources.collect_filing_earnings(["CYBR"], NOW + timedelta(seconds=1), **args)
    assert result["sources"][0]["reason"] == again["sources"][0]["reason"] == "release_dateline_unavailable"
    assert first.report()["transport_events"]["earnings_discovery.sec_release.release_dateline_unavailable"] == 1
    assert not any(k.startswith("earnings_discovery.sec_release.") for k in cached.report()["transport_events"])
    with PerformanceTrace() as private:
        profiling.release_validation_event("https://example.test/private?secret=value")
    assert private.report()["transport_events"] == {"earnings_discovery.sec_release.other_validation_error": 1}


def test_cold_and_warm_measurements_preserve_collection_and_freshness():
    get = get_fixture()
    args = dict(sec_user_agent="Research private@example.test", dart_api_key="", get=get)
    tickers = ["CYBR", "CYBR"]
    with PerformanceTrace() as cold:
        first = sources.collect_filing_earnings(tickers, NOW, **args)
    with PerformanceTrace() as warm:
        second = sources.collect_filing_earnings(tickers, NOW + timedelta(seconds=10), **args)
    assert len(first["results"]) == 1 and first["results"] == second["results"]
    assert first["events"] == second["events"]
    assert tickers == ["CYBR", "CYBR"] and get.call_count == 4
    assert not first["sources"][0]["from_cache"] and second["sources"][0]["from_cache"]
    assert not second["sources"][0]["attempted"]
    report = cold.report()
    events = report["transport_events"]
    assert events["earnings_discovery.http.sec.attempt"] == 4
    assert events["earnings_discovery.http.sec.unique_identity"] == 4
    assert events.get("earnings_discovery.http.sec.duplicate_identity", 0) == 0
    assert events["earnings_discovery.workers_started"] == 1
    assert events["earnings_discovery.cache.issuer_accounts_v1.miss"] == 1
    assert events["earnings_discovery.sec_release.accepted"] == 1
    names = {row["name"] for row in report["functions"]}
    assert {"earnings_discovery.setup_sec", "earnings_discovery.worker_join",
            "earnings_discovery.worker", "earnings_discovery.sec_rate_wait",
            "earnings_discovery.http_get.sec", "earnings_discovery.http_body",
            "earnings_discovery.parse_json", "earnings_discovery.parse_sec_release"} <= names
    warm_events = warm.report()["transport_events"]
    assert not any(key.endswith(".attempt") for key in warm_events)
    assert not any(key.startswith("earnings_discovery.sec_release.") for key in warm_events)
    assert warm_events["earnings_discovery.cache.issuer_accounts_v1.hit"] == 1
    assert warm_events["earnings_discovery.cache.sec_directory.hit"] == 1
    assert sources.CACHE_TTL == 600 and sources.FAILURE_TTL == 90 and sources.MAX_SECONDS == 24
    encoded = json.dumps(report)
    assert all(value not in encoded for value in ("private@example", "CYBR", "CIK", "sec.gov", "User-Agent"))


def test_duplicate_measurement_never_suppresses_retries_or_mutates_arguments():
    get = Mock(side_effect=[object(), object(), object(), object()])
    probe = profiling.FilingProbe(get)
    kwargs = dict(params={"crtfc_key": "private-key", "corp_code": "123"}, timeout=5)
    original = deepcopy(kwargs)
    with PerformanceTrace() as trace:
        first = probe.request("https://opendart.fss.or.kr/api/list.json", **kwargs)
        second = probe.request("https://opendart.fss.or.kr/api/list.json", **kwargs)
        probe.request("https://opendart.fss.or.kr/api/list.json", **dict(kwargs, timeout=6))
        probe.request("https://opendart.fss.or.kr/api/list.json", params={"crtfc_key": "another-key"}, timeout=5)
        probe.finish()
    events = trace.report()["transport_events"]
    assert first is not second and get.call_count == 4 and kwargs == original
    assert events["earnings_discovery.http.dart.attempt"] == 4
    assert events["earnings_discovery.http.dart.unique_identity"] == 3
    assert events["earnings_discovery.http.dart.duplicate_identity"] == 1
    assert "private-key" not in json.dumps(trace.report())
    assert "another-key" not in json.dumps(trace.report())


def test_failed_http_and_failure_cache_are_distinct():
    get = Mock(side_effect=requests.Timeout("private-secret-url"))
    kwargs = dict(sec_user_agent="Research private@example.test", dart_api_key="", get=get)
    with PerformanceTrace() as trace:
        one = sources.collect_filing_earnings(["CYBR"], NOW, **kwargs)
        two = sources.collect_filing_earnings(["CYBR"], NOW + timedelta(seconds=1), **kwargs)
    assert one["sources"][0]["reason"] == two["sources"][0]["reason"] == "request_timeout"
    assert get.call_count == 1
    events = trace.report()["transport_events"]
    assert events["earnings_discovery.http.sec.attempt"] == 1
    assert events["earnings_discovery.cache.sec_directory.failure_hit"] == 1
    assert "private-secret-url" not in json.dumps(trace.report())


def test_queue_metrics_are_durations_and_context_reaches_workers(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(profiling, "monotonic", lambda: 3.)
    collect = Mock(return_value="same-output")
    probe = profiling.FilingProbe(Mock())
    with PerformanceTrace() as trace:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = submit_with_context(pool, probe.worker, 1.5, collect, "CYBR").result()
        probe.finish()
    assert result == "same-output"
    collect.assert_called_once_with("CYBR")
    events = trace.report()["transport_events"]
    assert events["earnings_discovery.workers_started"] == 1
    assert events["earnings_discovery.queue_wait_us_total"] == 1_500_000
    assert events["earnings_discovery.collections"] == 1
    assert events["earnings_discovery.queue_wait_us_max_sum"] == 1_500_000
    assert not any("http" in key for key in events)


def test_each_execution_has_its_own_request_identity_set():
    with PerformanceTrace() as trace:
        for _ in range(2):
            probe = profiling.FilingProbe(Mock())
            probe.request("https://data.sec.gov/example.json", headers={"User-Agent": "secret"})
            probe.finish()
    events = trace.report()["transport_events"]
    assert events["earnings_discovery.http.sec.unique_identity"] == 2
    assert not events.get("earnings_discovery.http.sec.duplicate_identity")
