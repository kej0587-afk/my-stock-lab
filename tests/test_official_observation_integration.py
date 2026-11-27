"""Privacy and exceptional pool behavior of observation-only integration."""

from concurrent.futures import Future
from copy import deepcopy
import json

import pandas as pd
import pytest

from stock_lab_core import economic_consensus as consensus
from stock_lab_core import report_dashboard as dashboard
from stock_lab_core.report_generation_performance import generation_measurement, record_official_coverage
from tests.test_economic_consensus import NOW, PUBLIC_TARGET, Response, public_html, public_load


@pytest.mark.parametrize("field", ["economic_releases", "calendar_events", "calendar_sources",
    "earnings_results", "earnings_result_sources", "earnings_sources", "central_bank_results"])
def test_coverage_statuses_are_fixed_labels_without_mutating_input(field):
    normal = ["released", "stale", "pending", "connected", "official_result", "official_filing_result",
              "official", "verified_snapshot", "공식 실적 발표", "공식 정기보고서 확인"]
    rows = [{"status": status} for status in normal]
    rows += [{}, {"status": "private@example.test?api_key=SECRET"}, {"status": ["PRIVATE_LIST"]},
             {"status": {"PRIVATE_KEY": "PRIVATE_VALUE"}}, {"status": None}, {"status": 200}]
    context = {field: rows}
    original = deepcopy(context)
    state = {}
    with generation_measurement(state):
        record_official_coverage(context)
        state["today_market_memo_text"] = "unchanged report"
    report = state["auto_report_performance"]
    assert report["official_coverage"][field] == {
        "rows": len(rows), "with_actual": 0,
        "statuses": {**dict.fromkeys(normal, 1), "unspecified": 1, "other": 5},
    }
    assert context == original and state["today_market_memo_text"] == "unchanged report"
    assert all(value not in json.dumps(report) for value in ("private@", "SECRET", "PRIVATE_"))


def test_unknown_status_does_not_call_untrusted_string_or_hash_methods():
    class Untrusted:
        def __str__(self):
            pytest.fail("must not stringify arbitrary status")
        def __hash__(self):
            pytest.fail("must not hash arbitrary status")
    state = {}
    with generation_measurement(state):
        record_official_coverage({"calendar_events": [{"status": Untrusted()}]})
    assert state["auto_report_last_attempt"]["official_coverage"]["calendar_events"]["statuses"] == {"other": 1}


class DeferredFuture(Future):
    """Execute deterministically on consumption, keeping later work pending."""
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.task = fn, args, kwargs

    def result(self, timeout=None):
        if not self.done() and self.set_running_or_notify_cancel():
            fn, args, kwargs = self.task
            try:
                self.set_result(fn(*args, **kwargs))
            except BaseException as error:
                self.set_exception(error)
        return super().result(timeout)


class DeferredPool:
    """Model shutdown(wait=True): uncancelled queued work still runs on exit."""
    instances = []
    def __init__(self, max_workers):
        assert max_workers == 4
        self.futures = []
        self.instances.append(self)

    def __enter__(self):
        return self

    def submit(self, fn, *args, **kwargs):
        future = DeferredFuture(fn, args, kwargs)
        self.futures.append(future)
        return future

    def __exit__(self, *exc):
        for future in self.futures:
            if not future.done():
                future.result()


@pytest.mark.parametrize("path", ["consensus", "fred"])
@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_worker_failure_cancels_pending_work_and_preserves_exception(monkeypatch, path, failure_index, error_type):
    error = error_type("synthetic worker failure")
    calls = []
    monkeypatch.setattr(DeferredPool, "instances", [])
    if path == "consensus":
        consensus.clear_economic_consensus_cache()
        monkeypatch.setattr(consensus, "ThreadPoolExecutor", DeferredPool)
        rows, bodies = [], {}
        for spec, (url, title, category, domain) in consensus._PUBLIC_PAGES.items():
            rows.append({**PUBLIC_TARGET, "indicator": spec[0], "basis": spec[1], "unit": spec[2],
                         "source_url": "https://api." + domain + "/observations",
                         "release_source_url": "https://www." + domain + "/release"})
            bodies[url] = public_html(title=title, category=category,
                                      forecast="125K" if spec[2] == "thousand persons" else "0.2%")
        order = sorted(bodies)
        def fetch(url, **kwargs):
            calls.append(url)
            if url == order[failure_index]:
                raise error
            return Response([], raw=bodies[url])
        run = lambda: public_load(fetch, rows)
    else:
        import concurrent.futures
        from stock_lab_core import macro_monitor
        monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", DeferredPool)
        order = list(dashboard.OBSERVATORY_FRED)
        def loader(symbol, years, as_of):
            calls.append(symbol)
            return pd.Series([1.0], index=pd.to_datetime(["2026-10-20"]), name=symbol), ""
        original = macro_monitor.observation
        def observation(item, series, clock, reason):
            if series.name == order[failure_index]:
                raise error
            return original(item, series, clock, reason)
        monkeypatch.setattr(macro_monitor, "observation", observation)
        run = lambda: dashboard.observatory_fred_observations(NOW, loader=loader)
    try:
        with pytest.raises(error_type) as caught:
            run()
        assert caught.value is error
        assert calls == order[:failure_index + 1]
        futures = DeferredPool.instances[0].futures
        assert len(futures) == len(order)
        assert all(future.cancelled() for future in futures[failure_index + 1:])
        assert all(not future.cancelled() for future in futures[:failure_index + 1])
    finally:
        consensus.clear_economic_consensus_cache()
