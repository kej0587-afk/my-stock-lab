"""Same selected Naver scalar evidence; fixed public fields, no live requests.

005930 basic fields come from the saved Nov 21 public response. 379810's
20:20:23 regularMarket timestamp/session is the separately inspected response;
the later wall-clock hour must not override the explicit supplier session.
No private capture file is needed to run these contracts.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import lru_cache
import io
import json
import math
from pathlib import Path
import pickle
import subprocess
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from stock_lab_core import prices, quote_prefetch, decision_engine as engine
from stock_lab_core.performance import submit_with_context
from stock_lab_core.quote_observation import quote_provenance
from stock_lab_core.signal_basis import build_signal_basis
from stock_lab_core.ta_engine import build_indicators
from tests.fixtures_price import make_price_df


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "f2571029"
BASIC = {
    "itemCode": "005930", "closePrice": "180,900", "localTradedAt": "2026-11-20T20:20:21+09:00",
    "marketSessionType": "afterMarket", "marketStatus": "CLOSE", "fluctuationsRatio": "-8.13",
    "compareToPreviousClosePrice": "-16,000", "stockExchangeType": {"startTime": "0900", "endTime": "1530"},
    "overMarketPriceInfo": {"overPrice": "180,900", "localTradedAt": "2026-11-20T20:00:00+09:00",
                           "tradingSessionType": "AFTER_MARKET"},
}
POLLING_ROW = {
    "cd": "005930", "nv": 180900, "cr": 8.13, "cv": 16000, "rf": "5", "ms": "CLOSE",
    "nxtOverMarketPriceInfo": {"overPrice": "180,900", "localTradedAt": "2026-11-20T20:00:00+09:00",
                              "tradingSessionType": "AFTER_MARKET"},
}


def polling(*rows):
    return {"resultCode": "success", "result": {"time": 1795189441656,
            "areas": [{"name": "SERVICE_ITEM", "datas": list(rows)}]}}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    prices.clear_latest_price_cache()
    monkeypatch.setattr(prices.urllib.request, "urlopen", Mock(side_effect=AssertionError("unexpected network")))
    yield
    prices.clear_latest_price_cache()


def observe(obj=None, price=180900., ticker="005930.KS", source="naver_basic", field="closePrice", **kwargs):
    return prices._observe_naver_selected_price(price, ticker, deepcopy(BASIC if obj is None else obj), source, field, **kwargs)


def assert_untimed(value, source="naver_polling", ticker="005930.KS"):
    info = quote_provenance(value, ticker)
    assert info["source"] == source
    assert info["symbol"] == ticker
    assert info["price"] == float(value)
    assert "observed_at" not in info
    assert info["session"] == "unknown"


@pytest.mark.parametrize("code,stamp,session,expected", [
    ("005930", "2026-11-20T20:20:21+09:00", "afterMarket", "post"),
    ("379810", "2026-11-20T20:20:23+09:00", "regularMarket", "regular"),
    ("0167A0", "2026-11-20T08:20:21+09:00", "preMarket", "pre"),
])
def test_basic_own_time_and_explicit_session_never_replaced_by_clock(code, stamp, session, expected):
    obj = {**BASIC, "itemCode": code, "localTradedAt": stamp, "marketSessionType": session}
    selected = observe(obj, ticker=code + ".KS")
    assert float(selected).hex() == float(180900).hex()
    info = quote_provenance(selected, code + ".KS")
    assert info == dict(source="naver_basic", symbol=code + ".KS", price=180900.,
                        observed_at=pd.Timestamp(stamp).tz_convert("UTC").isoformat(),
                        session=expected, timestamp_kind="trade")


@pytest.mark.parametrize("stamp", [None, "", "-", "bad", "NaT", "2026-11-20", "2026-11-20T20:20:21",
                                 "2026-02-30T20:20:21+09:00", "2026-11-20T25:00:00+09:00",
                                 "2026-11-20T20:20:21+99:00", 1795189441, "1795189441", True, [], {}])
def test_invalid_root_time_keeps_price_known_source_but_no_time_or_session(stamp):
    value = observe({**BASIC, "localTradedAt": stamp})
    assert value == 180900.
    assert_untimed(value, "naver_basic")


@pytest.mark.parametrize("session", [None, "", "CLOSE", "OPEN", "normalMarket", "AFTER_MARKET", "unexpected", [], {}])
def test_only_documented_explicit_session_mapping_is_used(session):
    info = quote_provenance(observe({**BASIC, "marketSessionType": session}))
    assert info["observed_at"] == "2026-11-20T11:20:21+00:00"
    assert info["session"] == "unknown"


@pytest.mark.parametrize("field", ["nv", "stockEndPrice", "currentPrice", "tradePrice"])
def test_other_basic_price_fields_do_not_inherit_close_timestamp(field):
    assert_untimed(observe({**BASIC, field: 180900}, field=field), "naver_basic")


@pytest.mark.parametrize("status", ["CLOSE", "OPEN"])
def test_polling_never_borrows_response_or_nested_or_unsupported_root_time(status):
    obj = {**POLLING_ROW, "ms": status, "localTradedAt": BASIC["localTradedAt"],
           "marketSessionType": "afterMarket", "time": 1795189441656}
    value = observe(obj, source="naver_polling", field="nv")
    assert_untimed(value)
    parsed = prices._parse_naver_realtime_quotes(json.dumps(polling(obj)), ["005930.KS"])
    assert_untimed(parsed["005930.KS"]["price"])


@pytest.mark.parametrize("obj,item_code,ticker", [
    ({"closePrice": "180,900"}, "", "005930.KS"),
    ({**BASIC, "itemCode": "000660"}, "", "005930.KS"),
    (BASIC, "000660", "005930.KS"),
    ({**BASIC, "cd": "000660"}, "005930", "005930.KS"),
    ({**BASIC, "itemCode": "00593"}, "", "005930.KS"),
    (BASIC, "", "005930X.KS"), (BASIC, "", "SOXL"),
])
def test_unproven_or_conflicting_symbol_keeps_plain_selected_number(obj, item_code, ticker):
    value = observe(obj, item_code=item_code, ticker=ticker)
    assert value == 180900.
    assert quote_provenance(value) == {}


@pytest.mark.parametrize("identity", ["cd", "itemCode", "stockCode", "symbolCode", "code"])
def test_canonical_alphanumeric_embedded_identity(identity):
    obj = {identity: "0167a0", "nv": 12345.125}
    value = observe(obj, price=12345.125, ticker=" 0167a0.ks ", source="naver_polling", field="nv")
    assert float(value).hex() == float(12345.125).hex()
    assert_untimed(value, ticker="0167A0.KS")


@pytest.mark.parametrize("raw", ["180,901", "180900.01", None, "", "-", "bad"])
def test_raw_selected_field_must_equal_selected_scalar_exactly(raw):
    value = observe({**BASIC, "closePrice": raw})
    assert value == 180900.
    assert quote_provenance(value) == {}


@pytest.mark.parametrize("value", [0., -1., float("nan"), float("inf"), -float("inf")])
def test_invalid_numeric_value_is_not_repriced_or_given_provenance(value):
    result = observe({**BASIC, "closePrice": value}, price=value)
    assert math.isnan(result) if math.isnan(value) else result == value
    assert quote_provenance(result) == {}


@lru_cache
def baseline_nodes():
    source = subprocess.check_output(["git", "show", f"{BASELINE}:stock_lab_core/prices.py"],
                                     cwd=ROOT, encoding="utf-8")
    names = {"_fetch_naver_price", "_fetch_naver_realtime_price", "_coerce_naver_number", "_naver_quote_sign",
             "_extract_naver_quote_from_obj", "_naver_obj_code", "_walk_naver_quote_objects", "_parse_naver_realtime_quotes",
             "_fetch_naver_quotes_bulk", "_fetch_naver_realtime_quote", "_fetch_naver_basic_quote", "_fetch_naver_prices_bulk",
             "_fetch_price_uncached", "_load_latest_kr_quotes_batch_cached", "load_latest_prices_batch",
             "load_latest_price", "_load_latest_price_cached"}
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    return nodes


def baseline():
    namespace = dict(vars(prices))
    exec(compile(ast.Module(body=deepcopy(baseline_nodes()), type_ignores=[]), "<naver-before>", "exec"), namespace)
    return namespace


REGEX_CASES = [
    ("basic", json.dumps(BASIC), True),
    ("basic", json.dumps({**BASIC, "localTradedAt": "bad"}), True),
    ("basic", json.dumps({**BASIC, "localTradedAt": "2026-11-20T20:20:21"}), True),
    ("basic", json.dumps([{**BASIC}]), False),
    ("basic", json.dumps({**BASIC, "itemCode": "000660"}), False),
    ("basic", json.dumps({**BASIC, "closePrice": "0", "stockEndPrice": "180,900"}), False),
    ("basic", json.dumps({"itemCode": "005930", "stockEndPrice": "180,900"}), True),
    ("basic", json.dumps({**BASIC, "closePrice": 180900}), False),
    ("basic", json.dumps({**BASIC, "closePrice": "180900.25"}), False),
    ("basic", json.dumps({**BASIC, "nested": {"closePrice": "180,900"}}), False),
    ("basic", '{"itemCode":"005930","closePrice":"100","closePrice":"180900"}', False),
    ("basic", 'broken "closePrice":"180,900" "localTradedAt":"2026-11-20T20:20:21+09:00"', False),
    ("polling", json.dumps(polling(POLLING_ROW)), True),
    ("polling", json.dumps([POLLING_ROW]), True),
    ("polling", json.dumps({"SERVICE_ITEM:005930": POLLING_ROW}), True),
    ("polling", json.dumps({"SERVICE_ITEM:005930": {"nv": 180900}}), True),
    ("polling", json.dumps({"SERVICE_ITEM:000660": POLLING_ROW}), False),
    ("polling", json.dumps(polling(POLLING_ROW, {**POLLING_ROW, "cd": "000660"})), False),
    ("polling", json.dumps(polling(POLLING_ROW, POLLING_ROW)), False),
    ("polling", json.dumps({"unidentified": {"nv": 180900}, "payload": polling(POLLING_ROW)}), False),
    ("polling", json.dumps(polling({**POLLING_ROW, "nv": 180900.25})), False),
    ("polling", json.dumps(polling({**POLLING_ROW, "nv": -180900})), False),
    ("polling", 'broken "nv":180900', False),
    ("polling", 'null', False),
]


@pytest.mark.parametrize("kind,text,has_source", REGEX_CASES)
def test_scalar_regex_numeric_selection_and_request_match_frozen_baseline(monkeypatch, kind, text, has_source):
    calls = []
    def request(req, timeout):
        calls.append((req.full_url, timeout, tuple(req.header_items())))
        return io.BytesIO(text.encode())
    monkeypatch.setattr(prices.urllib.request, "urlopen", request)
    name = "_fetch_naver_price" if kind == "basic" else "_fetch_naver_realtime_price"
    expected = baseline()[name]("005930.KS")
    before_calls = calls.copy()
    calls.clear()
    actual = getattr(prices, name)("005930.KS")
    assert float(actual).hex() == float(expected).hex()
    assert calls == before_calls and len(calls) == 1
    assert bool(quote_provenance(actual, "005930.KS")) is has_source
    if kind == "polling" and has_source:
        assert_untimed(actual)


@pytest.mark.parametrize("obj", [BASIC, POLLING_ROW, {}, {"cr": 0}, {"nv": 0, "closePrice": "123.125"},
    {"nv": "", "closePrice": -5, "stockEndPrice": "2,000", "cr": 0, "cv": 20, "rf": "5"},
    {"tradePrice": 100., "cr": "bad", "changeRate": "1.2%", "compareToPreviousClosePrice": 10},
    {"nv": float("nan"), "currentPrice": 1.125, "cr": True}, {"nv": float("inf"), "cr": "inf"},
])
def test_optional_extractor_metadata_does_not_change_field_priority_or_change_numbers(obj):
    expected = baseline()["_extract_naver_quote_from_obj"](obj)
    assert prices._extract_naver_quote_from_obj(obj) == expected
    actual = prices._extract_naver_quote_from_obj(obj, ticker="005930.KS", source="naver_basic", item_code="005930")
    assert actual == expected
    assert list(actual) == list(expected)
    assert set(actual).issubset({"price", "change_pct", "change_abs"})


@pytest.mark.parametrize("text", [
    json.dumps(polling(POLLING_ROW, {"cd": "379810", "nv": 23180, "cr": 0})),
    json.dumps({"SERVICE_ITEM:005930": {"nv": "180,900", "cr": "0"}}),
    json.dumps({"SERVICE_ITEM:005930": {"nv": 100, "cd": "379810"}}),
    json.dumps(polling({"cd": "005930", "nv": 1, "cr": 0}, POLLING_ROW)),
    json.dumps(polling({"cd": "005930", "nv": None, "cr": 0}, POLLING_ROW)),
    'broken "SERVICE_ITEM:005930":{"nv":180900,"cr":8.13,"cv":16000,"rf":"5"}',
])
def test_parser_first_object_fallback_regex_and_numeric_dictionary_are_unchanged(text):
    tickers = ["005930.KS", "379810.KS"]
    expected = baseline()["_parse_naver_realtime_quotes"](text, tickers)
    actual = prices._parse_naver_realtime_quotes(text, tickers)
    assert actual == expected
    assert list(actual) == list(expected)
    for ticker, quote in actual.items():
        info = quote_provenance(quote.get("price"), ticker)
        if info:
            assert_untimed(quote["price"], ticker=ticker)
    if '"cd": "379810"' in text and "SERVICE_ITEM:005930" in text:
        assert quote_provenance(actual["005930.KS"]["price"]) == {}


class Transport:
    def __init__(self, mode):
        self.mode = mode
        self.calls = []

    def __call__(self, req, timeout):
        url = urlparse(req.full_url)
        self.calls.append((req.full_url, timeout))
        if url.netloc == "polling.finance.naver.com":
            codes = parse_qs(url.query)["query"][0].split(":", 1)[1].split(",")
            rows = [] if self.mode in {"basic", "empty"} else [{**POLLING_ROW, "cd": code} for code in codes]
            if self.mode == "missing_change":
                for row in rows:
                    row.pop("cr")
            payload = polling(*rows)
        else:
            assert url.netloc == "m.stock.naver.com"
            code = url.path.split("/")[-2]
            payload = {} if self.mode == "empty" else {**BASIC, "itemCode": code}
        return io.BytesIO(json.dumps(payload).encode())


@pytest.mark.parametrize("mode", ["polling", "basic", "missing_change", "empty"])
@pytest.mark.parametrize("name", ["load_latest_price", "load_latest_prices_batch", "_load_latest_kr_quotes_batch_cached"])
def test_original_selector_numbers_and_per_symbol_provider_order_unchanged(monkeypatch, mode, name):
    transport = Transport(mode)
    monkeypatch.setattr(prices.urllib.request, "urlopen", transport)
    monkeypatch.setattr(prices, "_force_live_price_refresh_active", lambda: False)
    monkeypatch.setattr(prices, "_fetch_pykrx_latest_close", lambda ticker: transport.calls.append(("pykrx", ticker)) or 77.)
    argument = "005930.KS" if name == "load_latest_price" else ("005930.KS", "379810.KS")
    expected = baseline()[name](argument)
    before_calls = transport.calls.copy()
    transport.calls.clear()
    actual = getattr(prices, name)(argument)
    assert actual == expected
    # Parallel dictionary fallback interleaving is not provider order; compare
    # each symbol's requests while retaining each endpoint and timeout exactly.
    def by_code(calls):
        return {code: [call for call in calls if code in str(call)] for code in ("005930", "379810")}
    assert by_code(transport.calls) == by_code(before_calls)
    assert len(transport.calls) == len(before_calls)
    if name == "load_latest_price":
        if mode == "basic":
            assert quote_provenance(actual)["observed_at"] == "2026-11-20T11:20:21+00:00"
        elif mode == "empty":
            assert quote_provenance(actual) == {}
        else:
            assert_untimed(actual)
    else:
        for ticker, entry in actual.items():
            value = entry.get("price") if isinstance(entry, dict) else entry
            if value is None:
                continue
            if mode == "basic" or (mode == "missing_change" and name == "_load_latest_kr_quotes_batch_cached"):
                assert quote_provenance(value, ticker)["source"] == "naver_basic"
                assert quote_provenance(value, ticker)["observed_at"] == "2026-11-20T11:20:21+00:00"
            elif mode == "empty":
                assert quote_provenance(value, ticker) == {}
            else:
                assert_untimed(value, ticker=ticker)
    before = transport.calls.copy()
    cached = getattr(prices, name)(argument)
    assert cached == actual
    def evidence(value):
        if isinstance(value, dict):
            return {key: evidence(item) for key, item in value.items()}
        return quote_provenance(value)
    assert evidence(cached) == evidence(actual)
    assert transport.calls == before


def test_final_merged_price_owns_metadata_even_when_change_only_fallback_arrives(monkeypatch):
    timed = observe()
    unknown = observe(POLLING_ROW, source="naver_polling", field="nv")
    for direct, expected in [({"change_pct": 0}, timed), ({"price": unknown, "change_pct": 0}, unknown),
                             ({"price": 181000., "change_pct": 0}, 181000.)]:
        monkeypatch.setattr(prices, "_fetch_naver_quotes_bulk", lambda tickers: {"005930.KS": {"price": timed}})
        monkeypatch.setattr(prices, "_fetch_naver_realtime_quote", lambda ticker: direct)
        result = prices._load_latest_kr_quotes_batch_cached.__wrapped__(("005930.KS",))["005930.KS"]
        assert result["price"] == expected and result["change_pct"] == 0
        assert quote_provenance(result["price"]) == quote_provenance(expected)


@pytest.mark.parametrize("kind", ["basic", "polling"])
def test_pickle_deepcopy_scope_worker_and_expiry_preserve_selected_evidence(monkeypatch, kind):
    selected = observe() if kind == "basic" else observe(POLLING_ROW, source="naver_polling", field="nv")
    info = quote_provenance(selected)
    for restored in (deepcopy(selected), pickle.loads(pickle.dumps(selected))):
        assert restored == selected and hash(restored) == hash(selected)
        assert quote_provenance(restored) == info
    now = [0.]
    monkeypatch.setattr(quote_prefetch.time, "monotonic", lambda: now[0])
    def bulk(keys):
        now[0] = 4.
        return {"005930.KS": selected}
    monkeypatch.setattr(prices, "_fetch_naver_prices_bulk", bulk)
    fallback = Mock(return_value=181000.)
    monkeypatch.setattr(prices, "_fetch_price_uncached", fallback)
    with prices.fresh_kr_quote_scope(["005930.KS"]):
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = submit_with_context(executor, prices.load_latest_price, "005930.KS").result()
        assert quote_provenance(result) == info
        now[0] = 14.999
        assert quote_provenance(prices.load_latest_price("005930.KS")) == info
        now[0] = 15.
        assert prices.load_latest_price("005930.KS") == 181000.
        fallback.assert_called_once_with("005930.KS")
    assert quote_prefetch.prefetched_quote("005930.KS") is None


def test_actual_bulk_scope_preserves_unknown_polling_source_without_extra_basic_request(monkeypatch):
    transport = Transport("polling")
    monkeypatch.setattr(prices.urllib.request, "urlopen", transport)
    with prices.fresh_kr_quote_scope(["005930.KS", "379810.KS"]):
        for ticker in ("005930.KS", "379810.KS"):
            assert_untimed(prices.load_latest_price(ticker), ticker=ticker)
    assert len(transport.calls) == 1
    assert "polling.finance.naver.com" in transport.calls[0][0]


def test_domestic_evidence_preserves_price_identity_indicators_and_atr(monkeypatch):
    source = make_price_df(seed=21)
    monkeypatch.setattr(engine, "_get_live_price_row_date", lambda ticker: source.index[-1])
    price = float(source.Close.iloc[-1]) * .95
    value = observe({**BASIC, "closePrice": price}, price=price)
    plain = engine.apply_live_price_with_indicators(source, price, "005930.KS", build_indicators)
    rich = engine.apply_live_price_with_indicators(source, value, "005930.KS", build_indicators)
    pd.testing.assert_frame_equal(plain[0], rich[0], check_exact=True)
    assert plain[1:] == rich[1:]
    assert engine.calc_atr_for_decision(plain[0]) == engine.calc_atr_for_decision(rich[0])
    before = build_signal_basis(source, plain, ticker="005930.KS", input_price=price)
    after = build_signal_basis(source, rich, ticker="005930.KS", input_price=value)
    assert before["가격입력ID"] == after["가격입력ID"]
    assert after["현재가관측시각"] == "2026-11-20 20:20:21 KST"


def test_selector_and_cache_decorators_are_identical_to_baseline():
    old_source = subprocess.check_output(["git", "show", f"{BASELINE}:stock_lab_core/prices.py"], cwd=ROOT, encoding="utf-8")
    current = Path(prices.__file__).read_text(encoding="utf-8-sig")
    functions = [{n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)} for source in (old_source, current)]
    for name in ("_fetch_price_uncached", "load_latest_price", "load_latest_prices_batch", "_load_latest_price_cached",
                 "_load_latest_kr_quotes_batch_cached", "_fetch_naver_prices_bulk"):
        assert ast.dump(functions[0][name]) == ast.dump(functions[1][name])
    for name in ("_fetch_naver_realtime_quote", "_fetch_naver_basic_quote"):
        assert [ast.dump(n) for n in functions[0][name].decorator_list] == [ast.dump(n) for n in functions[1][name].decorator_list]
