"""Read-only holding choices: keep business theses separate from execution gates."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import math

import pandas as pd

from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.portfolio_signal_cache import select_portfolio_signals


PRECISION_KEY = "_portfolio_precision_reviews"


def text(value, default="미확인"):
    if value is None or not pd.api.types.is_scalar(value) or pd.isna(value):
        return default
    value = str(value).strip()
    return value if value and value.lower() not in {"nan", "none", "null"} else default


def display_time(value):
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    return stamp.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M KST") if pd.notna(stamp) else "미확인"


def capture_precision_review(state, context, ticker, decision, final_check, *, valuation=None, captured_at=None):
    """Store only completed, scoped evidence; never persist account data externally."""
    key = portfolio_flow_ticker_key(ticker)
    if not context or not key or not isinstance(decision, Mapping) or not isinstance(final_check, Mapping):
        return
    cache = state.get(PRECISION_KEY)
    reviews = dict(cache.get("reviews", {})) if isinstance(cache, dict) and cache.get("context") == context else {}
    reviews[key] = deepcopy({
        "basis": decision.get("input_basis", {}),
        "workflow": decision.get("execution_workflow", {}),
        "final": final_check,
        "stop": decision.get("rr_stop"),
        "stop_source": decision.get("rr_stop_source"),
        "valuation": valuation if isinstance(valuation, Mapping) else {},
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
    })
    state[PRECISION_KEY] = {"context": context, "reviews": reviews}


def build_holding_review(holdings, signals, precision_cache, context):
    if not isinstance(holdings, pd.DataFrame) or holdings.empty:
        return pd.DataFrame(), {}
    signal_map = {
        portfolio_flow_ticker_key(row.get("티커")): row
        for row in signals.to_dict("records")
    } if isinstance(signals, pd.DataFrame) else {}
    cache = precision_cache if isinstance(precision_cache, dict) else {}
    precision = cache.get("reviews", {}) if cache.get("context") == context else {}
    rows, details = [], {}
    for holding in holdings.to_dict("records"):
        ticker = text(holding.get("티커"), "")
        key = portfolio_flow_ticker_key(ticker)
        if not key or key in details:
            continue
        qty = pd.to_numeric(holding.get("보유량"), errors="coerce")
        if not pd.notna(qty) or qty <= 0:
            continue
        signal = signal_map.get(key, {})
        review = precision.get(key, {})
        basis = review.get("basis") or {}
        ready = build_execution_readiness(review.get("workflow"), review.get("final"))
        name = text(holding.get("자산명"), ticker)
        row = {
            "종목": name, "티커": ticker,
            "개별 신호": text(signal.get("기술적타점")),
            "점검 게이트": text(signal.get("게이트상태")),
            "정밀 최종 체크": ready["label"] if review else "미점검",
            "점검 기준일": text(signal.get("가격자료기준일")),
            "정밀 기준일": text(basis.get("가격자료기준일")),
        }
        rows.append(row)
        details[key] = {"holding": holding, "signal": signal, "precision": review, "ready": ready}
    return pd.DataFrame(rows), details


def holding_choice_rows(detail, management=None):
    signal, precision = detail["signal"], detail["precision"]
    management = management if isinstance(management, Mapping) else {}
    stop = pd.to_numeric(precision.get("stop"), errors="coerce")
    stop_text = f"{stop:,.2f} ({text(precision.get('stop_source'))})" if pd.notna(stop) and math.isfinite(stop) and stop > 0 else "차트 기준선 미확인"
    valuation = precision.get("valuation") or {}
    interpretation = valuation.get("interpretation") or {}
    valuation_text = text(interpretation.get("headline"), text(valuation.get("status"), "밸류 미점검"))
    return pd.DataFrame([
        {"검토 방향": "보유 유지", "현재 근거": text(management.get("판정"), "기존 보유관리 계산 전") + " · " + valuation_text,
         "확인할 조건": "성장 전망과 현재 가격의 저평가 여부는 별도 검증. 이익 전망·FCF·밸류 근거가 없으면 판단 보류."},
        {"검토 방향": "축소 / 손절 검토", "현재 근거": text(management.get("근거")),
         "확인할 조건": f"기존 관리 조건: {text(management.get('재개/해제 조건'))}. 차트 계산선: {stop_text}. 개인 손실한도·청산 시점은 별도 결정."},
        {"검토 방향": "현금 대기", "현재 근거": text(signal.get("시장실행상태")),
         "확인할 조건": text(signal.get("게이트근거"), "시장·종목 게이트 미연결. 대기 해제 판단 불가.")},
        {"검토 방향": "대체 노출 / 후보 비교", "현재 근거": "기존 기업 전망과 상품 구조를 따로 비교",
         "확인할 조건": "비레버리지·분산 노출의 비용과 집중도를 비교. 오늘점검 후보도 해당 종목 정밀 최종 체크 전에는 교체 승인 아님."},
    ])


def render_portfolio_holding_review(st, holdings, *, context, management=None, metrics=None, refresh_evidence=None):
    signals = select_portfolio_signals(st.session_state, context, detailed=True)
    overview, details = build_holding_review(holdings, signals, st.session_state.get(PRECISION_KEY), context)
    if overview.empty:
        return
    from stock_lab_core.portfolio_commentary import portfolio_commentary, render_holding_commentary
    st.markdown("#### 내 포트폴리오 · 대응 해설")
    if metrics is not None:
        for paragraph in portfolio_commentary(metrics, details, management):
            st.markdown(paragraph)
    st.caption("저장된 점검의 비교입니다. 신규매수 제한은 보유 매도 명령이 아니며, 성장 전망만으로 레버리지 보유를 승인하지 않습니다.")
    with st.expander("보유 종목 판정·기준일 비교", expanded=False):
        st.dataframe(overview, hide_index=True, width="stretch")
    options = overview["티커"].tolist()
    names = dict(zip(options, overview["종목"]))
    ticker = st.selectbox("보유 종목 근거", options, format_func=lambda value: f"{names[value]} ({value})", key="portfolio_holding_review_ticker")
    detail = details[portfolio_flow_ticker_key(ticker)]
    signal, precision = detail["signal"], detail["precision"]
    st.caption(f"{text(signal.get('연결출처'))} 저장: {display_time(signal.get('저장시각'))} · 정밀 계산: {display_time(precision.get('captured_at'))}. 저장시각은 시세 제공시각이 아닙니다.")
    st.warning("현재 시세로 재검증한 통합 매매판정이 아닙니다. 계산시각·가격 기준이 다르거나 미확인이면 오늘점검과 정밀관측소를 다시 확인하세요.")
    action = {}
    if isinstance(management, pd.DataFrame) and "티커" in management:
        matched = management[management["티커"].map(portfolio_flow_ticker_key).eq(portfolio_flow_ticker_key(ticker))]
        if not matched.empty:
            action = matched.iloc[0].to_dict()
    from stock_lab_core.portfolio_market_review import render_market_review
    choices = holding_choice_rows(detail, action)
    render_market_review(st, ticker, context, refresh=refresh_evidence, choices=choices)
    with st.expander("저장 판정 · 기존 관리 조건", expanded=False):
        render_holding_commentary(st, detail, action, choices)
    if precision:
        st.caption(f"정밀 가격 입력: {text((precision.get('basis') or {}).get('가격반영'))}")
        st.caption(f"정밀 실행 제한: {detail['ready']['reason']} · 차트 계산선은 개인적으로 정한 손절가격과 다를 수 있습니다.")
        valuation = precision.get("valuation") or {}
        if valuation.get("status") == "ETF 별도판단":
            st.caption("ETF 밸류로 구성 기업의 저평가를 확인한 것은 아닙니다. 삼성전자·SK하이닉스 등 기업별 실적·전망·가격매력 점검이 별도로 필요합니다.")
    if portfolio_flow_ticker_key(ticker) == "RAM":
        st.markdown("[RAM 운용사: 일간 배수·복리·상품 위험](https://www.roundhillinvestments.com/etf/ram/)")
    elif portfolio_flow_ticker_key(ticker) == "0167A0":
        st.markdown("[SOL 운용사: 상품·구성종목](https://www.soletf.com/ko/fund/etf/211106?tabIndex=3)")
    if portfolio_flow_ticker_key(ticker) in {"RAM", "0167A0", "005930", "000660"}:
        if st.checkbox("기업별 실적·밸류 보조자료", key="portfolio_company_evidence_visible"):
            from stock_lab_core.memory_thesis import render_memory_thesis
            render_memory_thesis(st, portfolio_flow_ticker_key(ticker))


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
