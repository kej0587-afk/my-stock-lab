"""Complete the reading path from collected evidence; never fetch or score."""

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
    from stock_lab_core.report_analysis import sector_evidence
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
    rows = []
    for row in sorted(observations, key=lambda r: number(first(r, "1일수익률", "1D")), reverse=True):
        ticker = text(first(row, "Ticker", "티커"))
        label = sector_display_name(row)
        related = sector_related_news(ticker, day, clean_news, sector_name=label)
        evidence = sector_evidence(row, context.get("macro_data", {}),
            [dict(item, ticker=ticker) for item in related], observations=context.get("prices", {}))
        rows.append((f"{label}({ticker})", evidence["daily"], evidence["excess"], evidence["reading"]))
    return ["**업종 전체 비교 · 수집된 기초 업종 ETF**", *_table(
        ["업종", "일간·기준일", "시장 대비 초과", "관련 재료·해석"], rows)] if rows else []


def company_coverage_lines(context, summary_rows, market):
    """Show available representative/registered stocks; count only same-day closes."""
    from stock_lab_core.earnings_discovery import issuer_catalog
    day = context.get("sessions", {}).get(market)
    if not day:
        return []
    groups = {}
    for ticker, issuer in issuer_catalog(summary_rows).items():
        if issuer["market"] != market:
            continue
        obs = context.get("prices", {}).get(ticker, {})
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
    for sector, members in groups.items():
        members.sort(key=lambda item: item[2], reverse=True)
        values = " / ".join(f"{name}({ticker}) {value * 100:+.2f}%" for name, ticker, value, _ in members)
        rows.append((sector, f"{sum(value > 0 for _, _, value, _ in members)}/{len(members)}", values,
                     " / ".join(dict.fromkeys(source for *_, source in members))))
    return ([f"**대표·보유·관심 종목 등락 · {day} 확정 종가**",
             "상승/관측은 이번 보고서에 가격이 연결된 종목만 센 값입니다.",
             *_table(["분야", "상승/관측", "종목별 등락", "가격 출처"], rows)] if rows else [])


def context_news_lines(context, now, *, bucket, excluded=(), market=None):
    """Do not lose global or post-close events just because no fixed issuer matches."""
    from stock_lab_core.article_context import verified_body_facts
    from stock_lab_core.report_news_selection import matching_categories, TOPIC_CHECKS
    from stock_lab_core.report_presentation import kst_time
    from stock_lab_core.today_news import _session_article_keys
    seen, seen_titles, rows = set(excluded), set(), []
    # Validate separately: legacy topic clustering would collapse independent
    # BOJ/Fed events before the reading path could expose their different facts.
    items = [valid for raw in records(context.get(bucket))
             for valid in curate_news([raw], now=now, limit=1, session_scoped=True)]
    items.sort(key=lambda row: stamp(first(row, "published_at", "published")) or now, reverse=True)
    for item in items:
        key = text(first(item, "link", "url"))
        published = stamp(first(item, "published_at", "published"))
        if not key or key in seen or not published or published > now:
            continue
        if market and item.get("market") != market:
            continue
        canonical_link, canonical_title = _session_article_keys(item)
        title_key = (item.get("market"), item.get("session_date"), canonical_title)
        if canonical_link in seen or title_key in seen_titles:
            continue
        if bucket == "next_session_news":
            window = next((w for w in records(context.get("windows"))
                           if w.get("market") == item.get("market")
                           and w.get("date") == context.get("sessions", {}).get(item.get("market"))), {})
            end = stamp(window.get("end"))
            if not end or published <= end:
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
        else:
            detail += " (제목 확인·기사 주장)"
            check = next((TOPIC_CHECKS[t] for t in topics if t in TOPIC_CHECKS), "공식 발표·원문 및 후속 가격 확인")
        basis = "마감 후·다음 세션" if bucket == "next_session_news" else "해외·공통 맥락"
        rows.append(("·".join(topics[:2]) or "시장 이슈", detail,
                     f"{kst_time(published)} · {basis}", check))
    return _table(["분야", "확인된 재료", "보도시각·범위", "다음 확인"], rows) if rows else []
