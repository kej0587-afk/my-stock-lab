"""One read-only earnings view for coverage, evidence and report commentary."""

from copy import deepcopy
from datetime import timedelta

from stock_lab_core.earnings_discovery import canonical_ticker, discover_earnings_news, issuer_catalog, TOPICS
from stock_lab_core.earnings_reconciliation import METRIC_LABELS, reconcile_earnings
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import records, safe_link, stamp, text

register_loaded_source(__name__, __file__)

_ACTUAL_KEYS = ("revenue", "profit", "capex", "free_cash_flow")


def _metric_state(metric):
    if metric.get("status") in {"reported", "available", "observed_quote"} and text(metric.get("text")):
        return "확인" if metric.get("status") == "observed_quote" or safe_link(metric.get("source_url")) else "출처 미연결"
    if metric.get("status") == "deferred":
        return "콜 대기"
    return "미연결"


def _source_reason(ticker, context):
    rows = [row for key in ("earnings_result_sources", "earnings_sources")
            for row in records(context.get(key)) if canonical_ticker(row.get("ticker")) == ticker]
    failures = [row for row in rows if row.get("status") not in {"connected", "fallback"}]
    if failures:
        reason = text(failures[0].get("reason"))
        if reason.startswith("http_"):
            return "공식 출처 HTTP " + reason[5:]
        if reason.startswith("request_"):
            return "공식 원문 조회 실패·시간초과"
        if reason == "ticker_limit":
            return "수집 한도 밖"
        if reason in {"verified_coverage_unavailable", "announcement_evidence_changed"}:
            return "기존 공지 만료·내용 재확인 필요"
    if ticker in {canonical_ticker(value) for value in (context.get("earnings_collection_scope") or {}).get("not_submitted", [])}:
        return "수집 한도 밖"
    return "해당 기업·분기 공식 수집 미연결"


def _event_packet(event, catalog, context):
    ticker = canonical_ticker(event.get("ticker"))
    entry = catalog[ticker]
    metrics = deepcopy(event.get("result_metrics") or {})
    states = {key: _metric_state(metrics.get(key, {})) for key in METRIC_LABELS}
    official = event.get("result_confirmation") in {"official_result", "official_snapshot"} or event.get("event_status") == "released"
    release = "공식 발표 확인" if official else {
        "reported_results": "실적 보도·공식 미확인", "scheduled": "예정", "elapsed_unconfirmed": "예정일 경과·결과 미확인",
    }.get(event.get("event_status"), "미확인")
    reaction = metrics.get("price_reaction") or {}
    if reaction.get("status") == "reported":
        states["price_reaction"] = "보도 주장·시세 대조 미완료"
    gaps = [METRIC_LABELS[key] + " " + states[key] for key in METRIC_LABELS if states[key] != "확인"]
    if not official:
        gaps.insert(0, _source_reason(ticker, context))
    if event.get("result_stale"):
        gaps.insert(0, "원문 재조회 실패·마지막 확인값 사용")
    return dict(ticker=ticker, name=entry["name"], sector=entry["sector"], market=entry["market"],
        relationship="보유" if entry["held"] else "관심·점검" if entry["registered"] else "시장 대표",
        fiscal_period=event.get("fiscal_period", ""), release_status=release, official=official,
        date=event.get("date", ""), date_basis="공식 발표일" if official else "일정 기준일",
        metrics=metrics, stages=states, gaps=gaps, articles=[], topics=[],
        source_url=event.get("result_source_url") or event.get("source_url", ""),
        consensus_status="발표 당시 예상치 미연결·상회/하회 판단 보류", event=deepcopy(event))


def _commentary(packet):
    """Explain the evidence gap, never invent an earnings surprise or causality."""
    metrics = packet["metrics"]
    topics = [label for key, label, _ in TOPICS if key in packet["topics"]]
    if not packet["official"]:
        return (("보도에서 제기한 쟁점은 " + "·".join(topics) + "입니다. ") if topics else "실적 관련 보도 후보입니다. ") + \
            "아직 공식 분기 자료와 대조되지 않아 결과 확정이나 주가 원인으로 사용하지 않습니다."
    # Source prose can mix current, historical and forecast figures. Preserve it
    # verbatim in the evidence column; never infer the current FCF sign from it.
    if all(_metric_state(metrics.get(key, {})) == "확인" for key in ("capex", "free_cash_flow")):
        reading = "매출·이익과 투자 후 현금 창출력을 별도로 봐야 합니다. 설비투자와 FCF가 연결됐지만 기간·비교값을 구분해야 하며, 이 수치만으로 주가 반응의 원인을 확정하지 않습니다."
    else:
        absent = [METRIC_LABELS[key] for key in ("capex", "free_cash_flow") if _metric_state(metrics.get(key, {})) != "확인"]
        reading = ("공식 실적은 발표됐지만 " + "·".join(absent) + "가 미연결되어 투자 부담·현금 창출력 분석은 불완전합니다."
                   if absent else "공식 실적과 회사 전망을 구분해 확인합니다.")
    if packet["stages"]["guidance"] == "콜 대기":
        reading += " 회사 전망은 콜 확인 대기입니다."
    if packet["stages"]["price_reaction"] == "미연결":
        reading += " 발표 전후 주가 반응도 아직 대조되지 않았습니다."
    return reading


def _select_highlights(packets, now):
    recent = [p for p in packets if (day := stamp(p["date"])) is not None and
              now.date() - timedelta(days=7) <= day.date() <= now.date() and "예정" not in p["release_status"]]
    # Prefer the verified period over an unassigned follow-up about that issuer.
    official_tickers = {p["ticker"] for p in recent if p["official"]}
    recent = [p for p in recent if p["official"] or p["ticker"] not in official_tickers]
    recent.sort(key=lambda p: (p["date"], bool(p["topics"]), p["official"], p["relationship"] == "보유", p["ticker"]), reverse=True)
    picked, sectors, tickers = [], set(), set()
    # Diversity breaks ties among existing evidence; never invent missing sectors.
    for diverse in (True, False):
        for packet in recent:
            if packet["ticker"] in tickers or (diverse and packet["sector"] in sectors):
                continue
            picked.append(packet)
            sectors.add(packet["sector"])
            tickers.add(packet["ticker"])
            if len(picked) == 3:
                return picked
    return picked


def build_earnings_pipeline(context, summary_rows=(), news=(), now=None):
    now = stamp(now)
    if now is None:
        raise ValueError("now is required")
    events = reconcile_earnings(context, now)
    catalog = issuer_catalog(summary_rows, events)
    corpus = [*records(news), *(row for key in ("current_session_news", "session_news", "next_session_news")
                               for row in records(context.get(key)))]
    discovery = discover_earnings_news(corpus, catalog, now)
    packets, by_key = [], {}
    for event in events:
        ticker = canonical_ticker(event.get("ticker"))
        day = stamp(event.get("date"))
        if ticker not in catalog or not event.get("event_status") or not day or not -30 <= (day.date() - now.date()).days <= 45:
            continue
        key = (ticker, event.get("fiscal_period", ""))
        if key in by_key:
            continue
        packet = _event_packet(event, catalog, context)
        packets.append(packet)
        by_key[key] = packet
    discovered_groups = {}
    for item in discovery["items"]:
        # Unknown periods cannot borrow an old official result or surprise.
        packet = by_key.get((item["ticker"], item["fiscal_period"])) if item["fiscal_period"] else None
        if packet is None:
            key = (item["ticker"], item["fiscal_period"], item["published_at"][:10], item["phase"] == "preview")
            if key not in discovered_groups:
                entry = catalog[item["ticker"]]
                discovered_groups[key] = dict(ticker=item["ticker"], name=entry["name"], sector=entry["sector"],
                    market=entry["market"], relationship="보유" if entry["held"] else "관심·점검" if entry["registered"] else "시장 대표",
                    fiscal_period=item["fiscal_period"], release_status="발표 예정 보도" if item["phase"] == "preview" else "실적 관련 보도·공식 대조 대기",
                    official=False, date=item["published_at"][:10], date_basis="보도일·발표일 아님",
                    metrics={}, stages={key: "미연결" for key in METRIC_LABELS}, articles=[], topics=[], source_url="",
                    gaps=["분기 " + (item["fiscal_period"] or "미확인"), _source_reason(item["ticker"], context)],
                    consensus_status="기사의 예상 상회·하회 표현은 주장·수치 대조 미완료", event={})
                packets.append(discovered_groups[key])
            packet = discovered_groups[key]
        packet["articles"].append(item["article"])
        packet["topics"] = list(dict.fromkeys([*packet["topics"], *item["topics"]]))
    for packet in packets:
        packet["commentary"] = _commentary(packet)
    source_tickers = {canonical_ticker(row.get("ticker")) for row in records(context.get("earnings_sources")) if row.get("ticker")}
    requested = {canonical_ticker(value) for value in (context.get("earnings_collection_scope") or {}).get("requested", [])} | source_tickers
    requested &= catalog.keys()
    registered = {ticker for ticker, entry in catalog.items() if entry["registered"]}
    covered = {p["ticker"] for p in packets if p["official"]}
    missing = [dict(ticker=ticker, name=catalog.get(ticker, {}).get("name", ticker),
                    reason=_source_reason(ticker, context)) for ticker in sorted((requested | registered) - covered)
               if not any(p["ticker"] == ticker and p["release_status"] == "예정" for p in packets)]
    return dict(events=events, packets=packets, highlights=_select_highlights(packets, now), discovery=discovery,
                coverage=dict(registered=len(registered), official=len(covered),
                    discovered=len({item["ticker"] for item in discovery["items"]}), missing=missing),
                generated_at=now.isoformat(), scoring_used=False)
