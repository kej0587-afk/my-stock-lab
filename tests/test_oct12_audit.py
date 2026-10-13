import math

import pandas as pd
import pytest

from stock_lab_core.execution_gate import apply_execution_gate_columns, build_execution_gate
from stock_lab_core.review_audit import cross_view_flags
from stock_lab_core.signal_evaluation import next_open_outcomes
from tests.fixtures_price import make_price_df


def test_new_etf_missing_history_reason_is_not_ok():
    gate = build_execution_gate({"판정코드": "NEW_ETF_MIN_DATA_WATCH", "데이터상태": "OK"})
    assert gate["게이트상태"] == "데이터확인"
    assert "20봉" in gate["게이트근거"]


def test_final_read_uses_gate_and_reapplication_is_stable():
    df = pd.DataFrame([{"판정코드": "ETF_DCA_OK", "판정분류": "buyish", "최종읽기": "DCA 분할 가능", "시장실행상태": "레버리지 시장방어", "R/R": 2}])
    out = apply_execution_gate_columns(df)
    assert out.iloc[0]["최종읽기"] == "방어우선: 추가매수 보류"
    assert out.iloc[0]["원천최종읽기"] == "DCA 분할 가능"
    pd.testing.assert_frame_equal(out, apply_execution_gate_columns(out))


def test_flow_defense_is_audited_without_promoting_candidate():
    summary = pd.DataFrame([{"티커": "DELL", "게이트상태": "방어우선", "게이트근거": "상위 시간대 추세훼손"}])
    flow = pd.DataFrame([{"Ticker": "DELL", "상태": "강세 가속"}] * 2)
    flags = cross_view_flags(summary, flow)
    assert len(flags) == 1
    assert flags[0]["등급"] == "참고"
    assert "동시 존재" in flags[0]["문제"]


def test_next_open_gap_and_incomplete_horizons():
    df = pd.DataFrame({"Open": [100, 120, 110], "Close": [100, 110, 108], "Low": [99, 109, 105]}, index=pd.date_range("2026-01-01", periods=3))
    result = next_open_outcomes(df, 0, horizons=(1, 2, 5))
    assert result["진입가"] == 120
    assert result["1일후"] == pytest.approx((110 / 120 - 1) * 100)
    assert result["2일최대낙폭"] == pytest.approx((105 / 120 - 1) * 100)
    assert math.isnan(result["5일후"])
    df.loc[df.index[1], "Open"] = math.nan
    assert math.isnan(next_open_outcomes(df, 0)["진입가"])


@pytest.mark.parametrize("code", ["HARD_BLOCK_BOLLINGER_UPPER", "HARD_BLOCK_OVERWEIGHT", "DATA_ERROR"])
def test_timing_and_allocation_not_directional_avoid(app_module, code):
    assert app_module.classify_signal_journal_side(code, "하드차단", "추격금지") == "neutral"


def test_waiting_buy_candidate_not_counted_as_buy_hit(app_module):
    row = {"티커": "MAGS", "종목명": "MAGS", "판정코드": "ETF_DCA_OK", "최종읽기": "적립 매수 가능", "게이트상태": "대기/관찰", "볼린저 %B": 0.98}
    saved = app_module.make_signal_journal_row_from_summary(row)
    assert saved["signal_side"] == "neutral"
    assert saved["pct_b"] == 0.98


def test_error_row_unknown_weights_not_zero(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "load_display_live_price", lambda ticker: 10)
    row = app_module.build_summary_status_item({"ticker": "BITX", "name": "BITX", "is_etf": True}, "TypeError", code="DATA_ERROR")["row"]
    assert math.isnan(row["비중차이"])
    assert math.isnan(row["현재비중"])


@pytest.mark.parametrize("ticker,asset_class", [("069500.KS", "kr_etf"), ("BITX", "us_etf")])
@pytest.mark.parametrize("drift", [-0.003, 0.0, 0.003])
def test_queue_etf_decision_paths(app_module, monkeypatch, ticker, asset_class, drift):
    from tests.test_decision_golden_snapshot import _bench_info
    app = app_module
    frame = make_price_df(daily_drift=drift, seed=12)
    monkeypatch.setattr(app, "load_price_df", lambda *a, **k: frame.copy())
    monkeypatch.setattr(app, "load_display_live_price", lambda ticker: 0)
    monkeypatch.setattr(app, "get_my_price", lambda *a: 100)
    monkeypatch.setattr(app, "has_position", lambda *a: ticker == "BITX")
    monkeypatch.setattr(app, "get_effective_weights", lambda *a: (1.8, 4.0))
    monkeypatch.setattr(app, "get_effective_buy_amount", lambda *a: 220000)
    monkeypatch.setattr(app, "get_effective_bucket", lambda *a: "leverage" if ticker == "BITX" else "core")
    monkeypatch.setattr(app, "get_rs_score", lambda *a: (1, "보통"))
    monkeypatch.setattr(app, "get_rs_slope", lambda *a: (0, "보통", 0))
    monkeypatch.setattr(app, "get_auto_benchmark_info", lambda *a: _bench_info())
    monkeypatch.setattr(app, "build_precision_multi_timeframe_pack", lambda *a: {})
    result = app._compute_summary_item({"ticker": ticker, "name": ticker, "is_etf": True, "asset_class": asset_class}, "자유모드", 1.5, 1.5, 10000000, 0, 0)
    assert result["row"]["판정코드"] != "DATA_ERROR", result["row"]["데이터상태"]


def test_quote_only_volume_never_fabricated(monkeypatch):
    from stock_lab_core import decision_engine as de
    from stock_lab_core.ta_engine import build_indicators
    df = make_price_df(seed=11)
    original = df.copy(deep=True)
    monkeypatch.setattr(de, "_get_live_price_row_date", lambda ticker: df.index[-1] + pd.Timedelta(days=1))
    updated, applied, issue = de.apply_live_price_with_indicators(df, float(df.Close.iloc[-1]) * 1.02, "TEST", build_indicators)
    assert applied and not issue
    assert math.isnan(updated.Volume.iloc[-1])
    assert updated.attrs["live_quote"]["mfi_asof"] == str(df.index[-1])
    assert updated.MFI.iloc[-1] == df.MFI.iloc[-1]
    context = de.build_tactical_price_context(updated, updated.iloc[-1], updated.Close.iloc[-1])
    assert math.isnan(context["vol_ratio"])
    pd.testing.assert_frame_equal(df, original)


@pytest.mark.parametrize("ticker,provider", [("267260.KS", "fetch_naver_kr_snapshot"), ("ALAB", "fetch_fmp_valuation_snapshot")])
def test_yahoo_failure_does_not_skip_valuation_fallback(app_module, monkeypatch, ticker, provider):
    app = app_module
    class BrokenYahoo:
        def get_info(self):
            raise TypeError("Provider returned None")
    monkeypatch.setattr(app.yf, "Ticker", lambda *a, **k: BrokenYahoo())
    monkeypatch.setattr(app, "fetch_kiwoom_valuation_snapshot", lambda *a: {"ok": False})
    monkeypatch.setattr(app, provider, lambda *a: {"ok": True, "data": {"trailingPE": 18.0}})
    app.fetch_valuation_snapshot.clear()
    try:
        result = app.fetch_valuation_snapshot(ticker)
        assert result["ok"]
        assert result["data"]["trailingPE"] == 18
        assert "Yahoo 조회 실패" in result["reason"]
    finally:
        app.fetch_valuation_snapshot.clear()


def test_financial_weight_keys_do_not_repeat(app_module):
    keys = app_module.FIN_S_KEYS + app_module.FIN_A_KEYS + app_module.FIN_B_KEYS
    assert len(keys) == len(set(keys))


def test_small_overweight_display_does_not_imply_room_to_buy():
    from stock_lab_core.portfolio import apply_holdings_weight_columns
    frame = pd.DataFrame([{"원화환산": 310500, "목표비중": 31.0, "bucket": "core"}])
    row = apply_holdings_weight_columns(frame, 689500, 0, 1400).iloc[0]
    assert row["현재비중"] == pytest.approx(31.05)
    assert "추가매수 중단" in row["비중상태"]
