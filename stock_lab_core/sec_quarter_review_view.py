"""On-demand SEC quarter review UI, isolated from scoring and account writes."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)

from stock_lab_core.sec_quarter_review import LABELS, build_sec_quarter_review, quarter_tables, review_questions


PEERS = ("MSFT", "AMZN", "GOOGL", "META", "NVDA", "MU")


def load_quarter_evidence(ticker, *, resolve_cik, fetch_facts, now):
    symbol = str(ticker).strip().upper()
    cik, identity = resolve_cik(symbol)
    aliases = {symbol, symbol.replace(".", "-"), symbol.replace("-", ".")}
    if (not isinstance(identity, dict) or str(identity.get("ticker", "")).upper() not in aliases
            or not re.fullmatch(r"[0-9]{1,10}", str(cik))
            or str(identity.get("cik_str", "")).zfill(10) != str(cik).zfill(10)):
        raise ValueError("identity_unverified")
    cik = str(cik).zfill(10)
    result = build_sec_quarter_review(fetch_facts(cik), expected_cik=cik,
        as_of=now.astimezone(timezone(timedelta(hours=9))).date().isoformat())
    result.update(ticker=symbol, checked_at=now.isoformat(),
                  source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    return result


def _safe_error(error):
    message = str(error)
    if message in {"identity_unverified", "cik_mismatch"}:
        return "선택 종목과 SEC 기업코드 불일치로 표시 보류"
    if "403" in message:
        return "SEC 접근 제한(403) · 연락처 설정/접근 상태 확인"
    if "429" in message or "rate limit" in message:
        return "SEC 요청 제한 · 잠시 후 다시 조회"
    return "SEC 분기 연결 실패 · 이전 조회값을 최신값으로 사용하지 않음"


def render_sec_quarter_evidence(st, *, ticker, owner, configured, resolve_cik, fetch_facts,
                                is_demo=False, now=None):
    prefix = "sec_quarter_review_" + sha256(f"{owner}|{ticker}".encode()).hexdigest()[:20]
    st.caption("매출 → 이익 → 현금 창출 → 현금 투자지출을 최근 8분기로 비교합니다. 검토 근거이며 기존 점수·판정은 유지됩니다.")
    if is_demo or not owner:
        st.info("개인 계정에서 분기 근거를 조회할 수 있습니다.")
        return
    if not configured:
        st.info('Secrets 최상위의 sec_user_agent 설정이 필요합니다. 기존 SEC 연락처 설정을 사용합니다.')
        return
    selected = st.multiselect("비교 기업 (최대 4개)", list(dict.fromkeys([ticker, *PEERS])),
        default=[ticker], max_selections=4, key=prefix + "_symbols",
        help="선택 기업을 버튼을 눌렀을 때만 조회합니다. 회계연도와 분기 종료일은 회사마다 다릅니다.")
    if st.button("최근 8분기 근거 조회·새로고침 (점수 유지)", key=prefix + "_load", disabled=not selected):
        st.session_state.pop(prefix, None)
        results, errors = [], []
        with st.spinner("선택 기업의 SEC 분기 공시 확인 중..."):
            for symbol in selected[:4]:
                try:
                    results.append(load_quarter_evidence(symbol, resolve_cik=resolve_cik,
                        fetch_facts=fetch_facts, now=now or datetime.now(timezone.utc)))
                except Exception as error:
                    errors.append({"종목": symbol, "상태": _safe_error(error)})
        st.session_state[prefix] = {"selected": list(selected), "results": results, "errors": errors}
    bundle = st.session_state.get(prefix)
    if not bundle or bundle["selected"] != list(selected):
        return
    if bundle["errors"]:
        st.dataframe(bundle["errors"], hide_index=True, width="stretch")
    results = bundle["results"]
    if not results:
        return
    st.caption("USD 공시 · 금액 표는 백만 달러. 분기 종료일과 제출일을 구분하세요. 10-K/10-Q 기준으로, 최근 실적발표·가이던스·컨센서스 전체 반영은 미확인입니다.")
    overview = []
    for result in results:
        rows = result["quarter"]
        latest = rows[-1] if rows else {}
        overview.append({"종목": result["ticker"], "최근 분기 종료": latest.get("end", "미수집"),
            "조회 시각": result["checked_at"], "확인 분기": len(rows),
            "분기 연속성": "누락 구간 있음" if result["gaps"] else "표시 기간 연속" if rows else "미확인",
            "최근 분기 누락": ", ".join(LABELS[k] for k in latest.get("missing_fields", [])) or ("없음" if rows else "10-K/10-Q USD 근거 없음")})
    st.dataframe(overview, hide_index=True, width="stretch")
    for result in results:
        st.markdown(f"**{result['ticker']} · 최근 8개 관측 분기**")
        if not result["quarter"]:
            st.info("지원하는 US-GAAP 10-K/10-Q 분기자료가 없습니다. 20-F 외국기업은 별도 연간 근거에서 확인하세요.")
            continue
        for question in review_questions(result):
            st.markdown(f"**{question['검토축']} · 사실:** {question['확인된 사실']}")
            st.markdown(f"다음 확인: {question['다음 확인']}")
        latest = result["quarter"][-1]
        st.caption(f"최근 분기 범위: {latest['start']} ~ {latest['end']} · SEC 공시")
        financial, quality, sources = quarter_tables(result)
        numeric_format = {k: st.column_config.NumberColumn(format="%.1f") for k in financial[0]
                          if k.endswith("(백만$)") or k.endswith("(%)") or k == "FCF(단순차감·백만$)"}
        income_tab, cash_tab = st.tabs(["매출·수익성", "투자·현금흐름"])
        with income_tab:
            income_columns = ("분기 종료", "매출(백만$)", "영업이익(백만$)", "순이익(백만$)", "매출 YoY(%)", "영업이익률(%)")
            st.dataframe([{k: row[k] for k in income_columns} for row in financial], hide_index=True, width="stretch", column_config=numeric_format)
        with cash_tab:
            cash_columns = ("분기 종료", "영업현금흐름(백만$)", "현금 투자지출(백만$)", "FCF(단순차감·백만$)", "현금·현금성자산(백만$)", "투자지출 범위")
            st.dataframe([{k: row[k] for k in cash_columns} for row in financial], hide_index=True, width="stretch", column_config=numeric_format)
        st.caption("FCF(단순차감) = 영업현금흐름 − 현금 투자지출. 투자지출 범위 열에서 유형자산만인지 소프트웨어·무형자산까지 포함하는지 확인하세요. 회사 조정 FCF와 다를 수 있고, 비현금 리스·구매약정·인수대금은 포함하지 않습니다. 빈칸은 0이 아닙니다. 회사별 기간이 달라 동일 달력분기 순위로 해석하지 마세요.")
        with st.expander(f"{result['ticker']} · 누락·누적차감·공시 출처"):
            st.dataframe(quality, hide_index=True, width="stretch")
            st.caption("서로 다른 제출본의 누적 차감은 재작성·사업범위 확인 전 비교 해석을 보류합니다. 후속 재작성값과 이전 제출본의 차감은 표시하지 않습니다.")
            st.dataframe(sources, hide_index=True, width="stretch")
            st.markdown(f"[SEC 공식 원자료]({result['source_url']})")
    st.download_button("8분기 검토 파일 받기", json.dumps(bundle, ensure_ascii=False, indent=2),
        file_name="sec_quarter_review.json", mime="application/json", key=prefix + "_download")
