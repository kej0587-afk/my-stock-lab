import pandas as pd

from stock_lab_core.portfolio import (
    build_correlation_pair_summary,
    build_risk_contribution_df,
    calc_drawdown_details,
    calc_portfolio_leverage_summary,
    calc_series_mdd,
    get_active_portfolio_rows,
    get_holding_row_by_ticker,
    get_portfolio_analysis_start_date,
    infer_scenario_shock_multiplier,
)


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
