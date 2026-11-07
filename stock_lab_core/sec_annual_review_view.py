"""Explicit read-only SEC annual evidence panel, isolated from scoring providers."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from stock_lab_core.sec_annual_review import build_sec_20f_annual_review


def load_annual_evidence(ticker, *, resolve_cik, fetch_facts, tags, flow_fields, now):
    symbol = str(ticker).strip().upper()
    cik, identity = resolve_cik(symbol)
    aliases = {symbol, symbol.replace(".", "-"), symbol.replace("-", ".")}
    if (not isinstance(identity, dict) or str(identity.get("ticker", "")).upper() not in aliases
            or not re.fullmatch(r"[0-9]{1,10}", str(cik))):
        raise ValueError("identity_unverified")
    cik = str(cik).zfill(10)
    if str(identity.get("cik_str", "")).zfill(10) != cik:
        raise ValueError("identity_unverified")
    result = build_sec_20f_annual_review(fetch_facts(cik), tags, flow_fields,
        expected_cik=cik, currency="USD", as_of=now.astimezone(timezone(timedelta(hours=9))).date().isoformat())
    result.update(ticker=symbol, checked_at=now.isoformat(),
                  source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    return result


def evidence_tables(result):
    """Use base currency amounts without rounding or synthetic quarterly estimates."""
    income, balance, provenance = [], [], []
    for row in result["annual"][-3:]:
        common = {"기간 시작": row["start"], "기간 종료": row["end"], "통화": row["unit"]}
        income.append({**common, "매출": row.get("revenue"), "영업이익": row.get("op_income"),
                       "순이익(공시 태그 기준)": row.get("net_income"),
                       "영업현금흐름(전체)": row.get("ocf"),
                       "영업현금흐름(계속사업)": row.get("ocf_continuing"),
                       "영업현금흐름(중단사업)": row.get("ocf_discontinued")})
        balance.append({"기준일": row["end"], "통화": row["unit"], "자산": row.get("assets"),
                        "부채": row.get("liabilities"), "자본": row.get("equity"),
                        "현금": row.get("cash"), "미수집 항목": ", ".join(row["missing_fields"]) or "없음",
                        "제출본 혼합": "예" if "mixed_filing_accessions" in row["comparability_flags"] else "아니오"})
        for field, evidence in row["provenance"].items():
            for fact in evidence.get("facts", []):
                provenance.append({"기간 종료": row["end"], "항목": field, "공시 형식": fact["form"],
                    "공시일": fact["filed"], "접수번호": fact["accession"], "XBRL 태그": fact["tag"]})
    return income, balance, provenance


def _safe_error(error):
    # Never display provider response bodies, headers, URLs or contact details.
    message = str(error)
    if message in {"identity_unverified", "cik_mismatch"}:
        return "선택 종목과 SEC 기업코드를 대조하지 못했습니다. 자료 표시를 보류합니다."
    if "403" in message:
        return "SEC 접근 제한(HTTP 403)입니다. 운영 환경의 연락처 설정과 접근 상태를 확인해 주세요."
    if "429" in message or "rate limit" in message:
        return "SEC 요청 제한입니다. 잠시 후 다시 조회해 주세요."
    return "SEC 연간자료 연결을 확인하지 못했습니다. 기존 점수·판정은 유지됩니다."


def render_sec_annual_evidence(st, *, ticker, owner, configured, resolve_cik, fetch_facts,
                               tags, flow_fields, is_demo=False, now=None):
    prefix = "sec_annual_review_" + sha256(f"{owner}|{ticker}".encode()).hexdigest()[:20]
    current = now or datetime.now(timezone.utc)
    st.caption("20-F 외국기업 연간 공시 · USD 원금액 · 검토 전용. 기존 자동 재무점수와 별도로 확인합니다.")
    if is_demo or not owner:
        st.info("개인 계정에서 SEC 연간 근거를 조회할 수 있습니다.")
        return
    if not configured:
        st.info('운영 앱 Secrets의 최상위에 sec_user_agent = "StockLab 실제 연락 이메일" 설정이 필요합니다. 로컬 설정과 별개입니다.')
        return
    if st.button("SEC 연간 근거 조회·새로고침 (점수 유지)", key=prefix + "_load"):
        st.session_state.pop(prefix, None)
        try:
            with st.spinner("SEC 기업 확인·연간 근거 조회 중..."):
                st.session_state[prefix] = load_annual_evidence(ticker, resolve_cik=resolve_cik,
                    fetch_facts=fetch_facts, tags=tags, flow_fields=flow_fields, now=current)
        except Exception as error:
            st.warning(_safe_error(error))
    result = st.session_state.get(prefix)
    if not result:
        return
    st.caption(f"조회 시각: {result['checked_at']} · 선택 종목: {result['ticker']} · CIK: {result['cik']}")
    if not result["annual"]:
        st.info("검토 가능한 US-GAAP 20-F 연간 USD 자료가 없습니다. 10-K/10-Q는 기존 원자료 확인을 이용해 주세요. 분기·IFRS 자료는 이 표에 포함되지 않습니다.")
        return
    st.warning("연간 공시 근거만 조회했습니다. 최신 분기·잠정실적 반영은 미확인입니다. 기존 점수·판정에 자동 반영되지 않습니다.")
    income, balance, provenance = evidence_tables(result)
    st.markdown("**최근 3개년 손익·현금흐름**")
    st.dataframe(income, hide_index=True, width="stretch")
    st.caption("전체 현금흐름과 계속사업 현금흐름은 다를 수 있습니다. 사업 매각·중단 또는 제출본 혼합 시 연도 간 단순 성장 비교를 보류하세요. 빈칸은 0이 아닙니다.")
    st.markdown("**재무상태·자료 누락**")
    st.dataframe(balance, hide_index=True, width="stretch")
    with st.expander("항목별 공시 출처·검토 파일"):
        st.dataframe(provenance, hide_index=True, width="stretch")
        st.markdown(f"[SEC 공식 원자료]({result['source_url']})")
        st.download_button("SEC 연간 검토 파일 받기", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name=f"sec_annual_review_{result['cik']}.json", mime="application/json",
                           key=prefix + "_download")
