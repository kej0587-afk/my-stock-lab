"""Shared ETF constituent view; data access is explicit and never saves holdings."""

import logging
import re
import numpy as np
import pandas as pd
from stock_lab_core.formatters import clean_float, is_kr_listed, sanitize_ticker_value


def render_constituent_panel(st, ticker, *, name="", key_prefix="precision", load_catalog=None,
                             navigate=None, archives=None, archive_urls=None):
    """Fetch the selected ETF only; opening a constituent never saves a holding."""
    ticker = sanitize_ticker_value(ticker)
    snapshot_key = f"etf_constituents_{ticker}"
    snapshot = st.session_state.get(snapshot_key)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    if snapshot.get("rows") and snapshot.get("observed_at"):
        try:
            observed = pd.Timestamp(snapshot["observed_at"])
            if observed.tzinfo is not None and (pd.Timestamp.now(tz="UTC") - observed).total_seconds() > 3600:
                snapshot = {**snapshot, "status": "stale",
                            "reason": str(snapshot.get("reason") or "") + "; cached_snapshot_refresh_due"}
        except (ValueError, TypeError, OverflowError):
            pass
    with st.expander(f"ETF 구성종목 · 개별 검토 · {ticker}", expanded=bool(snapshot.get("rows"))):
        fetch_col, source_col = st.columns([1, 2])
        requested = fetch_col.button("구성종목 새로고침" if snapshot else "구성종목 조회",
                                     key=f"{key_prefix}_etf_fetch_{ticker}", icon=":material/refresh:")
        if requested:
            with st.spinner("ETF 구성종목 확인 중..."):
                try:
                    from stock_lab_core.etf_holdings import load_etf_holdings
                    fresh = load_etf_holdings(ticker, kr_catalog=load_catalog() if load_catalog and is_kr_listed(ticker) else None,
                                             force_refresh=bool(snapshot))
                    if not isinstance(fresh, dict):
                        raise ValueError("Invalid holdings snapshot")
                    archive = (archives or {}).get(ticker)
                    if not fresh.get("rows") and archive:
                        fresh = {**fresh, "status": "stale", "source": archive["source"] + " · 과거 확인 자료",
                                 "source_url": (archive_urls or {}).get(ticker),
                                 "as_of": archive["as_of"], "scope": "top5", "holdings_basis": "historical_reference",
                                 "reason": str(fresh.get("reason") or "") + "; historical_top5_not_current",
                                 "rows": [{"name": member, "ticker": symbol, "source_ticker": symbol,
                                           "weight_pct": weight, "kind": "security", "reviewable": True}
                                          for member, symbol, weight in archive["rows"]]}
                    snapshot = fresh
                except Exception as exc:
                    logging.warning("ETF holdings unavailable for %s (%s)", ticker, type(exc).__name__)
                    snapshot = {**snapshot, "status": "stale" if snapshot.get("rows") else "unavailable",
                                "reason": "구성종목 조회 실패: " + type(exc).__name__}
                st.session_state[snapshot_key] = snapshot
        if not snapshot:
            st.caption("구성종목 자료는 선택한 ETF만 조회합니다. 스왑·선물·현금은 개별 주식과 구분합니다.")
            return {"ticker": ticker, "status": "not_requested", "rows": []}
        source_url = str(snapshot.get("source_url") or "")
        if source_url.startswith("https://"):
            source_col.link_button("구성 자료 출처", source_url, icon=":material/open_in_new:")
        st.caption(f"출처: {snapshot.get('source') or '미확인'} · 구성 기준일: {snapshot.get('as_of') or '제공처 미제공'} · 조회시각: {snapshot.get('observed_at') or '미확인'}")
        rows = snapshot.get("rows")
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        reason_labels = {
            "holdings_as_of_unavailable": "구성 기준일 미제공",
            "partial_holdings_scope": "전체가 아닌 일부 구성자료",
            "some_weights_unavailable": "일부 비중 미수집",
            "creation_basket_not_full_economic_exposure": "한국 ETF 설정·환매 바스켓이며 실효 노출 전체와 다를 수 있음",
            "derivative_weights_are_not_daily_exposure": "파생상품 비중은 일일 실효 노출과 다름",
            "foreign_identifiers_retained_without_guessed_mapping": "해외 식별코드 중 검증되지 않은 거래소 코드는 개별 검토에서 제외",
            "yahoo_asset_types_and_holdings_date_unverified": "상위 편입 항목의 자산 종류·기준일 미확인",
            "catalog_has_no_verified_symbols_or_holdings_date": "저장 목록의 종목코드·구성 기준일 미검증",
            "request_timeout": "구성자료 제공처 응답시간 초과", "collection_deadline": "구성자료 조회 제한시간 초과",
            "invalid_or_unavailable_response": "구성자료 응답형식 또는 제공 여부 확인 필요",
            "holdings_date_too_old": "구성 기준일이 오래된 자료", "holdings_date_is_old": "구성 기준일이 오래된 자료", "future_holdings_date": "구성 기준일 오류",
            "cached_snapshot_refresh_due": "마지막 조회 후 1시간 이상 경과한 저장 자료 · 새로고침 필요",
            "historical_top5_not_current": "과거 확인 상위 5개 참고 자료이며 현재 편입·비중이 아님",
            "issuer_csv_date_minus_one": "구성 기준일은 운용사 화면과 동일하게 CSV Date의 전일 표시",
        }
        reasons = [reason.strip() for reason in str(snapshot.get("reason") or "").split(";") if reason.strip()]
        reason_text = " · ".join(dict.fromkeys(reason_labels.get(reason, "제공처 요청 거부(HTTP " + reason[5:] + ")" if reason.startswith("http_") else reason) for reason in reasons))
        if snapshot.get("status") not in {"ok", "success", "available"} and snapshot.get("reason"):
            st.warning(reason_text)
        elif reason_text:
            st.caption(reason_text)
        if not rows:
            st.info("확인 가능한 구성종목 자료가 없습니다. 비중을 0%로 채우거나 임의 종목을 붙이지 않습니다.")
            return snapshot
        kinds = {"equity": "주식", "stock": "주식", "security": "상장 증권", "fund": "펀드/ETF", "etf": "펀드/ETF",
                 "swap": "스왑", "future": "선물", "futures": "선물", "cash": "현금", "bond": "채권",
                 "option": "옵션", "derivative": "파생상품", "unknown": "종류 미확인"}
        display = pd.DataFrame([{"구성종목": row.get("name", ""), "티커": row.get("ticker") or "-", "원문 코드": row.get("source_ticker") or "-",
                                 "비중(%)": clean_float(row.get("weight_pct"), np.nan),
                                 "구분": kinds.get(row.get("kind"), row.get("kind") or "미확인"),
                                 "개별검토": "가능" if row.get("reviewable") and row.get("ticker") else "종목코드/자산종류 확인 필요"} for row in rows])
        st.dataframe(display, width='stretch', hide_index=True, height=min(440, 40 + len(display) * 35),
                     column_config={"비중(%)": st.column_config.NumberColumn("비중(%)", format="%.2f%%")})
        known_weights = pd.to_numeric(display["비중(%)"], errors="coerce").dropna()
        weight_note = f"표시 비중 합 {known_weights.sum():.2f}%" if not known_weights.empty else "비중 미수집"
        scope = {"all_reported": "제공처 보고 항목 전체", "partial": "일부 항목", "top10": "상위 10종목", "top5": "상위 5종목", "none": "미수집"}.get(snapshot.get("scope"), "확인 범위 미제공")
        st.caption(f"조회 범위: {scope} · 표시 {len(rows)}개 · {weight_note}. 표시 자료를 100%로 재환산하지 않습니다.")
        st.caption("레버리지 ETF의 스왑·담보 비중은 기초종목의 실효 노출 비중과 다릅니다. 구성종목의 높은 재무점수만으로 ETF의 위험 제한을 해제하지 않습니다.")
        reviewable = {f"{row.get('name') or row['ticker']} ({row['ticker']})": row["ticker"]
                      for row in rows if row.get("reviewable") and row.get("ticker")}
        if reviewable:
            select_key = f"{key_prefix}_etf_member_{ticker}"
            if st.session_state.get(select_key) not in reviewable:
                st.session_state.pop(select_key, None)
            target = st.selectbox("개별 검토 종목", list(reviewable), key=select_key)
            target_ticker = reviewable[target]
            exchange_unknown = not target_ticker.endswith((".KS", ".KQ")) and bool(re.fullmatch(r"[0-9A-Z]{6}", target_ticker) and any(c.isdigit() for c in target_ticker))
            if exchange_unknown:
                market = st.selectbox("구성종목 상장시장", ["시장 선택", "KOSPI (.KS)", "KOSDAQ (.KQ)"],
                                      key=f"{key_prefix}_etf_market_{ticker}_{target_ticker}")
                target_ticker = target_ticker + (".KS" if market == "KOSPI (.KS)" else ".KQ") if market != "시장 선택" else ""
            if st.button("정밀관측소 열기", key=f"{key_prefix}_etf_open_{ticker}", icon=":material/query_stats:", disabled=not target_ticker):
                if navigate and navigate(ticker, name or ticker, target_ticker):
                    st.rerun()
        return snapshot


def render_exposure_review(st, ticker, *, name="", key_prefix="precision", **dependencies):
    """Same composition snapshot in portfolio, precision and money-flow views."""
    from stock_lab_core.etf_issuer_evidence import UNDERLYING_FUNDS
    ticker = sanitize_ticker_value(ticker)
    snapshot = render_constituent_panel(st, ticker, name=name, key_prefix=key_prefix, **dependencies)
    underlying = UNDERLYING_FUNDS.get(ticker)
    if underlying:
        st.caption(f"{ticker} 직접 보유: 스왑·담보 등 / {underlying}: 기초 ETF 구성기업. 아래 비중은 {ticker}의 직접 보유비중이나 2배 환산 비중이 아닙니다.")
        render_constituent_panel(st, underlying, name=f"기초 ETF {underlying}",
                                 key_prefix=key_prefix + "_underlying", **dependencies)
    # No automatic issuer fan-out when a tab or a holding changes.
    render_constituent_earnings(st, ticker, key_prefix)
    return snapshot


def render_constituent_earnings(st, ticker, key_prefix):
    from datetime import datetime, timezone
    from stock_lab_core.etf_issuer_evidence import related_issuers, collect_issuer_earnings
    from stock_lab_core.report_evidence import stamp
    from stock_lab_core.earnings_discovery import canonical_ticker
    now = stamp(datetime.now(timezone.utc).isoformat())
    linked = related_issuers(ticker, st.session_state, now)
    linked.pop(canonical_ticker(ticker), None)
    if not linked:
        return
    with st.expander("구성기업 실적 · 선택 조회", expanded=False):
        names = {}
        for key, snapshot in st.session_state.items():
            if key.startswith("etf_constituents_") and isinstance(snapshot, dict):
                names.update({canonical_ticker(r.get("ticker")): r.get("name") for r in snapshot.get("rows", []) if r.get("ticker")})
        labels = {f"{names.get(t) or t} ({t})": t for t in linked}
        select_key = f"{key_prefix}_issuer_{ticker}"
        if st.session_state.get(select_key) not in labels:
            st.session_state.pop(select_key, None)
        choice = st.selectbox("실적 확인 기업", list(labels), key=select_key)
        issuer = labels[choice]
        st.caption(linked[issuer][0] + " · ETF 전체 실적이나 수익 기여율은 아닙니다.")
        cache_key = "etf_issuer_earnings_" + issuer
        if st.button("선택 기업 실적 조회", key=f"{key_prefix}_issuer_fetch_{ticker}", icon=":material/refresh:"):
            with st.spinner("선택 기업 공식 실적 확인 중..."):
                try:
                    st.session_state[cache_key] = collect_issuer_earnings(issuer, names.get(issuer))
                except Exception as exc:
                    logging.warning("Constituent earnings failed (%s)", type(exc).__name__)
                    st.session_state[cache_key] = {"checked_at": now.isoformat(), "earnings": [],
                        "earnings_missing": [{"ticker": issuer, "name": names.get(issuer) or issuer,
                                              "reason": "공식 실적 조회 실패: " + type(exc).__name__}]}
        extra = st.session_state.get(cache_key)
        if not extra:
            st.caption("아직 조회하지 않았습니다. 지원하지 않는 기업이나 만료된 공식 자료는 미연결 사유를 표시합니다.")
            return
        from stock_lab_core.portfolio_market_review import holding_market_review
        from stock_lab_core.etf_issuer_evidence import merge_issuer_evidence
        now = stamp(datetime.now(timezone.utc).isoformat())
        data = merge_issuer_evidence({}, {issuer: linked[issuer]}, st.session_state, now)
        view = holding_market_review(issuer, data, st.session_state, now=now)
        st.caption("실적 조회시각: " + str(extra.get("checked_at", "미확인")))
        if view["earnings"]:
            st.dataframe(pd.DataFrame(view["earnings"]), hide_index=True, width="stretch")
        else:
            for reason in data.get("earnings_missing", []):
                st.info(f"{reason.get('name') or issuer}: {reason.get('reason')}")
            if not data.get("earnings_missing"):
                st.info("최근 공식 실적 미연결 또는 조회 후 30분 경과 · 재조회 필요")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)

