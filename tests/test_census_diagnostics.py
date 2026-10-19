import logging

import pytest
import requests

from stock_lab_core import economic_releases as releases


@pytest.mark.parametrize("status,bad_json", [(403, False), (200, True)])
def test_census_http_diagnostics_never_log_key_or_body(monkeypatch, caplog, status, bad_json):
    class Response:
        status_code = status
        closed = False

        def json(self):
            if bad_json:
                raise ValueError("private-key-in-response")
            return []

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(releases.requests, "get", lambda *a, **k: response)
    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        releases._request(releases.CENSUS_URL, params={"key": "private-key", "time": "from 2025-01 to 2026-10",
                                                       "category_code": "44X72", "unexpected": "private-key"})
    assert response.closed and f"HTTP={status}" in caplog.text
    assert "44X72" in caplog.text and "2026-10" in caplog.text
    assert "private-key" not in caplog.text


def test_census_timeout_does_not_log_credential_bearing_exception(monkeypatch, caplog):
    def timeout(*args, **kwargs):
        raise requests.Timeout("https://example.org?key=private-key")
    monkeypatch.setattr(releases.requests, "get", timeout)
    with pytest.raises(requests.Timeout):
        releases._request(releases.CENSUS_URL, params={"key": "private-key"})
    assert "transport=Timeout" in caplog.text and "private-key" not in caplog.text
