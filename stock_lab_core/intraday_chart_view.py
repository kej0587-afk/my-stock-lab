"""Streamlit quick chart (분봉·일봉 + 이동평균선) shown first in 정밀관측소.

Runs as a fragment: changing the interval or moving averages reruns only this chart, not the
whole 정밀관측소 analysis. During a regular session the fragment refreshes every 30 s so the
in-progress last bar's price and volume update. Display only; never feeds decisions.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from stock_lab_core import chart_preferences as cp
from stock_lab_core import intraday_chart as ic
from stock_lab_core.result_cache import cache_result

LIVE_REFRESH_SECONDS = 30
DISPLAY_BARS = 1500  # sent to the browser; moving averages are computed on all received bars first
TIMING_KEY = "_quick_chart_timings"
MA_COLORS = ("#22c55e", "#fbbf24", "#60a5fa", "#f472b6", "#94a3b8", "#a78bfa", "#fb923c", "#2dd4bf",
             "#e879f9", "#facc15", "#38bdf8", "#f87171")
MARKET_ZONE = {"KR": "Asia/Seoul", "US": "America/New_York"}


@cache_result(ttl=900, failure_ttl=15, is_success=lambda frame: not frame.empty, trace_name="quick_chart_history")
def load_history(ticker, yahoo_interval, period):
    return ic.fetch_yahoo(ticker, yahoo_interval, period)


@cache_result(ttl=20, failure_ttl=10, is_success=lambda frame: not frame.empty, trace_name="quick_chart_tail")
def load_tail(ticker, yahoo_interval, period):
    return ic.fetch_yahoo(ticker, yahoo_interval, period)


def _session(market, now):
    try:
        from stock_lab_core.report_exchange_clock import exchange_clock
        return exchange_clock(market, now)
    except Exception:
        return {"phase": "unknown"}


def _labels(index, label, market):
    local = index.tz_convert(MARKET_ZONE[market]) if index.tz is not None else index
    return [t.strftime("%Y-%m-%d") if ic.SPEC[label]["minutes"] is None else t.strftime("%Y-%m-%d %H:%M") for t in local]


def build_figure(frame, label, market, ma_lines, overlay_lines, *, provisional=False):
    frame = frame.iloc[-DISPLAY_BARS:].round(4)
    ma_lines = {p: s.iloc[-DISPLAY_BARS:].round(4) for p, s in ma_lines.items()}
    overlay_lines = {p: s.iloc[-DISPLAY_BARS:].round(4) for p, s in overlay_lines.items()}
    x = _labels(frame.index, label, market)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=x, open=frame["Open"], high=frame["High"], low=frame["Low"],
                                 close=frame["Close"], name="가격",
                                 increasing_line_color="#22c55e", decreasing_line_color="#ef4444"), row=1, col=1)
    for i, (period, series) in enumerate(sorted(ma_lines.items())):
        fig.add_trace(go.Scatter(x=x, y=series.to_numpy(), mode="lines",
                                 name=period if isinstance(period, str) else f"MA{period}",
                                 line=dict(color=MA_COLORS[i % len(MA_COLORS)], width=1.4)), row=1, col=1)
    for i, (period, series) in enumerate(sorted(overlay_lines.items())):
        fig.add_trace(go.Scatter(x=x, y=series.to_numpy(), mode="lines", name=f"일봉 {period}일선",
                                 line=dict(color=MA_COLORS[(i + 6) % len(MA_COLORS)], width=1.2, dash="dash",
                                           shape="hv")), row=1, col=1)
    colors = ["#22c55e" if c >= o else "#ef4444" for o, c in zip(frame["Open"], frame["Close"])]
    if provisional and colors:
        colors[-1] = "#94a3b8"
    fig.add_trace(go.Bar(x=x, y=frame["Volume"], marker_color=colors, name="거래량", showlegend=False),
                  row=2, col=1)
    visible = ic.SPEC[label]["visible"]
    n = len(frame)
    start = max(0, n - visible)
    window = frame.iloc[start:]
    lows = [window["Low"].min()] + [s.iloc[start:].min() for s in list(ma_lines.values()) + list(overlay_lines.values())]
    highs = [window["High"].max()] + [s.iloc[start:].max() for s in list(ma_lines.values()) + list(overlay_lines.values())]
    lows = [v for v in lows if pd.notna(v)]
    highs = [v for v in highs if pd.notna(v)]
    if lows and highs:
        pad = (max(highs) - min(lows)) * 0.04 or max(highs) * 0.01
        fig.update_yaxes(range=[min(lows) - pad, max(highs) + pad], row=1, col=1)
    vol = window["Volume"].max()
    if pd.notna(vol) and vol > 0:
        fig.update_yaxes(range=[0, vol * 1.1], row=2, col=1)
    fig.update_xaxes(type="category", range=[start - 0.5, n - 0.5], nticks=8, showgrid=False)
    fig.update_layout(template="plotly_dark", height=520, xaxis_rangeslider_visible=False,
                      margin=dict(l=8, r=8, t=8, b=8), uirevision=f"{label}",
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def _shortage_text(status, label, overlay=False):
    notes = []
    for period, row in sorted(status.items()):
        if not row["ok"]:
            unit = "일" if overlay or label == "일봉" else "봉"
            notes.append(f"{'일봉 ' if overlay else ''}{period}{unit}선: 데이터 부족 (보유 {row['have']:,}개 < 필요 {row['need']:,}개)")
    return notes


def market_support_rows():
    """Per-market facts this app can state. Measured delay is shown separately per ticker."""
    return [
        {"시장": "미국", "공급처": "Yahoo Finance 차트 (정규장만)", "장중 마지막 봉": "진행 중 봉 30초마다 다시 조회",
         "지연": "종목별 측정값 표시 (아래 '마지막 봉')", "조회 가능 과거": "1분 8거래일 · 5·30분 60일 · 60·120분 730일 · 일봉 전체"},
        {"시장": "한국", "공급처": "Yahoo Finance 차트 (.KS/.KQ, 정규장만)", "장중 마지막 봉": "진행 중 봉 30초마다 다시 조회",
         "지연": "종목별 측정값 표시 · 2026-11-27 13:26 KST 삼성전자 1분봉 측정 약 20분 지연",
         "조회 가능 과거": "1분 8거래일 · 5·30분 60일 · 60·120분 730일 · 일봉 전체"},
    ]


BAR_UNIT = {"주봉": "주", "월봉": "개월"}
BASIS_DAILY = "거래일 기준 N일선"
BASIS_BAR = "봉 단위(N주선·N개월선)"


def daily_basis_view(daily_long, frame, label, enabled, basis):
    """2026-11-27: on 일/주/월봉 the user's N means trading days by default. Returns
    (ma_lines, overlay_lines, notes). ``daily_long`` is the long daily history the 주/월봉 were built from."""
    if label == "일봉":
        lines, status = ic.daily_basis_lines(daily_long, frame, enabled, label=label)
        ma = {f"{p}일선": s for p, s in lines.items()}
        return ma, {}, _basis_notes(status, "일선")
    if basis == BASIS_BAR:
        lines, status = ic.moving_averages(frame, enabled)
        unit = BAR_UNIT[label]
        notes = [f"{p}{unit}선: 계산 불가 (확보 {r['have']:,}{'주' if unit == '주' else '개월'}봉 < 필요 {r['need']:,})"
                 for p, r in sorted(status.items()) if not r["ok"]]
        return {f"{p}{unit}선": s for p, s in lines.items()}, {}, notes
    lines, status = ic.daily_basis_lines(daily_long, frame, enabled, label=label)
    notes = _basis_notes(status, "일선", prefix="일봉 ")
    if any(r.get("ok") for r in status.values()):
        notes.append("주·월봉 위 일선 = 각 봉의 마지막 거래일까지 계산한 일봉 이동평균. 진행 중인 봉은 마지막 일봉 날짜까지")
    return {}, lines, notes


def _basis_notes(status, unit, prefix=""):
    notes = []
    for period, row in sorted(status.items()):
        if row.get("ok"):
            notes.append(f"{prefix}{period}{unit} 마지막 값 {row['last_value']:,.2f} (일봉 {row['last_date']} 기준 · "
                         f"첫 유효 {row['first_date']} · 확보 {row['have']:,}거래일)")
        else:
            notes.append(f"{prefix}{period}{unit}: 계산 불가 (확보 {row['have']:,}거래일 < 필요 {row['need']:,}거래일)")
    return notes


def render_analysis_chart(st, ticker, *, store=None, key="analysis_chart", now_fn=None,
                          timeframe_frames=None, analysis_renderer=None, daily_long=None):
    if not ticker:
        return
    prefs = cp.load_into_state(st.session_state, store)
    market = ic.market_of(ticker)
    now_fn = now_fn or (lambda: pd.Timestamp(datetime.now(timezone.utc)))
    live_session = _session(market, now_fn()).get("phase") == "intraday"
    prefix = f"{key}_{ticker}"

    def body():
        started = time.perf_counter()
        now = now_fn()
        session = _session(market, now)
        current = dict(st.session_state.get(cp.STATE_KEY) or prefs)
        label = st.segmented_control("봉 간격", list(ic.INTERVALS), key=f"{prefix}_interval",
                                     default=current["interval"]) or current["interval"]
        spec = ic.SPEC[label]
        c1, c2 = st.columns([2, 1])
        periods_text = c1.text_input("이동평균 기간 (쉼표로 구분, 2~5000)", key=f"{prefix}_periods",
                                     value=", ".join(str(p) for p in current["periods"]))
        periods, rejected = ic.parse_ma_periods(periods_text)
        if rejected:
            c1.caption("무시한 입력: " + ", ".join(rejected))
        periods = periods or list(cp.DEFAULTS["periods"])
        live_on = c2.toggle("장중 자동 갱신", value=True, key=f"{prefix}_live",
                            help=f"정규장 중 {LIVE_REFRESH_SECONDS}초마다 진행 중인 마지막 봉을 다시 조회합니다.")
        enabled_default = [p for p in current["enabled"] if p in periods]
        enabled = st.pills("표시할 이동평균선", periods, selection_mode="multi", default=enabled_default,
                           format_func=lambda p: f"{p}", key=f"{prefix}_on_{'-'.join(map(str, periods))}") or []
        overlay = current["daily_overlay"]
        if spec["minutes"] is not None:
            overlay = st.checkbox("분봉 위에 일봉 기준 이동평균선 겹쳐 보기", value=current["daily_overlay"],
                                  key=f"{prefix}_overlay",
                                  help="각 분봉에는 전 거래일 종가까지 계산한 일봉 N일선 값을 표시합니다(당일 미확정 종가 미사용).")
        current = cp.normalize({"periods": periods, "enabled": enabled, "daily_overlay": overlay, "interval": label})
        st.session_state[cp.STATE_KEY] = current

        fetch_started = time.perf_counter()
        supplied = (timeframe_frames or {}).get(label)
        try:
            history = supplied if supplied is not None else load_history(ticker, spec["yahoo"], spec["period"])
            tail = None
            if supplied is None and session.get("phase") == "intraday" and live_on and not history.empty:
                tail = load_tail(ticker, spec["yahoo"], spec["tail"])
            frame = ic.build_frame(history, tail, label, market)
        except Exception as exc:
            st.warning(f"{ticker} {label} 차트 미연결 · {type(exc).__name__}: {exc}")
            return
        daily = None
        if overlay and enabled and spec["minutes"] is not None:
            daily_spec = ic.SPEC["일봉"]
            daily = load_history(ticker, daily_spec["yahoo"], daily_spec["period"])
        fetch_seconds = time.perf_counter() - fetch_started
        if frame is None or frame.empty:
            st.warning(f"{ticker} {label} 가격을 받지 못했습니다 (Yahoo 응답 없음). 잠시 뒤 다시 시도하세요.")
            return
        basis_notes = None
        if spec["minutes"] is None and supplied is not None and daily_long is not None and not daily_long.empty:
            basis = BASIS_DAILY
            if label in BAR_UNIT:
                basis = st.radio("주·월봉 이동평균 기준", [BASIS_DAILY, BASIS_BAR], horizontal=True,
                                 key=f"{prefix}_basis_{label}",
                                 help="기본은 같은 거래일 기준 일선(240일선=최근 240거래일)입니다. 봉 단위는 240주선처럼 단위를 붙여 표시합니다.")
            ma_lines, overlay_lines, basis_notes = daily_basis_view(daily_long, frame, label, enabled, basis)
            ma_status, overlay_status = {}, {}
        else:
            ma_lines, ma_status = ic.moving_averages(frame, enabled)
            overlay_lines, overlay_status = ic.daily_overlay(daily, frame, enabled) if daily is not None else ({}, {})
        state = ic.last_bar_state(frame, label, now, session)
        build_started = time.perf_counter()
        if analysis_renderer is not None:
            st.caption(f"{ticker} · {label} 가격·거래량·패턴·추세선·채널·매물대·SMC · "
                       "기존 투자판정·실행계획은 일/주/월봉 기준 유지")
            if spec["minutes"] is not None:
                st.caption("선택 분봉 구조 관찰 · 일봉 실행조건 체크표와 별도 · 거래량은 선택 봉의 50봉 기준")
            analysis_renderer(frame.tail(DISPLAY_BARS).copy(), label, ma_lines, overlay_lines, state["provisional"])
        else:
            fig = build_figure(frame, label, market, ma_lines, overlay_lines, provisional=state.get("provisional", False))
            st.plotly_chart(fig, width="stretch", key=f"{prefix}_fig_{label}", config={"displaylogo": False, "scrollZoom": True})
        build_seconds = time.perf_counter() - build_started

        zone = MARKET_ZONE[market]
        start_local = state["start"].tz_convert(zone) if state["start"].tz is not None else state["start"]
        bar_time = start_local.strftime("%Y-%m-%d") if label == "일봉" else start_local.strftime("%m-%d %H:%M")
        tz_name = "KST" if market == "KR" else "ET"
        price = f"{state['close']:,.0f}" if market == "KR" else f"{state['close']:,.2f}"
        volume = ("미수집" if state["volume"] is None
                  else "집계 전(공급처 0)" if state["volume"] == 0 and state["provisional"] else f"{state['volume']:,.0f}")
        from stock_lab_core.chart_structure import last_bar_is_provisional
        provisional = (state["provisional"] if spec["minutes"] is not None else last_bar_is_provisional(frame, ticker))
        status = "진행 중·미확정(공급처 최신 봉)" if provisional else "확정"
        parts = [f"마지막 봉 {bar_time} {tz_name if label != '일봉' else ''} · 가격 {price} · 거래량 {volume} · {status}"]
        if state["lag_minutes"] is not None:
            parts.append(f"조회 시각 대비 봉 시작 {state['lag_minutes']:.0f}분 전")
        if not session.get("phase") == "intraday":
            parts.append("정규장 시간 아님: 자동 갱신 없음")
        st.caption(" · ".join(p.strip() for p in parts))
        first = frame.index[0].tz_convert(zone) if frame.index.tz is not None else frame.index[0]
        shown = min(len(frame), DISPLAY_BARS)
        ma_scope = (f"장기 일봉 {len(daily_long):,}거래일로 먼저 계산" if basis_notes else "받은 전체로 계산")
        st.caption(f"받은 범위 {first.strftime('%Y-%m-%d')}부터 {len(frame):,}봉 (화면 최근 {shown:,}봉, 이동평균은 {ma_scope}) · 요청 한도 {ic.REQUEST_LIMIT_TEXT[label]} · "
                   f"공급처 {'기존 분석 원자료' if supplied is not None else 'Yahoo Finance(정규장)'}")
        aggregation = frame.attrs.get("aggregation")
        if aggregation:
            st.caption(f"120분 진단 · 받은 60분봉 {aggregation['received_60']:,} · 생성 120분봉 {len(frame):,} · "
                       f"화면 캔들 {shown:,} · 개장 기준 묶음 · 정규장 밖 제외 {aggregation['excluded']} · "
                       f"원봉 일부 미수집/진행 중 구간 {aggregation['incomplete']} · 마감 짧은 구간 보존")
        notes = _shortage_text(ma_status, label) + _shortage_text(overlay_status, label, overlay=True)
        if basis_notes:
            st.caption(" · ".join(basis_notes))
        if notes:
            st.caption(" · ".join(notes))
        total = time.perf_counter() - started
        lock_wait = history.attrs.get("lock_wait")
        timing = {"interval": label, "total": total, "fetch": fetch_seconds, "figure": build_seconds,
                  "bars": len(frame), "lock_wait": lock_wait, "at": now.isoformat()}
        st.session_state.setdefault(TIMING_KEY, []).append(timing)
        del st.session_state[TIMING_KEY][:-20]
        st.caption(f"서버 준비 {total:.2f}초 (가격 조회 {fetch_seconds:.2f}초 · 그림 준비 {build_seconds:.2f}초)")

        s1, s2 = st.columns([1, 2])
        if s1.button("이동평균 설정 저장", key=f"{prefix}_save"):
            cp.save_from_state(st.session_state, current, store)
        s2.caption(cp.STATUS_TEXT.get(st.session_state.get(cp.STATUS_KEY, "session"), ""))
        with st.expander("시장별 실시간 지원 · 지연 · 조회 가능 기간", expanded=False):
            st.dataframe(pd.DataFrame(market_support_rows()), hide_index=True, width="stretch")
            st.caption("30초는 화면 재조회 주기입니다. 봉 시작 이후 경과시간은 체결 시세 지연이 아닙니다. "
                       "공급처 실제 체결 지연은 별도 타임스탬프가 없어 미확인입니다. 한국 실시간(네이버 등) 연결은 아직 없습니다.")

    run_every = LIVE_REFRESH_SECONDS if live_session else None
    st.fragment(run_every=run_every)(body)()


# Backwards compatibility for non-observatory callers; no second chart in the app.
render_quick_chart = render_analysis_chart
