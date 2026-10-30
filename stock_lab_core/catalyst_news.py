"""Issuer-scoped retrieval plans and post-close evidence, never price causality.

No current headline or earnings number is embedded here. The only dated data
is a partial official ETF membership snapshot, which expires independently of
article caches. All network retrieval uses today's existing bounded RSS cache.
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import islice
import re
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

MAX_CATALYST_QUERIES = 4
_ISSUERS = {
    "GOOGL": ("Alphabet", r"\bAlphabet\b|\bGoogle\b|\bGOOGL?\b|알파벳|구글"),
    "MSFT": ("Microsoft", r"\bMicrosoft\b|\bMSFT\b|마이크로소프트"),
    "FFIV": ("F5", r"\bFFIV\b|\bF5(?:\s+Networks|,?\s+Inc\.?)?\b"),
    "FTNT": ("Fortinet", r"\bFortinet\b|\bFTNT\b|포티넷"),
    "ON": ("onsemi", r"\bonsemi\b|\bON Semiconductor\b|온세미|(?-i:\$ON\b|\bNASDAQ\s*:\s*ON\b)"),
    "AMZN": ("Amazon", r"\bAmazon\b|\bAMZN\b|아마존"),
    "INTC": ("Intel", r"\bIntel\b|\bINTC\b|인텔"),
    "SNDK": ("Sandisk", r"\bSanDisk\b|\bSNDK\b|샌디스크"),
}
_FINANCIAL = re.compile(r"\b(?:earnings|revenue|profit|EPS|capex|guidance|outlook|cash flow|shares?|stocks?|"
                        r"downgrad\w*|upgrad\w*|price target|options?|puts?|calls?|billings|FCF|cash burn)\b|"
                        r"실적|매출|이익|현금흐름|현금 흐름|설비투자|가이던스|주가|투자의견|목표주가|옵션", re.I)
_TOPICS = (
    ("capex_cash_flow", r"\bcapex\b|capital (?:expenditure|spend)|\bFCF\b|free cash flow|cash burn|설비투자|잉여.?현금|현금흐름|현금 흐름", "설비투자·현금흐름"),
    ("guidance", r"\bguidance\b|\boutlook\b|가이던스|실적 전망", "가이던스"),
    ("analyst_change", r"\bdowngrad\w*|\bupgrad\w*|price target|투자의견|목표주가", "투자의견·목표주가"),
    ("options_activity", r"\boptions? (?:flow|activity|volume)|\bput[ /-]call\b|\bputs?\b.{0,30}\b(?:volume|bought|buying)\b|옵션|풋콜", "옵션 거래 주장"),
    ("earnings", r"\bearnings\b|\brevenue\b|\bprofit\b|\bEPS\b|\bbillings\b|실적|매출|이익", "실적"),
)
_EXTENDED = re.compile(r"after[- ]?hours|extended (?:trading|hours)|post[- ](?:market|close)|시간외|장후|마감 후", re.I)
_FALL = re.compile(r"\b(?:falls?|falling|fell|drops?|dropped|dropping|slides?|slid|sliding|slumps?|slumped|plunges?|plunged|tumbles?|tumbled|sinks?|sank|down)\b|하락|급락", re.I)
_RISE = re.compile(r"\b(?:rises?|rising|rose|gains?|gained|rallies|rallied|jumps?|jumped|surges?|surged|up)\b|상승|급등", re.I)
_PREVIEW = re.compile(r"\b(?:preview|will report|due to report|ahead of earnings)\b|실적.{0,8}예정|발표 전", re.I)

# Official fund holdings, not the index or an inferred thematic relationship.
# Partial coverage only. No membership or weight is extrapolated after expiry.
CIBR_MEMBERSHIP = {
    "source_url": "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=CIBR",
    "as_of": "2026-10-27", "verified_at": "2026-10-29", "expires_at": "2026-11-03",
    "validity_timezone": "Asia/Seoul",
    "coverage": "partial_verified_constituents",
    "weights_pct": {"FTNT": 7.89, "FFIV": 3.50, "MSFT": 1.91, "GOOGL": 1.72},
}


def _stamp(value):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _now(value):
    stamp = datetime.now(timezone.utc) if value is None else _stamp(value)
    if stamp is None:
        raise ValueError("An offset-aware report timestamp is required")
    return stamp


def _tickers(rows):
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    if isinstance(rows, str):
        rows = [rows]
    values = []
    for row in islice(rows or (), 128):
        value = next((row.get(k) for k in ("Ticker", "ticker", "티커") if row.get(k)), "") if isinstance(row, Mapping) else row
        value = str(value or "").strip().upper()
        if value and value not in values:
            values.append(value)
    return values


def is_consumer_banking_promo(title):
    """Exclude product offers, not bank earnings, policy or deposit competition."""
    title = str(title or "")
    if re.search(r"기준금리|한국은행|연준|FOMC|순이자|실적|부실|유동성|예금.{0,6}(?:이탈|인출|경쟁)", title, re.I):
        return False
    return bool(re.search(r"은행|뱅크|신협|저축은행", title) and
                re.search(r"예[·ㆍ/]?적금|예금|적금|통장|예[·ㆍ/]적금", title) and
                re.search(r"우대금리|가입.{0,12}(?:혜택|이벤트)|특판|캐시백|경품|쿠폰", title))


def us_symbol_collision(title, ticker):
    """Apply only to the requested US symbol, never to Canadian news globally."""
    symbol = str(ticker or "").upper()
    if symbol not in {"CIBR", *_ISSUERS, "GOOG"}:
        return False
    return bool(re.search(r"(?<![A-Z0-9])" + re.escape(symbol) + r"(?::CA\b|\.(?:TO|V|NE)\b)|"
                          r"\b(?:TSX|TSXV|TSX-V|CSE|NEO)\s*:\s*" + re.escape(symbol) + r"\b",
                          str(title or ""), re.I))


def catalyst_entities(text):
    text = str(text or "")[:4000]
    if not _FINANCIAL.search(text):
        return []
    result = []
    for ticker, (_, pattern) in _ISSUERS.items():
        if us_symbol_collision(text, ticker):
            continue
        if ticker == "FFIV" and re.search(r"tornado|keyboard|refresh key|토네이도|새로고침", text, re.I):
            continue
        if re.search(pattern, text, re.I):
            result.append(ticker)
    return result


def catalyst_topics(text):
    return [key for key, pattern, _ in _TOPICS if re.search(pattern, str(text or ""), re.I)]


def extended_stock_reaction(title):
    """Require a price subject and an extended-session marker in its clause."""
    issuers = catalyst_entities(title)
    if len(issuers) != 1 or not _EXTENDED.search(title):
        return "unconfirmed"
    direction = "(?:" + _FALL.pattern + "|" + _RISE.pattern + ")"
    price = r"(?:\b(?:stock(?:\s+price)?|shares?)\b|주가(?:는|가|도)?)"
    bridge = r"(?:\s+|\b(?:is|are|was|were|continues?|continued|to|in|the|extended|trading|hours|after-hours|post-market)\b|시간외|장후|거래에서|거래|에서|마감 후){0,16}"
    price_move = re.compile(price + bridge + "(?P<direction>" + direction + ")", re.I)
    directions, extended = set(), set()
    for clause in re.split(r"[;!?]|,\s*|\.\s+|\s+(?:as|and|while|whereas|because|despite|following)\s+", str(title), flags=re.I):
        carry_price = False
        for part in re.split(r"\s+but\s+", clause, flags=re.I):
            # A bare 'stock ...' may refer back to the sole headline issuer;
            # 'Amazon stock ...' must not inherit Alphabet's identity.
            owner = re.search(_ISSUERS[issuers[0]][1], part, re.I) or re.match(r"\s*(?:its\s+|the\s+)?" + price, part, re.I)
            match = price_move.search(part) if owner else None
            if not match and carry_price:
                match = re.match(r"\s*(?P<direction>" + direction + ")", part, re.I)
            carry_price = bool(match)
            if not match:
                continue
            move = "down" if _FALL.fullmatch(match["direction"]) else "up"
            directions.add(move)
            if _EXTENDED.search(part):
                extended.add(move)
    if not extended:
        return "unconfirmed"
    if len(directions) > 1:
        return "reported_mixed_sessions"
    return "reported_extended_decline" if "down" in extended else "reported_extended_rise"


def prioritize_issuer_news(rows, *, query_issuers=()):
    """Reorder within existing market/category slots; never increase their caps."""
    relevant = set(query_issuers)
    groups = {}
    for index, row in enumerate(rows):
        groups.setdefault((row.get("market"), row.get("category")), []).append(index)
    result = list(rows)
    for (market, _), indexes in groups.items():
        if market != "US":
            continue
        candidates = []
        for index in indexes:
            row = rows[index]
            title = str(row.get("title") or "")
            issuers = set(catalyst_entities(title)) & relevant
            topics = catalyst_topics(title)
            if issuers and topics and not row.get("is_close_wrap") and not _PREVIEW.search(title):
                priority = 0 if "capex_cash_flow" in topics else 1 if "guidance" in topics else 2
                stamp = _stamp(row.get("published_at") or row.get("published"))
                candidates.append((priority, len(issuers), -(stamp.timestamp() if stamp else 0), index, issuers))
        covered, first = set(), []
        for _, _, _, index, issuers in sorted(candidates):
            if issuers - covered:
                first.append(index)
                covered.update(issuers)
        if not first:
            continue
        wraps = [index for index in indexes if rows[index].get("is_close_wrap")]
        leading = wraps + first
        ordered = leading + [index for index in indexes if index not in leading]
        for target, source in zip(indexes, ordered):
            result[target] = rows[source]
    return result


def constituent_links(title, ticker, *, now=None, published_at=None):
    now = _now(now)
    if str(ticker).upper() != "CIBR" or us_symbol_collision(title, ticker):
        return []
    spec = CIBR_MEMBERSHIP
    # Verification/expiry are Korean report dates; holdings as-of is a US date.
    day = now.astimezone(ZoneInfo(spec["validity_timezone"])).date().isoformat()
    if not spec["verified_at"] <= day < spec["expires_at"]:
        return []
    published = _stamp(published_at)
    if published_at is not None and published is None:
        return []
    if published and (published > now or published.astimezone(ZoneInfo("America/New_York")).date().isoformat() < spec["as_of"]):
        return []
    return [dict(etf="CIBR", constituent=issuer, relation="verified_constituent_indirect",
                 source_url=spec["source_url"], holdings_as_of=spec["as_of"], verified_at=spec["verified_at"],
                 expires_at=spec["expires_at"], coverage=spec["coverage"], weight_pct=spec["weights_pct"][issuer],
                 validity_timezone=spec["validity_timezone"],
                 price_contribution_verified=False, label="편입기업 간접 재료 · ETF 가격 원인·기여도 미확인")
            for issuer in catalyst_entities(title) if issuer in spec["weights_pct"] and catalyst_topics(title)]


def catalyst_query_specs(issuers, *, now=None):
    """Canonical specs shared verbatim by report and precision RSS caches."""
    now = _now(now).astimezone(ZoneInfo("America/New_York"))
    specs = []
    supported = list(dict.fromkeys("GOOGL" if t == "GOOG" else t for t in _tickers(issuers)
                                   if t in _ISSUERS or t == "GOOG"))
    # Preserve the request budget; overflow issuers share the final query.
    groups = [[t] for t in supported[:MAX_CATALYST_QUERIES - 1]]
    if supported[MAX_CATALYST_QUERIES - 1:]:
        groups.append(supported[MAX_CATALYST_QUERIES - 1:])
    for group in groups:
        names = " OR ".join(f'"{_ISSUERS[t][0]}" OR "{t}"' for t in group)
        terms = f'({names}) (earnings OR guidance OR capex OR "free cash flow" OR downgrade OR "options activity" OR "extended trading")'
        query = terms + f" after:{(now.date() - timedelta(days=3)).isoformat()} before:{(now.date() + timedelta(days=1)).isoformat()}"
        specs.append(dict(market="US", category="기업 촉매", query_kind="issuer_catalyst", query_issuers=group,
                          query_topics=[], query=terms,
                          url="https://news.google.com/rss/search?" + urlencode({"q": query}) + "&hl=en-US&gl=US&ceid=US:en"))
    return specs


def exposure_catalyst_specs(exposures, *, now=None):
    tickers = _tickers(exposures)
    issuers = ["GOOGL" if t == "GOOG" else t for t in tickers if t in _ISSUERS or t == "GOOG"]
    # Industry discovery remains useful after the separate membership evidence expires.
    if "CIBR" in tickers:
        issuers = ["FFIV", "FTNT", *issuers]
    if set(tickers) & {"QQQ", "QLD", "TQQQ", "XLK", "XLC", "IGV", "379810.KS", "418660.KS"}:
        issuers.extend(["GOOGL", "MSFT"])
    return catalyst_query_specs(issuers, now=now)


def matches_catalyst_query(title, spec):
    return bool(set(catalyst_entities(title)) & set(spec.get("query_issuers", ())) and catalyst_topics(title))


def catalyst_body_facts(paragraphs, title=""):
    """Conservative subject-bound body summaries. No numbers or consensus inferred."""
    facts, seen = [], set()
    for paragraph in paragraphs[:80]:
        # Do not transfer a competitor's cash flow or guidance to the headline issuer.
        subjects = catalyst_entities(paragraph)
        if len(subjects) != 1 or not _FINANCIAL.search(paragraph):
            continue
        issuer = subjects[0]
        for topic in catalyst_topics(paragraph):
            if (issuer, topic) in seen:
                continue
            seen.add((issuer, topic))
            label = next(label for key, _, label in _TOPICS if key == topic)
            facts.append(dict(topic=topic, subject_ticker=issuer,
                summary=f"{_ISSUERS[issuer][0]}의 {label} 내용이 보도됐습니다",
                implication="실적 성장과 투자·현금흐름 부담은 함께 나타날 수 있으며 가격 반응의 단독 원인은 확정할 수 없습니다",
                check="공식 실적·가이던스 원문과 같은 거래시간대 가격 확인",
                evidence=" ".join(str(paragraph).split()[:20])[:140]))
            if len(facts) >= 4:
                return facts
    return facts


def issuer_reported_issue(title):
    """Explicit title claims only; caller must check market/session alignment."""
    issuers = catalyst_entities(title)
    if len(issuers) != 1 or _EXTENDED.search(title) or _PREVIEW.search(title):
        return ""
    issues = []
    if re.search(r"\b(?:revenue|earnings|sales|profit)\s+miss(?:es|ed)?\b|(?:실적|매출|이익).{0,12}(?:기대|예상).{0,6}(?:하회|미달)", title, re.I):
        issues.append("실적 기대 미달 보도")
    if (re.search(r"\bcapex\b|capital (?:expenditure|spend)|설비투자", title, re.I)
            and re.search(r"jitters|fears?|concerns?|worr|burden|부담|우려", title, re.I)):
        issues.append("설비투자 부담")
    if (re.search(r"free cash flow|\bFCF\b|잉여.?현금", title, re.I)
            and re.search(r"negative|outflow|cash burn|declin|deteriorat|적자|악화|감소", title, re.I)):
        issues.append("잉여현금흐름 악화 보도")
    return _ISSUERS[issuers[0]][0] + " " + "·".join(issues) + "(제목 기준)" if issues else ""


def after_close_catalysts(rows, *, closed_end, now, exposures=(), limit=4):
    """Pure selection for headline/story use, independent of regular-close facts.

    Input may combine session/next-session/precision rows; ISO publication time
    must satisfy actual closed_end < published <= now. This does not infer an
    event time, price change, earnings surprise or causality from publication.
    source_keys match report_evidence.news_article_key for deduplication/citation.
    """
    now, end = _now(now), _stamp(closed_end)
    if end is None or end >= now:
        return []
    try:
        limit = max(0, min(int(limit), 4))
    except (TypeError, ValueError):
        limit = 4
    if not limit:
        return []
    from stock_lab_core.report_evidence import news_article_key
    from stock_lab_core.today_news import _us_close_recap

    selected, seen = [], set()
    tickers = _tickers(exposures)
    for raw in islice(rows or (), 240):
        if not isinstance(raw, Mapping):
            continue
        title = str(raw.get("title") or "")
        published = _stamp(raw.get("published_at") or raw.get("_pub_dt") or raw.get("published"))
        issuers = catalyst_entities(title)
        topics = catalyst_topics(title)
        link = str(raw.get("link") or raw.get("url") or "")
        try:
            parsed = urlsplit(link)
            safe = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            safe = False
        if (not safe or not published or not end < published <= now or not issuers or not topics or
                raw.get("market") in {"KR", "CA", "CN", "JP", "EU", "ASIA"} or
                ((raw.get("is_close_wrap") or raw.get("retrospective_close_wrap") or
                  _us_close_recap(title, published, {"end": end.isoformat()})) and not _EXTENDED.search(title))):
            continue
        if _PREVIEW.search(title):
            continue
        key = news_article_key(raw)
        if key in seen:
            continue
        seen.add(key)
        body = []
        if raw.get("body_status") == "verified":
            body_time, modified = _stamp(raw.get("body_published_at")), _stamp(raw.get("body_modified_at"))
            if body_time and modified and end < body_time <= now and body_time <= modified <= now:
                body = [deepcopy(f) for f in raw.get("body_facts", [])
                        if f.get("subject_ticker") in issuers and f.get("topic") in {t[0] for t in _TOPICS}]
        topics = list(dict.fromkeys([*topics, *(f["topic"] for f in body)]))
        labels = [label for topic, _, label in _TOPICS if topic in topics]
        reaction = extended_stock_reaction(title)
        links = [item for ticker in tickers for item in constituent_links(title, ticker, now=now, published_at=published)]
        label = "시간외 하락 보도" if reaction == "reported_extended_decline" else "시간외 상승 보도" if reaction == "reported_extended_rise" else "마감 이후 기업 보도"
        summary = ", ".join(_ISSUERS[t][0] for t in issuers) + " " + label + " · " + "·".join(labels[:3])
        if "options_activity" in topics:
            summary += " (옵션 거래만으로 방향·매매 의도 확정 불가)"
        selected.append(dict(summary=summary, issuers=issuers, topics=topics, reaction=reaction,
            timing_scope="after_close", closed_end=end.isoformat(), published_at=published.isoformat(),
            published_at_kst=published.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
            evidence_level="verified_body" if body else "headline_only", body_facts=body,
            source_keys=[key], sources=[dict(title=title, link=link, publisher=str(raw.get("publisher") or ""), published_at=published.isoformat())],
            direct_exposures=[t for t in tickers if ("GOOGL" if t == "GOOG" else t) in issuers],
            constituent_links=links, prior_close_cause=False, price_contribution_verified=False,
            caveat="정규장 종가 원인 아님 · 보도상 재료와 실제 시간외 가격은 별도 확인"))
    selected.sort(key=lambda row: (not bool(row["direct_exposures"] or row["constituent_links"]),
                                  0 if "capex_cash_flow" in row["topics"] else 1 if "guidance" in row["topics"] else 2,
                                  len(row["issuers"]),
                                  row["reaction"] == "unconfirmed", -_stamp(row["published_at"]).timestamp()))
    # Reserve a slot for each issuer before allowing several publishers' same story.
    diverse, covered = [], set()
    for row in selected:
        if set(row["issuers"]) - covered:
            diverse.append(row)
            covered.update(row["issuers"])
    return (diverse + [row for row in selected if row not in diverse])[:limit]
