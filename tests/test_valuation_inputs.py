"""Consensus provenance and request reuse, without live API access."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import math
import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

from stock_lab_core import news
from stock_lab_core.today_enrichment import attach_today_analyst_context
from stock_lab_core.valuation_inputs import (
    CONSENSUS_KEYS, consensus_connection_rows, resolve_valuation_inputs,
)
from stock_lab_core.yahoo_metadata import yahoo_metadata_reader


def analyst(**extra):
    return {"ok": True, "status": "available", "source": "common provider",
            "asof": "2026-10-30", "fetched_at": "2026-10-31T10:00:00+00:00",
            "data": {"targetMeanPrice": 120, "numberOfAnalystOpinions": 12}, **extra}


@pytest.mark.parametrize("current,target_key,target", [(100, "targetMeanPrice", 120),
                                                      (150, "targetMedianPrice", 130)])
def test_valuation_and_queue_use_the_same_target_provider_and_current_price(app_module, current, target_key, target):
    snapshot = {"ok": True, "data": {"targetMeanPrice": 999, "numberOfAnalystOpinions": 88,
                                       "forwardPE": 20, "currentPrice": 90}}
    shared = analyst(data={target_key: target, "numberOfAnalystOpinions": 7})
    before = deepcopy((snapshot, shared))
    data, context = resolve_valuation_inputs(snapshot, shared, "MSFT", current)
    queue = attach_today_analyst_context(pd.DataFrame([{"티커": "MSFT", "현재가": current}]),
                                        get_analyst_snapshot=lambda _: shared).iloc[0]
    valuation = app_module.build_valuation_interpretation(data, current, "MSFT")
    assert valuation["target_upside"] == pytest.approx(queue["애널목표Upside값"])
    assert context["애널목표출처"] == queue["애널목표출처"] == "common provider"
    assert context["애널목표종류"] == target_key
    assert data["numberOfAnalystOpinions"] == 7 and data["forwardPE"] == 20
    assert (snapshot, shared) == before


@pytest.mark.parametrize("status,stale", [("no_target", False), ("rate_limited", False),
                                         ("lookup_error", False), ("stale", True)])
def test_unavailable_common_target_cannot_be_filled_from_a_separate_valuation_path(status, stale):
    raw = {"ok": True, "data": {key: 999 for key in CONSENSUS_KEYS} | {"forwardPE": 20}}
    shared = analyst(ok=False, status=status, stale=stale)
    data, context = resolve_valuation_inputs(raw, shared, "MSFT", 100)
    assert not set(CONSENSUS_KEYS) & data.keys()
    assert data["forwardPE"] == 20 and context["애널목표상태"] == status
    assert consensus_connection_rows(context)[0]["목표가"] == "-"


@pytest.mark.parametrize("status,stale", [("stale", False), ("available", True), ("rate_limited", False)])
def test_contradictory_ok_flag_does_not_rehabilitate_stale_or_blocked_targets(status, stale):
    data, context = resolve_valuation_inputs({}, analyst(status=status, stale=stale), "MSFT", 100)
    assert "targetMeanPrice" not in data and context["애널목표상태"] != "available"


def test_missing_asof_is_not_replaced_with_fetch_date_and_report_has_no_eps_claim():
    _, context = resolve_valuation_inputs({}, analyst(asof=""), "MSFT", 100)
    row = consensus_connection_rows(context)[0]
    assert row["공급자 기준일"] == "미제공"
    assert row["조회시각"] == "2026-10-31T10:00:00+00:00"
    assert row["자료"] == "애널리스트 주가 목표"


def test_display_rounding_cannot_change_the_consensus_denominator(app_module):
    shared = analyst(data={"targetMeanPrice": 406.54807})
    price = 281.481
    row = {"티커": "GOOGL", "현재가": "$281.48", "현재가원값": price}
    queue = attach_today_analyst_context(pd.DataFrame([row]), get_analyst_snapshot=lambda _: shared).iloc[0]
    data, context = resolve_valuation_inputs({}, shared, "GOOGL", price)
    valuation = app_module.build_valuation_interpretation(data, price, "GOOGL")
    assert queue["애널가격출처"] == "현재가원값"
    assert queue["애널가격기준"] == price
    assert queue["애널목표Upside값"] == context["애널목표Upside값"] == valuation["target_upside"]


def test_explicit_custom_price_column_is_not_overridden_by_display_raw_price():
    shared = analyst()
    row = {"티커": "MSFT", "quote": 100, "현재가원값": 500}
    result = attach_today_analyst_context(pd.DataFrame([row]), get_analyst_snapshot=lambda _: shared, price_col="quote").iloc[0]
    assert result["애널목표Upside값"] == pytest.approx(20)


def test_only_high_low_targets_do_not_turn_into_consensus():
    data, context = resolve_valuation_inputs({}, analyst(data={"targetHighPrice": 200, "targetLowPrice": 100}), "MSFT", 100)
    assert not data and context["애널목표상태"] == "no_target"


def test_resolver_does_not_do_implicit_price_lookup():
    data, context = resolve_valuation_inputs({}, analyst(), "MSFT", None)
    assert not data and context["애널목표상태"] == "no_price"


@pytest.mark.parametrize("price", [None, math.nan, 0, -5, True])
@pytest.mark.parametrize("raw_price", [None, 90])
def test_shared_snapshot_price_fallback_reaches_valuation_and_final_check(app_module, monkeypatch, price, raw_price):
    from stock_lab_core.valuation_inputs import valuation_reference_price

    raw = {"ok": True, "data": {"currentPrice": raw_price}}
    shared = analyst(data={"targetMeanPrice": 120, "currentPrice": 100})
    data, context = resolve_valuation_inputs(raw, shared, "MSFT", price)
    assert data["currentPrice"] == data["regularMarketPrice"] == 100
    reference = valuation_reference_price(price, context)
    valuation = app_module.build_valuation_interpretation(data, reference, "MSFT")
    assert valuation["target_upside"] == pytest.approx(context["애널목표Upside값"]) == pytest.approx(20)
    monkeypatch.setattr(app_module, "fetch_valuation_snapshot", lambda _: raw)
    monkeypatch.setattr(app_module, "get_analyst_snapshot", lambda _: shared)
    monkeypatch.setattr(app_module, "ensure_fin_meta_for_valuation", lambda *args: {})
    assert app_module.get_valuation_headline_for_final_check("MSFT", False, price)[2] == pytest.approx(20)


def test_display_and_final_check_use_common_inputs_without_changing_financial_scores(app_module, monkeypatch):
    app = app_module
    monkeypatch.setattr(app, "fetch_valuation_snapshot", lambda _: {"ok": True, "data": {"targetMeanPrice": 999, "forwardPE": 20}})
    monkeypatch.setattr(app, "get_analyst_snapshot", lambda _: analyst())
    monkeypatch.setattr(app, "ensure_fin_meta_for_valuation", lambda ticker, is_etf, meta: meta)
    metadata = {"manual_score": 0, "auto_score": 4, "final_score": 0}
    before = deepcopy(metadata)
    _, _, upside = app.get_valuation_headline_for_final_check("MSFT", False, 100, metadata)
    assert upside == pytest.approx(20) and metadata == before


def test_valuation_and_analyst_share_one_info_request(app_module, monkeypatch):
    app = app_module
    app.fetch_valuation_snapshot.clear()
    news.get_analyst_snapshot.clear()
    calls = []

    def info():
        calls.append("info")
        return {"forwardPE": 20, "targetMeanPrice": 120, "numberOfAnalystOpinions": 7}

    monkeypatch.setattr(app.yf, "Ticker", lambda *a, **kw: SimpleNamespace(get_info=info))
    monkeypatch.setattr(app, "fetch_fmp_valuation_snapshot", lambda _: {"ok": False})
    monkeypatch.setattr(news, "_fetch_yahoo_analyst_data", lambda _: {})
    try:
        assert app.fetch_valuation_snapshot("TEST_COMMON_INFO")["data"]["forwardPE"] == 20
        assert news.get_analyst_snapshot("TEST_COMMON_INFO")["data"]["targetMeanPrice"] == 120
        assert calls == ["info"]
    finally:
        app.fetch_valuation_snapshot.clear()
        news.get_analyst_snapshot.clear()


def test_global_429_blocks_valuation_info_but_allows_other_provider(app_module, monkeypatch):
    app = app_module
    app.fetch_valuation_snapshot.clear()

    def limited(_):
        raise YFRateLimitError()

    yahoo_metadata_reader.read("info", "LIMITED", limited)
    monkeypatch.setattr(app.yf, "Ticker", lambda *a, **kw: pytest.fail("Bypassed global provider cooldown"))
    monkeypatch.setattr(app, "fetch_fmp_valuation_snapshot", lambda _: {"ok": True, "data": {"trailingPE": 18}})
    try:
        result = app.fetch_valuation_snapshot("TEST_LIMITED_VALUATION")
        assert result["ok"] and result["data"]["trailingPE"] == 18
        assert result["provider_attempts"][0]["status"] == "rate_limited"
        assert result["retryable_failure"] is True
    finally:
        app.fetch_valuation_snapshot.clear()


def test_outer_valuation_cache_does_not_extend_old_metadata_by_six_hours(app_module, monkeypatch):
    app = app_module
    old = {"ok": True, "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()}
    fresh = {"ok": True, "fetched_at": datetime.now(timezone.utc).isoformat()}
    calls = []

    def cache(ticker):
        calls.append(ticker)
        return old if len(calls) == 1 else fresh

    cleared = []
    cache.clear = lambda ticker: cleared.append(ticker)
    monkeypatch.setattr(app, "_fetch_valuation_snapshot_cached", cache)
    assert app.fetch_valuation_snapshot("MSFT") is fresh
    assert len(calls) == 2 and cleared == ["MSFT"]
