"""Print-report rendering with explicit app callbacks; investment rules stay in the app."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from stock_lab_core.formatters import (
    normalize_bucket, sanitize_ticker_value,
    report_num as _num, format_report_money as _fmt_money,
    format_report_pct as _fmt_pct,
)
from stock_lab_core.portfolio import calc_reserve_summary
from stock_lab_core.print_report_data import (
    make_report_asset_df, active_plan_rows, build_monthly_plan_report,
    build_total_needed_shares_report, format_asset_table, format_generic_table,
    format_monthly_plan_table, format_needed_shares_table,
)
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
KST = timezone(timedelta(hours=9))


def print_table(st, df, columns, max_rows=20):
    if df is None or df.empty:
        st.caption("표시할 데이터가 없습니다.")
        return
    show_cols = [col for col in columns if col in df.columns]
    if not show_cols:
        show_cols = list(df.columns[:8])
    st.table(df.loc[:, show_cols].head(max_rows))


def render_asset_report_charts(st, df):
    if df is None or df.empty or "원화환산" not in df.columns:
        return

    chart_df = df.copy()
    for col in ["원화환산", "수익률_pct", "현재비중", "목표비중", "리밸런싱목표비중", "비중차이", "평가손익_원화"]:
        if col in chart_df.columns:
            chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
    chart_df = chart_df[chart_df["원화환산"] > 0].copy()
    if chart_df.empty:
        return

    if "자산명" not in chart_df.columns:
        chart_df["자산명"] = chart_df.get("티커", "")
    if "티커" not in chart_df.columns:
        chart_df["티커"] = ""
    target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in chart_df.columns else "목표비중"
    if target_col not in chart_df.columns:
        chart_df[target_col] = 0.0
    if "비중차이" not in chart_df.columns:
        chart_df["비중차이"] = chart_df["현재비중"] - chart_df[target_col]

    st.markdown("#### 포트폴리오 히트맵 / 타점·비중·수익률 매트릭스")
    c1, c2 = st.columns(2)
    with c1:
        fig_tree = go.Figure(go.Treemap(
            labels=chart_df["자산명"],
            parents=[""] * len(chart_df),
            values=chart_df["원화환산"],
            marker=dict(
                colors=chart_df["수익률_pct"],
                colorscale=[[0, "#dc2626"], [0.5, "#64748b"], [1, "#16a34a"]],
                cmid=0,
                colorbar=dict(title="수익률"),
            ),
            customdata=chart_df[[target_col, "현재비중", "평가손익_원화", "수익률_pct"]],
            hovertemplate=(
                "<b>%{label}</b><br>"
                "평가금액: ₩%{value:,.0f}<br>"
                "현재/목표: %{customdata[1]:.2f}% / %{customdata[0]:.2f}%<br>"
                "평가손익: ₩%{customdata[2]:,.0f}<br>"
                "수익률: %{customdata[3]:.2f}%<extra></extra>"
            ),
        ))
        fig_tree.update_layout(template="plotly_dark", height=360, margin=dict(t=36, l=8, r=8, b=8), title="포트폴리오 히트맵")
        st.plotly_chart(fig_tree, width='stretch')

    with c2:
        matrix_df = chart_df.copy()
        if "bucket" in matrix_df.columns:
            matrix_df = matrix_df[~matrix_df["bucket"].apply(lambda b: normalize_bucket(str(b)) in {"cash", "reserve"})].copy()
        if matrix_df.empty:
            st.info("매트릭스로 표시할 운용 자산이 없습니다.")
        else:
            signal_cache = st.session_state.get("_ticker_signal_cache", {})
            matrix_df["타점"] = matrix_df["티커"].apply(lambda t: str(signal_cache.get(sanitize_ticker_value(t), "-") or "-"))
            max_value = max(float(matrix_df["원화환산"].max() or 0), 1.0)
            matrix_df["_size"] = np.clip(np.sqrt(matrix_df["원화환산"] / max_value) * 46, 12, 46)
            matrix_df["_label"] = ""
            top_label_idx = matrix_df.sort_values("원화환산", ascending=False).head(12).index
            matrix_df.loc[top_label_idx, "_label"] = matrix_df.loc[top_label_idx, "자산명"]
            fig_matrix = go.Figure(go.Scatter(
                x=matrix_df["비중차이"],
                y=matrix_df["수익률_pct"],
                mode="markers+text",
                text=matrix_df["_label"],
                textposition="top center",
                marker=dict(
                    size=matrix_df["_size"],
                    color=matrix_df["현재비중"],
                    colorscale="Viridis",
                    showscale=True,
                    colorbar=dict(title="현재비중"),
                    opacity=0.86,
                ),
                customdata=matrix_df[["자산명", "티커", "타점", "현재비중", target_col, "원화환산"]],
                hovertemplate=(
                    "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
                    "타점: %{customdata[2]}<br>"
                    "비중차이: %{x:.2f}%p<br>"
                    "수익률: %{y:.2f}%<br>"
                    "현재/목표: %{customdata[3]:.2f}% / %{customdata[4]:.2f}%<br>"
                    "평가금액: ₩%{customdata[5]:,.0f}<extra></extra>"
                ),
            ))
            fig_matrix.add_vline(x=0, line_dash="dash", line_color="#94a3b8")
            fig_matrix.add_hline(y=0, line_dash="dash", line_color="#94a3b8")
            fig_matrix.update_layout(
                template="plotly_dark",
                height=360,
                margin=dict(t=36, l=8, r=8, b=8),
                title="타점/비중/수익률 매트릭스",
                xaxis_title="비중차이(%p)",
                yaxis_title="수익률(%)",
            )
            st.plotly_chart(fig_matrix, width='stretch')


def render_monthly_report_charts(st, monthly_perf_df, *, build_benchmark_return_df, get_current_blended_benchmark_spec):
    if monthly_perf_df is None or monthly_perf_df.empty:
        return
    required = {"month_label", "evaluated_value", "total_invested", "cum_profit", "cum_return_pct"}
    if not required.issubset(set(monthly_perf_df.columns)):
        return

    st.markdown("#### 월별 흐름 차트")
    chart_df = monthly_perf_df.copy()
    for col in ["evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]:
        if col in chart_df.columns:
            chart_df[col] = pd.to_numeric(chart_df[col], errors="coerce").fillna(0.0)
    if "dividend" not in chart_df.columns:
        chart_df["dividend"] = 0.0

    p1, p2 = st.columns(2)
    with p1:
        fig_monthly_asset = go.Figure()
        fig_monthly_asset.add_trace(go.Scatter(
            x=chart_df["month_label"],
            y=chart_df["evaluated_value"],
            mode="lines+markers",
            name="평가자산",
            line=dict(color="#ef4444", width=3),
            hovertemplate="%{x}<br>평가자산: ₩%{y:,.0f}<extra></extra>",
        ))
        fig_monthly_asset.add_trace(go.Scatter(
            x=chart_df["month_label"],
            y=chart_df["total_invested"],
            mode="lines+markers",
            name="투입원금",
            line=dict(color="#cbd5e1", width=2),
            hovertemplate="%{x}<br>투입원금: ₩%{y:,.0f}<extra></extra>",
        ))
        fig_monthly_asset.update_layout(
            template="plotly_dark",
            height=350,
            title=dict(text="월별 투자 기록", y=0.97, x=0.5, xanchor="center"),
            yaxis_title="원",
            legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
            margin=dict(t=40, l=8, r=8, b=70),
        )
        st.plotly_chart(fig_monthly_asset, width='stretch')

    with p2:
        fig_pnl_div = make_subplots(specs=[[{"secondary_y": True}]])
        pnl_colors = np.where(chart_df["cum_profit"] >= 0, "#22d3ee", "#ef4444")
        fig_pnl_div.add_trace(go.Bar(
            x=chart_df["month_label"],
            y=chart_df["cum_profit"],
            name="누적손익",
            marker_color=pnl_colors,
            hovertemplate="%{x}<br>누적손익: ₩%{y:,.0f}<extra></extra>",
        ), secondary_y=False)
        fig_pnl_div.add_trace(go.Scatter(
            x=chart_df["month_label"],
            y=chart_df["dividend"],
            mode="lines+markers",
            name="월별배당금",
            line=dict(color="#fbbf24", width=3),
            hovertemplate="%{x}<br>월별배당금: ₩%{y:,.0f}<extra></extra>",
        ), secondary_y=True)
        fig_pnl_div.add_hline(y=0, line_color="#94a3b8")
        fig_pnl_div.update_layout(
            template="plotly_dark",
            height=350,
            title=dict(text="누적손익 / 월별배당금", y=0.97, x=0.5, xanchor="center"),
            legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
            margin=dict(t=40, l=8, r=8, b=70),
        )
        fig_pnl_div.update_yaxes(title_text="누적손익(원)", secondary_y=False)
        fig_pnl_div.update_yaxes(title_text="배당금(원)", secondary_y=True)
        st.plotly_chart(fig_pnl_div, width='stretch')

    p3, p4 = st.columns(2)
    with p3:
        fig_cum_return = go.Figure(go.Scatter(
            x=chart_df["month_label"],
            y=chart_df["cum_return_pct"],
            mode="lines+markers",
            name="월별 누적수익률",
            line=dict(color="#22c55e", width=3),
            hovertemplate="%{x}<br>누적수익률: %{y:.2f}%<extra></extra>",
        ))
        fig_cum_return.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
        fig_cum_return.update_layout(
            template="plotly_dark",
            height=320,
            title=dict(text="월별 누적수익률", y=0.97, x=0.5, xanchor="center"),
            yaxis_title="수익률(%)",
            margin=dict(t=40, l=8, r=8, b=30),
        )
        st.plotly_chart(fig_cum_return, width='stretch')

    with p4:
        try:
            benchmark_df = build_benchmark_return_df(monthly_perf_df, get_current_blended_benchmark_spec())
        except Exception:
            benchmark_df = pd.DataFrame()
        if benchmark_df is None or benchmark_df.empty:
            st.info("벤치마크 비교 데이터를 계산할 수 없습니다.")
        else:
            fig_benchmark = go.Figure()
            color_map = {
                "내 기간수익률": "#00ff38",
                "내 목표비중 벤치": "#facc15",
                "S&P500": "#f87171",
                "나스닥100": "#60a5fa",
                "코스피": "#a7f3d0",
            }
            for label in benchmark_df["구분"].drop_duplicates():
                part = benchmark_df[benchmark_df["구분"] == label]
                fig_benchmark.add_trace(go.Scatter(
                    x=part["month_label"],
                    y=part["수익률_pct"],
                    mode="lines+markers",
                    name=label,
                    line=dict(
                        color=color_map.get(label, "#cbd5e1"),
                        width=3 if label == "내 기간수익률" else 2,
                        dash="solid" if label == "내 기간수익률" else "dot",
                    ),
                    hovertemplate=f"%{{x}}<br>{label}: %{{y:.2f}}%<extra></extra>",
                ))
            fig_benchmark.add_hline(y=0, line_color="#94a3b8", line_dash="dash")
            fig_benchmark.update_layout(
                template="plotly_dark",
                height=320,
                title=dict(text="첫 기록월 대비 수익률 변화 vs 벤치마크", y=0.97, x=0.5, xanchor="center"),
                yaxis_title="수익률(%)",
                legend=dict(orientation="h", yanchor="top", y=-0.18, x=0.5, xanchor="center"),
                margin=dict(t=40, l=8, r=8, b=70),
            )
            st.plotly_chart(fig_benchmark, width='stretch')


def render_print_report(
    st, *, holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw,
    reserve_target_weight, monthly_logs_df, sanitize_asset_name, signal_multiplier,
    build_portfolio_analysis_report, get_portfolio_analysis_start_date,
    prepare_monthly_performance_df, build_benchmark_return_df,
    get_current_blended_benchmark_spec,
):
    with st.sidebar:
        st.success("인쇄 모드")
        st.caption("브라우저에서 Ctrl + P를 누르면 현재 리포트를 출력할 수 있습니다.")
        if st.button("인쇄 모드 끄기", key="print_mode_off_v2"):
            st.session_state["print_mode_toggle_final"] = False
            st.rerun()

    st.markdown(
        """
        <style>
        @media print {
            [data-testid="stSidebar"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none !important; }
            .main .block-container { max-width: 100% !important; padding: 12px 24px !important; }
            .print-page-break { page-break-before: always; }
        }
        .print-note {
            border: 1px solid rgba(148, 163, 184, .35);
            border-radius: 8px;
            padding: 12px 14px;
            color: #cbd5e1;
            background: rgba(15, 23, 42, .45);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    report_df = make_report_asset_df(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw)
    reserve_summary = calc_reserve_summary(report_df, reserve_target_weight) if not report_df.empty else {}
    current_asset = _num(portfolio_summary.get("current_asset"), 0.0)
    stock_value = _num(portfolio_summary.get("stock_value"), 0.0)
    cash_value = _num(portfolio_summary.get("cash_value"), 0.0)
    cum_profit = _num(portfolio_summary.get("cum_profit"), 0.0)
    cum_return = _num(portfolio_summary.get("cum_return"), 0.0)
    total_dividend = _num(portfolio_summary.get("total_dividend"), 0.0)
    waiting_value = _num(reserve_summary.get("waiting_value"), cash_value)
    waiting_pct = _num(reserve_summary.get("waiting_pct"), 0.0)
    target_waiting_pct = _num(reserve_summary.get("target_pct"), reserve_target_weight)

    st.title("Stock Lab 출력 리포트")
    st.caption(f"생성일시: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} / 기준 환율: {_num(usdkrw, 0):,.2f}원")
    st.markdown(
        "<div class='print-note'>투자 추천서가 아니라 현재 자산, 포트폴리오 리스크, 오늘 점검할 항목을 한 번에 보기 위한 개인용 관리 리포트입니다.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("## 1. 자산현황")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총자산", _fmt_money(current_asset), f"투자자산 {_fmt_money(stock_value)}")
    k2.metric("누적손익", _fmt_money(cum_profit), _fmt_pct(cum_return))
    k3.metric("누적수익률", _fmt_pct(cum_return), f"누적배당 {_fmt_money(total_dividend)}")
    k4.metric("대기자금", _fmt_money(waiting_value), f"{waiting_pct:.2f}% / 목표 {target_waiting_pct:.2f}%")

    if not report_df.empty:
        st.markdown("#### 자산 구성/비중 상세")
        asset_detail_df = report_df.sort_values("현재비중", ascending=False) if "현재비중" in report_df.columns else report_df
        st.table(format_asset_table(asset_detail_df, max_rows=35))
        render_asset_report_charts(st, report_df)
    else:
        st.info("출력할 보유 자산이 없습니다.")

    st.markdown("<div class='print-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 2. 이번달 운용계획")
    # Both summaries use the same read-only, per-render selection, not a persistent cache.
    active_df = active_plan_rows(holdings_table)
    plan_df, plan_metrics = build_monthly_plan_report(
        active_df, st.session_state, usdkrw,
        sanitize_asset_name=sanitize_asset_name, signal_multiplier=signal_multiplier,
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("이번달 투입 가능", _fmt_money(plan_metrics["total_invest"]), f"적립 {_fmt_money(plan_metrics['monthly'])}")
    m2.metric("예상 매수금", _fmt_money(plan_metrics["total_rec_krw"]))
    m3.metric("달러 환전 필요", f"${plan_metrics['usd_buy']:,.2f}", _fmt_money(plan_metrics["usd_buy_krw"]))
    m4.metric("1주 미달", f"{plan_metrics['underalloc_count']}개", f"이월 {_fmt_money(plan_metrics['carryover'])}")

    st.markdown("#### 이번달 분배계획")
    if plan_df.empty:
        st.info("이번달 분배계획을 계산할 목표비중 또는 적립금이 없습니다.")
    else:
        st.table(format_monthly_plan_table(plan_df, max_rows=24))
        st.caption("인쇄 리포트의 분배계획은 월 적립 리밸런싱 계산기의 월 적립금, 이월금, 누적금을 읽어와 목표비중 기준으로 요약합니다.")

    st.markdown("#### 총 필요 주수")
    needed_df = build_total_needed_shares_report(
        active_df, st.session_state, usdkrw, portfolio_summary,
        sanitize_asset_name=sanitize_asset_name, signal_multiplier=signal_multiplier,
    )
    if needed_df.empty:
        st.info("총 필요 주수를 계산할 운용 대상 자산이 없습니다.")
    else:
        st.table(format_needed_shares_table(needed_df, max_rows=24))

    st.markdown("<div class='print-page-break'></div>", unsafe_allow_html=True)
    st.markdown("## 3. 포트폴리오 분석 및 월별 성과")
    try:
        metrics, asset_risk_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = build_portfolio_analysis_report(
            holdings_table,
            krw_cash,
            usd_cash,
            usdkrw,
            reserve_target_weight,
            period="1y",
            analysis_start_date=get_portfolio_analysis_start_date(monthly_logs_df),
        )
    except Exception as exc:
        metrics, asset_risk_df, notes_df, corr_df, portfolio_curve, risk_contrib_df = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float), pd.DataFrame()
        st.warning(f"포트폴리오 분석 계산 중 일부 데이터를 불러오지 못했습니다: {exc}")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("위험도", f"{metrics.get('risk_grade', '-')}", f"{_num(metrics.get('risk_index'), 0):.0f}/100")
    p2.metric("연환산 변동성", _fmt_pct(metrics.get("portfolio_vol"), 1))
    p3.metric("분석기간 MDD", _fmt_pct(metrics.get("portfolio_mdd"), 1))
    p4.metric("상위 3개 비중", _fmt_pct(metrics.get("top3_weight"), 1))

    if asset_risk_df is not None and not asset_risk_df.empty:
        st.markdown("#### 자산별 위험 요약")
        print_table(
            st,
            format_generic_table(asset_risk_df, max_rows=20),
            ["자산명", "티커", "원화환산", "전체비중", "운용비중", "기간수익률", "연환산변동성", "MDD", "데이터"],
            max_rows=20,
        )
    if notes_df is not None and not notes_df.empty:
        st.markdown("#### 확인할 리스크")
        st.table(notes_df.head(12))

    try:
        monthly_perf_df = prepare_monthly_performance_df(monthly_logs_df)
    except Exception:
        monthly_perf_df = pd.DataFrame()
    if monthly_perf_df is not None and not monthly_perf_df.empty:
        st.markdown("#### 월별 성과 기록")
        latest_month = monthly_perf_df.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("최근 기록월", str(latest_month.get("month_label", "-")))
        c2.metric("기록 평가자산", _fmt_money(latest_month.get("evaluated_value")))
        c3.metric("기록 누적손익", _fmt_money(latest_month.get("cum_profit")))
        c4.metric("기록 누적수익률", _fmt_pct(latest_month.get("cum_return_pct")))

        perf_cols = ["month_label", "evaluated_value", "total_invested", "cum_profit", "cum_return_pct", "dividend"]
        perf_df = monthly_perf_df.tail(12).copy()
        perf_df = perf_df[[c for c in perf_cols if c in perf_df.columns]].rename(columns={
            "month_label": "월",
            "evaluated_value": "평가자산",
            "total_invested": "투입원금",
            "cum_profit": "누적손익",
            "cum_return_pct": "누적수익률",
            "dividend": "월배당",
        })
        st.table(format_generic_table(perf_df, max_rows=12))
        render_monthly_report_charts(
            st, monthly_perf_df, build_benchmark_return_df=build_benchmark_return_df,
            get_current_blended_benchmark_spec=get_current_blended_benchmark_spec,
        )
    else:
        st.info("월별 성과 기록이 없습니다.")
