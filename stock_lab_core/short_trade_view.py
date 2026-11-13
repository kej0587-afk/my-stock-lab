"""Per-symbol opt-in validation. No writes to account, scores or execution gates."""

from datetime import datetime, timezone
import logging

import pandas as pd
import streamlit as cache_st

from stock_lab_core.execution_readiness import precision_display_context
from stock_lab_core.report_eventstudy import _exchange_schedule
from stock_lab_core.short_trade_data import research_profile, load_current, load_history
from stock_lab_core.short_trade_evidence import VERSION, build_report, current_context, comparable_history
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _schedule(frames, captured, profile):
    starts = [f.index.min() for f in frames.values() if not f.empty]
    if not starts:
        raise ValueError("no_history")
    start = min(starts).date().isoformat()
    return _exchange_schedule(profile["market"], start, pd.Timestamp(captured).date().isoformat())


@cache_st.cache_data(ttl=86400, show_spinner=False, max_entries=12)
def cached_evidence(frames, captured, profile, cost_bps, version=VERSION):
    return build_report(frames, _schedule(frames, captured, profile), captured, profile, cost_bps)


def _time(value, profile):
    if value is None:
        return "미확보"
    return pd.Timestamp(value).tz_convert(profile["timezone"]).strftime("%Y-%m-%d %H:%M %Z")


def _pct(value):
    return "미산출" if value is None else f"{value:+.2f}%"


def _frequency(value):
    return "미산출" if value is None else f"{value:.1f}%"


def render_evidence(st, report, current, profile, key):
    if report.get("issue") or not report.get("policies"):
        st.warning(report.get("issue") or "검증 자료 미확보 · 승률 미산출")
        return
    st.caption(f"{profile['ticker']} 개별 표본 · {profile['rule']} · 자료 ID {report['fingerprint']} · "
               f"{_time(report['first'], profile)} ~ {_time(report['last'], profile)}")
    st.caption(f"편도 비용 {report['cost_bps']:g}bp 가정(수수료·스프레드·슬리피지·세금 합계는 직접 확인) · "
               "다른 종목과 승률을 섞지 않음 · 기존 시장방어 적용 승률 아님")
    statuses, rates, risks, similar = [], [], [], []
    for policy_key, label in (("day", "당일 청산"), ("overnight", "야간 허용 · 최대 18시간봉")):
        policy = report["policies"][policy_key]
        stats, interval = policy["stats"], policy["stats"]["interval"]
        status, reason = policy["validation"]
        statuses.append({"조건": label, "연구 검증": status, "근거": reason})
        rates.append({"조건": label, "거래 수": stats["n"], "과거 승률": _frequency(stats["win_pct"]),
                      "95% 참고구간": "미산출" if not interval else f"{interval[0]:.1f}~{interval[1]:.1f}%",
                      "평균 순손익": _pct(stats["mean_pct"])})
        risks.append({"조건": label, "최악 거래": _pct(stats["worst_pct"]),
                      "거래종료 MDD": _pct(stats["mdd_pct"]),
                      "후반 평균": _pct(policy["late"]["mean_pct"]),
                      "비용 2배 평균": _pct(policy["cost20"]["mean_pct"])})
        comparable = comparable_history(policy, current)
        similar.append({"조건": label, "같은 사전 구간": current.get("cohort") or "미형성",
                        "완료 표본": comparable["n"],
                        "과거 빈도": _frequency(comparable["win_pct"]) if comparable["n"] >= 20 else "표본 부족 · 미제시",
                        "평균 순손익": _pct(comparable["mean_pct"]) if comparable["n"] else "미산출"})
    st.table(statuses)
    st.dataframe(rates, hide_index=True, width="stretch")
    st.dataframe(risks, hide_index=True, width="stretch")
    st.markdown("**현재 조건과 비교 가능한 표본**")
    if not current["setup"]:
        st.info("현재 연구 진입조건 미충족 · 현재 가격의 승률을 붙이지 않습니다: " + current["issue"])
    else:
        st.dataframe(similar, hide_index=True, width="stretch")
    st.caption("현재 조건 표본은 신호봉 손절거리(1% 이하/1~2%/2% 초과)와 직전 5봉 방향을 미리 고정해 나눕니다. "
               "20건 미만 빈도는 숨깁니다. 이 값도 현재 진입가격의 성공 확률이나 매수 허가는 아닙니다.")
    with st.expander("검증 가정 · 표본 손실 · 거래 내역", expanded=False):
        st.write({"미확보 시간봉": report["missing"], "발생 신호": report["signals"],
                  "수집 시각": _time(report["captured_at"], profile), "게이트 이력": report["gate_history"]})
        for policy_key, label in (("day", "당일 청산"), ("overnight", "야간 허용")):
            policy = report["policies"][policy_key]
            st.markdown("**" + label + "**")
            st.table([{"기간": name, "표본": stats["n"], "과거 승률": _frequency(stats["win_pct"]),
                       "평균 순손익": _pct(stats["mean_pct"])}
                      for name, stats in (("전반", policy["early"]), ("후반", policy["late"]))])
            st.write({"제외": policy["rejected"]})
            ledger = pd.DataFrame(policy["trades"])
            if not ledger.empty:
                st.dataframe(ledger.tail(20), hide_index=True, width="stretch")
                st.download_button(label + " 검증 CSV", ledger.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"{profile['ticker']}_{profile['rule']}_{policy_key}.csv",
                                   mime="text/csv", key=key + policy_key)
        st.caption("확정 피벗·신호 시점까지 140봉으로 재계산. 신호 다음 정규장 봉 시가 진입, 신호봉 저가 손절, "
                   "실제 진입-손절 거리의 1R 목표. 같은 봉에서 양쪽 접촉은 손절 우선, 갭 이탈은 시가. "
                   "마지막 잔여 봉은 체결 대용값에만 사용. OHLC 체결 대용값이지 실제 체결 보장이 아닙니다.")
        st.caption("시간분할 후반은 완전히 독립된 미관측 검증이 아닙니다. Wilson 95% 구간은 거래 간 상관·국면변화를 "
                   "보정하지 않습니다. MDD는 연구 자금 전액 재투자·거래종료 기준이며 실제 계좌 MDD와 다릅니다. "
                   "30/20건은 연구 표시 기준일 뿐입니다. 결측 경로 제외도 결과를 편향시킬 수 있습니다. "
                   "여러 종목 중 좋은 결과만 고르면 선택편향이 생깁니다.")


def render_symbol_research(st, ticker, decision=None, *, show_plan=True):
    profile = research_profile(ticker)
    if not profile:
        st.caption("단기 검증: 한국·미국 상장 주식/ETF 외 자료는 별도 검증 필요")
        return
    key = f"short_evidence_v{VERSION}_{profile['ticker']}"
    with st.expander("단기 전략 검증 · 현재 조건·과거 승률·손실", expanded=False):
        if decision is not None:
            workflow = precision_display_context(decision).get("execution_workflow") or {}
            st.caption("기존 실행 판정 유지: " + str(workflow.get("게이트상태", "미확인")) + " · "
                       + str(workflow.get("게이트근거", "기존 시장방어·개별 판정 참조")))
        st.caption(f"기준 종목 {profile['reference']} / 체결 대용 {profile['ticker']} · "
                   f"{profile['market']} 정규장 완료 1시간 수정 OHLC. 시간외·데이마켓 제외.")
        st.caption("각 ETF 실제 가격을 사용하며 기초자산 수익률을 2배·3배로 곱하지 않습니다. "
                   "현물 BTC의 24시간 흐름이나 다른 국가의 비동시 가격을 섞지 않습니다.")
        cost = st.number_input("편도 총 거래비용 가정 (bp)", min_value=0., max_value=100., value=10.,
                               step=1., key=key + "_cost")
        if st.button("이 종목 단기 검증 실행", key=key + "_load"):
            with st.spinner("현재 완료봉·과거 표본 조회 및 검증 중..."):
                history, live = load_history(profile["ticker"]), load_current(profile["ticker"])
                report = dict(issue=history["issue"], policies={})
                if history["ok"]:
                    try:
                        report = cached_evidence(history["frames"], history["captured_at"], profile, cost)
                    except Exception as exc:
                        logging.warning("Short evidence %s: %s", ticker, type(exc).__name__)
                        report = dict(issue="검증 실패: " + type(exc).__name__, policies={})
                st.session_state[key] = dict(report=report, live=live, cost=cost)
        saved = st.session_state.get(key)
        if not saved:
            st.info("과거 검증 미실행 · 승률은 0%가 아니라 미산출")
            return
        if saved["cost"] != cost:
            st.info("비용 가정 변경 · 다시 실행해야 새 조건의 결과를 표시합니다.")
            return
        now = pd.Timestamp(datetime.now(timezone.utc))
        live = saved["live"]
        current = dict(setup=False, cohort=None, as_of=None, plan={}, issue=live["issue"])
        if live["ok"]:
            try:
                current = current_context(live["frames"], _schedule(live["frames"], now, profile), now, profile)
            except Exception as exc:
                current["issue"] = "현재 기준 확인 실패: " + type(exc).__name__
        st.caption("계획 기준 완료 시각: " + _time(current["as_of"], profile) + " · 실시간 주문 호가 아님")
        if show_plan and current["plan"]:
            plan = current["plan"]
            st.table([{"구분": name, profile["currency"]: f"{plan[field]:,.4f}", "의미": meaning}
                      for field, name, meaning in (("entry", "가정 진입 기준", "최근 완료봉 종가 · 실제 연구 진입은 다음 봉 시가"),
                          ("stop", "가격 손절 참고", "동일 종목 신호봉 저가 · 갭으로 손실 확대 가능"),
                          ("target", "1R 목표 참고", "동일 진입가-손절거리 · 주문가/수익 보장 아님"))])
        render_evidence(st, saved["report"], current, profile, key)
