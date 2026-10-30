"""Evidence-only Korean market safeguard history; no requests or trading gates.

``safeguard_events(news, now=None)`` accepts news dicts, an iterable, or a
DataFrame. Headlines are always ``reported``, even when labelled KRX. An
``official`` row requires a krx.co.kr source URL, ``body_status='verified'``,
and an explicit event date in the verified body/fact (or its event_date field).
Verified bodies use the existing body_text/body_facts and body_source_url
contract. Missing/ambiguous market, direction, date or trigger is omitted.
Output is an evidence subset, never a complete exchange history or YTD count.
"""

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from itertools import islice
import re
from urllib.parse import urlsplit

from stock_lab_core.release_calendar import _clock
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, first, safe_link, stamp, text

register_loaded_source(__name__, __file__)

MAX_NEWS_ROWS = 256
MAX_FACTS = 32
_MARKETS = {
    "KOSPI": re.compile(r"\bKOSPI(?:200)?\b|\ucf54\uc2a4\ud53c|\uc720\uac00\uc99d\uad8c\uc2dc\uc7a5", re.I),
    "KOSDAQ": re.compile(r"\bKOSDAQ(?:150)?\b|\ucf54\uc2a4\ub2e5", re.I),
}
_KINDS = {
    "sidecar": re.compile(r"\uc0ac\uc774\ub4dc\uce74|\bside\s*car\b", re.I),
    "circuit_breaker": re.compile(r"\uc11c\ud0b7\s*\ube0c\ub808\uc774\ucee4|\bcircuit[ -]*breaker\b", re.I),
}
_BUY = re.compile(r"\ub9e4\uc218|\b(?:buy|buying)\b", re.I)
_SELL = re.compile(r"\ub9e4\ub3c4|\b(?:sell|selling)\b", re.I)
_DOWN = re.compile(r"\ud558\ub77d|\uae09\ub77d|\ud3ed\ub77d|\b(?:fall|drop|plunge)\b", re.I)
_TRIGGER = re.compile(r"\ubc1c\ub3d9|\b(?:triggered|activated)\b", re.I)
_NOT_EVENT = re.compile(
    r"\ubbf8\ubc1c\ub3d9|\ubc1c\ub3d9[^.!?]{0,20}(?:\uc870\uac74|\uae30\uc900|\uac00\ub2a5|\uc6b0\ub824|\uc608\uc0c1|\uc9c1\uc804|\uc548\s|\uc54a|\uc5c6|\ub418\uba74|\ud558\uba74|\ud560\s|\ub420\s|\uc2dc\uc5d0|\uc2dc\s|\uc5b4\ub5a4)|"
    r"(?:\uc870\uac74|\uacbd\uc6b0)[^.!?]{0,40}\ubc1c\ub3d9|\ubc1c\ub3d9(?:\ud55c\ub2e4|\ub41c\ub2e4|\ud558\ub294|\ub418\ub294)|\ud574\uc81c|\b(?:could|may|might|would|not|never|if|threshold|explained)\b", re.I)
_HISTORICAL = re.compile(r"\uc9c0\ub09c|\uc791\ub144|\uc804\ub144|\uc804\uc77c|\uc804\s*\uac70\ub798\uc77c|\uc608\uc804|\ub2f9\uc2dc|\uc774\ub825|\uc5ed\uc0ac|\byesterday|previous|last year|history\b", re.I)


def _rows(news):
    if news is None:
        return []
    if isinstance(news, Mapping):
        return [news]
    if hasattr(news, "head") and hasattr(news, "to_dict"):
        return news.head(MAX_NEWS_ROWS).to_dict("records")
    return (row for row in islice(news, MAX_NEWS_ROWS) if isinstance(row, Mapping))


def _market(value):
    matches = [market for market, pattern in _MARKETS.items() if pattern.search(value)]
    return matches[0] if len(matches) == 1 else None


def _event_date(value, published, explicit=""):
    if explicit:
        try:
            day = date.fromisoformat(text(explicit))
            claimed, basis = _event_date(value, published)
            if basis in {"body_date", "relative_event_date", "article_day"} and claimed != day:
                return None, "event_date_mismatch"
            if basis in {"invalid_event_date", "ambiguous_event_date"}:
                return None, basis
            return day, "explicit_event_date"
        except ValueError:
            return None, "invalid_event_date"
    full = re.findall(r"(?<!\d)(\d{4})\s*(?:\ub144|[-./])\s*(\d{1,2})\s*(?:\uc6d4|[-./])\s*(\d{1,2})(?:\uc77c)?(?!\d)", value)
    short = re.findall(r"(?<!\d)(\d{1,2})\uc6d4\s*(\d{1,2})\uc77c", value) if not full else []
    try:
        days = {date(int(y), int(m), int(d)) for y, m, d in full}
        days.update(date(published.year, int(m), int(d)) for m, d in short)
        if days:
            return (days.pop(), "body_date") if len(days) == 1 else (None, "ambiguous_event_date")
        if re.search(r"\uc804\ub0a0|\uc5b4\uc81c|\byesterday\b", value, re.I):
            return published.date() - timedelta(days=1), "relative_event_date"
        if _HISTORICAL.search(value):
            return None, "historical_date_unconfirmed"
        days = {int(d) for d in re.findall(r"(?<!\d)(\d{1,2})\uc77c(?!\s*(?:\ub9cc|\uac04))", value)}
        if days:
            return (date(published.year, published.month, days.pop()), "article_day") if len(days) == 1 else (None, "ambiguous_event_date")
    except ValueError:
        return None, "invalid_event_date"
    return published.date(), "publication_date"


def _verified_parts(row, published, now, link):
    if row.get("body_status") != "verified":
        return []
    body_link = safe_link(row.get("body_source_url")) if text(row.get("body_source_url")) else link
    body_at = stamp(row.get("body_published_at")) if text(row.get("body_published_at")) else published
    modified = stamp(row.get("body_modified_at")) if text(row.get("body_modified_at")) else body_at
    if not body_link or not body_at or not modified or not body_at <= modified <= now:
        return []
    parts = []
    body = text(row.get("body_text"))
    if body:
        parts.append((body[:16_000], text(row.get("event_date")), body_link, body_at))
    facts = row.get("body_facts", [])
    if isinstance(facts, (list, tuple)):
        for fact in facts[:MAX_FACTS]:
            if isinstance(fact, Mapping):
                value = text(first(fact, "evidence", "text", "fact"))[:2000]
                if value:
                    parts.append((value, text(fact.get("event_date") or row.get("event_date")), body_link, body_at))
    return [part for part in parts if any(pattern.search(part[0]) for pattern in _KINDS.values())]


def _extract(value, *, title, explicit, published, now, link, publisher, verified):
    candidates = []
    host = urlsplit(link).hostname or ""
    official_host = host == "krx.co.kr" or host.endswith(".krx.co.kr")
    for clause in re.split(r"[;\n]|(?<=[.!?])\s+|,\s+", value)[:64]:
        if not _TRIGGER.search(clause) or _NOT_EVENT.search(clause):
            continue
        market = _market(clause)
        if not market and not any(p.search(clause) for p in _MARKETS.values()):
            market = _market(title)
        if not market:
            continue
        day, basis = _event_date(clause, published, explicit)
        if not day or day > min(published.date(), now.astimezone(KST).date()):
            continue
        for kind, pattern in _KINDS.items():
            if not pattern.search(clause):
                continue
            buy, sell = bool(_BUY.search(clause)), bool(_SELL.search(clause))
            if kind == "sidecar":
                if buy == sell:
                    continue
                direction = "buy" if buy else "sell"
            else:
                direction = "down" if _DOWN.search(clause) else "unknown"
            official = verified and official_host and basis in {"explicit_event_date", "body_date"}
            candidates.append(dict(
                market=market, kind=kind, direction=direction, date=day.isoformat(),
                fact=clause.strip()[:1000], source="Korea Exchange" if official else publisher, source_url=link,
                published_at=published.isoformat(), status="official" if official else "reported",
                evidence_level="verified_body" if verified else "headline_only", date_basis=basis,
                reason="" if official else "official_event_not_verified", coverage="provided_evidence_only",
                price_reaction_verified=False,
            ))
    return candidates


def safeguard_events(news, now=None):
    """Extract dated triggers, deduplicating market/kind/direction/event day.

    No events means no supported input, not proof that no trigger occurred.
    No cumulative counts, circuit-breaker levels, prices or trading decisions
    are inferred. Existing verified bodies take precedence over headlines.
    """
    now = _clock(now).astimezone(KST)
    groups = {}
    for row in _rows(news):
        title = text(first(row, "title", "headline", "\uc81c\ubaa9"))[:2000]
        link = safe_link(first(row, "source_url", "link", "\ub9c1\ud06c"))
        published = stamp(first(row, "published_at", "published", "\uc2dc\uac04"))
        if not link or not published or published > now:
            continue
        publisher = text(first(row, "publisher", "source", "\ucd9c\ucc98")) or (urlsplit(link).hostname or "")
        parts = _verified_parts(row, published, now, link)
        found = []
        for value, explicit, body_link, body_at in parts:
            found.extend(_extract(value, title=title, explicit=explicit, published=body_at,
                                  now=now, link=body_link, publisher=publisher, verified=True))
        if not found and not parts:
            found = _extract(title, title=title, explicit=text(row.get("event_date")),
                             published=published, now=now, link=link, publisher=publisher, verified=False)
        for event in found:
            key = tuple(event[field] for field in ("market", "kind", "direction", "date"))
            previous = groups.get(key)
            citation = {field: event[field] for field in ("source", "source_url", "published_at", "status")}
            if previous is None:
                event["sources"] = [citation]
                groups[key] = event
                continue
            sources = previous["sources"]
            if citation not in sources and len(sources) < 8:
                sources.append(citation)
            rank = lambda e: (e["status"] == "official", e["evidence_level"] == "verified_body",
                              e["date_basis"] != "publication_date", e["published_at"])
            if rank(event) > rank(previous):
                event["sources"] = sources
                groups[key] = event
    return sorted(groups.values(), key=lambda e: (e["date"], e["market"], e["kind"], e["direction"]), reverse=True)
