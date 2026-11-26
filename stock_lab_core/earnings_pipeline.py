"""One read-only earnings view for coverage, evidence and report commentary."""

from copy import deepcopy
from datetime import timedelta

from stock_lab_core.earnings_discovery import canonical_ticker, discover_earnings_news, issuer_catalog, TOPICS
from stock_lab_core.earnings_reconciliation import METRIC_LABELS, reconcile_earnings
from stock_lab_core.performance import timed_call
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
    rows = [row for key in ("earnings_sources", "earnings_result_sources")
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
        if reason.startswith("dart_corporate_mapping_"):
            cause = reason.removeprefix("dart_corporate_mapping_")
            if cause in {"connect_timeout", "read_timeout", "timeout", "transport_error"}:
                return "DART 회사 식별자 조회 실패·시간초과 (" + cause + ")"
            if cause.startswith("api_error"):
                return "DART 회사 식별자 API 오류 (" + cause + ")"
            return "DART 회사 식별자 연결 실패 (" + cause + ")"
        meanings = {"sec_user_agent_missing": "SEC 연락처 설정 미연결",
                    "dart_api_key_missing": "DART API 설정 미연결",
                    "collection_time_budget": "공식 공시 수집 시간 한도·이번 조회 보류",
                    "sec_rate_limited": "SEC 접근 제한으로 요청 일시 중지·조회 실패",
                    "recent_earnings_filing_unavailable": "최근 SEC 실적 공시 미확인",
                    "explicit_fiscal_quarter_unavailable": "공식 발표문 기준분기 대조 미완료",
                    "release_dateline_unavailable": "공식 발표문 발표일 대조 미완료",
                    "dart_period_report_unavailable": "DART 정기보고서 기준기간 미확인",
                    "dart_ticker_mapping_unavailable": "DART 종목·회사 식별자 미연결",
                    "dart_ticker_mapping_unavailable_in_snapshot": "DART 종목·회사 식별자 미등록 · 보관 목록 기준(저장 이후 신규 상장 가능)",
                    "dart_api_error": "DART 정기보고서 API 오류·결과 미확인",
                    "dart_no_reports": "조회 기간 내 DART 정기보고서 없음",
                    "unique_earnings_exhibit_unavailable": "SEC 실적 발표문 첨부 대조 미완료",
                    "document_size_limit": "공식 원문 크기 한도 초과·수치 추출 보류",
                    "sec_ticker_mapping_unavailable": "SEC 회사 식별자 미연결"}
        if reason in meanings:
            return meanings[reason]
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
    if event.get("source_kind") == "dart_discovered_report":
        release = "공식 정기보고서 확인·실적 발표일 미확인"
        if event.get("financial_values"):
            release = "공식 공시 실제치 대조·실적 발표일 미확인"
    reaction = metrics.get("price_reaction") or {}
    if reaction.get("status") == "reported":
        states["price_reaction"] = "보도 주장·시세 대조 미완료"
    gaps = [METRIC_LABELS[key] + " " + states[key] for key in METRIC_LABELS if states[key] != "확인"]
    if not official:
        gaps.insert(0, _source_reason(ticker, context))
    if event.get("result_stale"):
        gaps.insert(0, "원문 재조회 실패·마지막 확인값 사용")
    if event.get("financial_reason"):
        gaps.insert(0, "DART 수치 연결 보류: " + event["financial_reason"])
    return dict(ticker=ticker, name=entry["name"], sector=entry["sector"], market=entry["market"],
        relationship="보유" if entry["held"] else "관심·점검" if entry["registered"] else "시장 대표",
        fiscal_period=event.get("fiscal_period", ""), release_status=release, official=official,
        date=event.get("date", ""), date_basis=event.get("date_basis") or ("공식 발표일" if official else "일정 기준일"),
        metrics=metrics, stages=states, gaps=gaps, articles=[], topics=[],
        source_url=event.get("result_source_url") or event.get("source_url", ""),
        consensus_status="발표 당시 예상치 미연결·상회/하회 판단 보류", event=deepcopy(event))


def _commentary(packet):
    """Explain the evidence gap, never invent an earnings surprise or causality."""
    if packet.get("event", {}).get("source_kind") == "dart_discovered_report":
        if packet["event"].get("financial_values"):
            return "공시 실제치에서 3개월 손익과 누적 현금흐름을 구분해 확인합니다. 접수일은 실적 발표일이 아니며, 회사 전망·컨센서스·주가 반응은 별도 대조가 필요합니다."
        return "공식 정기보고서의 접수일·보고기간은 확인했습니다. 실제 실적 발표일·회계분기와 개별 수치는 아직 대조되지 않았으며, 이 공시를 새로운 실적 발표나 주가 변화의 원인으로 해석하지 않습니다."
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
    recent = [p for p in packets if (day := stamp(p["date"])) is not None and day.date() <= now.date()
              and p.get("event", {}).get("source_kind") != "dart_discovered_report"
              and (evidence := stamp(p.get("latest_evidence_at") or p["date"])) is not None
              and now.date() - timedelta(days=7) <= evidence.date() and evidence <= now
              and "예정" not in p["release_status"]]
    # Prefer the verified period over an unassigned follow-up about that issuer.
    official_tickers = {p["ticker"] for p in recent if p["official"]}
    recent = [p for p in recent if p["official"] or p["ticker"] not in official_tickers]
    recent.sort(key=lambda p: (stamp(p.get("latest_evidence_at") or p["date"]), bool(p["topics"]),
                              p["official"], p["relationship"] == "보유", p["ticker"]), reverse=True)
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


_FAILED_MARKERS = ("실패", "시간초과", "HTTP", "시간 한도", "수집 한도", "API 오류")


def coverage_state(coverage):
    """미계산 / 확인 결과 0개 / 일부 조회 실패 / 공식값 없음 counts for the earnings coverage line."""
    missing = coverage.get("missing") or []
    failed = [row for row in missing if any(m in text(row.get("reason")) for m in _FAILED_MARKERS)]
    return dict(not_computed=coverage.get("summary_available") is False,
                official=coverage.get("official", 0), failed=len(failed), no_official=len(missing) - len(failed))


@timed_call("report_assembly", "earnings_pipeline")
def build_earnings_pipeline(context, summary_rows=None, news=(), now=None):
    now = stamp(now)
    if now is None:
        raise ValueError("now is required")
    events = reconcile_earnings(context, now)
    catalog = issuer_catalog(summary_rows, events)
    corpus = [*records(news), *(row for key in ("current_session_news", "session_news", "next_session_news")
                               for row in records(context.get(key)))]
    discovery = discover_earnings_news(corpus, catalog, now)
    linked = [item for item in discovery["items"] if safe_link(item["article"].get("link"))]
    if len(linked) != len(discovery["items"]):
        discovery["excluded"]["원문 URL 미연결"] = len(discovery["items"]) - len(linked)
        discovery["items"] = linked
    packets, by_key = [], {}
    for event in events:
        ticker = canonical_ticker(event.get("ticker"))
        day = stamp(event.get("date"))
        if ticker not in catalog or not event.get("event_status") or not day or not -200 <= (day.date() - now.date()).days <= 45:
            continue
        key = (ticker, event.get("fiscal_period", ""))
        if event.get("source_kind") == "dart_discovered_report":
            key += ("filing",)
        if key in by_key:
            continue
        packet = _event_packet(event, catalog, context)
        packets.append(packet)
        by_key[key] = packet
    discovered_groups = {}
    for item in discovery["items"]:
        # Unknown periods cannot borrow an old official result or surprise.
        # A preview also cannot renew a past result, even with the same period.
        packet = (by_key.get((item["ticker"], item["fiscal_period"]))
                  if item["fiscal_period"] and item["phase"] != "preview" else None)
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
        event = packet["event"]
        baseline = (event.get("release_at") if packet["official"] and event.get("release_precision") == "datetime"
                    else packet["date"])
        latest = stamp(baseline)
        packet["latest_evidence_at"] = baseline if latest and latest <= now else ""
        packet["latest_evidence_basis"] = packet["date_basis"] if packet["latest_evidence_at"] else ""
        # Use publication evidence, never the collection/check time. The release
        # date, fiscal period, official metrics and calendar events stay intact.
        for article in packet["articles"]:
            published = stamp(article.get("published_at") or article.get("published"))
            if published and published <= now and (not packet["latest_evidence_at"] or published > latest):
                latest = published
                packet["latest_evidence_at"] = published.isoformat()
                packet["latest_evidence_basis"] = "보도일·발표일 아님"
        packet["commentary"] = _commentary(packet)
    source_tickers = {canonical_ticker(row.get("ticker")) for row in records(context.get("earnings_sources")) if row.get("ticker")}
    requested = {canonical_ticker(value) for value in (context.get("earnings_collection_scope") or {}).get("requested", [])} | source_tickers
    requested &= catalog.keys()
    registered = {ticker for ticker, entry in catalog.items() if entry["registered"]}
    covered = {p["ticker"] for p in packets if p["official"]}
    filings = {p["ticker"] for p in packets if p["event"].get("source_kind") == "dart_discovered_report"}
    announcements = {p["ticker"] for p in packets if p["official"] and p["event"].get("source_kind") != "dart_discovered_report"}
    missing = [dict(ticker=ticker, name=catalog.get(ticker, {}).get("name", ticker),
                    reason=_source_reason(ticker, context)) for ticker in sorted((requested | registered) - covered)
               if not any(p["ticker"] == ticker and p["release_status"] == "예정" for p in packets)]
    return dict(events=events, packets=packets, highlights=_select_highlights(packets, now), discovery=discovery,
                coverage=dict(summary_available=None if summary_rows is None else bool(records(summary_rows)),
                    registered=len(registered), official=len(announcements), filings=len(filings),
                    discovered=len({item["ticker"] for item in discovery["items"]}), missing=missing),
                generated_at=now.isoformat(), scoring_used=False)
