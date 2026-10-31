"""Offline ETF review navigation; no app startup, provider, or account saves."""

import ast
from contextlib import nullcontext
from copy import deepcopy
import logging
from pathlib import Path
import re
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
import urllib.request

import numpy as np
import pandas as pd
import pytest
import requests

from stock_lab_core.formatters import clean_float, is_kr_listed, sanitize_ticker_value


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    blocked = Mock(side_effect=AssertionError("ETF navigation tests must stay offline"))
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    yield
    blocked.assert_not_called()


class ReviewUI:
    def __init__(self):
        self.session_state = {
            "holdings": [{"ticker": "SPY", "quantity": 3}],
            "watchlist": [{"ticker": "MSFT", "target_weight": 5}],
        }
        self.pressed = set()
        self.buttons = []
        self.disabled_buttons = {}
        self.frames = []
        self.captions = []
        self.warnings = []
        self.infos = []
        self.selections = []
        self.selected = None
        self.selection_by_key = {}
        self.rerun = Mock()
        self.link_button = Mock()
        self.column_config = SimpleNamespace(NumberColumn=Mock())

    def button(self, label, *, key, **kwargs):
        self.buttons.append((label, key))
        self.disabled_buttons[key] = bool(kwargs.get("disabled", False))
        return key in self.pressed and not self.disabled_buttons[key]

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def columns(self, widths):
        return [self] * len(widths)

    def caption(self, text):
        self.captions.append(text)

    def warning(self, text):
        self.warnings.append(text)

    def info(self, text):
        self.infos.append(text)

    def dataframe(self, frame, **kwargs):
        self.frames.append(frame.copy(deep=True))

    def selectbox(self, label, options, *, key):
        assert self.session_state.get(key) is None or self.session_state[key] in options
        self.selections.append((label, list(options), key))
        selected = self.selection_by_key.get(key, self.selected if label == "개별 검토 종목" else None)
        target = selected or self.session_state.get(key) or options[0]
        assert target in options
        self.session_state[key] = target
        return target


@pytest.fixture(scope="module")
def app_definitions():
    functions = {
        "queue_etf_constituent_review", "render_etf_parent_return", "render_etf_constituent_review",
        "prioritize_precision_review_request",
        "set_precision_target_ticker", "_queue_precision_selected_option", "_queue_precision_free_target",
        "_split_precision_free_ticker", "_is_precision_kr_code_like",
    }
    constants = {
        "FREE_SEARCH_OPTION", "PRECISION_FREE_MARKET_KEY", "PRECISION_US_MARKET_OPTION",
        "PRECISION_KR_MARKET_OPTIONS", "PRECISION_PENDING_SELECTED_OPTION_KEY",
        "PRECISION_PENDING_FREE_TICKER_KEY", "PRECISION_PENDING_FREE_MARKET_KEY",
    }
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in functions
    ) or (
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in constants
                                            for target in node.targets)
    )]
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == functions
    assert {target.id for node in nodes if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)} == constants
    return compile(ast.Module(body=nodes, type_ignores=[]), str(APP_PATH), "exec")


@pytest.fixture
def offline_app(app_definitions, monkeypatch):
    provider = ModuleType("stock_lab_core.etf_holdings")
    provider.load_etf_holdings = Mock()
    monkeypatch.setitem(sys.modules, provider.__name__, provider)
    timestamp = Mock(wraps=pd.Timestamp)
    timestamp.now.return_value = pd.Timestamp("2026-10-31T00:30:00Z")
    # Keep the cached fixture fresh without changing the process-wide clock.
    app_pandas = SimpleNamespace(DataFrame=pd.DataFrame, to_numeric=pd.to_numeric, Timestamp=timestamp)
    app = SimpleNamespace(
        st=ReviewUI(), pd=app_pandas, np=np, re=re, logging=logging,
        sanitize_ticker_value=sanitize_ticker_value, clean_float=clean_float, is_kr_listed=is_kr_listed,
        build_precision_select_options=Mock(return_value=(["free"], {"free": {"type": "free"}})),
        find_precision_select_label_by_ticker=Mock(return_value=None),
        load_cached_kr_etf_lab_data=Mock(return_value=pd.DataFrame({"ticker": ["069500"]})),
        save_holdings_db=Mock(side_effect=AssertionError("Navigation must not save holdings")),
        save_watchlist_db=Mock(side_effect=AssertionError("Navigation must not save watchlist")),
        provider=provider,
    )
    exec(app_definitions, app.__dict__)
    yield app
    app.save_holdings_db.assert_not_called()
    app.save_watchlist_db.assert_not_called()
    assert app.st.session_state["holdings"] == [{"ticker": "SPY", "quantity": 3}]
    assert app.st.session_state["watchlist"] == [{"ticker": "MSFT", "target_weight": 5}]


def cached_snapshot(ticker="SMH"):
    return {
        "ticker": ticker, "status": "ok", "source": "synthetic issuer",
        "source_url": "https://example.org/holdings", "as_of": "2026-10-30",
        "observed_at": "2026-10-31T00:00:00Z", "scope": "partial",
        "rows": [
            {"name": "Nvidia", "ticker": "NVDA", "weight_pct": 25.5, "kind": "equity", "reviewable": True},
            {"name": "Microsoft", "ticker": "MSFT", "weight_pct": None, "kind": "equity", "reviewable": True},
            {"name": "Cash", "ticker": None, "weight_pct": 0.0, "kind": "cash", "reviewable": False},
            {"name": "Index swap", "ticker": "SWAP", "weight_pct": 10.0, "kind": "swap", "reviewable": False},
        ],
    }


def kr_snapshot(child="005930"):
    snapshot = cached_snapshot("069500.KS")
    snapshot["scope"] = "top5"
    snapshot["rows"] = [
        {"name": "Synthetic security", "ticker": child, "weight_pct": 25.5,
         "kind": "security", "reviewable": True},
    ]
    return snapshot


@pytest.mark.parametrize("child,expected,market", [
    (" nvda ", "NVDA", "미국/기타 (접미사 없음)"),
    ("005930.ks", "005930.KS", "KOSPI (.KS)"),
    ("247540.kq", "247540.KQ", "KOSDAQ (.KQ)"),
])
def test_queue_child_targets_precision_and_only_changes_navigation_state(offline_app, child, expected, market):
    app = offline_app
    original = deepcopy(app.st.session_state)
    assert app.queue_etf_constituent_review(" smh ", "Semiconductors", child) is True
    state = app.st.session_state
    assert state["_precision_parent_etf_review"] == {"ticker": "SMH", "name": "Semiconductors", "child": expected}
    assert state["_pending_main_page_nav"] == "precision"
    assert state[app.PRECISION_PENDING_SELECTED_OPTION_KEY] == app.FREE_SEARCH_OPTION
    assert state[app.PRECISION_PENDING_FREE_TICKER_KEY] == expected.split(".")[0]
    assert state[app.PRECISION_PENDING_FREE_MARKET_KEY] == market
    assert state["_precision_prefill_ticker"] == expected
    assert {key: state[key] for key in original} == original
    app.provider.load_etf_holdings.assert_not_called()
    app.st.rerun.assert_not_called()


def test_queue_existing_selection_uses_the_matching_label(offline_app):
    app = offline_app
    app.find_precision_select_label_by_ticker.return_value = "Nvidia (NVDA)"
    assert app.queue_etf_constituent_review("SMH", "Semiconductors", "nvda") is True
    assert app.st.session_state[app.PRECISION_PENDING_SELECTED_OPTION_KEY] == "Nvidia (NVDA)"
    assert app.PRECISION_PENDING_FREE_TICKER_KEY not in app.st.session_state
    assert app.st.session_state["_precision_parent_etf_review"]["child"] == "NVDA"


@pytest.mark.parametrize("child", ["005930", " 247540 "])
@pytest.mark.parametrize("saved_market", [None, "KOSPI (.KS)", "KOSDAQ (.KQ)"])
def test_queue_bare_kr_code_never_infers_exchange_or_changes_navigation(offline_app, child, saved_market):
    app = offline_app
    app.st.session_state.update(
        _pending_main_page_nav="money_flow",
        _precision_parent_etf_review={"ticker": "SMH", "child": "NVDA"},
    )
    if saved_market is not None:
        app.st.session_state[app.PRECISION_FREE_MARKET_KEY] = saved_market
    before = deepcopy(app.st.session_state)
    app.set_precision_target_ticker = Mock(wraps=app.set_precision_target_ticker)
    assert app.queue_etf_constituent_review("069500.KS", "Synthetic ETF", child) is False
    assert app.st.session_state == before
    app.set_precision_target_ticker.assert_not_called()
    app.build_precision_select_options.assert_not_called()
    app.provider.load_etf_holdings.assert_not_called()
    app.st.rerun.assert_not_called()


@pytest.mark.parametrize("child", [None, "", "NVDA"])
def test_queue_failure_preserves_existing_parent_and_pending_page(offline_app, child):
    app = offline_app
    app.st.session_state.update(_pending_main_page_nav="money_flow", _precision_parent_etf_review={"ticker": "SPY", "child": "MSFT"})
    before = deepcopy(app.st.session_state)
    app.set_precision_target_ticker = Mock(return_value="")
    assert app.queue_etf_constituent_review("SMH", "Semiconductors", child) is False
    assert app.st.session_state == before
    if child:
        app.set_precision_target_ticker.assert_called_once_with("NVDA")
    else:
        app.set_precision_target_ticker.assert_not_called()


@pytest.mark.parametrize("parent", [None, "invalid", [], {}, {"ticker": "SMH", "child": "MSFT"}])
def test_parent_return_is_hidden_unless_current_child_matches(offline_app, parent):
    app = offline_app
    app.st.session_state["_precision_parent_etf_review"] = parent
    before = deepcopy(app.st.session_state)
    app.render_etf_parent_return("NVDA")
    assert app.st.buttons == [] and app.st.session_state == before
    app.st.rerun.assert_not_called()
    app.build_precision_select_options.assert_not_called()


@pytest.mark.parametrize("clicked", [False, True])
def test_parent_return_matching_child_queues_original_etf_only_on_click(offline_app, clicked):
    app = offline_app
    app.st.session_state["_precision_parent_etf_review"] = {"ticker": "SMH", "name": "Semiconductors", "child": "NVDA"}
    before = deepcopy(app.st.session_state)
    if clicked:
        app.st.pressed.add("etf_parent_return_NVDA")
    app.render_etf_parent_return("NVDA")
    assert app.st.buttons == [("Semiconductors 구성종목으로 돌아가기", "etf_parent_return_NVDA")]
    if clicked:
        assert app.st.session_state["_pending_main_page_nav"] == "precision"
        assert app.st.session_state[app.PRECISION_PENDING_FREE_TICKER_KEY] == "SMH"
        assert app.st.session_state["_precision_prefill_ticker"] == "SMH"
        app.st.rerun.assert_called_once_with()
    else:
        assert app.st.session_state == before
        app.st.rerun.assert_not_called()
    app.provider.load_etf_holdings.assert_not_called()


@pytest.mark.parametrize("key_prefix", ["precision", "money_flow", "demo_precision"])
def test_common_review_uses_cached_snapshot_without_fetch_and_preserves_weights(offline_app, key_prefix):
    app, snapshot = offline_app, cached_snapshot()
    app.st.session_state["etf_constituents_SMH"] = snapshot
    before = deepcopy(snapshot)
    result = app.render_etf_constituent_review("smh", name="Semiconductors", key_prefix=key_prefix)
    assert result is snapshot and snapshot == before
    app.provider.load_etf_holdings.assert_not_called()
    app.load_cached_kr_etf_lab_data.assert_not_called()
    assert [key for _, key in app.st.buttons] == [f"{key_prefix}_etf_fetch_SMH", f"{key_prefix}_etf_open_SMH"]
    display = app.st.frames[0].set_index("구성종목")
    assert display.loc["Nvidia", "비중(%)"] == 25.5
    assert pd.isna(display.loc["Microsoft", "비중(%)"])
    assert display.loc["Cash", "비중(%)"] == 0
    assert display.loc["Index swap", "구분"] == "스왑"
    assert display["원문 코드"].tolist() == ["-"] * len(display)
    assert app.st.selections[0][1] == ["Nvidia (NVDA)", "Microsoft (MSFT)"]
    assert any("35.50%" in caption for caption in app.st.captions)
    assert any("조회 범위: 일부 항목 ·" in caption for caption in app.st.captions)
    assert app.st.warnings == []
    app.st.rerun.assert_not_called()


@pytest.mark.parametrize("cache", [None, [], "invalid"])
def test_missing_or_malformed_cache_does_not_fetch_on_render(offline_app, cache):
    app = offline_app
    app.st.session_state["etf_constituents_SMH"] = cache
    before = deepcopy(app.st.session_state)
    assert app.render_etf_constituent_review("SMH") == {"ticker": "SMH", "status": "not_requested", "rows": []}
    assert app.st.session_state == before and app.st.frames == []
    app.provider.load_etf_holdings.assert_not_called()
    app.load_cached_kr_etf_lab_data.assert_not_called()


@pytest.mark.parametrize("has_cache", [False, True], ids=["first-fetch", "refresh"])
@pytest.mark.parametrize("ticker", ["SMH", "069500.KS"])
def test_provider_runs_only_after_selected_etf_button_and_gets_refresh_contract(offline_app, ticker, has_cache):
    app = offline_app
    old = cached_snapshot(ticker)
    if has_cache:
        app.st.session_state[f"etf_constituents_{ticker}"] = old
    fresh = cached_snapshot(ticker)
    fresh["rows"] = [fresh["rows"][1]]
    before_old, before_fresh = deepcopy(old), deepcopy(fresh)
    app.provider.load_etf_holdings.return_value = fresh
    app.st.pressed.add(f"precision_etf_fetch_{ticker}")
    result = app.render_etf_constituent_review(ticker)
    assert result is fresh and app.st.session_state[f"etf_constituents_{ticker}"] is fresh
    app.provider.load_etf_holdings.assert_called_once_with(
        ticker, kr_catalog=app.load_cached_kr_etf_lab_data.return_value if is_kr_listed(ticker) else None,
        force_refresh=has_cache,
    )
    if is_kr_listed(ticker):
        app.load_cached_kr_etf_lab_data.assert_called_once_with()
    else:
        app.load_cached_kr_etf_lab_data.assert_not_called()
    assert old == before_old and fresh == before_fresh
    app.st.rerun.assert_not_called()


@pytest.mark.parametrize("has_cache", [False, True], ids=["no-old-rows", "preserve-old-rows"])
@pytest.mark.parametrize("fresh", [None, [], "invalid", RuntimeError("PRIVATE_PROVIDER_DETAIL")],
                         ids=["none", "list", "string", "exception"])
def test_invalid_provider_result_preserves_old_rows_and_reports_safe_fallback(offline_app, has_cache, fresh, caplog):
    app, old = offline_app, cached_snapshot()
    if has_cache:
        app.st.session_state["etf_constituents_SMH"] = old
    before = deepcopy(old)
    if isinstance(fresh, Exception):
        app.provider.load_etf_holdings.side_effect = fresh
    else:
        app.provider.load_etf_holdings.return_value = fresh
    app.st.pressed.add("precision_etf_fetch_SMH")
    result = app.render_etf_constituent_review("SMH")
    assert result is app.st.session_state["etf_constituents_SMH"]
    assert result["status"] == ("stale" if has_cache else "unavailable")
    assert "구성종목 조회 실패" in result["reason"]
    assert result.get("rows", []) == (before["rows"] if has_cache else [])
    assert old == before
    if has_cache:
        assert result["source"] == before["source"] and result["as_of"] == before["as_of"]
        assert result is not old and len(app.st.frames) == 1
    else:
        assert app.st.frames == [] and app.st.infos
    assert app.st.warnings == [result["reason"]]
    assert "PRIVATE_PROVIDER_DETAIL" not in str(result) + str(app.st.warnings) + caplog.text
    app.provider.load_etf_holdings.assert_called_once_with("SMH", kr_catalog=None, force_refresh=has_cache)


def test_open_child_reuses_cache_and_queues_selected_identity_without_saves(offline_app):
    app, snapshot = offline_app, cached_snapshot()
    before = deepcopy(snapshot)
    app.st.session_state.update(etf_constituents_SMH=snapshot, precision_etf_member_SMH="Removed member")
    app.st.selected = "Microsoft (MSFT)"
    app.st.pressed.add("precision_etf_open_SMH")
    result = app.render_etf_constituent_review("SMH", name="Semiconductors")
    assert result is snapshot and snapshot == before
    assert app.st.session_state["_pending_main_page_nav"] == "precision"
    assert app.st.session_state[app.PRECISION_PENDING_FREE_TICKER_KEY] == "MSFT"
    assert app.st.session_state["_precision_parent_etf_review"] == {"ticker": "SMH", "name": "Semiconductors", "child": "MSFT"}
    app.provider.load_etf_holdings.assert_not_called()
    app.load_cached_kr_etf_lab_data.assert_not_called()
    app.st.rerun.assert_called_once_with()


@pytest.mark.parametrize("pressed", [False, True])
def test_bare_kr_member_requires_market_selection_and_disables_open(offline_app, pressed):
    app, snapshot = offline_app, kr_snapshot()
    app.st.session_state["_pending_main_page_nav"] = "money_flow"
    app.st.session_state["etf_constituents_069500.KS"] = snapshot
    app.st.session_state[app.PRECISION_FREE_MARKET_KEY] = "KOSPI (.KS)"
    before_snapshot, before_state = deepcopy(snapshot), deepcopy(app.st.session_state)
    market_key = "precision_etf_market_069500.KS_005930"
    open_key = "precision_etf_open_069500.KS"
    if pressed:
        app.st.pressed.add(open_key)
    app.set_precision_target_ticker = Mock(wraps=app.set_precision_target_ticker)
    result = app.render_etf_constituent_review("069500.KS", name="Synthetic ETF")
    assert result is snapshot and snapshot == before_snapshot
    assert app.st.selections[1] == (
        "구성종목 상장시장", ["시장 선택", "KOSPI (.KS)", "KOSDAQ (.KQ)"], market_key,
    )
    assert app.st.session_state[market_key] == "시장 선택"
    assert app.st.disabled_buttons[open_key] is True
    assert {key: app.st.session_state[key] for key in before_state} == before_state
    assert app.PRECISION_PENDING_FREE_TICKER_KEY not in app.st.session_state
    assert "_precision_parent_etf_review" not in app.st.session_state
    app.set_precision_target_ticker.assert_not_called()
    app.provider.load_etf_holdings.assert_not_called()
    app.load_cached_kr_etf_lab_data.assert_not_called()
    app.st.rerun.assert_not_called()


@pytest.mark.parametrize("key_prefix", ["precision", "money_flow", "demo_precision"])
@pytest.mark.parametrize("market,suffix", [("KOSPI (.KS)", ".KS"), ("KOSDAQ (.KQ)", ".KQ")])
def test_bare_kr_member_uses_explicit_market_choice_for_navigation(offline_app, key_prefix, market, suffix):
    app, snapshot = offline_app, kr_snapshot()
    app.st.session_state["etf_constituents_069500.KS"] = snapshot
    app.st.session_state[app.PRECISION_FREE_MARKET_KEY] = "KOSDAQ (.KQ)" if suffix == ".KS" else "KOSPI (.KS)"
    before = deepcopy(snapshot)
    market_key = f"{key_prefix}_etf_market_069500.KS_005930"
    open_key = f"{key_prefix}_etf_open_069500.KS"
    app.st.selection_by_key[market_key] = market
    app.st.pressed.add(open_key)
    result = app.render_etf_constituent_review("069500.KS", name="Synthetic ETF", key_prefix=key_prefix)
    assert result is snapshot and snapshot == before
    assert app.st.disabled_buttons[open_key] is False
    assert app.st.session_state["_pending_main_page_nav"] == "precision"
    assert app.st.session_state[app.PRECISION_PENDING_FREE_TICKER_KEY] == "005930"
    assert app.st.session_state[app.PRECISION_PENDING_FREE_MARKET_KEY] == market
    assert app.st.session_state["_precision_prefill_ticker"] == "005930" + suffix
    assert app.st.session_state["_precision_parent_etf_review"] == {
        "ticker": "069500.KS", "name": "Synthetic ETF", "child": "005930" + suffix,
    }
    app.provider.load_etf_holdings.assert_not_called()
    app.load_cached_kr_etf_lab_data.assert_not_called()
    app.st.rerun.assert_called_once_with()


@pytest.mark.parametrize("child,market,saved_market", [
    ("247540.KQ", "KOSDAQ (.KQ)", "KOSPI (.KS)"),
    ("005930.KS", "KOSPI (.KS)", "KOSDAQ (.KQ)"),
])
def test_explicit_kr_suffix_is_preserved_without_an_extra_market_prompt(offline_app, child, market, saved_market):
    app, snapshot = offline_app, kr_snapshot(child)
    app.st.session_state["etf_constituents_069500.KS"] = snapshot
    app.st.session_state[app.PRECISION_FREE_MARKET_KEY] = saved_market
    before = deepcopy(snapshot)
    app.st.pressed.add("precision_etf_open_069500.KS")
    assert app.render_etf_constituent_review("069500.KS") is snapshot
    assert [label for label, _, _ in app.st.selections] == ["개별 검토 종목"]
    assert app.st.disabled_buttons["precision_etf_open_069500.KS"] is False
    assert app.st.session_state[app.PRECISION_PENDING_FREE_MARKET_KEY] == market
    assert app.st.session_state["_precision_prefill_ticker"] == child
    assert app.st.session_state["_precision_parent_etf_review"]["child"] == child
    assert snapshot == before
    app.provider.load_etf_holdings.assert_not_called()
    app.st.rerun.assert_called_once_with()


@pytest.mark.parametrize("source_ticker", [None, "A005930"])
def test_security_translation_and_optional_original_code_preserve_source(offline_app, source_ticker):
    app, snapshot = offline_app, kr_snapshot()
    if source_ticker is not None:
        snapshot["rows"][0]["source_ticker"] = source_ticker
    before = deepcopy(snapshot)
    app.st.session_state["etf_constituents_069500.KS"] = snapshot
    assert app.render_etf_constituent_review("069500.KS") is snapshot
    row = app.st.frames[0].iloc[0]
    assert row["구분"] == "상장 증권"
    assert row["티커"] == "005930"
    assert row["원문 코드"] == (source_ticker or "-")
    assert snapshot == before
    app.provider.load_etf_holdings.assert_not_called()


@pytest.mark.parametrize("scope,label", [
    ("all_reported", "제공처 보고 항목 전체"), ("partial", "일부 항목"),
    ("top10", "상위 10종목"), ("top5", "상위 5종목"),
    ("none", "미수집"), ("unknown-provider-scope", "확인 범위 미제공"),
])
def test_scope_is_rendered_in_korean_without_changing_snapshot(offline_app, scope, label):
    app, snapshot = offline_app, cached_snapshot()
    snapshot["scope"] = scope
    before = deepcopy(snapshot)
    app.st.session_state["etf_constituents_SMH"] = snapshot
    assert app.render_etf_constituent_review("SMH") is snapshot
    assert any(caption.startswith(f"조회 범위: {label} ·") for caption in app.st.captions)
    assert snapshot == before
    app.provider.load_etf_holdings.assert_not_called()


def test_nonreviewable_constituents_do_not_offer_stock_navigation(offline_app):
    app, snapshot = offline_app, cached_snapshot()
    snapshot["rows"] = snapshot["rows"][2:]
    app.st.session_state["etf_constituents_SMH"] = snapshot
    before = deepcopy(snapshot)
    assert app.render_etf_constituent_review("SMH") is snapshot
    assert app.st.selections == []
    assert [key for _, key in app.st.buttons] == ["precision_etf_fetch_SMH"]
    assert "_precision_parent_etf_review" not in app.st.session_state
    assert snapshot == before
    app.provider.load_etf_holdings.assert_not_called()


@pytest.mark.parametrize("live_available", [False, True])
def test_old_top_five_is_only_an_explicit_historical_fallback(offline_app, live_available):
    app = offline_app
    live = cached_snapshot()
    if not live_available:
        live.update(rows=[], status="unavailable", reason="http_401")
    app.US_ETF_COMPOSITION_FALLBACKS = {
        "SMH": {"source": "old issuer", "as_of": "2026-09-29", "rows": [("Archived member", "OLD", 5.0)]},
    }
    app.US_ETF_HOLDINGS_URLS = {"SMH": "https://issuer.example/holdings"}
    app.provider.load_etf_holdings.return_value = live
    app.st.pressed.add("precision_etf_fetch_SMH")
    result = app.render_etf_constituent_review("SMH")
    if live_available:
        assert result is live
        assert result["rows"][0]["ticker"] != "OLD"
    else:
        assert result["status"] == "stale" and result["as_of"] == "2026-09-29"
        assert result["holdings_basis"] == "historical_reference"
        assert result["source_url"] == "https://issuer.example/holdings"
        assert result["rows"][0]["ticker"] == "OLD"
        assert any("현재 편입·비중이 아님" in text for text in app.st.warnings)


@pytest.mark.parametrize("ticker,base,market", [("SOXX", "SOXX", "미국/기타 (접미사 없음)"),
                                               ("247540.KQ", "247540", "KOSDAQ (.KQ)")])
def test_review_target_wins_over_old_widget_callback_and_keeps_durable_identity(offline_app, ticker, base, market):
    app = offline_app
    previous = {"ticker": "GOOGL"}
    app.st.session_state["_precision_review_requested_ticker"] = ticker
    assert app.prioritize_precision_review_request({"free": {"type": "free"}}, previous) == {}
    assert previous == {"ticker": "GOOGL"}
    assert "_precision_review_requested_ticker" not in app.st.session_state
    identity = app.st.session_state["_precision_last_free_identity"]
    assert identity["ticker"] == base and identity["market"] == market
    assert app.st.session_state[app.PRECISION_PENDING_FREE_TICKER_KEY] == base


def test_normal_selector_callback_is_unchanged_without_review_request(offline_app):
    identity = {"ticker": "MSFT"}
    assert offline_app.prioritize_precision_review_request({}, identity) is identity
