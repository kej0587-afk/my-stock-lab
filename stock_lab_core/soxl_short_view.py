"""SOXL-only observation UI; no allocations, execution approvals or orders."""

from datetime import datetime, timezone
import logging

import pandas as pd
import plotly.graph_objects as go

from stock_lab_core.execution_readiness import precision_display_context
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.soxl_short_data import load_short_hours
from stock_lab_core.soxl_short_observation import VERSION, build_short_observation
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _time(value):
    return "미연결" if value is None else pd.Timestamp(value).tz_convert("America/New_York").strftime("%m/%d %H:%M ET")


def _price(value):
    return "미연결" if value is None else f"{value:,.2f}"


def short_chart(model):
    frame = model["frame"]
    labels = [t.tz_convert("America/New_York").strftime("%m/%d %H:%M") for t in frame.index]
    fig = go.Figure(go.Candlestick(x=labels, open=frame.Open, high=frame.High,
                                   low=frame.Low, close=frame.Close, name="SOXX 1시간"))
    channel = model["channel"]
    for key, name in (("lower", "하단 · 무효화 참고"), ("middle", "중심선"), ("upper", "상단 · 익절 참고")):
        if channel:
            x = [pd.Timestamp(t).tz_convert("America/New_York").strftime("%m/%d %H:%M") for t in channel["x"]]
            fig.add_trace(go.Scatter(x=x, y=channel[key], name=name, mode="lines",
                                    line=dict(width=1, dash="dot" if key == "middle" else "solid")))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10),
                      xaxis=dict(type="category", rangeslider=dict(visible=False), nticks=6, title="봉 시작 · ET"),
                      yaxis_title="SOXX USD", legend=dict(orientation="h", y=-.25),
                      dragmode="pan")
    return fig


def render_observation_result(st, model):
    st.markdown("**단기 관찰: " + model["status"] + "**")
    st.caption("기준 봉 종료: " + _time(model["as_of"]) + " · 기대 완료봉: " + _time(model["expected_end"]))
    if model["channel"]:
        st.caption("SOXX 채널 하단 " + _price(model["channel"]["lower"][-1])
                   + " / 상단 " + _price(model["channel"]["upper"][-1])
                   + " · 완료봉 종가 " + _price(float(model["frame"].Close.iloc[-1])))
    plan = model["plan"]
    if plan:
        st.table([
            {"단계": "진입 검토 기준가(가정)", "SOXX USD": _price(plan["entry"]),
             "조건": "최근 완료봉 종가 · 지지 재확인 전 진입 확정 아님"},
            {"단계": "손절/가설 무효 참고", "SOXX USD": _price(plan["stop"]),
             "조건": "같은 1시간봉 종가가 기준 하단 아래면 지지 가설 폐기"},
            {"단계": "1R 참고", "SOXX USD": _price(plan["one_r"]),
             "조건": "같은 진입가+손절거리" + ("" if plan["one_r_before_target"] else " · 채널 상단이 먼저, 1R 확보 안 됨")},
            {"단계": "익절 검토 참고", "SOXX USD": _price(plan["target"]),
             "조건": "같은 봉의 채널 상단 · 도달/수익 보장 아님"},
        ])
        st.caption(f"기준가 대비 손절거리 {plan['risk_pct']:.2f}% · 상단까지 R/R {plan['rr']:.2f} · "
                   + ("최근 완료봉 하단 접촉 후 위 마감" if plan["support_reaction"] else "최근 완료봉 하단 지지 반응 미확인"))
        st.caption("위 가격은 SOXX 관찰 가정이며 SOXL 주문가가 아닙니다. 실제 SOXL 진입가·허용손실·수량은 별도입니다. "
                   "3배 단순 환산 없음 · 가격은 조회 시점 기준이며 갭/슬리피지로 손실이 커질 수 있습니다.")
    else:
        st.info("진입·익절·손절 계획 보류 · 자료 또는 유효한 채널 내부 가격을 확인하세요.")
    if not model["frame"].empty:
        st.plotly_chart(short_chart(model), width="stretch", key="soxl_short_chart_v1")
    with st.expander("SOX · SMH · QQQ 참고 흐름", expanded=False):
        st.dataframe([{"종목": row["ticker"], "역할": row["role"], "완료봉 종가": _price(row["close"]),
                       "직전 완료봉 대비": "미연결" if row["change_pct"] is None else f"{row['change_pct']:+.2f}%",
                       "봉 종료": _time(row["end"]), "자료 상태": row["status"]} for row in model["rows"]],
                     width="stretch", hide_index=True)
        st.caption("참고 흐름은 단기 타점이나 기존 중기 회복점수에 합산하지 않습니다. 지수는 포인트, ETF는 USD.")


def render_soxl_short_observation(st, ticker, decision):
    if str(ticker).upper() != "SOXL":
        return
    with st.expander("SOXL 단기 관찰 · SOXX 1시간봉", expanded=False):
        workflow = precision_display_context(decision).get("execution_workflow") or {}
        st.markdown("**관찰 전용 · 매수 승인 아님**")
        st.caption("기존 실행 제한: " + str(workflow.get("게이트상태", "미확인")) + " · "
                   + str(workflow.get("게이트근거", "기존 중기 판정·시장방어 유지")))
        st.caption("Yahoo 미국 정규장 완료 60분봉 · 수정 OHLC · 프리/애프터/데이마켓 제외. "
                   "개장 시각부터 1시간 단위이며 마지막 30분 및 단축장 잔여 봉 제외. 조회 지연 가능.")
        key = f"soxl_short_hours_v{VERSION}"
        if st.button("SOXX 단기 자료 조회", key="soxl_short_load_v1"):
            with st.spinner("SOXX와 참고 흐름 1시간봉 조회 중..."):
                st.session_state[key] = load_short_hours()
        payload = st.session_state.get(key)
        if not payload:
            return
        st.caption("수집 시각: " + _time(payload["captured_at"]) + " · 조회 캐시 최대 5분")
        if payload.get("issue"):
            st.warning(payload["issue"])
        try:
            now = datetime.now(timezone.utc)
            schedule = _exchange_schedule("US", (pd.Timestamp(now) - pd.Timedelta(days=65)).date().isoformat(),
                                          (pd.Timestamp(now) + pd.Timedelta(days=1)).date().isoformat())
            model = build_short_observation(payload["frames"], schedule, now)
            render_observation_result(st, model)
        except Exception as exc:
            logging.warning("SOXL short observation unavailable: %s", type(exc).__name__)
            st.warning("단기 관찰 자료 확인 필요: " + type(exc).__name__ + " · 기존 판정은 유지됩니다.")
