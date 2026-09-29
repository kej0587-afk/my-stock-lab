import pandas as pd

from stock_lab_core.portfolio import (
    build_asset_overview_dashboard_state,
    build_asset_overview_kpis,
    build_cash_buffer_scenario,
    build_market_scenario_summary,
    build_monthly_record_status,
    build_portfolio_blended_benchmark_spec,
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
    snapshot = {"command_flow_df": pd.DataFrame()}

    aligned = app_module.build_portfolio_market_alignment_df(
        {"strategy_df": strategy_df},
        pd.DataFrame(),
        snapshot,
    )

    row = aligned.iloc[0]
    assert row["시장판정"] == "기준축"
    assert row["포트판정"] == "계획적 적립"
    assert row["주도축"] != "미연결"


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
