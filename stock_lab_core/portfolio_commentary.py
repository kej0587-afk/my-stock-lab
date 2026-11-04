"""Explain existing, account-scoped portfolio evidence without new trade rules."""

import math

import pandas as pd

from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def _text(value, default="미확인"):
    if value is None or not pd.api.types.is_scalar(value) or pd.isna(value):
        return default
    result = str(value).strip()
    return result if result and result.lower() not in {"nan", "none", "null", "-"} else default


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def portfolio_commentary(metrics, details, management):
    metrics = metrics if isinstance(metrics, dict) else {}
    sentences = []
    top3 = _number(metrics.get("top3_weight"))
    leverage = metrics.get("leverage_summary") or {}
    principal = _number(leverage.get("leveraged_principal_pct"))
    effective = _number(leverage.get("effective_exposure_pct"))
    if top3 is not None:
        sentences.append(f"상위 3개 자산이 전체의 {top3:.1f}%입니다. 종목 수보다 같은 산업·기초자산에 겹쳐 투자했는지를 먼저 볼 필요가 있습니다.")
    if principal is not None and principal > 0:
        exposure = f" 단순 배수 환산노출은 {effective:.1f}%입니다(다른 보유자산 제외, 실제 손실 예측 아님)." if effective is not None else ""
        sentences.append(f"레버리지 상품 원금비중은 {principal:.1f}%입니다.{exposure} 기업 성장 가설이 맞아도 변동성과 보유 경로 때문에 상품 손익은 다르게 움직일 수 있습니다.")
    strategy = metrics.get("strategy_df")
    groups = {}
    if isinstance(strategy, pd.DataFrame):
        for row in strategy.to_dict("records"):
            detail = details.get(portfolio_flow_ticker_key(row.get("티커")), {})
            signal = detail.get("signal", {})
            group = _text(signal.get("돈흐름_후보군"), "")
            weight = _number(row.get("현재비중", row.get("전체비중")))
            if group and group not in {"미연결", "미확인"} and weight is not None and weight > 0:
                groups[group] = groups.get(group, 0.0) + weight
    if groups:
        group, weight = max(groups.items(), key=lambda pair: pair[1])
        sentences.append(f"저장된 돈흐름 연결에서 가장 큰 축은 '{group}'으로 묶인 보유자산 {weight:.1f}%입니다. 이 축의 전망이 바뀌면 여러 상품이 같이 영향을 받을 수 있습니다. ETF 구성종목을 풀어 계산한 실효 업종비중은 아닙니다.")
    if not sentences:
        sentences.append("비중·위험 계산이 연결되지 않아 포트폴리오의 집중도나 위험 수준을 단정하지 않습니다.")

    connected = [d for d in details.values() if d.get("signal")]
    dated = [d for d in connected if _text(d["signal"].get("가격자료기준일"), "")]
    sentences.append(f"보유 {len(details)}종목 중 계좌 조건이 맞는 저장 점검은 {len(connected)}종목, 가격 기준일이 있는 점검은 {len(dated)}종목입니다. 저장 결과는 현재 장중 상황과 다를 수 있습니다.")
    if isinstance(management, pd.DataFrame) and not management.empty and "티커" in management:
        rows = management[management["티커"].map(portfolio_flow_ticker_key).isin(details)].copy()
        if "우선" in rows:
            rows = rows.sort_values("우선", kind="stable")
        if not rows.empty:
            row = rows.iloc[0]
            sentences.append(f"기존 보유관리의 우선 점검 대상은 {_text(row.get('자산'), _text(row.get('티커')))}입니다. '{_text(row.get('판정'))}'의 근거인 {_text(row.get('근거'))}부터 확인하세요. 신규매수 제한과 보유 매도 결정은 구분합니다.")
    return sentences


def holding_commentary(detail, management):
    holding, signal = detail.get("holding", {}), detail.get("signal", {})
    precision = detail.get("precision", {})
    management = management if isinstance(management, dict) else {}
    ticker = portfolio_flow_ticker_key(holding.get("티커", ""))
    name = _text(holding.get("자산명"), ticker)
    decision = _text(management.get("판정"))
    reason = _text(management.get("근거"))
    condition = _text(management.get("재개/해제 조건"))
    gate = _text(signal.get("게이트상태"))
    date = _text(signal.get("가격자료기준일"))
    flow = _text(signal.get("돈흐름_판정"))
    context = _text(signal.get("돈흐름_시장맥락"), "")
    market = _text(signal.get("시장실행상태"))
    basis = precision.get("basis") or {}
    precision_date = _text(basis.get("가격자료기준일"))

    facts = f"{name}의 기존 보유관리 판정은 '{decision}'입니다. 근거는 {reason}입니다."
    if signal:
        facts += f" 저장 점검({date})의 시장 실행 상태는 '{market}', 종목 게이트는 '{gate}', 돈흐름 판정은 '{flow}'입니다."
        if context:
            facts += f" 연결된 시장 맥락: {context}"
    else:
        facts += " 계좌 조건이 맞는 오늘점검 근거가 없어 현재 시황에 맞춘 대응은 보류합니다."

    if decision in {"축소/교체 검토", "위성/집중 축소 검토", "비중초과 관리"}:
        interpretation = "산업이 성장하지 않는다는 판정이 아니라 현재 보유위험을 조절할 필요가 있다는 해석입니다. 성장 전망만으로 기존 비중·추세 관리 조건을 무시하기보다, 노출을 줄이거나 같은 투자 가설을 더 낮은 위험으로 유지할 방법을 비교하는 쪽이 맞습니다."
    elif "유지" in decision:
        interpretation = "기존 보유관리는 전량 교체보다 보유와 비중 관리를 구분하고 있습니다. 다만 보유 유지가 신규매수 승인이나 손실 회복 보장은 아닙니다."
    elif decision != "미확인":
        interpretation = "손실률이나 장기 성장 기대 하나로 결론내리기보다 기존 대기·재개 조건이 실제로 충족되는지를 확인할 단계입니다. 목표비중 미달만으로 부족분을 채우는 판단과는 다릅니다."
    else:
        interpretation = "보유관리 근거가 없어 유지·축소 중 어느 쪽이 적합한지 단정할 수 없습니다."

    if ticker == "RAM":
        interpretation += " RAM은 삼성전자·SK하이닉스·마이크론 등 메모리 기업에 노출되는 DRAM의 일간 2배 목표 상품입니다. 메모리 전망을 유지하는 것과 RAM의 레버리지 비중을 유지하는 것은 다른 결정입니다."
    elif ticker == "0167A0":
        interpretation += " SOL TOP2는 두 기업을 포함한 국내 반도체 10종목에 노출됩니다. RAM과 함께 보유하면 계좌가 달라도 메모리·반도체 경기 위험은 겹칠 수 있습니다."

    if not signal or date == "미확인":
        next_step = "시장·종목의 기준일과 실행 제한을 먼저 갱신하세요. 현재 자료로 추가매수·교체 시점을 제시하지 않습니다."
    elif gate != "실행가능":
        next_step = f"저장 점검의 실행 제한 근거: {_text(signal.get('게이트근거'))}. 새로운 비중 확대는 이 제한과 정밀 최종 체크를 다시 확인한 뒤 검토합니다. 매도 시점은 이 게이트만으로 결정하지 않습니다."
    else:
        next_step = "오늘점검의 실행가능은 후보 확인 단계입니다. 최신 정밀 최종 체크·보유 비중·현금까지 맞기 전에는 추가매수나 교체를 승인한 것으로 읽지 않습니다."
    if precision:
        next_step += f" 저장된 정밀 최종 체크: {_text((precision.get('final') or {}).get('final_label'))} ({precision_date})."
        if precision_date != date or date == "미확인":
            next_step += " 점검 간 가격 기준이 다르거나 미확인이므로 하나의 최신 판정으로 합치지 않습니다."

    next_step += f" 기존 보유관리의 재개 조건은 '{condition}'입니다."
    return {"facts": facts, "interpretation": interpretation, "next_step": next_step}


def render_holding_commentary(st, detail, management, choices):
    report = holding_commentary(detail, management)
    st.markdown("**내 보유를 어떻게 볼까**")
    st.markdown(report["facts"])
    st.markdown(report["interpretation"])
    st.markdown("**대응을 바꾸기 전에**")
    st.markdown(report["next_step"])
    with st.expander("판단의 근거와 선택지", expanded=False):
        st.dataframe(choices, hide_index=True, width="stretch")
