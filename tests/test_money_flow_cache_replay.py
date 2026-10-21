"""Exercise real Streamlit message replay, not just bare-mode cache hits."""

import json
from contextlib import contextmanager

import numpy as np
import pandas as pd
import pytest
import requests
from streamlit.testing.v1 import AppTest

from stock_lab_core import money_flow as flow


def injected_payload():
    days = np.arange(150)
    close = 100 + days * 0.1 + np.sin(days)
    quote = {"open": close.tolist(), "close": close.tolist(),
             "high": (close + 2).tolist(), "low": (close - 2).tolist(),
             "volume": (1000 + days * 2).tolist()}
    timestamps = (pd.bdate_range("2025-01-02", periods=150).asi8 // 10**9).tolist()
    return {"chart": {"result": [{"timestamp": timestamps,
            "indicators": {"quote": [quote], "adjclose": [{"adjclose": close.tolist()}]}}]}}


@contextmanager
def injected_provider(monkeypatch):
    calls = []
    payload = json.dumps(injected_payload()).encode()

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield payload

    def request(url, **kwargs):
        calls.append((url, kwargs))
        if request.fail:
            raise requests.ReadTimeout("injected timeout")
        return Reply()

    request.fail = False
    universe = [{"ticker": "4062.T", "name": f"member-{i}",
                 "테마": theme, "하위테마": "sub", "구분": "JP", "섹터": theme,
                 "랭킹보조점수": float(i)} for i, theme in enumerate(["A", "B"])]
    monkeypatch.setattr(requests, "get", request)
    monkeypatch.setattr(flow, "_FDR_AVAILABLE", True)
    monkeypatch.setattr(flow, "_AV_API_KEY", "")
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    monkeypatch.setattr(flow, "IMAGE_THEME_UNIVERSE", universe)
    monkeypatch.setattr(flow, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    caches = (flow._fetch_fdr_ohlc, flow.calculate_image_theme_flow_df, flow.calculate_money_flow_df)
    for cached in caches:
        cached.clear()
    try:
        yield calls, request
    finally:
        for cached in caches:
            cached.clear()


@pytest.fixture
def injected_flow(monkeypatch):
    with injected_provider(monkeypatch) as injected:
        yield injected


@pytest.mark.parametrize("fail", [False, True], ids=["success", "timeout"])
@pytest.mark.parametrize("path", ["fallback", "theme_hit", "theme_miss", "etf_hit", "etf_miss"])
def test_cached_flow_never_replays_external_progress_container(injected_flow, path, fail):
    calls, request = injected_flow
    request.fail = fail
    expression = ("flow._fetch_fdr_ohlc('4062.T')" if path == "fallback" else
                  "flow.calculate_image_theme_flow_df('')" if path.startswith("theme") else
                  "flow.calculate_money_flow_df()")
    source = f'''
import streamlit as st
from stock_lab_core import money_flow as flow
from stock_lab_core.performance import PerformanceTrace, measure
progress = st.empty()
with PerformanceTrace(on_phase=lambda name, elapsed: progress.write(name)) as trace:
    with measure("phase", "outer_flow"):
        st.session_state["result"] = {expression}
st.session_state["trace"] = trace.report()
'''
    app = AppTest.from_string(source, default_timeout=15).run()
    assert not app.exception
    expected = app.session_state["result"].copy(deep=True)
    assert len(calls) == 1
    for _ in range(2):
        if path == "theme_miss":
            flow.calculate_image_theme_flow_df.clear()
        elif path == "etf_miss":
            flow.calculate_money_flow_df.clear()
        app.run()
        assert not app.exception
        actual = app.session_state["result"]
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert actual.attrs == expected.attrs
        assert all(row["errors"] == 0 for row in app.session_state["trace"]["functions"])
    assert len(calls) == 1
    assert app.markdown[0].value == "outer_flow"
    assert calls[0][1]["timeout"] == (2, 4)
    assert calls[0][1]["params"]["interval"] == "1d"
    assert calls[0][1]["params"]["includeAdjustedClose"] == "true"
