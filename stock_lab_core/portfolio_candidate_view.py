"""Display portfolio candidates beside scoped gates; never rescore or allocate."""

import re

import pandas as pd

from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT
from stock_lab_core.formatters import clean_float
from stock_lab_core.portfolio import PORTFOLIO_ADD_ACTIONS, portfolio_flow_ticker_key
from stock_lab_core.report_build import register_loaded_source


DISPLAY_COLUMNS = ["실행 확인", "제한·확인 사유", "연결 게이트", "판정 기준일", "판정 출처", "판정 저장시각"]


def _text(value, default="미연결"):
    if value is None or not pd.api.types.is_scalar(value) or pd.isna(value):
        return default
    result = str(value).strip()
    return result if result and result.lower() not in {"nan", "none"} else default


def _ticker(value):
    value = _text(value, "")
    # A theme's list of representative names is not a single ticker.
    return portfolio_flow_ticker_key(value) if re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^-]{0,24}", value) else ""


def candidate_execution_view(frame, signals, *, ticker_column="티커"):
    """Use already account-scoped rows; preserve all original rows and amounts."""
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    result = frame.copy(deep=True)
    records = signals.to_dict("records") if isinstance(signals, pd.DataFrame) else []
    by_ticker = {}
    for row in records:
        key = _ticker(row.get("티커"))
        if key:
            by_ticker.setdefault(key, []).append(row)
    display = []
    for value in result.get(ticker_column, pd.Series("", index=result.index)):
        matches = by_ticker.get(_ticker(value), [])
        row = matches[0] if len(matches) == 1 else {}
        gate = _text(row.get("게이트상태"))
        date = _text(row.get("가격자료기준일"))
        reason = _text(row.get("게이트근거"), "제한 근거 미연결")
        if gate == GATE_EXECUTABLE:
            status = "정밀 최종 확인"
            reason = "후보 게이트 통과 · 정밀 최종 체크·비중·현금 확인 필요"
            if pd.isna(pd.to_datetime(date, errors="coerce")):
                status, reason = "기준일 확인", "가격 기준일 미확인 · 실행 여부 재확인 필요"
        elif gate == GATE_DEFENSE:
            status = "추가매수 보류"
        elif gate == GATE_WAIT:
            status = "대기/관찰"
        elif gate == GATE_DATA_CHECK:
            status = "데이터 확인"
        else:
            status, reason = "게이트 미연결", "같은 계좌 조건의 종목 판정 확인 필요"
            if len(matches) > 1:
                reason = "중복 판정 입력 · 기준일과 출처 재확인 필요"
        display.append([status, reason, gate, date,
                        _text(row.get("연결출처")), _text(row.get("저장시각"))])
    for i, column in enumerate(DISPLAY_COLUMNS):
        result[column] = [values[i] for values in display]
    return result


def alignment_candidate_summary(align_df, signals):
    view = candidate_execution_view(align_df, signals)
    actions = view.get("포트판정", pd.Series("", index=view.index))
    candidates = view.loc[actions.isin(PORTFOLIO_ADD_ACTIONS)]
    counts = candidates["실행 확인"].value_counts() if not candidates.empty else pd.Series(dtype=int)
    return view, {
        "candidates": len(candidates),
        "restricted": int(counts.get("추가매수 보류", 0) + counts.get("대기/관찰", 0)),
        "check": int(counts.get("정밀 최종 확인", 0)),
        "unconfirmed": int(sum(counts.get(k, 0) for k in ("데이터 확인", "기준일 확인", "게이트 미연결"))),
    }


def render_alignment_overview(st, align_df, signals):
    view, counts = alignment_candidate_summary(align_df, signals)
    st.info(
        f"주도축 보강 검토 {counts['candidates']}개 · 추가매수 보류/대기 {counts['restricted']}개 · "
        f"정밀 최종 확인 {counts['check']}개 · 데이터/연결 확인 {counts['unconfirmed']}개"
    )
    st.caption("주도축 분류와 저장된 실행 게이트를 구분합니다. 후보 게이트 통과는 매수 허가가 아니며, 매수 제한은 매도 명령이 아닙니다.")
    if not view.empty:
        cols = ["자산", "실행 확인", "제한·확인 사유", "티커", "포트판정", "판정 기준일", "판정 출처", "판정 저장시각"]
        st.dataframe(view[[c for c in cols if c in view]], width="stretch", hide_index=True)
    return view


def render_recommendation_candidates(st, rec_df, signals):
    if not isinstance(rec_df, pd.DataFrame) or rec_df.empty:
        return
    show = candidate_execution_view(rec_df, signals, ticker_column="티커/대표")
    show["우선점수"] = show["우선점수"].map(lambda v: f"{clean_float(v):.1f}")
    with st.expander("주도축 관찰 후보 · 실행 제한", expanded=True):
        st.caption("기존 후보 순위입니다. 교체 재원은 매도 확정이 아니며, 여러 대표주를 묶은 테마는 개별 종목 게이트를 따로 확인합니다.")
        cols = ["후보", "실행 확인", "제한·확인 사유", "티커/대표", "추천구분", "우선", "우선점수",
                "판정 기준일", "판정 출처", "판정 저장시각"]
        st.dataframe(show[[c for c in cols if c in show]], width="stretch", hide_index=True)
        with st.expander("기존 후보 산출 근거", expanded=False):
            st.dataframe(show.rename(columns={"실행강도": "원래 계획강도", "다음 행동": "원래 검토 조건"}),
                         width="stretch", hide_index=True)


register_loaded_source(__name__, __file__)
