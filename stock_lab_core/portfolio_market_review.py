"""Read-only bridge from collected report evidence to holding commentary.

No prices, scores, gates or orders are calculated here. Collection is explicit;
selecting another holding only joins the completed, account-scoped snapshot.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pandas as pd

from stock_lab_core.earnings_discovery import canonical_ticker
from stock_lab_core.earnings_pipeline import build_earnings_pipeline
from stock_lab_core.earnings_reconciliation import METRIC_LABELS
from stock_lab_core.portfolio import portfolio_flow_ticker_key
from stock_lab_core.report_evidence import curate_news, number, records, safe_link, stamp, text
from stock_lab_core.report_holdings import UNDERLYINGS

EVIDENCE_KEY = "_portfolio_market_evidence_v1"
MAX_AGE = timedelta(minutes=30)  # Display freshness, not an investment threshold.
_FIELDS = ("sessions", "prices", "intraday_prices", "extended_prices", "closed_flow_rows",
           "quote_checked_at", "market_states", "missing")


def capture_market_review(state, scope, context, summary_rows=()):
    checked = stamp(context.get("quote_checked_at"))
    if not scope or checked is None or not context.get("sessions"):
        return False
    completed = stamp(datetime.now(timezone.utc).isoformat())
    packet = {key: deepcopy(context.get(key)) for key in _FIELDS}
    # IR collection may finish after quote collection; keep both clocks intact.
    packet["captured_at"] = completed.isoformat()
    packet["earnings"] = build_earnings_pipeline(context, summary_rows, now=completed)["packets"]
    packet["news"] = curate_news([r for key in ("current_session_news", "session_news")
                                  for r in records(context.get(key))], now=completed, limit=120, session_scoped=True)
    state[EVIDENCE_KEY] = {"scope": deepcopy(scope), "data": packet}
    state.pop(EVIDENCE_KEY + "_error", None)
    return True


def select_market_review(state, scope, *, now=None):
    saved = state.get(EVIDENCE_KEY) or {}
    if not scope or saved.get("scope") != scope:
        return {}, "현재 계좌 조건의 시황 근거 미연결"
    data = saved.get("data") or {}
    checked = stamp(data.get("quote_checked_at"))
    now = stamp(now or datetime.now(timezone.utc).isoformat())
    if checked is None or now is None or not timedelta(0) <= now - checked <= MAX_AGE:
        return {}, "시황 근거 재조회 필요 · 수집 후 30분 경과 또는 시각 미확인"
    return data, "수집 " + checked.strftime("%m/%d %H:%M KST")


def _market(ticker):
    return "KR" if ticker.endswith((".KS", ".KQ")) else "US"


def _percent(value, scale=1):
    value = number(value)
    return f"{value * scale:+.2f}%" if value is not None else "미연결"


def _related_issuers(ticker, state, now):
    """Only verified, dated holdings can turn an issuer into ETF evidence."""
    linked = {canonical_ticker(ticker): ("직접 기업", "")}
    snapshot = state.get("etf_constituents_" + ticker) or {}
    observed, as_of = stamp(snapshot.get("observed_at")), stamp(snapshot.get("as_of"))
    url = safe_link(snapshot.get("source_url"))
    if (snapshot.get("status") not in {"ok", "partial"}
            or snapshot.get("holdings_basis") in {"unverified_reference", "provider_reported_unverified", "historical_reference"}
            or not observed or not as_of or not url
            or not timedelta(0) <= now - observed <= timedelta(hours=1)
            or not 0 <= (now.date() - as_of.date()).days <= 7):
        return linked
    for row in records(snapshot.get("rows")):
        if row.get("reviewable") and row.get("kind") == "security":
            key = canonical_ticker(row.get("ticker"))
            if key:
                linked[key] = (f"구성기업 간접 · 구성 {as_of:%Y-%m-%d}", url)
    return linked


def holding_market_review(ticker, data, state, *, now=None):
    """Keep regular close, live quote, price momentum and company releases distinct."""
    now = stamp(now or datetime.now(timezone.utc).isoformat())
    if not data or now is None:
        return {"facts": [], "earnings": [], "news": [], "reading": "최신 연결 근거가 없어 시장 상황에 따른 대응 해석을 보류합니다."}
    ticker = str(ticker).upper()
    bases = UNDERLYINGS.get(portfolio_flow_ticker_key(ticker), ())
    symbols = list(dict.fromkeys([ticker, *bases]))
    facts, changes = [], []
    for symbol in symbols:
        obs = (data.get("prices") or {}).get(symbol) or {}
        date = text(obs.get("date"))
        expected = text((data.get("sessions") or {}).get(_market(symbol)))
        valid = bool(date and expected and date == expected and number(obs.get("return")) is not None)
        relation = "보유 종목" if symbol == ticker else "기초 비교 · ETF 자체 수익률 아님"
        facts.append({"근거": relation, "대상": symbol, "기준": date or "미연결",
                      "관측": _percent(obs.get("return"), 100) if valid else "종가 기준일 미정합/미연결",
                      "출처": text(obs.get("source")) or "출처 미확인"})
        if valid:
            changes.append((symbol, number(obs["return"])))
        for key, label in (("intraday_prices", "정규장 장중"), ("extended_prices", "시간외")):
            live = (data.get(key) or {}).get(symbol) or {}
            at = stamp(live.get("as_of"))
            if number(live.get("return")) is not None and at and timedelta(0) <= now - at <= MAX_AGE:
                facts.append({"근거": relation + " · " + label, "대상": symbol,
                              "기준": text(live.get("as_of") or live.get("date")) or "시각 미확인",
                              "관측": _percent(live.get("return"), 100),
                              "출처": text(live.get("source")) or "출처 미확인"})
    flow_rows = [r for r in records(data.get("closed_flow_rows")) if r.get("Ticker") in symbols]
    readings = []
    for row in flow_rows:
        symbol = row["Ticker"]
        date = text(row.get("기준일"))
        if not date or date != text((data.get("sessions") or {}).get(_market(symbol))):
            continue
        five, medium = number(row.get("5일수익률")), number(row.get("3개월수익률"))
        facts.append({"근거": "가격 기반 흐름 · 실제 순매수 아님", "대상": symbol, "기준": date,
                      "관측": f"5D {_percent(five, 100)} / 3M {_percent(medium, 100)}", "출처": "시황과 동일한 종가 이력"})
        if five is not None and medium is not None:
            if five < 0 < medium:
                readings.append(f"{symbol}은 중기 상승과 최근 5일 약세가 겹칩니다. 중기 성장 가설만으로 단기 손실 위험을 상쇄했다고 보기는 어렵습니다.")
            elif five > 0 > medium:
                readings.append(f"{symbol}의 최근 5일 반등은 중기 약세 안에서의 회복입니다. 반등 자체와 추세 회복 확인을 구분합니다.")
            elif five < 0 and medium < 0:
                readings.append(f"{symbol}은 최근 5일과 중기 가격 흐름이 모두 약합니다. 실적 기대와 별개로 보유위험·기존 축소 조건을 먼저 점검할 근거입니다.")
            elif five > 0 and medium > 0:
                readings.append(f"{symbol}은 최근 5일과 중기 가격 흐름이 모두 양수입니다. 보유 가설을 뒷받침하는 가격 근거이나, 비중 초과나 최종 체크 제한을 해제하는 신호는 아닙니다.")
    if not readings and changes:
        readings.append("연결된 종가 등락은 " + ", ".join(f"{s} {_percent(v, 100)}" for s, v in changes) +
                        "입니다. 단일 거래일 방향만으로 유지·축소를 바꾸지 않고 실적과 기존 관리 조건을 함께 봅니다.")
    linked = _related_issuers(ticker, state, now)
    earnings = []
    seen = set()
    for packet in sorted(data.get("earnings") or [], key=lambda p: text(p.get("date")), reverse=True):
        issuer, day = canonical_ticker(packet.get("ticker")), stamp(packet.get("date"))
        if issuer not in linked or issuer in seen or not day or not 0 <= (now.date() - day.date()).days <= 45:
            continue
        if "예정" in text(packet.get("release_status")):
            continue
        seen.add(issuer)
        relation, holdings_url = linked[issuer]
        for key in ("revenue", "profit", "capex", "free_cash_flow", "guidance", "price_reaction"):
            metric = (packet.get("metrics") or {}).get(key) or {}
            confirmed = (packet.get("official") and not (packet.get("event") or {}).get("result_stale")
                         and (packet.get("stages") or {}).get(key) == "확인")
            earnings.append({"기업": packet.get("name") or issuer, "연결": relation,
                             "발표/기간": f"{packet.get('date')} / {packet.get('fiscal_period') or '기간 미확인'}",
                             "항목": METRIC_LABELS[key],
                             "근거": text(metric.get("text")) if confirmed else "미연결/재확인 필요",
                             "구분": "확인 보류" if not confirmed else "회사 전망 · 실제치 아님" if key == "guidance" else "관측 주가 · 인과 아님" if key == "price_reaction" else "공식 발표",
                             "출처": safe_link(metric.get("source_url")) if confirmed else "",
                             "구성 출처": holdings_url})
        readings.append(f"{packet.get('name') or issuer} 실적은 매출·이익과 CAPEX·FCF·전망을 분리해 봅니다. "
                        "확인되지 않은 항목은 저평가나 회복의 근거로 채우지 않으며, 구성기업 자료는 ETF 전체 실적이나 하락 원인을 뜻하지 않습니다.")
    if not earnings:
        readings.append("해당 기업 또는 검증된 ETF 구성기업의 실적 연결이 없습니다. 실적 호조·저평가를 가정해 보유 지속을 정당화하지 않습니다.")
    from stock_lab_core.report_presentation import sector_related_news
    articles, seen_urls = [], set()
    for symbol in symbols:
        session = text((data.get("sessions") or {}).get(_market(symbol)))
        active = text(((data.get("market_states") or {}).get(_market(symbol)) or {}).get("active_date"))
        related = [article for day in dict.fromkeys([active, session]) if day
                   for article in sector_related_news(symbol, day, data.get("news") or [])]
        for article in related:
            url = safe_link(article.get("link"))
            published = stamp(article.get("published_at") or article.get("published"))
            if not url or url in seen_urls or not published or not now - timedelta(days=3) <= published <= now:
                continue
            seen_urls.add(url)
            articles.append({"대상": symbol, "시장/세션": f"{article.get('market')} / {article.get('session_date')}",
                             "보도 제목 · 주장": article.get("title"), "출처": url,
                             "연결": "시장 공통 배경 · 직접 원인 아님" if article.get("market_context_only") else "업종 보도 · 개별 보유의 원인 미확정"})
    if articles:
        readings.append("연결된 보도 쟁점: " + text(articles[0]["보도 제목 · 주장"]) +
                        ". 이는 기사 주장으로, 보유 종목 등락의 인과관계나 매매 신호로 확정하지 않습니다.")
    return {"facts": facts, "earnings": earnings, "news": articles[:3], "reading": "\n\n".join(readings)}


def render_market_review(st, ticker, scope, *, refresh=None, choices=None):
    if refresh is not None and st.button("시황·실적 근거 갱신", key="portfolio_market_review_refresh"):
        with st.spinner("시황과 동일한 출처를 확인하는 중입니다..."):
            try:
                refresh()
                st.session_state.pop(EVIDENCE_KEY + "_error", None)
            except Exception as exc:
                import logging
                logging.warning("Portfolio evidence refresh failed (%s)", type(exc).__name__)
                st.session_state[EVIDENCE_KEY + "_error"] = type(exc).__name__
    if st.session_state.get(EVIDENCE_KEY + "_error"):
        st.warning("근거 갱신 실패 · 이전 결과를 새 자료로 간주하지 않습니다.")
        return
    data, status = select_market_review(st.session_state, scope)
    st.caption(status)
    if not data:
        st.caption("시황 리포트 생성 또는 근거 갱신 후 연결됩니다. 저장된 매매판정은 변경하지 않습니다.")
        return
    review = holding_market_review(ticker, data, st.session_state)
    st.markdown("**시황·실적과 연결한 해석**")
    for paragraph in review["reading"].split("\n\n"):
        st.markdown(paragraph)
    if isinstance(choices, pd.DataFrame) and not choices.empty:
        st.markdown("**검토할 방향 · 기존 조건 유지**")
        st.dataframe(choices, hide_index=True, width="stretch")
    st.markdown("**연결 근거 · 종가와 장중 구분**")
    st.dataframe(pd.DataFrame(review["facts"]), hide_index=True, width="stretch")
    if review["news"]:
        with st.expander("연결된 보도 · 시장과 기준일", expanded=False):
            st.dataframe(pd.DataFrame(review["news"]), hide_index=True, width="stretch")
    with st.expander("기업 실적 · 실제치와 전망", expanded=False):
        if review["earnings"]:
            st.dataframe(pd.DataFrame(review["earnings"]), hide_index=True, width="stretch")
        else:
            st.caption("실적 근거 미연결. ETF는 정밀관측소에서 확인한 최신 구성자료가 있어야 기업 실적을 연결합니다.")
    st.caption("해석은 관찰용입니다. 축소는 기존 비중·손실 관리 조건, 현금 대기는 신규 투입 제한, 유지는 보유 가설 점검을 뜻하며 서로 같은 매도·매수 명령이 아닙니다.")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
