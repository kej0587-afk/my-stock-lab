import numpy as np
import pandas as pd

from stock_lab_core.portfolio import (
    annualize_period_return,
    build_asset_overview_dashboard_state,
    build_asset_overview_kpis,
    build_cash_buffer_scenario,
    build_market_scenario_summary,
    build_monthly_record_status,
    build_portfolio_action_decision_df_from_inputs,
    build_portfolio_blended_benchmark_spec,
    build_portfolio_market_alignment_df_from_inputs,
    build_correlation_pair_summary,
    build_risk_contribution_df,
    build_scenario_context,
    calc_asset_shock_table,
    calc_benchmark_metrics_from_returns,
    calc_drawdown_details,
    calc_pnl_krw_from_row,
    calc_portfolio_leverage_summary,
    calc_series_mdd,
    get_active_portfolio_rows,
    get_holding_row_by_ticker,
    get_portfolio_analysis_start_date,
    infer_benchmark_leverage_multiplier,
    infer_blended_benchmark_proxy,
    infer_scenario_shock_multiplier,
    merge_portfolio_signal_details,
)


def test_app_portfolio_report_imports_annualized_return_helper(app_module):
    assert app_module.annualize_period_return(0.10, 252) == annualize_period_return(0.10, 252)


def _signal_backtest_price_frame(rows=180, high_value=None):
    dates = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = pd.Series(np.linspace(100, 130, rows), index=dates)
    high = pd.Series(high_value if high_value is not None else close, index=dates)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": high,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 100_000,
            "MA20": close * 0.99,
            "MA50": close * 0.98,
            "MA120": close * 0.95,
            "RSI": 50,
            "MFI": 50,
            "%B": 0.50,
            "MACD": np.linspace(0, 1, rows),
            "MACD_Sig": np.linspace(-0.1, 0.8, rows),
        },
        index=dates,
    )


def test_signal_backtest_supports_current_app_breakout_signal(app_module, monkeypatch):
    df = _signal_backtest_price_frame()
    monkeypatch.setattr(app_module, "load_price_df", lambda ticker, period: df)
    monkeypatch.setattr(app_module, "build_indicators", lambda price_df: price_df)
    monkeypatch.setattr(app_module, "get_rs_benchmark", lambda ticker, asset_class: "")

    events_df, _, message = app_module.build_signal_backtest(
        "TEST",
        "테스트",
        "us_stock",
        "52주 신고가 돌파",
        period="2y",
        min_gap=20,
    )

    assert message == ""
    assert not events_df.empty
    assert set(["5일후", "20일후", "60일후"]).issubset(events_df.columns)


def test_detect_52w_breakout_uses_prior_high_not_today_high(app_module):
    dates = pd.date_range("2026-01-01", periods=80, freq="B")
    close = pd.Series(95.0, index=dates)
    high = pd.Series(100.0, index=dates)
    volume = pd.Series(100_000.0, index=dates)
    close.iloc[-2] = 99.0
    close.iloc[-1] = 105.0
    high.iloc[-1] = 110.0
    volume.iloc[-1] = 250_000.0
    df = pd.DataFrame({
        "High": high,
        "Low": close * 0.98,
        "Close": close,
        "Volume": volume,
    })

    result = app_module.detect_52w_breakout(df)

    assert result["breakout"] is True
    assert "52주 신고가 돌파" in result["label"]


def test_detect_52w_breakout_handles_missing_or_sparse_inputs(app_module):
    assert app_module.detect_52w_breakout(None)["label"] == "데이터부족"
    assert app_module.detect_52w_breakout(pd.DataFrame({"Close": [1, 2, 3]}))["label"] == "데이터부족"

    dates = pd.date_range("2026-01-01", periods=80, freq="B")
    df = pd.DataFrame(
        {
            "High": [np.nan] * 30 + [100.0] * 50,
            "Close": [np.nan] * 30 + [95.0] * 50,
            "Volume": [100_000.0] * 80,
        },
        index=dates,
    )

    assert app_module.detect_52w_breakout(df)["breakout"] is False


def test_calc_atr_returns_zero_for_bad_inputs(app_module):
    assert app_module.calc_atr(None) == 0.0
    assert app_module.calc_atr(pd.DataFrame({"Close": [1, 2, 3]})) == 0.0

    dates = pd.date_range("2026-01-01", periods=20, freq="B")
    bad_df = pd.DataFrame({"High": np.nan, "Low": np.nan, "Close": np.nan}, index=dates)

    assert app_module.calc_atr(bad_df) == 0.0


def test_signal_backtest_supports_leveraged_dca_signal(app_module, monkeypatch):
    df = _signal_backtest_price_frame(high_value=200.0)
    monkeypatch.setattr(app_module, "load_price_df", lambda ticker, period: df)
    monkeypatch.setattr(app_module, "build_indicators", lambda price_df: price_df)
    monkeypatch.setattr(app_module, "get_rs_benchmark", lambda ticker, asset_class: "")

    events_df, _, message = app_module.build_signal_backtest(
        "RAM",
        "RAM",
        "us_etf_nasdaq",
        "레버리지 DCA 조건부",
        period="2y",
        min_gap=20,
    )

    assert message == ""
    assert not events_df.empty
    assert "레버리지 DCA 조건부" in app_module.SIGNAL_BACKTEST_TYPES


def test_signal_validation_infers_backtest_types_from_current_decisions(app_module):
    assert app_module.infer_signal_backtest_types_from_decision(
        "LEVERAGED_DCA_CONDITIONAL",
        "⚡레버리지 DCA 조건부: 단계별 소액",
        is_leveraged_product=True,
    ) == ["레버리지 DCA 조건부"]

    assert app_module.infer_signal_backtest_types_from_decision(
        "LEVERAGED_DCA_CONDITIONAL",
        "⚡레버리지 DCA 조건부: 단계별 소액",
        is_leveraged_product=False,
    ) == []

    assert app_module.infer_signal_backtest_types_from_decision(
        "QUALITY_RECOVERY_CANDIDATE",
        "✅우량주 회복 후보: 분할 검토",
    ) == ["우량주 회복 후보"]

    assert app_module.infer_signal_backtest_types_from_decision(
        "STRUCTURE_DAMAGE_NO_ENTRY",
        "⚠️추세방어",
    ) == ["구조훼손 경고"]


def test_build_signal_validation_summary_aggregates_backtest_rows(app_module, monkeypatch):
    events = pd.DataFrame(
        {
            "날짜": ["2024-01-01", "2024-02-01"],
            "종목명": ["테스트", "테스트"],
            "티커": ["TEST", "TEST"],
            "신호": ["52주 신고가 돌파", "52주 신고가 돌파"],
            "신호가": [100.0, 110.0],
            "5일후": [1.0, -1.0],
            "20일후": [5.0, -2.0],
            "60일후": [8.0, 1.0],
            "20일최대낙폭": [-2.0, -6.0],
            "60일최대낙폭": [-4.0, -8.0],
        }
    )
    monkeypatch.setattr(app_module, "build_signal_backtest", lambda **kwargs: (events, pd.DataFrame(), ""))

    summary_df, combined_events, messages = app_module.build_signal_validation_summary(
        "TEST",
        "테스트",
        "us_stock",
        ["52주 신고가 돌파"],
    )

    assert messages == []
    assert len(combined_events) == 2
    assert summary_df.iloc[0]["검증신호"] == "52주 신고가 돌파"
    assert summary_df.iloc[0]["표본"] == 2
    assert summary_df.iloc[0]["검증적중률"] == 50.0
    assert summary_df.iloc[0]["20일승률"] == 50.0
    assert summary_df.iloc[0]["20일평균"] == 1.5


def test_signal_journal_row_captures_current_context(app_module):
    row = {
        "종목명": "마이크로소프트",
        "티커": "MSFT",
        "🔥기술적 타점": "⛔추격금지",
        "판정코드": "OVERHEAT_NO_CHASE",
        "최종읽기": "과열대기",
        "현재가": "$510.25",
        "목표비중": "12.5%",
        "현재비중": "9.0%",
        "매크로상태": "주의",
    }

    out = app_module.make_signal_journal_row_from_summary(row, source="unit", signal_date="2026-01-15")

    assert out["ticker"] == "MSFT"
    assert out["source"] == "unit"
    assert out["signal_side"] == "avoid"
    assert out["price"] == 510.25
    assert out["target_weight"] == 12.5
    assert out["current_weight"] == 9.0
    assert out["macro_state"] == "주의"
    assert out["snapshot"]["현재가"] == "$510.25"


def test_score_signal_journal_rows_scores_buy_and_avoid_signals(app_module):
    dates = pd.date_range("2024-01-02", periods=80, freq="B")

    def fake_loader(ticker, period):
        if ticker == "DOWN":
            close = np.linspace(100, 80, len(dates))
        else:
            close = np.linspace(100, 130, len(dates))
        return pd.DataFrame({"Close": close}, index=dates)

    journal = pd.DataFrame([
        {
            "signal_date": "2024-01-02",
            "source": "unit",
            "ticker": "UP",
            "name": "상승",
            "decision_label": "S급 눌림목",
            "final_read": "진입검토",
            "signal_side": "buy",
            "price": 100.0,
        },
        {
            "signal_date": "2024-01-02",
            "source": "unit",
            "ticker": "UP",
            "name": "상승 회피",
            "decision_label": "추격금지",
            "final_read": "과열대기",
            "signal_side": "avoid",
            "price": 100.0,
        },
        {
            "signal_date": "2024-01-02",
            "source": "unit",
            "ticker": "DOWN",
            "name": "하락 회피",
            "decision_label": "구조훼손",
            "final_read": "방어",
            "signal_side": "avoid",
            "price": 100.0,
        },
    ])

    scored = app_module.score_signal_journal_rows(journal, price_loader=fake_loader)
    result_by_name = dict(zip(scored["종목명"], scored["검증결과"]))

    assert result_by_name["상승"] == "적중"
    assert result_by_name["상승 회피"] == "미스"
    assert result_by_name["하락 회피"] == "적중"
    assert app_module.summarize_scored_signal_journal(scored)["hit_rate"] == 2 / 3 * 100


def test_holding_lookup_matches_us_suffix_variants():
    holdings = pd.DataFrame([
        {"티커": "FCX.US", "자산명": "프리포트 맥모란", "보유량": 2, "매입가": 78.5},
    ])

    row = get_holding_row_by_ticker(holdings, "FCX")

    assert row is not None
    assert row["매입가"] == 78.5


def test_holding_lookup_matches_prefixed_us_ticker():
    holdings = pd.DataFrame([
        {"티커": "NYSE:FCX", "자산명": "프리포트 맥모란", "보유량": 2, "매입가": 78.5},
    ])

    row = get_holding_row_by_ticker(holdings, "FCX")

    assert row is not None
    assert row["자산명"] == "프리포트 맥모란"


def test_calc_series_mdd_and_drawdown_details():
    curve = pd.Series(
        [1.0, 1.2, 0.9, 1.1],
        index=pd.date_range("2026-01-01", periods=4),
    )

    details = calc_drawdown_details(curve)

    assert round(calc_series_mdd(curve), 4) == -0.25
    assert round(details["avg_drawdown"], 1) == -16.7
    assert details["mdd_duration_days"] == 2
    assert details["n_drawdown_periods"] == 1


def test_active_portfolio_rows_filter_cash_reserve_and_inactive_rows():
    holdings = pd.DataFrame(
        [
            {"티커": "VOO", "자산명": "S&P500", "원화환산": 1000, "bucket": "core", "운용대상": True},
            {"티커": "SGOV", "자산명": "대기자금", "원화환산": 500, "bucket": "reserve", "운용대상": False},
            {"티커": "KRW_CASH", "자산명": "원화예수금", "원화환산": 300, "bucket": "cash", "운용대상": False},
            {"티커": "FCX", "자산명": "프리포트", "원화환산": 0, "bucket": "swing", "운용대상": True},
        ]
    )

    active = get_active_portfolio_rows(holdings)

    assert active["티커"].tolist() == ["VOO"]


def test_calc_pnl_krw_from_row_converts_foreign_pnl_only():
    assert calc_pnl_krw_from_row({"티커": "005930.KS", "평가손익": 10_000}, 1400) == 10_000
    assert calc_pnl_krw_from_row({"티커": "KRW_CASH", "평가손익": 0}, 1400) == 0
    assert calc_pnl_krw_from_row({"티커": "FCX", "평가손익": 10}, 1400) == 14_000


def test_core_portfolio_action_decision_marks_underweight_leverage_loss_as_dca_wait():
    metrics = {
        "risk_index": 35,
        "reserve_gap": 0,
        "usdkrw": 1400,
    }
    asset_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.6,
            "목표비중": 10.0,
            "비중차이": 1.4,
            "평가손익_원화": -558_304,
            "수익률_pct": -21.7,
            "기술적타점": "⚡레버리지 조건부 DCA 대기: $12.96 이하 눌림 우선",
            "RS": "RS 강함",
        }
    ])

    decision_df = build_portfolio_action_decision_df_from_inputs(metrics, asset_df)

    row = decision_df.iloc[0]
    assert row["판정"] == "레버리지 DCA 대기"
    assert row["실행"] == "추가매수 중단 · 가격/기초축 회복 조건 대기"
    assert row["재개/해제 조건"] == "DCA 가격조건 + 기초축 회복 + 시장 위험 완화"


def test_core_portfolio_market_alignment_marks_direct_weak_flow_as_hold_check():
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.6,
            "목표비중": 10.0,
            "비중차이": 1.4,
            "수익률_pct": -22.2,
            "기술적타점": "",
        }
    ])
    direct_df = pd.DataFrame([
        {
            "Ticker": "RAM",
            "구분": "미국 섹터",
            "섹터": "DRAM 2배",
            "흐름명": "DRAM 2배",
            "돈흐름점수": -64.7,
        }
    ])

    aligned = build_portfolio_market_alignment_df_from_inputs(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        direct_df=direct_df,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "직접흐름 약세"
    assert row["포트판정"] == "보유점검"
    assert row["판단"] == "개별 돈흐름이 약세라 추가매수보다 회복 조건 확인이 먼저입니다."


def test_merge_portfolio_signal_details_matches_ticker_variants():
    holdings = pd.DataFrame([
        {"티커": "NYSE:FCX", "자산명": "프리포트", "원화환산": 1000, "기술적타점": "이전값"},
        {"티커": "379800.KS", "자산명": "S&P500", "원화환산": 2000},
    ])
    signals = pd.DataFrame([
        {"티커": "FCX", "기술적타점": "추세방어", "후보등급": "B급", "RSI": 51},
        {"티커": "379800", "기술적타점": "장기코어 유지", "후보등급": "코어", "RSI": 48},
    ])

    merged = merge_portfolio_signal_details(holdings, signals)

    fcx = merged[merged["티커"].eq("NYSE:FCX")].iloc[0]
    core = merged[merged["티커"].eq("379800.KS")].iloc[0]
    assert fcx["기술적타점"] == "추세방어"
    assert fcx["후보등급"] == "B급"
    assert fcx["RSI"] == 51
    assert core["기술적타점"] == "장기코어 유지"


def test_portfolio_action_decision_formats_pnl_from_holding_columns(app_module):
    metrics = {
        "risk_index": 35,
        "reserve_gap": 0,
        "usdkrw": 1400,
    }
    asset_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.4,
            "목표비중": 10.0,
            "비중차이": 1.6,
            "평가손익": -10.5,
            "수익률": -0.15,
            "기술적타점": "⚡레버리지 조건부 DCA: 회복 확인",
            "RS": "RS 강함",
        }
    ])

    decision_df = app_module.build_portfolio_action_decision_df(metrics, asset_df)

    row = decision_df.iloc[0]
    assert row["손익"] == "-15.0%"
    assert row["평가손익"] == "-14,700원"
    assert "손익 -15.0%" in row["근거"]


def test_portfolio_action_decision_marks_underweight_leverage_loss_as_dca_wait(app_module):
    metrics = {
        "risk_index": 35,
        "reserve_gap": 0,
        "usdkrw": 1400,
    }
    asset_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.6,
            "목표비중": 10.0,
            "비중차이": 1.4,
            "평가손익_원화": -558_304,
            "수익률_pct": -21.7,
            "기술적타점": "⚡레버리지 조건부 DCA 대기: $12.96 이하 눌림 우선",
            "RS": "RS 강함",
        }
    ])

    decision_df = app_module.build_portfolio_action_decision_df(metrics, asset_df)

    row = decision_df.iloc[0]
    assert row["판정"] == "레버리지 DCA 대기"
    assert row["실행"] == "추가매수 중단 · 가격/기초축 회복 조건 대기"
    assert row["재개/해제 조건"] == "DCA 가격조건 + 기초축 회복 + 시장 위험 완화"


def test_portfolio_market_alignment_maps_leveraged_ai_to_conditional_small(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.4,
            "목표비중": 10.0,
            "비중차이": 1.6,
            "수익률_pct": -15.0,
            "기술적타점": "⚡레버리지 조건부 DCA: 회복 확인",
        }
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "정밀관측",
                "후보군": "미국 AI·반도체",
                "연결테마": "미국 AI·빅테크",
                "내부세부축": "메모리·CPU",
                "ETF/대표": "마이크론 (MU)",
                "판단": "후보 압축, 종목 타점 확인",
                "_점수": 8.5,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["티커"] == "RAM"
    assert row["시장판정"] == "정밀관측"
    assert row["포트판정"] == "조건부 소액"
    assert row["주도축"] == "미국 AI·반도체"


def test_portfolio_market_alignment_marks_underweight_core_leader_as_add_candidate(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "버킷": "core",
            "현재비중": 2.0,
            "목표비중": 5.0,
            "비중차이": 3.0,
            "수익률_pct": 4.2,
            "기술적타점": "분할 매수",
        }
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "정밀관측",
                "후보군": "미국 AI·빅테크",
                "연결테마": "미국 AI·빅테크",
                "내부세부축": "클라우드·AI 플랫폼",
                "ETF/대표": "마이크로소프트 (MSFT)",
                "판단": "후보 압축, 종목 타점 확인",
                "_점수": 9.0,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["티커"] == "MAGS"
    assert row["포트판정"] == "비중확대 후보"
    assert "목표비중 미달" in row["근거"]


def test_portfolio_market_alignment_does_not_attach_semiconductor_to_cyber_representative(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.5,
            "목표비중": 10.0,
            "비중차이": 1.5,
            "수익률_pct": -23.2,
            "기술적타점": "레버리지 회복 대기",
        }
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "눌림대기",
                "후보군": "소프트웨어·사이버",
                "연결테마": "미국 AI·빅테크",
                "내부세부축": "AI 소프트웨어·사이버보안",
                "ETF/대표": "크라우드스트라이크 (CRWD)",
                "판단": "흐름 유지, 진입가 대기",
                "_점수": 3.3,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "연결대기"
    assert row["포트판정"] == "보유점검"
    assert "반도체" in row["주도축"]
    assert "CRWD" not in row["대표/ETF"]


def test_portfolio_market_alignment_does_not_attach_ram_to_generic_domestic_semi_subtheme(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.5,
            "목표비중": 10.0,
            "비중차이": 1.5,
            "수익률_pct": -23.2,
            "기술적타점": "레버리지 회복 대기",
        }
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "관심등록",
                "후보군": "AI·반도체",
                "연결테마": "국내 AI 반도체·소부장",
                "내부세부축": "검사/테스트",
                "ETF/대표": "마이크로컨텍솔 (098120.KQ) ★",
                "판단": "하위테마만 강함, 확인 필요",
                "_점수": -12.7,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "연결대기"
    assert row["포트판정"] == "보유점검"
    assert "반도체" in row["주도축"]
    assert "마이크로컨텍솔" not in row["대표/ETF"]


def test_portfolio_market_alignment_marks_direct_weak_flow_as_hold_check(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "버킷": "leverage",
            "현재비중": 8.6,
            "목표비중": 10.0,
            "비중차이": 1.4,
            "수익률_pct": -22.2,
            "기술적타점": "",
        }
    ])
    snapshot = {
        "flow_df": pd.DataFrame([
            {
                "Ticker": "RAM",
                "구분": "미국 섹터",
                "섹터": "DRAM 2배",
                "name": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
                "돈흐름점수": -64.7,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "직접흐름 약세"
    assert row["포트판정"] == "보유점검"
    assert row["판단"] == "개별 돈흐름이 약세라 추가매수보다 회복 조건 확인이 먼저입니다."


def test_portfolio_market_alignment_marks_broad_index_as_core_axis_not_unlinked(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "S&P500",
            "티커": "379800.KS",
            "버킷": "core",
            "현재비중": 20.0,
            "목표비중": 30.0,
            "비중차이": 10.0,
            "수익률_pct": 1.0,
            "기술적타점": "",
        }
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "관망/제외",
                "후보군": "AI·반도체",
                "연결테마": "AI·반도체",
                "내부세부축": "S&P500",
                "ETF/대표": "마이크론 테크놀로지 -, 어플라이드 머티리얼즈 -, 램 리서치 -",
                "판단": "방향 불일치, 관망",
                "_점수": -21.9,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "기준축"
    assert row["포트판정"] == "계획적 적립"
    assert row["주도축"] != "미연결"
    assert "AI·반도체" not in row["주도축"]
    assert "마이크론" not in row["대표/ETF"]


def test_magnificent_news_terms_match_big_tech_news(app_module):
    text = app_module._brief_axis_news_text(
        {"name": "Magnificent 7", "representatives": "Magnificent 7"},
        [
            {
                "읽기분류": "핵심속보",
                "카테고리": "반도체·AI",
                "종목": "MSFT",
                "제목": "Microsoft Meta Nvidia AI 데이터센터 투자 확대",
                "초보요약": "빅테크 AI 투자 뉴스입니다.",
                "체크": "AI 재료",
            }
        ],
    )

    assert "Microsoft" in text


def test_strict_portfolio_news_ignores_generic_semiconductor_category_for_mags(app_module):
    text = app_module._brief_axis_news_text(
        {"name": "Magnificent 7", "representatives": "Magnificent 7"},
        [
            {
                "읽기분류": "반도체/AI",
                "카테고리": "반도체·AI",
                "종목": "",
                "제목": "LPDDR6는 같은 선상, 메모리 업체 경쟁 심화",
                "초보요약": "메모리 반도체 뉴스입니다.",
                "체크": "반도체·AI 재료",
            }
        ],
        require_direct=True,
    )

    assert text == "-"


def test_strict_portfolio_news_matches_dram_memory_terms(app_module):
    text = app_module._brief_axis_news_text(
        {"name": "DRAM 2배", "representatives": "DRAM 2배"},
        [
            {
                "읽기분류": "반도체/AI",
                "카테고리": "반도체·AI",
                "종목": "",
                "제목": "LPDDR6 경쟁 심화, 메모리 업황 회복 기대",
                "초보요약": "DRAM과 메모리 업체 흐름입니다.",
                "체크": "반도체·AI 재료",
            }
        ],
        require_direct=True,
    )

    assert "LPDDR6" in text


def test_portfolio_bridge_fallback_splits_nasdaq_from_sp500(app_module):
    row = app_module._portfolio_bridge_fallback_row({
        "자산명": "TIGER 미국나스닥100레버리지(합성)",
        "티커": "418660.KS",
    })

    assert row["세부축"] == "NASDAQ100"
    assert row["ETF/대표"] == "QQQ"
    assert "S&P500" not in row["연결테마"]


def test_portfolio_market_alignment_labels_direct_flow_without_command_as_direct(app_module):
    strategy_df = pd.DataFrame([
        {
            "자산명": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "버킷": "core",
            "현재비중": 0.8,
            "목표비중": 6.0,
            "비중차이": 5.2,
            "수익률_pct": -2.1,
            "기술적타점": "",
        }
    ])
    snapshot = {
        "theme_flow_df": pd.DataFrame([
            {
                "Ticker": "MAGS",
                "테마": "미국 AI·빅테크",
                "하위테마": "Magnificent 7",
                "돈흐름점수": 5.8,
            }
        ])
    }

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "직접흐름"
    assert row["포트판정"] == "직접흐름 확인"
    assert row["주도축"] == "Magnificent 7"


def test_portfolio_market_alignment_brief_separates_add_and_caution_groups(app_module):
    align_df = pd.DataFrame([
        {"티커": "379800.KS", "포트판정": "계획적 적립", "시장판정": "기준축", "현재비중": 31.9},
        {"티커": "MAGS", "포트판정": "직접흐름 확인", "시장판정": "직접흐름", "현재비중": 0.8},
        {"티커": "RAM", "포트판정": "관망", "시장판정": "관망/제외", "현재비중": 8.5},
        {"티커": "BITX", "포트판정": "별도관리", "시장판정": "별도관리", "현재비중": 1.1},
    ])

    brief = app_module.build_portfolio_market_alignment_brief(align_df)

    assert "379800.KS" in brief["add_names"]
    assert "MAGS" in brief["direct_names"]
    assert "RAM" in brief["caution_names"]
    assert "BITX" in brief["separate_names"]


def test_portfolio_rebalance_playbook_allocates_leaders_and_separates_trim_candidates(app_module):
    align_df = pd.DataFrame([
        {
            "자산": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "구분": "core",
            "현재비중": 2.0,
            "목표비중": 5.0,
            "비중차이": 3.0,
            "포트판정": "비중확대 후보",
            "시장판정": "정밀관측",
            "점수": 9.0,
            "근거": "주도축과 내 목표비중 미달이 같이 맞습니다.",
        },
        {
            "자산": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "구분": "leverage",
            "현재비중": 8.4,
            "목표비중": 10.0,
            "비중차이": 1.6,
            "포트판정": "조건부 소액",
            "시장판정": "정밀관측",
            "점수": 8.5,
            "근거": "주도축은 맞지만 레버리지는 정해둔 회차와 금액만 봅니다.",
        },
        {
            "자산": "Old Satellite",
            "티커": "OLD",
            "구분": "swing",
            "현재비중": 6.0,
            "목표비중": 3.0,
            "비중차이": -3.0,
            "포트판정": "축소/교체 후보",
            "시장판정": "관망/제외",
            "점수": 1.0,
            "근거": "현재 주도축과 맞지 않고 목표보다 많아 대체 후보와 비교합니다.",
        },
    ])
    metrics = {
        "total_asset": 10_000_000,
        "risk_index": 35,
        "reserve_summary": {"deployable_value": 500_000},
    }

    playbook = app_module.build_portfolio_rebalance_playbook_df(
        align_df,
        metrics,
        monthly_budget=1_000_000,
    )

    mags = playbook[playbook["티커"].eq("MAGS")].iloc[0]
    ram = playbook[playbook["티커"].eq("RAM")].iloc[0]
    old = playbook[playbook["티커"].eq("OLD")].iloc[0]
    assert playbook.attrs["total_budget"] == 1_500_000
    assert mags["제안금액"] == 300_000
    assert ram["제안금액"] == 40_000
    assert old["구분"] == "축소/중단 후보"
    assert old["제안금액"] == 0


def test_portfolio_rebalance_playbook_uses_action_decision_for_separate_conditional_assets(app_module):
    align_df = pd.DataFrame([
        {
            "자산": "2x Bitcoin ETF",
            "티커": "BITX",
            "구분": "leverage",
            "현재비중": 1.1,
            "목표비중": 4.0,
            "비중차이": 2.9,
            "포트판정": "별도관리",
            "시장판정": "별도관리",
            "점수": 0.0,
            "근거": "주식 주도맵과 별도 흐름이라 전용 기준과 목표비중으로 관리합니다.",
        }
    ])
    action_df = pd.DataFrame([
        {
            "티커": "BITX",
            "판정": "조건부 소액",
            "실행": "정해둔 회차와 금액만, 추격 금지",
            "재개/해제 조건": "시장 위험 완화 + 손절선 확인",
        }
    ])
    metrics = {
        "total_asset": 10_000_000,
        "risk_index": 35,
        "reserve_summary": {"deployable_value": 0},
    }

    playbook = app_module.build_portfolio_rebalance_playbook_df(
        align_df,
        metrics,
        monthly_budget=100_000,
        action_df=action_df,
    )

    bitx = playbook[playbook["티커"].eq("BITX")].iloc[0]
    assert bitx["포트판정"] == "별도 소액"
    assert bitx["자산현황판정"] == "조건부 소액"
    assert bitx["제안금액"] == 34_800
    assert "전용 기준" in bitx["조건"]


def test_portfolio_recommendation_df_combines_owned_market_and_funding_candidates(app_module):
    align_df = pd.DataFrame([
        {
            "자산": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "구분": "core",
            "현재비중": 0.8,
            "목표비중": 6.0,
            "비중차이": 5.2,
            "손익": "-2.0%",
            "주도축": "Magnificent 7",
            "세부축": "Magnificent 7",
            "시장판정": "직접흐름",
            "포트판정": "직접흐름 확인",
            "판단": "개별 돈흐름은 잡혔지만 상위 주도축 확인이 더 필요합니다.",
            "대표/ETF": "Magnificent 7",
            "점수": 6.8,
            "근거": "개별 돈흐름 확인",
        },
        {
            "자산": "SOXL",
            "티커": "SOXL",
            "구분": "leverage",
            "현재비중": 5.0,
            "목표비중": 3.0,
            "비중차이": -2.0,
            "손익": "-14.0%",
            "주도축": "Semiconductor Bull 3X",
            "세부축": "Semiconductor Bull 3X",
            "시장판정": "직접흐름 약세",
            "포트판정": "보유점검",
            "판단": "회복 조건 확인",
            "대표/ETF": "SOXL",
            "점수": -46.0,
            "근거": "비중초과와 회복 조건 확인",
        },
    ])
    action_df = pd.DataFrame([
        {"티커": "MAGS", "판정": "조건부 적립", "실행": "분할", "재개/해제 조건": "시장 위험 완화"},
        {"티커": "SOXL", "판정": "축소/교체 검토", "실행": "추가매수 중단", "재개/해제 조건": "목표비중 이하"},
    ])
    snapshot = {
        "command_flow_df": pd.DataFrame([
            {
                "행동": "정밀관측",
                "후보군": "AI 서버·보안",
                "연결테마": "미국 AI·빅테크",
                "세부축": "서버·보안",
                "ETF/대표": "DELL · CRWD",
                "판단": "서버와 보안 대표주 동행 확인",
                "다음확인": "정밀관측소 R/R 확인",
                "_점수": 8.5,
            },
            {
                "행동": "추격금지",
                "후보군": "과열 테마",
                "ETF/대표": "HOT",
                "_점수": 9.9,
            },
        ])
    }
    news_rows = [
        {
            "읽기분류": "핵심속보",
            "카테고리": "반도체·AI",
            "종목": "DELL",
            "제목": "Dell AI 서버 수요 증가",
            "초보요약": "AI 서버 투자 뉴스입니다.",
            "체크": "AI 재료",
        }
    ]

    rec_df = app_module.build_portfolio_recommendation_df(
        align_df,
        metrics={"risk_index": 45},
        snapshot=snapshot,
        action_df=action_df,
        news_rows=news_rows,
        limit=8,
    )

    groups = set(rec_df["추천구분"])
    assert "조건부 보강" in groups
    assert "신규 정밀관측" in groups
    assert "교체 재원" in groups
    assert rec_df[rec_df["후보"].eq("AI 서버·보안")]["티커/대표"].iloc[0] == "DELL · CRWD"
    assert "HOT" not in " ".join(rec_df["티커/대표"].astype(str))
    assert rec_df[rec_df["티커/대표"].eq("SOXL")]["실행강도"].iloc[0] == "재원 점검"


def test_portfolio_next_check_candidates_combine_action_news_and_alignment(app_module):
    align_df = pd.DataFrame([
        {
            "자산": "S&P500",
            "티커": "379800.KS",
            "구분": "core",
            "현재비중": 18.0,
            "목표비중": 35.0,
            "비중차이": 17.0,
            "손익": "+2.0%",
            "주도축": "S&P500",
            "세부축": "미국 대형주",
            "시장판정": "기준축",
            "포트판정": "계획적 적립",
            "판단": "장기 기준축입니다.",
            "대표/ETF": "VOO",
            "점수": 3.0,
            "근거": "장기 기준축이라 정해둔 적립률 안에서 봅니다.",
        },
        {
            "자산": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "구분": "core",
            "현재비중": 0.8,
            "목표비중": 8.0,
            "비중차이": 7.2,
            "손익": "+1.0%",
            "주도축": "미국 AI·반도체",
            "세부축": "빅테크 AI",
            "시장판정": "직접흐름",
            "포트판정": "직접흐름 확인",
            "판단": "대표주 동행 확인이 필요합니다.",
            "대표/ETF": "Microsoft Meta Amazon Nvidia",
            "점수": 7.0,
            "근거": "개별 돈흐름은 잡혔지만 상위 주도축 확인이 더 필요합니다.",
        },
        {
            "자산": "2x Bitcoin ETF",
            "티커": "BITX",
            "구분": "leverage",
            "현재비중": 1.1,
            "목표비중": 4.0,
            "비중차이": 2.9,
            "손익": "+5.0%",
            "주도축": "비트코인",
            "세부축": "디지털자산",
            "시장판정": "별도관리",
            "포트판정": "별도관리",
            "판단": "전용 기준으로 관리합니다.",
            "대표/ETF": "Bitcoin",
            "점수": 0.0,
            "근거": "주식 주도맵과 별도 흐름이라 전용 기준과 목표비중으로 관리합니다.",
        },
        {
            "자산": "Roundhill T-REX 2X Long DRAM Daily Target ETF",
            "티커": "RAM",
            "구분": "leverage",
            "현재비중": 8.0,
            "목표비중": 4.0,
            "비중차이": -4.0,
            "손익": "-12.0%",
            "주도축": "미국 AI·반도체",
            "세부축": "DRAM",
            "시장판정": "관망/제외",
            "포트판정": "축소/교체 후보",
            "판단": "대체 후보와 비교합니다.",
            "대표/ETF": "Micron",
            "점수": -1.0,
            "근거": "현재 주도축과 맞지 않고 목표보다 많아 대체 후보와 비교합니다.",
        },
    ])
    action_df = pd.DataFrame([
        {"티커": "MAGS", "판정": "조건부 적립", "실행": "정해둔 금액만", "재개/해제 조건": "뉴스와 대표주 동행 유지"},
        {"티커": "BITX", "판정": "조건부 소액", "실행": "회차 금액만", "재개/해제 조건": "시장 위험 완화 + 손절선 확인"},
        {"티커": "RAM", "판정": "축소/교체 검토", "실행": "추가매수 중단", "재개/해제 조건": "하락 패턴 해소"},
    ])
    news_rows = [
        {
            "읽기분류": "핵심속보",
            "카테고리": "반도체·AI",
            "종목": "MSFT",
            "제목": "Microsoft Meta Nvidia AI 데이터센터 투자 확대",
            "초보요약": "AI 반도체와 빅테크 투자 뉴스입니다.",
            "체크": "반도체·AI 재료",
        }
    ]

    candidates = app_module.build_portfolio_next_check_candidates_df(
        align_df,
        action_df=action_df,
        news_rows=news_rows,
        limit=4,
    )

    mags = candidates[candidates["티커"].eq("MAGS")].iloc[0]
    bitx = candidates[candidates["티커"].eq("BITX")].iloc[0]
    ram = candidates[candidates["티커"].eq("RAM")].iloc[0]
    assert mags["자산판정"] == "조건부 적립"
    assert "Microsoft" in mags["뉴스/재료"]
    assert bitx["점검유형"] == "별도 소액 후보"
    assert bitx["다음 확인"] == "시장 위험 완화 + 손절선 확인"
    assert ram["점검유형"] == "축소/중단 점검"
    assert ram["우선점수"] >= 70
    assert mags["점검그룹"] == "늘리기/적립 확인"
    assert ram["점검그룹"] == "줄이기/중단 점검"


def test_portfolio_next_check_candidates_balance_reduce_and_add_groups(app_module):
    align_df = pd.DataFrame([
        {
            "자산": "SOL AI 반도체 Top2 플러스",
            "티커": "0167A0.KS",
            "구분": "core",
            "현재비중": 6.3,
            "목표비중": 5.0,
            "비중차이": -1.3,
            "손익": "-22.7%",
            "주도축": "AI·반도체",
            "세부축": "검사/테스트",
            "시장판정": "관심등록",
            "포트판정": "보유점검",
            "판단": "하위테마만 강함, 확인 필요",
            "대표/ETF": "마이크로컨텍솔",
            "점수": -12.7,
            "근거": "내 기술 신호가 방어라서 시장 흐름보다 회복 조건을 먼저 봅니다.",
        },
        {
            "자산": "SOXL",
            "티커": "SOXL",
            "구분": "leverage",
            "현재비중": 5.0,
            "목표비중": 3.0,
            "비중차이": -2.0,
            "손익": "-14.6%",
            "주도축": "Semiconductor Bull 3X",
            "세부축": "Semiconductor Bull 3X",
            "시장판정": "직접흐름 약세",
            "포트판정": "보유점검",
            "판단": "회복 조건 확인",
            "대표/ETF": "SOXL",
            "점수": -76.7,
            "근거": "내 기술 신호가 방어라서 시장 흐름보다 회복 조건을 먼저 봅니다.",
        },
        {
            "자산": "RAM",
            "티커": "RAM",
            "구분": "leverage",
            "현재비중": 8.6,
            "목표비중": 10.0,
            "비중차이": 1.4,
            "손익": "-22.1%",
            "주도축": "DRAM 2배",
            "세부축": "DRAM 2배",
            "시장판정": "직접흐름 약세",
            "포트판정": "보유점검",
            "판단": "회복 조건 확인",
            "대표/ETF": "DRAM 2배",
            "점수": -64.7,
            "근거": "개별 돈흐름이 약세라 추가매수보다 회복 조건 확인이 먼저입니다.",
        },
        {
            "자산": "나스닥",
            "티커": "379810.KS",
            "구분": "core",
            "현재비중": 30.5,
            "목표비중": 27.0,
            "비중차이": -3.5,
            "손익": "+0.8%",
            "주도축": "미국 지수·코어",
            "세부축": "NASDAQ100",
            "시장판정": "기준축",
            "포트판정": "보유점검",
            "판단": "장기 기준축입니다.",
            "대표/ETF": "QQQ",
            "점수": np.nan,
            "근거": "기준축이지만 목표보다 많아 새 매수는 멈춥니다.",
        },
        {
            "자산": "S&P500",
            "티커": "379800.KS",
            "구분": "core",
            "현재비중": 31.8,
            "목표비중": 40.0,
            "비중차이": 8.2,
            "손익": "+0.0%",
            "주도축": "미국 지수·코어",
            "세부축": "S&P500",
            "시장판정": "기준축",
            "포트판정": "계획적 적립",
            "판단": "장기 기준축입니다.",
            "대표/ETF": "SPY/VOO",
            "점수": np.nan,
            "근거": "장기 기준축이라 정해둔 적립률 안에서만 봅니다.",
        },
        {
            "자산": "Roundhill Magnificent Seven ETF",
            "티커": "MAGS",
            "구분": "core",
            "현재비중": 0.8,
            "목표비중": 6.0,
            "비중차이": 5.2,
            "손익": "-2.1%",
            "주도축": "Magnificent 7",
            "세부축": "Magnificent 7",
            "시장판정": "직접흐름",
            "포트판정": "직접흐름 확인",
            "판단": "개별 돈흐름은 잡혔지만 상위 주도축 확인이 더 필요합니다.",
            "대표/ETF": "Magnificent 7",
            "점수": 5.8,
            "근거": "개별 돈흐름은 잡혔지만 상위 주도축 확인이 더 필요합니다.",
        },
        {
            "자산": "2x Bitcoin ETF",
            "티커": "BITX",
            "구분": "leverage",
            "현재비중": 1.2,
            "목표비중": 4.0,
            "비중차이": 2.8,
            "손익": "-5.6%",
            "주도축": "디지털자산 > Bitcoin",
            "세부축": "Bitcoin",
            "시장판정": "별도관리",
            "포트판정": "별도관리",
            "판단": "전용 기준으로 관리합니다.",
            "대표/ETF": "BTC/BITX",
            "점수": np.nan,
            "근거": "주식 주도맵과 별도 흐름이라 전용 기준과 목표비중으로 관리합니다.",
        },
    ])
    action_df = pd.DataFrame([
        {"티커": "0167A0.KS", "판정": "위성/집중 축소 검토", "실행": "추가매수 중단", "재개/해제 조건": "반도체 돈흐름 회복"},
        {"티커": "SOXL", "판정": "축소/교체 검토", "실행": "추가매수 중단", "재개/해제 조건": "목표비중 이하"},
        {"티커": "RAM", "판정": "레버리지 DCA 대기", "실행": "추가매수 중단", "재개/해제 조건": "DCA 가격조건 + 기초축 회복 + 시장 위험 완화"},
        {"티커": "379810.KS", "판정": "장기코어 유지·신규중단", "실행": "추가매수 중단", "재개/해제 조건": "목표비중 이하"},
        {"티커": "379800.KS", "판정": "장기코어 유지·회복확인", "실행": "분할 적립", "재개/해제 조건": "10Y/VIX 안정"},
        {"티커": "MAGS", "판정": "조건부 적립", "실행": "분할", "재개/해제 조건": "시장 위험 완화"},
        {"티커": "BITX", "판정": "조건부 소액", "실행": "회차 금액만", "재개/해제 조건": "시장 위험 완화"},
    ])

    candidates = app_module.build_portfolio_next_check_candidates_df(
        align_df,
        action_df=action_df,
        news_rows=[],
        limit=6,
    )

    tickers = candidates["티커"].tolist()
    groups = candidates["점검그룹"].tolist()
    assert sum(group == "줄이기/중단 점검" for group in groups) == 3
    assert sum(group == "회복/DCA 대기" for group in groups) == 1
    assert sum(group == "늘리기/적립 확인" for group in groups) == 2
    assert "RAM" in tickers
    assert "MAGS" in tickers
    assert "379810.KS" in tickers
    assert "379800.KS" in tickers

    summary = app_module.build_portfolio_next_check_summary(candidates)
    assert "줄이기/중단 3개" in summary
    assert "회복/DCA 대기 1개" in summary
    assert "늘리기/적립 2개" in summary
    assert "RAM" in summary
    assert "남는 예산" in summary


def test_asset_overview_kpis_detects_cash_concentration_and_stale_prices():
    holdings = pd.DataFrame(
        [
            {
                "티커": "VOO",
                "자산명": "S&P500",
                "원화환산": 7_000_000,
                "현재비중": 55.0,
                "리밸런싱목표비중": 40.0,
                "비중차이": -15.0,
                "현재가": 100.0,
                "is_etf": True,
                "운용대상": True,
            },
            {
                "티커": "FCX",
                "자산명": "프리포트",
                "원화환산": 2_000_000,
                "현재비중": 15.0,
                "리밸런싱목표비중": 10.0,
                "비중차이": -5.0,
                "현재가": 0.0,
                "is_etf": False,
                "운용대상": True,
            },
            {
                "티커": "KRW_CASH",
                "자산명": "현금",
                "원화환산": 1_000_000,
                "현재비중": 10.0,
                "운용대상": False,
            },
        ]
    )

    kpis, alerts = build_asset_overview_kpis(
        holdings,
        {"current_asset": 10_000_000, "cum_return": -3.2},
        {"waiting_pct": 8.0, "target_pct": 15.0},
    )

    by_title = {item["title"]: item for item in kpis}
    assert by_title["대기자금"]["status"] == "부족"
    assert by_title["집중도"]["status"] == "집중위험"
    assert by_title["데이터"]["value"] == "1개"
    assert any("대기자금" in alert for alert in alerts)
    assert any("최대 비중" in alert for alert in alerts)


def test_asset_overview_dashboard_state_prepares_metrics_and_kpis():
    holdings = pd.DataFrame(
        [
            {
                "티커": "VOO",
                "자산명": "S&P500",
                "원화환산": 7_000_000,
                "현재비중": 70.0,
                "리밸런싱목표비중": 60.0,
                "비중차이": -10.0,
                "현재가": 100.0,
                "bucket": "core",
                "is_etf": True,
                "운용대상": True,
            },
        ]
    )

    state = build_asset_overview_dashboard_state(
        holdings,
        {
            "current_asset": 10_000_000,
            "stock_value": 7_000_000,
            "cash_value": 3_000_000,
            "total_dividend": 50_000,
            "cum_profit": -100_000,
            "cum_return": -1.0,
        },
        krw_cash=2_000_000,
        usd_cash=1_000,
        usdkrw=1000,
        reserve_target_weight=25.0,
    )

    metrics = state["metrics"]
    assert metrics["profit_label"] == "손실"
    assert metrics["waiting_value"] == 3_000_000
    assert metrics["waiting_pct"] == 30.0
    assert metrics["waiting_delta"] == "+5.00%p vs 목표"
    assert metrics["invest_pct"] == 70.0
    assert metrics["deployable_value"] == 500_000
    assert state["full_df"]["티커"].tolist() == ["VOO", "KRW_CASH", "USD_CASH"]
    assert {item["title"] for item in state["kpis"]} >= {"운용 상태", "대기자금", "집중도"}


def test_scenario_helpers_apply_leverage_and_cash_buffer():
    holdings = pd.DataFrame(
        [
            {
                "티커": "VOO",
                "자산명": "S&P500",
                "원화환산": 6_000_000,
                "bucket": "core",
                "운용대상": True,
            },
            {
                "티커": "SOXL",
                "자산명": "반도체 3X",
                "원화환산": 1_000_000,
                "bucket": "leverage",
                "운용대상": True,
            },
        ]
    )

    context = build_scenario_context(
        holdings,
        krw_cash=2_000_000,
        usd_cash=0,
        usdkrw=1400,
        reserve_target_weight=20.0,
    )
    active = context["active_df"]
    total_asset = context["total_asset"]

    detail = calc_asset_shock_table(active, total_asset, -10, use_multiplier=True)
    soxl = detail[detail["티커"].eq("SOXL")].iloc[0]
    summary = build_market_scenario_summary(active, total_asset, [-10], use_multiplier=True)
    buffer = build_cash_buffer_scenario(active, total_asset, context["reserve_summary"], 30.0, -10, use_multiplier=True)

    assert total_asset == 9_000_000
    assert soxl["적용충격"] == -30.0
    assert soxl["예상손익"] == -300_000
    assert summary.iloc[0]["예상손익"] == -900_000
    assert buffer["additional_waiting"] == 700_000
    assert buffer["rebalanced_loss"] > buffer["current_loss"]


def test_leverage_summary_uses_ticker_and_name_multiplier_hints():
    asset_df = pd.DataFrame(
        [
            {"티커": "SOXL", "자산명": "Semiconductor Bull 3X", "전체비중": 2.6, "운용비중": 3.0},
            {"티커": "BITX", "자산명": "2x Bitcoin ETF", "전체비중": 1.7, "운용비중": 2.0},
            {"티커": "VOO", "자산명": "S&P500", "전체비중": 40.0, "운용비중": 45.0},
        ]
    )

    summary, leverage_df = calc_portfolio_leverage_summary(asset_df)

    assert infer_scenario_shock_multiplier({"티커": "SQQQ"}) == -3.0
    assert round(summary["leveraged_principal_pct"], 1) == 4.3
    assert round(summary["effective_exposure_pct"], 1) == 11.2
    assert round(summary["extra_exposure_pct"], 1) == 6.9
    assert leverage_df["티커"].tolist() == ["SOXL", "BITX"]


def test_risk_contribution_and_correlation_pair_summary():
    asset_df = pd.DataFrame(
        [
            {"티커": "AAA", "자산명": "Alpha"},
            {"티커": "BBB", "자산명": "Beta"},
        ]
    )
    aligned_returns = pd.DataFrame(
        {
            "AAA": [0.01, -0.02, 0.015, 0.005],
            "BBB": [0.004, -0.005, 0.002, 0.003],
        }
    )
    weights = pd.Series({"AAA": 0.6, "BBB": 0.4})

    risk_df = build_risk_contribution_df(asset_df, aligned_returns, weights)
    pair_df = build_correlation_pair_summary(pd.DataFrame([[1.0, 0.85], [0.85, 1.0]], columns=["Alpha", "Beta"], index=["Alpha", "Beta"]))

    assert set(risk_df["티커"]) == {"AAA", "BBB"}
    assert round(risk_df["리스크기여도"].sum(), 1) == 100.0
    assert pair_df.iloc[0]["구분"] == "매우 높음"


def test_portfolio_analysis_start_date_uses_first_month_record():
    monthly_logs = pd.DataFrame(
        [
            {"month": "2026-03", "total_invested": 120, "evaluated_value": 130, "dividend": 0},
            {"month": "2026-01", "total_invested": 100, "evaluated_value": 103, "dividend": 1},
        ]
    )

    assert get_portfolio_analysis_start_date(monthly_logs) == pd.Timestamp("2026-01-01")


def test_monthly_record_status_classifies_current_previous_and_stale_records():
    summary = {"current_asset": 1_200_000}
    current = build_monthly_record_status(
        pd.DataFrame([
            {"month": "2026-08", "total_invested": 1_000_000, "evaluated_value": 1_100_000, "dividend": 10_000},
            {"month": "2026-09", "total_invested": 1_000_000, "evaluated_value": 1_150_000, "dividend": 0},
        ]),
        summary,
        today="2026-09-14",
    )
    previous = build_monthly_record_status(
        pd.DataFrame([
            {"month": "2026-08", "total_invested": 1_000_000, "evaluated_value": 1_100_000, "dividend": 0},
        ]),
        summary,
        today="2026-09-14",
    )
    stale = build_monthly_record_status(
        pd.DataFrame([
            {"month": "2026-07", "total_invested": 1_000_000, "evaluated_value": 1_050_000, "dividend": 0},
        ]),
        summary,
        today="2026-09-14",
    )
    empty = build_monthly_record_status(pd.DataFrame(), summary, today="2026-09-14")

    assert current["status"] == "이번 달 기록 있음"
    assert current["record_count"] == 2
    assert current["asset_gap"] == 50_000
    assert previous["status"] == "최근 월 기록 완료"
    assert stale["status"] == "업데이트 필요"
    assert empty["is_empty"] is True


def test_blended_benchmark_spec_groups_core_and_leveraged_assets():
    holdings = pd.DataFrame(
        [
            {"티커": "VOO", "자산명": "S&P500", "목표비중": 38.0, "현재비중": 37.0, "원화환산": 3800, "bucket": "core", "운용대상": True},
            {"티커": "QQQ", "자산명": "나스닥100", "목표비중": 23.0, "현재비중": 22.0, "원화환산": 2300, "bucket": "core", "운용대상": True},
            {"티커": "SOXL", "자산명": "반도체 3X", "목표비중": 2.6, "현재비중": 2.0, "원화환산": 260, "bucket": "leverage", "운용대상": True},
            {"티커": "KRW_CASH", "자산명": "원화예수금", "목표비중": 0.0, "현재비중": 15.0, "원화환산": 1500, "bucket": "cash", "운용대상": False},
        ]
    )

    spec = build_portfolio_blended_benchmark_spec(holdings)
    components = {(item["label"], item["multiplier"]): item["weight"] for item in spec["components"]}

    assert spec["basis"] == "목표비중"
    assert round(components[("S&P500", 1.0)], 1) == 38.0
    assert round(components[("나스닥100", 1.0)], 1) == 23.0
    assert round(components[("나스닥100", 3.0)], 1) == 2.6
    assert "KRW_CASH" not in spec["description"]


def test_benchmark_proxy_and_leverage_multiplier_classification():
    assert infer_blended_benchmark_proxy("MSFT") == {"label": "나스닥100", "ticker": "379810.KS"}
    assert infer_blended_benchmark_proxy("FCX") == {"label": "S&P500", "ticker": "379800.KS"}
    assert infer_blended_benchmark_proxy("005930.KS") == {"label": "코스피", "ticker": "069500.KS"}
    assert infer_blended_benchmark_proxy("KRW_CASH", bucket="cash") is None
    assert infer_benchmark_leverage_multiplier("SOXL") == 3.0
    assert infer_benchmark_leverage_multiplier("SQQQ") == -3.0
    assert infer_benchmark_leverage_multiplier("BITX") == 2.0


def test_benchmark_metrics_from_returns_uses_common_dates():
    index = pd.date_range("2026-01-01", periods=30, freq="B")
    benchmark_returns = pd.Series(
        [0.001, 0.002, -0.001, 0.003, -0.002] * 6,
        index=index,
    )
    portfolio_returns = benchmark_returns * 1.5

    metrics = calc_benchmark_metrics_from_returns(
        portfolio_returns,
        benchmark_returns,
        label="테스트 벤치",
        benchmark_ticker="TEST",
    )

    assert metrics["benchmark_label"] == "테스트 벤치"
    assert metrics["benchmark_ticker"] == "TEST"
    assert metrics["n_common_days"] == 30
    assert 1.4 < metrics["beta"] < 1.6
