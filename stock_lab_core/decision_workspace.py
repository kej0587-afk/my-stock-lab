"""Shared judgment/scenario views using already captured account-scoped results."""

from collections.abc import Mapping

import pandas as pd

from stock_lab_core.decision_brief import build_decision_brief, compare_decision_briefs, text
from stock_lab_core.formatters import escape_html_value, format_zoned_timestamp
from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.portfolio_holding_review import PRECISION_KEY
from stock_lab_core.portfolio_signal_cache import SIGNAL_SOURCES


def _saved_choice(st, control, label, options, *, key, context=None, **kwargs):
    # Streamlit deletes widget keys on navigation; keep selection outside widgets.
    memory = dict(st.session_state.get("_decision_choice_memory", {}))
    saved = memory.get(key, {})
    value = st.session_state.get(key, saved.get("value"))
    if saved.get("context") != context or value not in options:
        value = options[0]
    st.session_state[key] = value
    selected = control(label, options, key=key, **kwargs)
    memory[key] = {"value": selected, "context": context}
    st.session_state["_decision_choice_memory"] = memory
    return selected


def collect_decision_briefs(state, context):
    """Only scoped, timestamped captures; retain each source separately."""
    if not context:
        return []
    result = []
    for key, source in SIGNAL_SOURCES.items():
        frame = state.get(key)
        if not isinstance(frame, pd.DataFrame) or frame.empty or "티커" not in frame:
            continue
        at = frame.attrs.get("portfolio_signal_at")
        if frame.attrs.get("portfolio_signal_context") != context or pd.isna(pd.to_datetime(at, utc=True, errors="coerce")):
            continue
        # Duplicate source rows are ambiguous, not permission to select one.
        keys = frame["티커"].map(portfolio_flow_ticker_key)
        for row in frame.loc[keys.ne("") & ~keys.duplicated(keep=False)].to_dict("records"):
            result.append(build_decision_brief(row, source=source, calculated_at=at))
    cache = state.get(PRECISION_KEY)
    if isinstance(cache, Mapping) and cache.get("context") == context:
        reviews = cache.get("reviews")
        for key, review in (reviews.items() if isinstance(reviews, Mapping) else ()):
            if not isinstance(review, Mapping):
                continue
            at, row = review.get("captured_at"), review.get("workflow")
            if not isinstance(row, Mapping) or pd.isna(pd.to_datetime(at, utc=True, errors="coerce")):
                continue
            if not key or portfolio_flow_ticker_key(row.get("티커")) != key:
                continue
            final = review.get("final")
            if isinstance(final, Mapping) and "summary" in final:
                final = final["summary"]
            result.append(build_decision_brief(row, source="정밀관측소", calculated_at=at, final_check=final))
    return result


def _table(st, rows, headings):
    escape = escape_html_value
    header = "".join(f"<th scope='col'>{escape(col)}</th>" for col in headings)
    body = "".join("<tr>" + "".join("<td>" + escape(text(row.get(col))).replace("\n", "<br>") + "</td>" for col in headings) + "</tr>" for row in rows)
    st.markdown(
        "<div class='decision-brief-table'><style>"
        ".decision-brief-table table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:14px;}"
        ".decision-brief-table th,.decision-brief-table td{padding:8px;text-align:left;vertical-align:top;"
        "overflow-wrap:anywhere;border-bottom:1px solid #64748b44;line-height:1.5;}"
        ".decision-brief-table th:first-child{width:24%;}"
        "</style><table><thead><tr>" + header + "</tr></thead><tbody>" + body + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def render_decision_brief(st, brief, *, expanded=False):
    with st.expander("판단 근거 · 조건별 대응", expanded=expanded):
        # HTML escaping also keeps currency dollars out of Markdown math.
        escape = escape_html_value
        st.markdown(f"<p><b>{escape(brief['name'])} ({escape(brief['ticker'])})</b><br>"
                    f"기존 판정: {escape(brief['decision'])}<br>"
                    f"현재 실행: {escape(brief['ready']['label'])} · {escape(text(brief['ready']['reason']))}</p>",
                    unsafe_allow_html=True)
        st.caption(f"{brief['source']} · 계산 {format_zoned_timestamp(brief['calculated_at'])} · 가격 기준일 {brief['basis']} · {brief['price_basis']}")
        _table(st, [{"판단 축": row["단계"], "상태·근거": row["상태"] + "\n" + row["근거"] + "\n" + row["확인"]}
                    for row in brief["layers"]], ("판단 축", "상태·근거"))
        st.markdown("**조건별 대응**")
        st.caption("가정 시나리오 · 발생 여부·승률 미판정 · 기존 신규매수 제한은 보유분 전량매도 명령이 아닙니다.")
        for row in brief["scenarios"]:
            st.markdown(f"<p><b>{escape(row['상황'])}</b><br>{escape(row['조건'])}<br>"
                        f"<b>{escape(row['대응'])}</b><br><small>{escape(row['재확인'])}</small></p>", unsafe_allow_html=True)
        _table(st, [{"항목": key, "원계획": value} for key, value in brief["plan"].items()], ("항목", "원계획"))
        st.caption("종목 선별 시점의 가격 계획입니다. 정밀관측소의 상세 분할 실행계획과 구분하며, 가격·주수·손익비를 재계산하거나 시장방어를 해제하지 않습니다.")


def render_frame_decision_brief(st, frame, *, source, key):
    if not isinstance(frame, pd.DataFrame) or frame.empty or "티커" not in frame:
        return
    records = [row for row in frame.to_dict("records") if portfolio_flow_ticker_key(row.get("티커"))]
    if not records:
        return
    def holding_first(row):
        weight = pd.to_numeric(row.get("현재비중"), errors="coerce")
        return not (pd.notna(weight) and weight > 0)
    records.sort(key=holding_first)
    tickers = [text(row.get("티커")) for row in records]
    options = list(dict.fromkeys(tickers))
    names = {text(row.get("티커")): text(row.get("종목명"), text(row.get("자산명"), text(row.get("티커")))) for row in records}
    selection = _saved_choice(st, st.selectbox, "판단·대응 종목", options, key=key,
                             context=frame.attrs.get("portfolio_signal_context"),
                             format_func=lambda ticker: f"{names[ticker]} ({ticker})")
    selected = [row for row in records if portfolio_flow_ticker_key(row.get("티커")) == portfolio_flow_ticker_key(selection)]
    if len(selected) != 1:
        st.warning("동일 종목의 계산 결과가 중복되어 공통 요약을 보류합니다.")
        return
    render_decision_brief(st, build_decision_brief(selected[0], source=source,
                          calculated_at=frame.attrs.get("portfolio_signal_at")))


def render_scenario_workspace(st, *, context, open_precision=None):
    briefs = collect_decision_briefs(st.session_state, context)
    if not briefs:
        st.info("현재 계좌 입력과 일치하는 저장 판정이 없습니다. 오늘점검 또는 정밀관측소 계산 후 연결됩니다.")
        return
    options = list(dict.fromkeys(item["ticker"] for item in briefs))
    ticker = _saved_choice(st, st.selectbox, "대응 계획 종목", options,
                           key="scenario_decision_ticker", context=context)
    key = portfolio_flow_ticker_key(ticker)
    candidates = [item for item in briefs if portfolio_flow_ticker_key(item["ticker"]) == key]
    sources = [item["source"] for item in candidates]
    source = _saved_choice(st, st.radio, "판정 출처", sources, key="scenario_decision_source",
                           context=(context, key), horizontal=True)
    selected = next(item for item in candidates if item["source"] == source)
    render_decision_brief(st, selected, expanded=True)
    if len(candidates) > 1:
        with st.expander("화면 간 기준 비교"):
            st.dataframe(pd.DataFrame(compare_decision_briefs(candidates)), hide_index=True, width="stretch")
            st.caption("출처별 독립 계산입니다. 날짜가 같아도 입력 시각·가격·최종 체크가 같다는 뜻은 아닙니다. 다른 출처의 유리한 값만 합치지 않습니다.")
    if open_precision is not None and st.button("선택 종목 차트·최종 체크", icon=":material/candlestick_chart:", key="scenario_open_precision"):
        open_precision(ticker)


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
