"""Precision chart presentation, without fetching prices or changing signals."""

import math

import pandas as pd
import plotly.graph_objects as go


def prepare_channel_display(frame, channel, *, provisional_last=False):
    """Retire broken rails for display only; preserve geometry and causal events."""
    if not channel:
        return channel
    times = pd.DatetimeIndex(channel["x"])
    closes = pd.to_numeric(frame["Close"], errors="coerce").reindex(times)
    rising = channel["direction"] == "상승"
    edge = channel["lower"] if rising else channel["upper"]
    outside = closes.lt(edge) if rising else closes.gt(edge)
    confirmed = times >= pd.Timestamp(channel["known_at"])
    if provisional_last:
        confirmed &= times != frame.index[-1]
    if "LiveQuoteOnly" in frame:
        confirmed &= ~frame["LiveQuoteOnly"].reindex(times).fillna(False).astype(bool).to_numpy()
    broken = [i for i, hit in enumerate(outside.to_numpy() & confirmed) if hit]
    if broken:
        end = broken[0]
        return dict(channel, display_end_index=end, display_state="과거 채널 · 종료",
                    ended_at=times[end], execution_guide_eligible=False)
    if outside.iloc[-1]:
        return dict(channel, display_state="미확정 봉 이탈 · 재확인",
                    execution_guide_eligible=False)
    return channel


def channel_caption(channel):
    if not channel:
        return ""
    end = channel.get("display_end_index", len(channel["x"]) - 1)
    values = (f"하단 {channel['lower'][end]:,.2f} / 중심 {channel['middle'][end]:,.2f} / "
              f"상단 {channel['upper'][end]:,.2f}")
    if channel.get("ended_at") is not None:
        breach = "하단 이탈" if channel["direction"] == "상승" else "상단 돌파"
        return (f"과거 {channel['direction']} 평행 채널 · {pd.Timestamp(channel['ended_at']):%Y-%m-%d} "
                f"{breach}로 종료 · 종료봉 기준 {values} · 현재 지지·저항 안내에서 제외")
    state = channel.get("display_state", channel["state"])
    return (f"{channel['direction']} 평행 채널 · {state} · "
            f"확인 {pd.Timestamp(channel['known_at']):%Y-%m-%d} · {values}")


def prepare_chart_layers(frame, *, show_patterns, show_channel, show_signals,
                         load_structure, detect_patterns, build_trendlines, provisional_last=False):
    """Independent layer switches; explanations follow the lines actually drawn."""
    structure = load_structure(frame) if show_channel or show_signals else {}
    patterns = (structure["patterns"] if "patterns" in structure and not structure.get("issue")
                else detect_patterns(frame)) if show_patterns else []
    channel = prepare_channel_display(frame, structure.get("channel") or {},
                                      provisional_last=provisional_last) if show_channel else {}
    if channel:
        guides = [{
            "kind": kind, "label": label, "direction": channel["direction"],
            "x0": channel["x"][0], "x1": channel["x"][-1],
            "y0": channel[rail][0], "y1": channel[rail][-1],
            "source": "parallel_channel", "channel_state": channel["state"],
        } for rail, kind, label in (("lower", "support", "채널 하단"),
                                   ("upper", "resistance", "채널 상단"))
                  if channel.get("execution_guide_eligible", True)]
    else:
        guides = build_trendlines(frame) if show_patterns else []
    return structure, patterns, channel, guides


def arrange_price_level_labels(fig, frame):
    """Move only label boxes; arrows retain the original price coordinates."""
    levels = [a for a in fig.layout.annotations
              if not a.showarrow and a.yref in (None, "y")
              and isinstance(a.y, (int, float)) and math.isfinite(a.y)]
    bounds = fig.layout.yaxis.range
    low, high = bounds if bounds else (frame.Low.min(), frame.High.max())
    if not levels or not math.isfinite(low) or not math.isfinite(high) or not high > low:
        return
    levels = [a for a in levels if low <= a.y <= high]
    if not levels:
        return
    domain = fig.layout.yaxis.domain or (0, 1)
    height = (fig.layout.height - fig.layout.margin.t - fig.layout.margin.b) * (domain[1] - domain[0])
    levels = sorted(levels, key=lambda a: a.y)
    positions = []
    for a in levels:
        wanted = (a.y - low) / (high - low) * height
        positions.append(max(12, wanted, positions[-1] + 22 if positions else 12))
    overflow = max(0, positions[-1] - (height - 12))
    fig.update_layout(margin=dict(r=145))
    for a, position in zip(levels, positions):
        wanted = (a.y - low) / (high - low) * height
        label = {"EQL": "동일 저점", "EQH": "동일 고점"}.get(a.text, a.text)
        a.update(x=1, xref="paper", xanchor="left", yanchor="middle",
                 text=f"{label} {a.y:,.2f}", showarrow=True, arrowhead=0,
                 ax=10, ay=wanted - (position - overflow),
                 bgcolor="rgba(15,23,42,0.88)", font=dict(size=11))


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
                line=dict(color=color, width=width, dash=dash), name=col, mode="lines",
            ))
    if avg_price and avg_price > 0:
        fig.add_hline(y=avg_price, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
    return fig


def finish_price_figure(fig, frame, volume_signals, *, show_level_labels=False):
    if not volume_signals.empty:
        volume_signals = volume_signals.reindex(frame.index).copy()
        volume_signals["color"] = volume_signals["color"].fillna("#94A3B8")
        volume_signals["signal"] = volume_signals["signal"].fillna("UNAVAILABLE")
    if not volume_signals.empty and volume_signals["volume"].notna().any():
        hover_data = volume_signals[["signal", "rvol"]].copy()
        hover_data["rvol"] = hover_data["rvol"].map(lambda value: f"{value:.2f}x" if pd.notna(value) else "미수집")
        fig.add_trace(go.Bar(
            x=frame.index, y=volume_signals["volume"], marker_color=volume_signals["color"],
            yaxis="y2", name="거래량 신호", customdata=hover_data.to_numpy(),
            hovertemplate="%{x|%Y-%m-%d}<br>거래량 %{y:,.0f}<br>%{customdata[0]} · RVOL %{customdata[1]}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=frame.index, y=volume_signals["volume_ma"], yaxis="y2",
            name="거래량 MA", line=dict(color="#fbbf24", width=1), mode="lines",
        ))
        fig.update_layout(yaxis=dict(domain=[0.25, 1]),
                          yaxis2=dict(domain=[0, 0.17], title="거래량", anchor="x",
                                      rangemode="tozero", fixedrange=True))
    # Zones remain visible; crowded labels can be restored without changing data.
    fig.update_annotations(visible=show_level_labels)
    fig.update_layout(
        template="plotly_dark", height=640, xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, entrywidth=100),
        margin=dict(l=8, r=8, t=24, b=120),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame) > 2:
        interval = frame.index.to_series().diff().median()
        count = 60 if interval >= pd.Timedelta(days=20) else 104 if interval >= pd.Timedelta(days=5) else 180
        if len(frame) > count:
            visible = frame.tail(count)
            lower = pd.to_numeric(visible["Low"], errors="coerce").min()
            upper = pd.to_numeric(visible["High"], errors="coerce").max()
            fig.update_xaxes(range=[visible.index[0], frame.index[-1] + interval])
            if pd.notna(lower) and pd.notna(upper) and upper > lower > 0:
                padding = (upper - lower) * 0.08
                fig.update_layout(yaxis=dict(range=[max(0, lower - padding), upper + padding]))
    if show_level_labels:
        arrange_price_level_labels(fig, frame)
    return fig


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
