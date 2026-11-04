"""Portfolio-only thesis review; deliberately independent of scores and gates."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_lab_core.memory_thesis_sources import COMPANIES, fetch_memory_evidence, number
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
STATE_KEY = "_memory_company_thesis_v1"


def _fmt(value, digits=2):
    value = number(value)
    return f"{value:,.{digits}f}" if value is not None else "미확인"


def _ratio(price, denominator):
    price, denominator = number(price), number(denominator)
    return price / denominator if price is not None and price > 0 and denominator is not None and denominator > 0 else None


def build_thesis_tables(evidence):
    """Pure presentation: no new fair-value multiple, price target or trade signal."""
    estimates, cash_rows, interpretations, sources, sensitivity = [], [], [], [], []
    for code, spec in COMPANIES.items():
        pack = evidence.get(code, {})
        forecast, cash = pack.get("consensus", {}), pack.get("cash", {})
        f = forecast if forecast.get("ok") else {}
        c = cash if cash.get("ok") else {}
        per = _ratio(f.get("close"), f.get("eps"))
        pbr = _ratio(f.get("close"), f.get("bps"))
        current_ocf, previous_ocf = number(c.get("ocf_trillion")), number(c.get("prior_ocf_trillion"))
        cash_caution = "영업현금흐름은 직전 분기보다 감소. " if current_ocf is not None and previous_ocf is not None and current_ocf < previous_ocf else ""

        def trillion(key):
            value = number(f.get(key))
            return _fmt(value / 10000 if value is not None else None)

        estimates.append({
            "기업": spec["name"], "종가 기준일": f.get("price_asof", "미확인"),
            "종가(원)": _fmt(f.get("close"), 0), "연간 예상 기간": f.get("estimate_period", "미확인"),
            "예상 매출(조원)": trillion("revenue_100m"), "예상 영업이익(조원)": trillion("operating_profit_100m"),
            "예상 지배순익(조원)": trillion("net_profit_100m"), "예상 EPS(원)": _fmt(f.get("eps")),
            "예상 BPS(원)": _fmt(f.get("bps")), "계산 PER(배)": _fmt(per), "계산 PBR(배)": _fmt(pbr),
        })
        cash_rows.append({
            "기업": spec["name"], "공시 기간": c.get("period", "미확인"),
            "영업현금흐름(조원)": _fmt(c.get("ocf_trillion")),
            "직전 분기 영업현금흐름(조원)": _fmt(c.get("prior_ocf_trillion")),
            "현금 유형자산 취득(조원)": _fmt(c.get("cash_ppe_trillion")),
            "단순 차감 잔액(조원)": _fmt(c.get("cash_surplus_trillion")),
            "회사 정의 FCF": "미확인",
        })
        supported = per is not None and number(c.get("cash_surplus_trillion")) is not None
        interpretations.append({
            "기업": spec["name"],
            "확인된 근거": (f"연간 예상 EPS 기준 PER {per:.2f}배. " if per is not None else "예상 PER 계산 불가. ")
                + (f"영업현금흐름에서 현금 유형자산 취득을 뺀 잔액 {_fmt(c.get('cash_surplus_trillion'))}조원." if c else "현금흐름 자료 미연결."),
            "저평가 가설 검토": "조건부 검토 가능 · 저평가 확정 아님" if supported else "자료 부족 · 판단 보류",
            "반대 근거 / 확인할 것": cash_caution + "메모리 가격·마진 정상화 시 예상 EPS 하향 가능. 예상 실적의 실현 여부와 추가 설비투자·운전자본 부담 확인. 적정 배수·동종 비교·정상화 이익은 미검증.",
        })
        sensitivity.append({"기업": spec["name"], "컨센서스 EPS 유지": _fmt(per),
                            "EPS 20% 감소 가정": _fmt(per / 0.8 if per is not None else None),
                            "EPS 40% 감소 가정": _fmt(per / 0.6 if per is not None else None)})
        for kind, result in (("예상 실적·시세", forecast), ("공식 분기 현금흐름", cash)):
            sources.append({"기업": spec["name"], "자료": kind,
                            "상태": "조회됨" if result.get("ok") else result.get("reason", "미조회"),
                            "조회 시각(UTC)": result.get("fetched_at", "미확인"),
                            "출처": result.get("source_url", ""),
                            "공시 페이지": str(result.get("page", ""))})
    return {"estimates": pd.DataFrame(estimates), "cash": pd.DataFrame(cash_rows),
            "interpretations": pd.DataFrame(interpretations), "sources": pd.DataFrame(sources),
            "sensitivity": pd.DataFrame(sensitivity)}


def render_memory_thesis(st, ticker):
    if ticker not in {"RAM", "0167A0", "005930", "000660"}:
        return
    st.markdown("#### 삼성전자·SK하이닉스 · 저평가 가설")
    if st.button("기업 근거 조회·갱신", key="portfolio_memory_thesis_fetch"):
        with st.spinner("예상 실적과 공식 현금흐름 확인 중"):
            if STATE_KEY in st.session_state:
                for code in COMPANIES:
                    for kind in ("consensus", "cash"):
                        fetch_memory_evidence.clear(code, kind)
            evidence = {code: {kind: fetch_memory_evidence(code, kind) for kind in ("consensus", "cash")}
                        for code in COMPANIES}
            st.session_state[STATE_KEY] = evidence
    evidence = st.session_state.get(STATE_KEY)
    if not evidence:
        return
    tables = build_thesis_tables(evidence)
    failures = tables["sources"][tables["sources"]["상태"].ne("조회됨")]
    if not failures.empty:
        st.warning("자료 미확인: " + " / ".join(f"{row['기업']} {row['자료']} ({row['상태']})" for row in failures.to_dict("records")))
    st.markdown("**예상 실적과 가격**")
    st.dataframe(tables["estimates"].set_index("기업").T.rename_axis("항목").reset_index(), hide_index=True, width="stretch")
    st.caption("FnGuide 연결 연간 컨센서스(E), 확정 실적 아님. PER·PBR은 표시된 종가 ÷ 예상 EPS·BPS이며 향후 12개월 기준이 아닙니다. 개별 추정 기준일은 공급자가 제공하지 않습니다. 실시간 ETF 가격과 시점이 다릅니다.")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    dates = [v.get("consensus", {}).get("price_asof") for v in evidence.values()]
    if any(d and (today - datetime.fromisoformat(d).date()).days > 7 for d in dates):
        st.warning("7일 넘게 지난 종가가 포함되어 있습니다. 현재 저평가 여부로 읽지 마세요.")
    st.markdown("**실제 현금흐름**")
    st.dataframe(tables["cash"].set_index("기업").T.rename_axis("항목").reset_index(), hide_index=True, width="stretch")
    st.caption("공식 2026년 3분기 IR 연결 자료(잠정·정정 가능). 단순 차감 잔액 = 영업현금흐름 − 현금 유형자산 취득. 회사 정의 FCF가 아니며 무형자산·리스 등은 반영하지 않았습니다. 총 CAPEX 계획·현금 보유액과도 다릅니다. 이후 분기는 아직 연결하지 않았습니다.")
    st.markdown("**가설과 반대 근거**")
    st.dataframe(tables["interpretations"], hide_index=True, width="stretch")
    with st.expander("예상 이익이 줄어드는 경우"):
        st.dataframe(tables["sensitivity"], hide_index=True, width="stretch")
        st.caption("표시된 주가 고정 시 PER(배). EPS 20%·40% 감소는 임의 민감도 가정이지 예측·투자 임계값이 아닙니다. 적정주가를 계산한 것이 아닙니다.")
    st.markdown("**기업 전망과 상품 위험은 별개**")
    st.dataframe(pd.DataFrame([
        {"상품": "RAM", "위험": "DRAM 일간 수익률 2배 목표. 일별 재설정·복리 경로·파생상품 비용 위험.",
         "가설과의 차이": "삼성전자·SK하이닉스 저평가만으로 RAM 저평가나 장기 회복을 보장하지 않음. DRAM의 다른 구성기업도 영향."},
        {"상품": "SOL AI반도체TOP2플러스", "위험": "국내 반도체 10종목 집중. 삼성전자·SK하이닉스 외 SK스퀘어·장비 등에도 노출.",
         "가설과의 차이": "두 기업 전망이 맞아도 ETF 전체 성과·매입가격은 다를 수 있음. RAM과 기초 노출이 겹쳐 분산효과 제한."},
    ]), hide_index=True, width="stretch")
    st.caption("기존 후보점수·시장 게이트·보유 축소 조건은 변경하지 않습니다. 매도·추가매수 승인이나 손실 회복 예측이 아닙니다.")
    with st.expander("출처·조회 상태"):
        st.dataframe(tables["sources"], hide_index=True, width="stretch")
        st.markdown("[RAM 운용사 위험 설명](https://www.roundhillinvestments.com/etf/ram/) · [SOL 운용사 구성종목](https://www.soletf.com/ko/fund/etf/211106?tabIndex=3)")
