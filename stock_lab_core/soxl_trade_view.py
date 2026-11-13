"""One connected research desk; existing permission and account settings stay read-only."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as cache_st

from stock_lab_core.soxl_trade_plan import RULE, build_price_context, paired_five, price_plan, size_scenario
from stock_lab_core.soxl_trade_research import replay
from stock_lab_core.soxl_short_data import load_trade_history
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


@cache_st.cache_data(ttl=86400, show_spinner=False, max_entries=4)
def cached_replay(frames, captured_at, rule=RULE):
    first = min(f.index.min() for f in frames.values()).date().isoformat()
    now = pd.Timestamp(captured_at)
    schedule = _exchange_schedule("US", first, now.date().isoformat())
    return replay(frames, schedule, now)


def _pct(value):
    return "계산 불가" if value is None else f"{value:+.2f}%"


def render_stats(st, report, format_time):
    if report.get("issue") or not report.get("policies"):
        st.info(report.get("issue") or "과거 검증 자료 없음 · 승률 미산출")
        return
    st.caption(f"규칙 {report['rule']} · {format_time(report['first'])} ~ {format_time(report['last'])}")
    rows = []
    for key, label in (("day", "당일 청산"), ("overnight", "야간 허용 · 최대 18시간봉")):
        policy = report["policies"][key]
        stats = policy["stats"]
        interval = stats["interval"]
        rows.append({"보유 정책": label, "거래/승리": f"{stats['n']} / {stats['wins']}",
                     "과거 승률": "미산출" if not stats["n"] else f"{stats['win_pct']:.1f}%",
                     "95% 구간": "미산출" if interval is None else f"{interval[0]:.1f}~{interval[1]:.1f}%",
                     "평균 순수익": _pct(stats["mean_pct"]), "최악 거래": _pct(stats["worst_pct"]),
                     "거래종료 MDD": _pct(stats["mdd_pct"])})
    st.dataframe(rows, hide_index=True, width="stretch")
    for key, label in (("day", "당일 청산"), ("overnight", "야간 허용")):
        stats = report["policies"][key]["stats"]
        if stats["n"] and stats["mean_pct"] <= 0:
            st.warning(label + ": 비용 후 평균 손익이 0 이하 · 이 표본에서 매매 우위 미확인")
        elif stats["n"]:
            st.caption(label + ": 과거 평균은 양수지만 현재 가격의 승률/향후 수익 보장은 아닙니다.")
    st.warning("현재 진입가격의 성공 확률은 미산출입니다. 위 값은 동일 연구 규칙의 과거 빈도이며, "
               "기존 시장방어 적용 승률이 아닙니다. 5분 확인을 추가한 진입·수동 가격에는 그대로 적용할 수 없습니다.")
    st.caption("수수료·슬리피지 가정 편도 10bp. 체결은 OHLC 대용값이며 실제 체결 보장이 아닙니다. "
               "95% 구간은 표본 불확실성 참고이며 거래 간 상관·국면 변화는 반영하지 않습니다.")
    st.caption("MDD는 연구 자금을 매 거래 전액 재투자한 거래종료 기준 하락폭입니다. 실제 계좌 MDD나 장중 최대손실과 다릅니다.")
    paired = report.get("comparison")
    if paired:
        st.caption(f"동일 진입 {paired['paired']}건 비교: 당일 청산 유리 {paired['day_better']}건 / 불리 {paired['day_worse']}건. "
                   f"야간 허용 대비 최대 손익 개선 {paired['max_saved_pp']:.2f}%p / 최대 포기 수익 {paired['max_forgone_pp']:.2f}%p. "
                   f"진입이 달라 짝비교 제외 {paired['unpaired']}건.")
    with st.expander("검증 상세 · 제외 사유 · 거래 내역", expanded=False):
        for key, label in (("day", "당일 청산"), ("overnight", "야간 허용")):
            policy = report["policies"][key]
            st.markdown("**" + label + "**")
            st.table([{"구간": name, "표본": stats["n"], "과거 승률": "미산출" if stats["win_pct"] is None else f"{stats['win_pct']:.1f}%",
                       "평균 순수익": _pct(stats["mean_pct"])}
                      for name, stats in (("전반", policy["early"]), ("후반", policy["late"]), ("비용 20bp/편도", policy["cost20"]))])
            st.caption("장중 최악손실 하한 참고: " + _pct(policy["stats"]["mae_pct"])
                       + " · 청산봉 전체 저가를 포함한 보수적 경계이며 실제 MAE 아님")
            st.write({"제외": policy["rejected"], "결측 봉": report["missing"]})
            ledger = pd.DataFrame(policy["trades"])
            if not ledger.empty:
                st.dataframe(ledger.tail(20), width="stretch", hide_index=True)
                st.download_button(label + " 검증 CSV", ledger.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"soxl_{RULE}_{key}.csv", mime="text/csv", key="soxl_ledger_" + key)
        st.caption("수정 OHLC 사용. 신호 때까지의 140봉으로 매번 재계산. 동시 손절·목표 접촉은 손절 우선. "
                   "갭 손절은 시가. 마지막 30분봉은 체결 대용값에만 사용. 자료 결측·검증 종료 미청산은 제외. "
                   "표본을 보고 임계값을 최적화하지 않았으며 과거 시장방어 입력은 미확보입니다.")


def render_research(st, format_time):
    from stock_lab_core.short_trade_view import render_symbol_research
    render_symbol_research(st, "SOXL", show_plan=False)


def render_sizing(st, plan):
    with st.expander("거래당 손실예산 · 수량 시나리오", expanded=False):
        equity = st.number_input("계좌 평가액 (USD 환산, 시나리오)", min_value=0., value=0., step=100., key="soxl_budget_equity")
        cash = st.number_input("사용 가능 현금 (USD, 시나리오)", min_value=0., value=0., step=100., key="soxl_budget_cash")
        allowance = st.number_input("추가 갭·지연 손실 가정 (%p)", min_value=0., max_value=50., value=0., step=.5, key="soxl_budget_gap")
        rows = []
        for budget in (.25, .5, 1.):
            value = size_scenario(plan, equity, cash, budget, allowance)
            rows.append({"손실예산": f"{budget:g}%", "수량": value.get("shares", "미산출"),
                         "금액 (USD)": f"{value['amount']:.2f}" if value else "미산출",
                         "계좌 비중": f"{value['weight_pct']:.2f}%" if value else "미산출",
                         "가정 손실 (USD)": f"{value['loss']:.2f}" if value else "미산출"})
        st.table(rows)
        st.caption("원화 계좌는 직접 USD 환산값을 입력해야 합니다. 자동 환율 추정 없음. "
                   "편도 10bp 비용 포함 · 현금/계좌 평가액 한도 적용 · 반올림 아닌 정수 내림. "
                   "0.25/0.5/1%는 비교 가정이며 권장 비중이 아닙니다. 실제 갭·청산 지연은 예산을 초과할 수 있습니다. "
                   "기존 보유·목표비중·중기 배분에 저장하지 않습니다.")
        if allowance == 0:
            st.caption("추가 갭·지연 가정 0%p: 비용 외 초과 손실을 반영하지 않은 시나리오입니다.")


def render_trade_desk(st, payload, hourly, schedule, now, decision, format_time):
    context = build_price_context(payload["frames"], hourly, schedule, now)
    five = paired_five((payload.get("five_minute") or {}).get("frames", {}), schedule, now)
    readiness = build_execution_readiness(decision.get("execution_workflow"), decision.get("chart_final_check"))
    st.markdown("**SOXL 단기 가격 계획 · 별도 연구안**")
    st.table([
        {"구분": "기존 실행 판정", "현재 상태": readiness["label"], "근거": readiness["reason"]},
        {"구분": "SOXX 타점 조건", "현재 상태": "지지 반응 관찰" if context["signal"] else "조건 대기", "근거": context["reason"]},
        {"구분": "거래 세션", "현재 상태": "미국 정규장" if context["session_active"] else "정규장 외 · 다음 정규장 재확인", "근거": "시간외·데이마켓을 정규장 가격에 섞지 않음"},
    ])
    st.caption("계획 기준 봉 종료: " + format_time(context["as_of"]) + " · 완료봉 가격이며 실시간 체결 호가가 아닙니다.")
    plan = context["plan"]
    price_time = context["as_of"]
    if plan and not five["issue"] and five["end"] >= price_time:
        if five["end"].tz_convert("America/New_York").date() == price_time.tz_convert("America/New_York").date():
            plan = price_plan(next(r["close"] for r in five["rows"] if r["ticker"] == "SOXL"), plan["stop"])
            price_time = five["end"]
    if plan:
        st.caption("가정 진입 기준 가격시각: " + format_time(price_time) + " · 최근 동일 시각 완료봉, 체결가 아님")
        entry = st.number_input("SOXL 가정 진입가 (USD, 0 = 표시 기준가격)", min_value=0., value=0., step=.01,
                                key="soxl_scenario_entry_v1")
        custom = entry > 0
        reference_stop = plan["stop"]
        plan = price_plan(entry or plan["entry"], reference_stop)
        if custom:
            st.caption("수동 진입가 시나리오 · 이 가격의 조건부 승률은 검증되지 않았습니다.")
        if plan:
            st.table([
                {"SOXL 가격 기준": "가정 진입가", "USD": f"{plan['entry']:.4f}", "의미": "수정 OHLC 참고값 · 실제 주문/매수 승인 아님"},
                {"SOXL 가격 기준": "가격 손절 참고선", "USD": f"{plan['stop']:.4f}", "의미": "같은 SOXL 1시간봉 저가 · 갭 손실 확대 가능"},
                {"SOXL 가격 기준": "1R 익절 참고선", "USD": f"{plan['target']:.4f}", "의미": f"동일 진입·손절 기준, 가격거리 {plan['risk_pct']:.2f}% · 수익 보장 아님"},
            ])
            st.caption("가격 시나리오는 타점 미충족 때도 표시하지만 실행 가능을 뜻하지 않습니다. "
                       "SOXX 1시간 지지 실패는 별도 무효 조건이고, SOXL 가격 손절은 그보다 먼저 발생할 수 있습니다.")
            st.caption("신규 후보 계획입니다. 조회할 때 기준봉이 바뀌므로 이미 진입한 포지션의 손절선을 자동으로 바꾸는 용도가 아닙니다.")
            with st.expander("SOXL 자체 가격 차트 · 계획선", expanded=False):
                frame = context["soxl_frame"]
                labels = [format_time(t) for t in frame.index]
                fig = go.Figure(go.Candlestick(x=labels, open=frame.Open, high=frame.High, low=frame.Low, close=frame.Close, name="SOXL"))
                for field, label, color in (("entry", "가정 진입", "#3b82f6"), ("stop", "가격 손절 참고", "#ef4444"), ("target", "1R 목표 참고", "#16a34a")):
                    fig.add_hline(y=plan[field], annotation_text=f"{label} {plan[field]:.2f}", line_color=color, line_dash="dot")
                fig.update_layout(height=350, margin=dict(l=10,r=10,t=30,b=15), xaxis=dict(type="category",nticks=5,rangeslider=dict(visible=False),title="봉 시작 · ET"), yaxis_title="SOXL USD")
                st.plotly_chart(fig, width="stretch", key="soxl_plan_chart_v1")
        else:
            st.warning(f"가정 진입가 {entry:.2f} USD가 자동 손절 참고선 {reference_stop:.2f} USD 이하입니다. "
                       "같은 SOXL 1시간봉 저가를 손절선으로 쓰는 기존 연구안에서는 손익비·수량을 산출할 수 없습니다.")
            st.caption("진입가만 바뀌며 손절선은 자동으로 낮아지지 않습니다. 별도로 정한 더 낮은 손절가의 "
                       "시나리오나 이 가격의 승률을 검증한 결과가 아닙니다.")
    else:
        st.info("동일 시각 SOXL 가격 계획 미산출 · 자료 또는 손절거리 확인 필요")
    st.markdown("**같은 시각 5분 가격 · 이탈은 관찰 전용**")
    st.table([{"종목": r["ticker"], "5분 종가": "미연결" if r["close"] is None else f"{r['close']:.2f}",
               "봉 종료": format_time(five["end"]), "자료 상태": r["issue"] or "동일 완료봉"} for r in five["rows"]])
    if five["issue"]:
        st.info(five["issue"])
    st.caption("5분 확인은 1시간 타점의 조기 경고입니다. 새로운 진입 승인이나 자동 손절 주문이 아닙니다. "
               "연구안: SOXX 지지 회복 → 다음 정규장 봉 시가 진입 대용값 → SOXL 자체 손절/1R. "
               "SOX·SMH·QQQ는 참고만 사용. SOXL은 일간 3배 목표이며 구간 수익률을 3배로 환산하지 않습니다.")
    render_sizing(st, plan)
    render_research(st, format_time)
