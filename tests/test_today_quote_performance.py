"""Offline contracts for queue-only HTML scope and render quote union."""

import ast
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import subprocess
from threading import Barrier, Lock
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pandas as pd
import pytest

from stock_lab_core import kr_sector_snapshot as kr, prices
from stock_lab_core.formatters import clean_float, sanitize_ticker_value
from stock_lab_core.money_flow import SECTOR_CLUSTERS_KR, SECTOR_CLUSTERS_US
from stock_lab_core.performance import PerformanceTrace, submit_with_context
from tests.test_quote_html_wiring import Response, app_fetch


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "04d41218fbc802558f5e9811d7c25d3af8c31bfa"
NOW = 1_800_000_000


@lru_cache
def source(path, before=False):
    if before:
        return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT, encoding="utf-8")
    return (ROOT / path).read_text(encoding="utf-8-sig")


def app_context(before=False):
    functions = {"_kr_rotation_context_requests", "_preload_today_queue_kr_context",
                 "_today_queue_overnight_tickers", "_get_market_cluster_snapshot_cached",
                 "_lookup_kr_rotation_cluster", "_lookup_us_rotation_cluster",
                 "_is_us_rotation_context", "_is_kr_rotation_ticker", "_extract_flow_ticker"}
    constants = {"MARKET_CLUSTER_CONTEXT_CACHE_KEY", "MARKET_CLUSTER_CONTEXT_CACHE_VERSION",
                 "MARKET_CLUSTER_CONTEXT_CACHE_TTL_SECONDS", "KR_ROTATION_SECTOR_CLUSTER_MAP",
                 "KR_ROTATION_THEME_CLUSTER_MAP", "US_ROTATION_THEME_CLUSTER_MAP", "INDEX_ROTATION_BASKET",
                 "TODAY_FLOW_SHORTLIST_VERSION"}
    nodes = []
    for node in ast.parse(source("app.py", before)).body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
            nodes.append(node)
    env = dict(pd=pd, re=re, clean_float=clean_float, sanitize_ticker_value=sanitize_ticker_value,
               st=SimpleNamespace(session_state={}), SECTOR_CLUSTERS_KR=SECTOR_CLUSTERS_KR,
               SECTOR_CLUSTERS_US=SECTOR_CLUSTERS_US, build_kr_cluster_snapshot=kr.build_kr_cluster_snapshot,
               preload_kr_cluster_snapshots=kr.preload_kr_cluster_snapshots)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<queue-integration>", "exec"), env)
    return env


class ReplayTransport:
    """Generated provider-shaped responses, not recordings of live quote payloads."""

    def __init__(self, html_bytes=512):
        self.calls = []
        self.lock = Lock()
        self.html_bytes = html_bytes
        self.expired = False
        self.html_payloads = {}

    def prepare_html(self, tickers):
        for ticker in tickers:
            payload = {"symbol": ticker, "overnightMarketPrice": {"raw": 123.45},
                       "overnightMarketTime": {"raw": NOW - (1_000_000 if self.expired else 5)}}
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.html_payloads[(ticker, self.expired)] = gzip.compress(
                body + b" " * max(0, self.html_bytes - len(body)))

    def open(self, request, **kwargs):
        url = urlsplit(request.full_url)
        with self.lock:
            self.calls.append(request.full_url)
        if url.netloc == "finance.yahoo.com":
            ticker = unquote(url.path.split("/")[2])
            if (ticker, self.expired) not in self.html_payloads:
                self.prepare_html([ticker])
            return Response(self.html_payloads[(ticker, self.expired)], "gzip")
        if url.netloc in {"query1.finance.yahoo.com", "query2.finance.yahoo.com"}:
            result = {"timestamp": [NOW - 5], "meta": {}, "indicators": {"quote": [{"close": [123.45]}]}}
            return Response(json.dumps({"chart": {"result": [result]}}).encode())
        if url.netloc == "polling.finance.naver.com":
            codes = parse_qs(url.query)["query"][0].split(":", 1)[1].split(",")
            data = {f"SERVICE_ITEM:{code}": {"nv": 10000 + int(code), "cr": 1.25, "cv": 100, "rf": "2"}
                    for code in codes}
            return Response(json.dumps(data).encode())
        raise AssertionError(f"Unexpected replay URL: {request.full_url}")


@pytest.fixture
def offline(monkeypatch):
    transport = ReplayTransport()
    monkeypatch.setattr(prices.urllib.request, "urlopen", transport.open)
    monkeypatch.setattr(prices, "_is_recent_epoch", lambda ts: 0 <= NOW - ts < 60)
    monkeypatch.setattr(prices, "_us_equity_regular_session_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_after_hours_active", lambda: False)
    monkeypatch.setattr(prices, "_us_equity_market_closed_today", lambda: False)
    monkeypatch.setattr(prices, "_is_live_priority_us_ticker", lambda t: False)
    monkeypatch.setattr(prices, "_YAHOO_BLOCK_UNTIL", 0)
    prices.clear_latest_price_cache()
    yield transport
    prices.clear_latest_price_cache()


def cluster_fixture(monkeypatch):
    names = list(SECTOR_CLUSTERS_KR)

    def select(cluster, detail):
        i = names.index(cluster)
        rows = pd.DataFrame([{"ticker": f"{i * 3 + j + 1:06d}.KS", "name": f"row-{i}-{j}",
                              "current": 10000.0, "change_pct": -1.0, "rank": j, "volume": 1000}
                             for j in range(3)])
        industry = pd.DataFrame([{"sector_name": cluster, "change_pct": -1.0}])
        return detail, {}, [cluster], industry, rows

    monkeypatch.setattr(kr, "_select_cluster_rows", select)
    snapshot = {"sector_rotation_df": pd.DataFrame([
        {"Ticker": SECTOR_CLUSTERS_KR[name][0], "섹터": name} for name in names]),
        "flow_df": pd.DataFrame({"Ticker": ["069500.KS"]})}
    return names, snapshot


def test_scope_limits_html_but_keeps_chart_fallback_and_precision(offline):
    with PerformanceTrace() as trace, prices.overnight_quote_scope([" held ", "QQQ"]):
        assert prices.load_latest_price("HELD") == 123.45
        assert prices.load_latest_price("QQQ") == 123.45
        assert prices.load_latest_price("WATCH") == 123.45
        assert app_fetch()("WATCH") == 0.0
    events = trace.report()["transport_events"]
    assert events["yahoo_overnight.request"] == 2
    assert events["yahoo_chart.request"] == 1
    before = len(offline.calls)
    assert prices.load_latest_price("WATCH") == 123.45
    assert len(offline.calls) == before + 1 and "/quote/WATCH/" in offline.calls[-1]


def test_quote_cache_clear_includes_scoped_batch_entries(offline):
    with prices.overnight_quote_scope(["HELD", "QQQ"]):
        prices.load_latest_prices_batch(("HELD", "QQQ"))
        prices.clear_latest_price_cache()
        prices.load_latest_prices_batch(("HELD", "QQQ"))
    assert len(offline.calls) == 4


def test_regular_fallback_is_still_session_unconfirmed(offline, monkeypatch):
    from stock_lab_core.signal_basis import quote_display_label

    for name in ("_fetch_us_realtime_price", "_fetch_yahoo_quote", "_fetch_yf_download_price",
                 "_fetch_robinhood_us_quote", "_fetch_configured_us_quote_price", "_fetch_pyth_us_live_price",
                 "_fetch_cboe_book_price", "_fetch_kis_us_quote_price", "_fetch_yf_fast_info_price"):
        monkeypatch.setattr(prices, name, lambda *a, **kw: 0.0)
    monkeypatch.setattr(prices, "_fetch_yahoo_regular_close_price", lambda t: 80.0)
    with prices.overnight_quote_scope([]):
        value = prices.load_latest_price("WATCH")
    assert value == 80.0
    assert quote_display_label(auto_price=value) == "조회 현재가 · 세션 미확인"
    assert offline.calls == []


@pytest.mark.parametrize("batch", [False, True])
def test_scoped_fallback_does_not_poison_unrestricted_quote_caches(offline, monkeypatch, batch):
    monkeypatch.setattr(prices, "_fetch_yahoo_quote", lambda t: 88.0)
    loader = (lambda: prices.load_latest_prices_batch(("WATCH", "OTHER"))["WATCH"]) if batch else lambda: prices.load_latest_price("WATCH")
    with prices.overnight_quote_scope(["HELD"]):
        assert loader() == 88.0
        assert loader() == 88.0
    assert loader() == 123.45
    with prices.overnight_quote_scope([]):
        assert loader() == 88.0  # A warm unrestricted quote cannot bypass policy.


def test_scope_is_nested_exception_safe_and_propagated_to_workers(offline):
    with prices.overnight_quote_scope(["HELD"]), ThreadPoolExecutor(max_workers=2) as pool:
        assert submit_with_context(pool, prices.overnight_quote_allowed, "HELD").result()
        assert not submit_with_context(pool, prices.overnight_quote_allowed, "WATCH").result()
        with pytest.raises(RuntimeError), prices.overnight_quote_scope(["WATCH"]):
            assert not prices.overnight_quote_allowed("HELD")
            raise RuntimeError("stop")
        assert prices.overnight_quote_allowed("HELD")
    assert prices.overnight_quote_allowed("WATCH")
    barrier = Barrier(2)

    def run(ticker):
        with prices.overnight_quote_scope([ticker]):
            barrier.wait(timeout=5)
            return [prices.overnight_quote_allowed(t) for t in ("ONE", "TWO")]

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(run, "ONE"), pool.submit(run, "TWO")
        assert one.result() == [True, False] and two.result() == [False, True]


def test_expired_html_and_missing_quotes_are_not_manufactured_live(offline, monkeypatch):
    offline.expired = True
    with prices.overnight_quote_scope(["HELD"]):
        assert prices._fetch_yahoo_overnight_page_price("HELD") == 0
        assert app_fetch()("HELD") == 0
        assert prices._fetch_yahoo_overnight_page_price("WATCH") == 0
    for name in ("_fetch_yahoo_quote", "_fetch_yf_download_price", "_fetch_robinhood_us_quote",
                 "_fetch_configured_us_quote_price", "_fetch_pyth_us_live_price", "_fetch_cboe_book_price",
                 "_fetch_kis_us_quote_price"):
        monkeypatch.setattr(prices, name, lambda *a, **kw: 0.0)
    with prices.overnight_quote_scope([]):
        assert prices._fetch_us_realtime_price("WATCH") == 0


def test_allowlist_uses_actual_positions_and_rotation_not_watchlist():
    from stock_lab_core.market_observation import DEFAULT_SECTOR_MAP

    env = app_context()
    env["holdings_table"] = pd.DataFrame([
        {"티커": "held", "보유량": 2}, {"티커": "WEIGHT", "현재비중": 1},
        {"티커": "SOLD", "보유량": 0}, {"티커": "WATCH", "보유량": 0}])
    env["st"].session_state["watchlist"] = [{"ticker": "WATCH"}]
    with prices.overnight_quote_scope(env["_today_queue_overnight_tickers"]()):
        for ticker in ("HELD", "WEIGHT", "QQQ", "SOXX", "DIA", "VOO"):
            assert prices.overnight_quote_allowed(ticker)
        assert not prices.overnight_quote_allowed("SOLD")
        assert not prices.overnight_quote_allowed("WATCH")
        us_rotation = {ticker for ticker, spec in DEFAULT_SECTOR_MAP.items() if spec["market"] == "US"}
        assert len(us_rotation) == 20 and {"DRAM", "VNQ"} <= us_rotation
        assert all(prices.overnight_quote_allowed(ticker) for ticker in us_rotation)


def test_cached_shortlist_closed_details_never_preload_unused_frames(offline, monkeypatch):
    _, snapshot = cluster_fixture(monkeypatch)
    env = app_context()
    snapshot.update({
        "_flow_shortlist_df": pd.DataFrame({"Ticker": ["HELD"]}),
        "_flow_shortlist_version": env["TODAY_FLOW_SHORTLIST_VERSION"],
        "theme_flow_df": snapshot["sector_rotation_df"].rename(columns={"섹터": "테마"}),
        "theme_rotation_df": snapshot["sector_rotation_df"].rename(columns={"섹터": "테마"}),
    })
    env["st"].session_state.update({"today_queue_open_flow_detail": False,
                                     "today_queue_summary_df": pd.DataFrame({"티커": ["HELD"]})})
    preload_calls = []
    env["preload_kr_cluster_snapshots"] = lambda requests: preload_calls.append(requests)
    for _ in range(2):
        prices.clear_latest_price_cache()
        with kr.kr_cluster_snapshot_scope(owner_scope="replay"):
            env["_preload_today_queue_kr_context"](snapshot)
    assert preload_calls == offline.calls == []
    assert env["MARKET_CLUSTER_CONTEXT_CACHE_KEY"] not in env["st"].session_state


def test_uncached_shortlist_closed_details_preloads_only_consumed_tables(offline, monkeypatch):
    _, snapshot = cluster_fixture(monkeypatch)
    env = app_context()
    env["st"].session_state["today_queue_open_flow_detail"] = False
    snapshot["theme_flow_df"] = snapshot["sector_rotation_df"].rename(columns={"섹터": "테마"})
    snapshot["theme_rotation_df"] = snapshot["theme_flow_df"].copy()
    # flow_df is only a readiness/benchmark input, not a KR quote consumer.
    snapshot["flow_df"] = pd.DataFrame([{"Ticker": "999999.KS", "섹터": "unused"}])
    requests = list(dict.fromkeys(
        request for key, label in (("sector_rotation_df", "섹터"), ("theme_rotation_df", "테마"), ("theme_flow_df", "테마"))
        for request in env["_kr_rotation_context_requests"](snapshot[key], label)))
    assert len(requests) >= 2
    with PerformanceTrace() as trace, kr.kr_cluster_snapshot_scope(owner_scope="replay"):
        env["_preload_today_queue_kr_context"](snapshot)
        for cluster, detail in requests:
            env["_get_market_cluster_snapshot_cached"]("KOSPI", cluster, detail)
    assert trace.report()["transport_events"]["naver_bulk.request"] == 1
    assert all("999999" not in url for url in offline.calls)


def test_render_union_is_one_batch_with_identical_snapshots_and_warm_cache(offline, monkeypatch):
    names, snapshot = cluster_fixture(monkeypatch)
    outputs = []
    for before in (True, False):
        prices.clear_latest_price_cache()
        offline.calls.clear()
        env = app_context(before)
        with kr.kr_cluster_snapshot_scope(owner_scope="replay"):
            if not before:
                env["_preload_today_queue_kr_context"](snapshot)
            outputs.append([env["_get_market_cluster_snapshot_cached"]("KOSPI", name, name) for name in names])
        assert len(offline.calls) == (10 if before else 1)
        if not before:
            with kr.kr_cluster_snapshot_scope(owner_scope="replay"):
                env["_preload_today_queue_kr_context"](snapshot)
            assert len(offline.calls) == 1
    assert outputs[0] == outputs[1]
    assert kr._KR_CLUSTER_RUN.get() is None


def test_investment_functions_are_unchanged():
    from tests.test_summary_wait_diagnostics import strip_added_timing
    from tests.decision_finalization_reference import restore_finalization_for_ast
    # Freeze after the approved recovery display fix. Precision context was
    # extracted and has three-view frozen-input coverage in test_execution_context.
    baseline = subprocess.check_output(["git", "show", "31513a51:app.py"], cwd=ROOT, encoding="utf-8-sig")
    names = {"_compute_summary_item", "calc_scores_and_decision",
             "load_display_live_price", "build_holdings_table"}
    trees = []
    expected_metadata = ast.parse(
        '{"qty": clean_float(item.get("qty"), np.nan), '
        '"has_pos": clean_float(item.get("qty"), float(has_p)) > 0}', mode="eval").body
    for index, code in enumerate((baseline, source("app.py"))):
        functions = {node.name: node for node in ast.parse(code).body
                     if isinstance(node, ast.FunctionDef) and node.name in names}
        if index:
            # Restore only the approved SMC/finalization extractions. Their actual
            # bodies, arguments, return order and outputs are independently frozen
            # by test_decision_smc_refactor / test_decision_finalization_refactor,
            # both included in the combined gate. Keep this older baseline intact.
            functions["calc_scores_and_decision"] = restore_finalization_for_ast(
                functions["calc_scores_and_decision"]
            )
            row = next(node.value for node in functions["_compute_summary_item"].body
                       if isinstance(node, ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id == "row" for target in node.targets))
            metadata = [(key, value) for key, value in zip(row.keys, row.values)
                        if isinstance(key, ast.Constant) and key.value in {"qty", "has_pos"}]
            assert ast.dump(ast.Dict(keys=[key for key, _ in metadata],
                                     values=[value for _, value in metadata])) == ast.dump(expected_metadata)
            # Exclude only the approved output metadata, never decision expressions.
            retained = [(key, value) for key, value in zip(row.keys, row.values)
                        if not (isinstance(key, ast.Constant) and key.value in {"qty", "has_pos"})]
            row.keys, row.values = [key for key, _ in retained], [value for _, value in retained]
        trees.append({name: ast.dump(strip_added_timing(node), include_attributes=False) for name, node in functions.items()})
    assert trees[0].keys() == names
    assert trees[0] == trees[1]
