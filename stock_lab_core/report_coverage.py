"""Complete the reading path from collected evidence; never fetch or score."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, curate_news, first, number, records, stamp, text

register_loaded_source(__name__, __file__)


def _table(header, rows):
    return [" | ".join(header), " | ".join("---" for _ in header),
            *(" | ".join(_cell(v) for v in row) for row in rows), ""]


def sector_coverage_lines(context, news, market, now):
    """Every collected base-sector proxy, not just top/bottom or technology."""
    from stock_lab_core.market_observation import DEFAULT_SECTOR_MAP
    from stock_lab_core.report_prices import SECTORS
    from stock_lab_core.report_analysis import sector_body_reasons, sector_evidence
    from stock_lab_core.report_presentation import sector_display_name, sector_related_news

    day = context.get("sessions", {}).get(market)
    if not day:
        return []
    allowed = set(DEFAULT_SECTOR_MAP) | set(SECTORS)
    source = records(context.get("sector_rows")) + records(context.get("closed_flow_rows"))
    have_soxx = any(text(first(r, "Ticker", "티커")) == "SOXX"
                    and text(first(r, "기준일", "date")) == day
                    and number(first(r, "1일수익률", "1D")) is not None for r in source)
    seen, observations = set(), []
    clean_news = curate_news(news, now=now, limit=240, session_scoped=True)
    for row in source:
        ticker = text(first(row, "Ticker", "티커"))
        if (ticker not in allowed or ticker in seen or (ticker == "SMH" and have_soxx)
                or (ticker.endswith((".KS", ".KQ"))) != (market == "KR")
                or text(first(row, "기준일", "date")) != day
                or any(x in text(row.get("수치종류")) for x in ("장중", "미확인"))
                or number(first(row, "1일수익률", "1D")) is None):
            continue
        seen.add(ticker)
        observations.append(row)
    rows, shared = [], {}
    for row in sorted(observations, key=lambda r: number(first(r, "1일수익률", "1D")), reverse=True):
        ticker = text(first(row, "Ticker", "티커"))
        label = sector_display_name(row)
        related = sector_related_news(ticker, day, clean_news, sector_name=label)
        direct_news = [item for item in related if not item.get("market_context_only")]
        body = sector_body_reasons(row, news, context, now)
        direct_body = [item for item in body if item.get("scope") == "sector_report"]
        direct_news = [item for item in direct_news if not (
            item.get("body_status") == "verified" and item.get("body_source_url")
            and any(item["body_source_url"] in reason["source"] for reason in body))]
        for item in body:
            if item.get("scope") == "market_common_theme":
                shared.setdefault((item["source"], item["evidence"]), item)
        evidence = sector_evidence(row, context.get("macro_data", {}),
            [dict(item, ticker=ticker) for item in direct_news], observations=context.get("prices", {}),
            body_reasons=direct_body)
        rows.append((f"{label}({ticker})", evidence["daily"], evidence["excess"], evidence["reading"]))
    if not rows:
        return []
    output = ["**업종 전체 비교 · 수집된 기초 업종 ETF**", "업종 직접 관련 재료만 연결합니다. IPO·금리·시장 전체 수급은 공통 시황과 구분하며 업종의 실제 자금 유입을 뜻하지 않습니다.", *_table(
        ["업종", "일간·기준일", "시장 대비 초과", "관련 재료·해석"], rows)]
    if shared:
        output += ["**동일 시장 공통 배경 · 업종 초과수익의 직접 근거 아님**", *_table(
            ["본문 보도·출처", "해석(추정)·다음 확인"], [
                (f"{item['evidence']} {item['source']} · {item['observation']}",
                 " / ".join(item["implications"]) + " · 다음 확인: " + " / ".join(item["checks"]))
                for item in shared.values()])]
    return output


def company_coverage_lines(context, summary_rows, market):
    """Show available representative/registered stocks; count only same-day closes."""
    from stock_lab_core.report_company_prices import company_catalog
    day = context.get("sessions", {}).get(market)
    if not day:
        return []
    groups = {}
    company_prices = context.get("company_prices", context.get("prices", {}))
    for ticker, issuer in company_catalog(summary_rows).items():
        if issuer["market"] != market:
            continue
        obs = company_prices.get(ticker, {})
        value = number(obs.get("return"))
        if (obs.get("date") != day or value is None or obs.get("stale")
                or any(x in text(obs.get("kind")) for x in ("장중", "미확인"))):
            continue
        base = context.get("prices", {}).get("^KS11" if market == "KR" else "^GSPC", {})
        if obs.get("previous_date") and base.get("previous_date") and obs["previous_date"] != base["previous_date"]:
            continue
        groups.setdefault(issuer["sector"], []).append((issuer["name"], ticker, value,
                                                       obs.get("source") or "공급처 미기록"))
    rows = []
    sources = list(dict.fromkeys(source for members in groups.values() for *_, source in members))
    for sector, members in groups.items():
        members.sort(key=lambda item: item[2], reverse=True)
        values = " / ".join(f"{name}({ticker}) {value * 100:+.2f}%" + (f" [{sources.index(source) + 1}]" if len(sources) > 1 else "")
                            for name, ticker, value, source in members)
        rows.append((sector, f"{sum(value > 0 for _, _, value, _ in members)}/{len(members)}", values))
    coverage = context.get("company_price_diagnostics", {}).get("coverage", {}).get(market, {})
    connected, expected = number(coverage.get("connected")), number(coverage.get("expected"))
    coverage_line = ([f"기업 가격 수집 연결 {connected:g}/{expected:g} · 동일 세션 표기 {sum(map(len, groups.values()))}개."]
                     if connected is not None and expected is not None else [])
    if not rows and "company_prices" in context:
        return [*coverage_line, f"대표·보유·관심 종목 등락: {market} {day}의 유효한 동일 세션 기업 가격 미확보 · 상승/관측 집계 보류.", ""]
    return ([f"**대표·보유·관심 종목 등락 · {day} 확정 종가**",
             "상승/관측은 이번 보고서에 가격이 연결된 종목만 센 값입니다.",
             *coverage_line, *_table(["분야", "상승/관측", "종목별 등락"], rows),
             "가격 출처: " + " / ".join((f"[{i}] " if len(sources) > 1 else "") + _cell(source)
                                       for i, source in enumerate(sources, 1)), ""] if rows else [])


def context_news_lines(context, now, *, bucket, excluded=(), market=None, summary_rows=()):
    """Do not lose global or post-close events just because no fixed issuer matches."""
    from stock_lab_core.article_context import verified_body_facts
    from stock_lab_core.report_news_selection import matching_categories, TOPIC_CHECKS
    from stock_lab_core.report_presentation import kst_time
    from stock_lab_core.today_news import _news_timestamp, _session_article_keys
    from stock_lab_core.report_brief import _BRIEF_TERMS, explicit_news_market, material_news, news_observation, news_session_bounds, brief_theme
    seen, seen_titles, rows = set(excluded), set(), []
    # Validate separately: legacy topic clustering would collapse independent
    # BOJ/Fed events before the reading path could expose their different facts.
    raw_items = records(context.get(bucket))
    if bucket == "other_market_news":
        # Mis-tagged search results belong in dated context, not the US/KR close.
        raw_items = [*raw_items, *(row for name in ("session_news", "current_session_news", "next_session_news")
            for row in records(context.get(name)) if explicit_news_market(row)
            and explicit_news_market(row) != row.get("market"))]
    items = [valid for raw in raw_items if material_news(raw)
             for valid in curate_news([raw], now=now, limit=1, session_scoped=True, title_pattern=_BRIEF_TERMS)]
    items.sort(key=lambda row: stamp(first(row, "published_at", "published")) or now, reverse=True)
    for item in items:
        key = text(first(item, "link", "url"))
        published = _news_timestamp(first(item, "published_at", "published"))
        if not key or key in seen or not published or published > now:
            continue
        if market and item.get("market") != market:
            continue
        subject = explicit_news_market(item)
        if bucket == "next_session_news" and subject and subject != item.get("market"):
            continue
        canonical_link, canonical_title = _session_article_keys(item)
        title_key = (item.get("market"), item.get("session_date"), canonical_title)
        if canonical_link in seen or title_key in seen_titles:
            continue
        if bucket == "next_session_news":
            window = next((w for w in records(context.get("windows"))
                           if w.get("market") == item.get("market")
                           and w.get("date") == context.get("sessions", {}).get(item.get("market"))), {})
            _, close = news_session_bounds(context, item.get("market"), window.get("date"))
            if not close or published <= close:
                continue
        seen.add(key)
        seen.add(canonical_link)
        seen_titles.add(title_key)
        topics = matching_categories(item.get("title"))
        facts = verified_body_facts(item)
        detail = citation(item)
        if facts:
            detail += " · 본문: " + " / ".join(dict.fromkeys(f["summary"] for f in facts))
            check = "해석(추정): " + " / ".join(dict.fromkeys(f["implication"] for f in facts))
            check += " · 다음 확인: " + " / ".join(dict.fromkeys(f["check"] for f in facts))
            from stock_lab_core.report_brief import ENTITIES, _holding_links
            from stock_lab_core.report_evidence import is_held
            evidence = " ".join(f["summary"] for f in facts)
            held = [row for row in records(summary_rows) if is_held(row)]
            if held:
                entities = [ticker for ticker, pattern in ENTITIES if re.search(pattern, evidence, re.I)]
                check = _holding_links(held, evidence, entities, brief_theme(item), item.get("market")) + " · " + check
        else:
            detail += " (제목 확인·기사 주장)"
            check = next((TOPIC_CHECKS[t] for t in topics if t in TOPIC_CHECKS), "공식 발표·원문 및 후속 가격 확인")
        basis = "마감 후·다음 세션 · 해당 종가 원인 미확인" if bucket == "next_session_news" else news_observation(item, context)[1]
        rows.append((brief_theme(item, comprehensive=True), detail,
                     f"{kst_time(published)} · {basis}", check))
    return _table(["분야", "확인된 재료", "보도시각·범위", "다음 확인"], rows) if rows else []
