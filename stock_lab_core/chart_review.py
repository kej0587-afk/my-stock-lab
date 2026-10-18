"""Compact chart-side review of existing price and financial evidence."""

import pandas as pd
import plotly.graph_objects as go

from stock_lab_core.chart_enrichment import build_financial_snapshot_rows, build_volume_at_price_profile

LABELS = {
    "Price": "현재가", "Market cap": "시가총액", "Trailing P/E": "후행 PER", "Forward P/E": "선행 PER",
    "Price / book": "PBR", "Price / sales": "PSR", "EV / EBITDA": "EV/EBITDA", "ROE": "ROE", "ROA": "ROA",
    "Operating margin": "영업이익률", "Net margin": "순이익률", "Revenue growth": "매출 성장률",
    "Earnings growth": "이익 성장률", "Current ratio": "유동비율", "Quick ratio": "당좌비율",
    "Operating cash flow": "영업현금흐름", "Free cash flow": "잉여현금흐름", "Payout ratio": "배당성향",
    "Trailing dividend yield": "후행 배당수익률", "Total assets": "총자산", "NAV": "NAV",
    "Annual expense ratio": "연 보수율",
}


def saved_financial_chart_info(fields):
    """Saved Stock Lab ratios are percentage points, not Yahoo fractions."""
    result = dict(fields or {})
    for key in ("profitMargins", "operatingMargins", "returnOnEquity", "revenueGrowth", "earningsGrowth"):
        value = result.get(key)
        if value is not None and not str(value).strip().endswith("%"):
            result[key] = f"{str(value).strip()}%"
    return result


def render_chart_review(st, frame, *, ticker="", info=None, is_etf=False, source="", key="chart_review"):
    profile = build_volume_at_price_profile(frame, lookback=300, bins=31)
    with st.expander("매물 분포 · 재무 스냅샷", expanded=False):
        if profile["ok"]:
            a, b, c = st.columns(3)
            a.metric("최대 거래량 가격대(POC)", f"{profile['poc']['mid']:,.2f}")
            b.metric("가치영역 하단", f"{profile['value_area_low']:,.2f}")
            c.metric("가치영역 상단", f"{profile['value_area_high']:,.2f}")
            rows = pd.DataFrame(profile["rows"])
            fig = go.Figure(go.Bar(y=rows["mid"], x=rows["fraction"] * 100, orientation="h",
                                   marker_color=["#0f766e" if value else "#b8c2cc" for value in rows["in_value_area"]],
                                   customdata=rows[["low", "high"]].to_numpy(),
                                   hovertemplate="%{customdata[0]:,.2f}~%{customdata[1]:,.2f}<br>거래량 비중 %{x:.1f}%<extra></extra>"))
            fig.add_hline(y=profile["poc"]["mid"], line_color="#d97706", line_dash="dash")
            fig.update_layout(height=270, margin=dict(l=0, r=0, t=8, b=8), xaxis_title="추정 거래량 비중(%)", yaxis_title=None)
            st.plotly_chart(fig, width="stretch", key=f"{key}_profile")
            st.caption(f"{profile['bars_used']}봉 · 가치영역 {profile['value_area_fraction']:.0%}. 일봉 고가~저가에 거래량을 균등 배분한 추정치이며 실제 체결분포·호가·매수 대기물량이 아닙니다.")
        else:
            st.info("거래량이 있는 OHLCV가 부족해 매물 분포를 계산하지 않았습니다.")
        financial_rows = build_financial_snapshot_rows(info, is_etf=is_etf)
        if financial_rows:
            display = [{"항목": LABELS.get(row["label"], row["label"]),
                        "값": f"{row['value']:,.2f}",
                        "단위": row["currency"] if row["unit"] == "currency" else row["unit"]}
                       for row in financial_rows]
            st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch")
            st.caption(f"기존 저장 재무자료 · {source or '출처/기준시각 미제공'} · 결측을 0점으로 바꾸지 않음 · 차트 매매판정과 별개")
        else:
            st.caption("재무 스냅샷 미수집. ETF는 기업 재무점수로 평가하지 않습니다." if is_etf else "저장된 재무 스냅샷이 없습니다. 하단 재무 상세에서 자료를 갱신할 수 있습니다.")
