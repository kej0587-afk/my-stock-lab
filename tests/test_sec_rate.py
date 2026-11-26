"""App-wide SEC limiter (user decision A, 2026-11-27): 8/s window, access-limit pause, legacy fallback."""
from datetime import datetime, timedelta

import pytest
import requests

from stock_lab_core import sec_rate


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.slept += seconds


@pytest.fixture
def limiter(monkeypatch):
    monkeypatch.setattr(sec_rate, "_FORCED", False)
    clock = Clock()
    lim = sec_rate.SecLimiter(clock=clock, sleep=clock.sleep, wall=lambda: sec_rate.TRIAL_STARTS_AT)
    return lim, clock


def starts_in_any_window(times, window=1.0):
    return max(sum(1 for u in times if t <= u < t + window) for t in times)


def test_trial_never_exceeds_eight_in_any_second(limiter):
    lim, clock = limiter
    times = []
    for _ in range(40):
        lim.acquire()
        times.append(clock.now)
    assert starts_in_any_window(times) == 8 and lim.mode() == "trial_8"
    assert clock.now == pytest.approx(4.0)  # 40 requests at 8/s


def test_trial_ends_without_extension_and_forced_legacy(limiter, monkeypatch):
    lim, clock = limiter
    lim._wall = lambda: sec_rate.TRIAL_ENDS_AT + timedelta(seconds=1)
    assert lim.limit() == 5
    monkeypatch.setattr(sec_rate, "ADOPTED", True)
    assert lim.limit() == 8
    monkeypatch.setattr(sec_rate, "_FORCED", True)
    assert lim.limit() == 5


def test_access_limit_pauses_everything_then_second_limit_returns_to_legacy(limiter):
    lim, clock = limiter
    lim.acquire()
    lim.access_limited("30")
    with pytest.raises(sec_rate.SecRateLimited):
        lim.acquire()
    clock.now += 30
    lim.acquire()  # resumes after SEC's wait
    assert lim.mode() == "trial_8"
    lim.access_limited(None)
    assert lim.mode() == "legacy_5" and lim.status()["paused_seconds"] == pytest.approx(600)


def test_session_hook_counts_every_sec_send_once(monkeypatch):
    sent = []

    class Response:
        status_code, headers, text = 200, {}, ""

    monkeypatch.setattr(sec_rate, "_original_send", lambda self, request, **kw: sent.append(request.url) or Response())
    calls = []
    monkeypatch.setattr(sec_rate.limiter, "acquire", lambda: calls.append(1))
    session = requests.Session()
    session.get("https://data.sec.gov/submissions/CIK0000000001.json")
    session.get("https://example.com/")
    assert calls == [1] and len(sent) == 2
    with sec_rate.slot():
        session.get("https://www.sec.gov/files/company_tickers.json")
    assert calls == [1, 1]  # the prepaid slot is not charged twice


def test_429_from_sec_triggers_pause(monkeypatch):
    class Response:
        status_code, headers, text = 429, {"Retry-After": "12"}, ""

    monkeypatch.setattr(sec_rate, "_original_send", lambda self, request, **kw: Response())
    monkeypatch.setattr(sec_rate.limiter, "acquire", lambda: None)
    hits = []
    monkeypatch.setattr(sec_rate.limiter, "access_limited", lambda retry=None: hits.append(retry))
    requests.Session().get("https://data.sec.gov/x.json")
    assert hits == ["12"]
