"""Portfolio integration regressions with synthetic holdings only, no network."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def state(app_module, monkeypatch):
    session = {
        "_app_holdings_table": pd.DataFrame([
            {"티커": "AAA", "보유량": 2., "매입가": 100., "목표비중": 60., "bucket": "core"},
            {"티커": "BBB", "보유량": 1., "매입가": 200., "목표비중": 30., "bucket": "core"},
        ]),
        "acc_filter": ["A"], "_app_krw_cash": 100., "_app_usd_cash": 0.,
    }
    monkeypatch.setattr(app_module, "st", SimpleNamespace(session_state=session))
    monkeypatch.setattr(app_module, "CURRENT_USER_EMAIL", "test@example.invalid")
    return session


def stamped(app, rows, at):
    frame = app.stamp_portfolio_signal_context(pd.DataFrame(rows))
    frame.attrs["portfolio_signal_at"] = at
    return frame


def test_account_filter_and_cost_change_reject_previous_signals(app_module, state):
    state["_ticker_signal_detail_df"] = stamped(app_module, [{"티커": "AAA", "기술적타점": "old"}], "2026-11-01T01:00Z")
    assert not app_module.get_cached_portfolio_signal_details().empty
    state["acc_filter"] = ["B"]
    assert app_module.get_cached_portfolio_signal_details().empty
    state["acc_filter"] = ["A"]
    state["_app_holdings_table"].loc[0, "매입가"] = 120.
    assert app_module.get_cached_portfolio_signal_details().empty


def test_latest_per_ticker_not_first_partial_source_wins(app_module, state):
    state["_ticker_signal_detail_df"] = stamped(app_module, [
        {"티커": "AAA.US", "기술적타점": "old", "후보등급": "old grade"},
        {"티커": "CCC", "기술적타점": "unshared"},
    ], "2026-11-01T01:00Z")
    state["portfolio_today_signal_df"] = stamped(app_module, [
        {"티커": "AAA", "🔥기술적 타점": "new", "📌후보등급": "new grade"},
        {"티커": "BBB", "🔥기술적 타점": "new B"},
    ], "2026-11-01T02:00Z")
    result = app_module.get_cached_portfolio_signal_details().set_index("티커")
    assert result.loc["AAA", "기술적타점"] == "new"
    assert result.loc["AAA", "후보등급"] == "new grade"
    assert result.loc["BBB", "기술적타점"] == "new B"
    assert result.loc["CCC", "기술적타점"] == "unshared"
    state["_ticker_signal_detail_df"].attrs["portfolio_signal_at"] = "2026-11-01T03:00Z"
    result = app_module.get_cached_portfolio_signal_details().set_index("티커")
    assert result.loc["AAA.US", "기술적타점"] == "old"
    assert result.loc["BBB", "기술적타점"] == "new B"


def test_legacy_unscoped_cache_not_reused_and_live_ticks_do_not_invalidate(app_module, state):
    raw = pd.DataFrame([{"티커": "AAA", "기술적타점": "old"}])
    state["_ticker_signal_detail_df"] = raw
    state["today_queue_summary_df"] = raw
    state["_ticker_signal_cache"] = {"AAA": "old"}
    assert app_module.get_cached_portfolio_signal_details().empty
    state["_ticker_signal_detail_df"] = stamped(app_module, raw.to_dict("records"), "2026-11-01T01:00Z")
    context = app_module.portfolio_signal_input_context()
    state["_app_holdings_table"]["현재가"] = [110., 220.]
    state["_app_usdkrw"] = 1350.
    assert app_module.portfolio_signal_input_context() == context
    assert not app_module.get_cached_portfolio_signal_details().empty


def test_unrelated_financial_score_does_not_disconnect_held_signals(app_module, state):
    state["fin_score_map"] = {"AAA": 3}
    context = app_module.portfolio_signal_input_context()
    state["fin_score_map"]["UNHELD"] = 1
    assert app_module.portfolio_signal_input_context() == context
    state["fin_score_map"]["AAA"] = 2
    assert app_module.portfolio_signal_input_context() != context


def test_snapshot_restores_original_context_and_time_not_a_fresh_stamp(app_module, state, tmp_path):
    from stock_lab_core.today_snapshot import save_today_queue_summary_snapshot, load_today_queue_summary_snapshot

    frame = stamped(app_module, [{"티커": "AAA", "기술적타점": "saved"}], "2026-11-01T01:00Z")
    path = tmp_path / "summary.json"
    save_today_queue_summary_snapshot(frame, "same", path=path, owner_scope="test@example.invalid")
    loaded, _, _ = load_today_queue_summary_snapshot(path=path, owner_scope="test@example.invalid", expected_signature="same")
    assert loaded.attrs == frame.attrs
    state["portfolio_today_signal_df"] = loaded
    assert app_module.get_cached_portfolio_signal_details().iloc[0]["기술적타점"] == "saved"
    state["acc_filter"] = ["B"]
    assert app_module.get_cached_portfolio_signal_details().empty


def test_derived_summary_invalidation_clears_portfolio_copy(app_module, state):
    from stock_lab_core.today_snapshot import invalidate_incompatible_summary_state

    frame = stamped(app_module, [{"티커": "AAA", "기술적타점": "saved"}], "2026-11-01T01:00Z")
    state["portfolio_today_signal_df"] = frame
    assert not app_module.get_cached_portfolio_signal_details().empty
    app_module.invalidate_watchlist_dependent_state()
    assert app_module.get_cached_portfolio_signal_details().empty
    state["portfolio_today_signal_df"] = frame
    assert invalidate_incompatible_summary_state(state)
    assert app_module.get_cached_portfolio_signal_details().empty


def synthetic_report(app, monkeypatch, histories):
    monkeypatch.setattr(app, "load_price_df", lambda ticker, period: pd.DataFrame({"Close": histories[ticker]}))
    monkeypatch.setattr(app, "calc_blended_benchmark_comparison", lambda *a, **kw: {})
    monkeypatch.setattr(app, "calc_benchmark_comparison", lambda *a, **kw: {})
    holdings = pd.DataFrame([
        {"티커": ticker, "자산명": ticker, "원화환산": 400., "목표비중": 40.,
         "bucket": "core", "운용대상": True} for ticker in histories
    ])
    return app.build_portfolio_analysis_report(holdings, 200., 0., 1300., 10.)


def test_short_history_does_not_manufacture_flat_prelisting_days(app_module, monkeypatch):
    dates = pd.bdate_range("2026-08-03", periods=80)
    long = pd.Series(np.linspace(100., 120., 80), index=dates)
    short = pd.Series(np.linspace(100., 130., 22), index=dates[-22:])
    metrics, _, _, _, curve, _ = synthetic_report(app_module, monkeypatch, {"AAA": long, "BBB": short})
    assert metrics["portfolio_observation_count"] == 21
    assert metrics["return_window"]["start"] == short.index[0]
    assert curve.index[0] == short.index[0]
    expected = (1 + .4 * long.pct_change().loc[short.index[1:]] + .4 * short.pct_change().dropna()).prod()
    assert curve.iloc[-1] == pytest.approx(expected)


def test_first_day_loss_is_included_in_mdd_and_cash_dampens_returns(app_module, monkeypatch):
    dates = pd.bdate_range("2026-09-01", periods=25)
    prices = pd.Series([100.] + [90.] * 24, index=dates)
    metrics, _, _, _, curve, _ = synthetic_report(app_module, monkeypatch, {"AAA": prices, "BBB": prices})
    assert metrics["portfolio_period_return"] == pytest.approx(-8.)
    assert metrics["portfolio_mdd"] == pytest.approx(-8.)
    assert curve.iloc[0] == 1.
    assert metrics["reserve_summary"]["cash_value"] == 200.


def test_internal_gap_is_not_implicitly_padded_beyond_limit(app_module, monkeypatch):
    dates = pd.bdate_range("2026-08-03", periods=80)
    full = pd.Series(np.linspace(100., 120., 80), index=dates)
    gapped = full.drop(dates[30:40])
    metrics, *_ = synthetic_report(app_module, monkeypatch, {"AAA": full, "BBB": gapped})
    assert metrics["portfolio_observation_count"] == 71
    assert metrics["return_window"]["excluded_days"] == 8


@pytest.mark.parametrize("ticker,multiplier", [("RAM", 1.85), ("BITX", 1.85), ("418660.KS", 1.85), ("SOXL", 2.8)])
def test_stress_proxy_uses_shared_leverage_identity(app_module, ticker, multiplier):
    assets = pd.DataFrame([{"티커": ticker, "자산명": ticker, "전체비중": 100.}])
    result = app_module.calc_historical_stress_test({}, assets, 1000.)
    assert result[0]["포트 추정 손익(%)"] == pytest.approx(round((-30. if ticker.endswith(".KS") else -35.) * multiplier, 1))


def test_stress_uses_real_etf_prices_without_multiplying_twice(app_module):
    dates = pd.bdate_range("2020-02-20", "2020-03-23")
    prices = pd.Series(np.linspace(100., 60., len(dates)), index=dates)
    assets = pd.DataFrame([{"티커": "RAM", "자산명": "RAM", "전체비중": 100.}])
    result = app_module.calc_historical_stress_test({"RAM": prices}, assets, 1000.)
    assert result[1]["포트 추정 손익(%)"] == -40.


def test_total_assets_and_waiting_funds_match_overview_and_scenario(app_module, monkeypatch):
    from stock_lab_core.portfolio import build_asset_overview_dashboard_state, build_scenario_context, calc_portfolio_summary

    dates = pd.bdate_range("2026-09-01", periods=25)
    monkeypatch.setattr(app_module, "load_price_df", lambda *a: pd.DataFrame({"Close": np.linspace(100., 110., 25)}, index=dates))
    monkeypatch.setattr(app_module, "calc_blended_benchmark_comparison", lambda *a, **kw: {})
    monkeypatch.setattr(app_module, "calc_benchmark_comparison", lambda *a, **kw: {})
    holdings = pd.DataFrame([
        {"티커": "AAA", "자산명": "AAA", "원화환산": 700., "bucket": "core", "운용대상": True, "목표비중": 70.},
        {"티커": "SGOV", "자산명": "SGOV", "원화환산": 200., "bucket": "reserve", "운용대상": False, "목표비중": 0.},
    ])
    summary = calc_portfolio_summary(holdings, 1000., 50., 1., 50., pd.DataFrame())
    overview = build_asset_overview_dashboard_state(holdings, summary, 50., 1., 50., 30.)
    scenario = build_scenario_context(holdings, 50., 1., 50., 30.)
    metrics, assets, *_ = app_module.build_portfolio_analysis_report(holdings, 50., 1., 50., 30.)
    assert metrics["total_asset"] == summary["current_asset"] == scenario["total_asset"] == 1000.
    assert metrics["reserve_summary"] == overview["reserve_summary"] == scenario["reserve_summary"]
    assert metrics["reserve_summary"]["waiting_value"] == 300.
    assert metrics["reserve_summary"]["cash_value"] == 100.
    assert assets["전체비중"].sum() == 70.
