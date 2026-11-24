"""KR (DART) issuers must not queue behind SEC fair-access waits (2026-11-24, status #5)."""
import threading
import time

from stock_lab_core import earnings_discovery_performance as profiling
from stock_lab_core import earnings_filing_sources as sources
from tests.test_earnings_filing_discovery import NOW, Response


def test_kr_issuer_starts_while_sec_workers_are_busy(monkeypatch):
    sources.clear_cache()
    started, busy, peak, lock = {}, [0], [0], threading.Lock()
    t0 = time.monotonic()
    original = profiling.FilingProbe.worker

    def worker(self, queued_at, collect, ticker):
        started[ticker] = time.monotonic() - t0
        return original(self, queued_at, collect, ticker)

    def slow_sec(*args, **kwargs):
        with lock:
            busy[0] += 1
            peak[0] = max(peak[0], busy[0])
        time.sleep(0.4)
        with lock:
            busy[0] -= 1
        raise ValueError("request_timeout")

    monkeypatch.setattr(profiling.FilingProbe, "worker", worker)
    monkeypatch.setattr(sources, "_sec_collect", slow_sec)
    get = lambda *a, **k: Response({"0": dict(ticker="AAA", cik_str=1)})
    us = ["AAA", "BBB", "CCC", "DDD"]
    result = sources.collect_filing_earnings([*us, "005930.KS"], NOW, sec_user_agent="Research test@example.test",
                                             dart_api_key="", get=get)
    assert started["005930.KS"] < 0.3  # Old shared 3-worker pool: >= 0.4s behind SEC work.
    assert peak[0] <= sources.MARKET_WORKERS == 3  # SEC concurrency unchanged.
    assert [row["ticker"] for row in result["sources"]] == [*us, "005930.KS"]  # Order preserved.
    kr = result["sources"][-1]
    assert kr["reason"] == "dart_api_key_missing" and not kr["attempted"]
    sources.clear_cache()
