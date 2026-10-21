"""Precision chart presentation, without fetching prices or changing signals."""

import pandas as pd
import plotly.graph_objects as go


def frame_last_date(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return ""
    stamp = frame.index[-1]
    return "" if pd.isna(stamp) else stamp.strftime("%Y-%m-%d")


def chart_basis_rows(daily_source, chart_frame, timeframe_pack, *, live_applied=False):
    """Keep source dates distinct from quote overlays and resampling bucket labels."""
    rows = [{
        "구분": "일봉",
        "원자료 마지막 날짜": frame_last_date(daily_source) or "미확인",
        "차트 마지막 봉": frame_last_date(chart_frame) or "미확인",
        "가격 반영": "현재가 보정 · OHLCV 확정봉 아님" if live_applied else "가격 이력 기준",
    }]
    for label in ("주봉", "월봉"):
        item = (timeframe_pack or {}).get(label) or {}
        fallback = item.get("source_kind") == "daily_fallback"
        source_date = frame_last_date(daily_source) if fallback else item.get("source_asof")
        price_basis = "장기 가격 이력 집계 · 주/월 종료일 표기"
        if fallback:
            price_basis = "일봉 대체 집계" + (" · 현재가 보정 포함" if live_applied else "")
        rows.append({
            "구분": label,
            "원자료 마지막 날짜": source_date or "미확인",
            "차트 마지막 봉": frame_last_date(item.get("df")) or "미확인",
            "가격 반영": price_basis,
        })
    return rows


def render_chart_basis(st, daily_source, chart_frame, timeframe_pack, *, live_applied=False):
    rows = chart_basis_rows(daily_source, chart_frame, timeframe_pack, live_applied=live_applied)
    st.markdown("#### 차트 데이터 기준")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("날짜는 거래소 현지일입니다. 주·월봉의 끝 날짜는 묶음 이름이며, 그날까지 수집됐다는 뜻은 아닙니다.")
    if live_applied:
        if any(((timeframe_pack or {}).get(label) or {}).get("source_kind") == "daily_fallback" for label in ("주봉", "월봉")):
            st.caption("장기 이력 조회가 부족해 보정 일봉을 대체 집계한 주·월봉에도 현재가 보정이 포함됩니다.")
        else:
            st.caption("현재가 보정은 일봉에만 반영됩니다. 주·월봉은 별도로 조회한 장기 이력 기준입니다.")
    return rows


def build_price_figure(frame, avg_price=0.0):
    fig = go.Figure(data=[go.Candlestick(
        x=frame.index, open=frame["Open"], high=frame["High"],
        low=frame["Low"], close=frame["Close"], name="Price",
    )])
    for col, color, width, dash in (
        ("MA5", "#22c55e", 1.4, None),
        ("MA20", "#fbbf24", 2, None),
        ("MA50", "#60a5fa", 1.6, None),
        ("MA120", "#94a3b8", 1.5, "dot"),
    ):
        if col in frame.columns:
            fig.add_trace(go.Scatter(
                x=frame.index, y=frame[col],
                line=dict(color=color, width=width, dash=dash), name=col,
            ))
    if avg_price and avg_price > 0:
        fig.add_hline(y=avg_price, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
    return fig


def finish_price_figure(fig, frame, volume_signals, *, show_level_labels=False):
    if not volume_signals.empty and volume_signals["volume"].notna().any():
        fig.add_trace(go.Bar(
            x=frame.index, y=volume_signals["volume"], marker_color=volume_signals["color"],
            yaxis="y2", name="거래량 신호", customdata=volume_signals[["signal", "rvol"]].to_numpy(),
            hovertemplate="%{x}<br>거래량 %{y:,.0f}<br>%{customdata[0]} · RVOL %{customdata[1]:.2f}x<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=frame.index, y=volume_signals["volume_ma"], yaxis="y2",
            name="거래량 MA", line=dict(color="#fbbf24", width=1),
        ))
        fig.update_layout(yaxis=dict(domain=[0.25, 1]),
                          yaxis2=dict(domain=[0, 0.17], title="거래량", anchor="x"))
    # Zones remain visible; crowded labels can be restored without changing data.
    fig.update_annotations(visible=show_level_labels)
    fig.update_layout(
        template="plotly_dark", height=600, xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        margin=dict(l=8, r=8, t=32, b=32),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig
