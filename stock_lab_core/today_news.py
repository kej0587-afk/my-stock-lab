"""Today dashboard news plans and beginner-friendly quality scoring."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone, timedelta
from email.utils import parsedate_to_datetime
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.result_cache import cache_result

register_loaded_source(__name__, __file__)


TODAY_MARKET_STORY_RSS_PLAN = [
    {
        "category": "국채/유동성",
        "query": '"Treasury buyback" OR "Treasury repurchase" OR refunding OR "long-dated Treasury" OR "Treasury liquidity"',
    },
    {
        "category": "반도체·AI",
        "query": 'NVIDIA OR Micron OR DRAM OR HBM OR "AI chip" OR semiconductor OR "Meta Compute" OR "excess AI compute" OR CXMT OR "SK Hynix buyback" OR "SK hynix share cancellation"',
    },
    {
        "category": "반도체·AI 리스크",
        "query": '"Meta" "excess AI compute" OR "surplus compute" OR "Apple" CXMT OR "Chinese memory chips" OR "DRAM selloff" OR "memory stocks"',
    },
    {
        "category": "바이오·헬스케어",
        "query": 'Moderna vaccine OR "skin cancer vaccine" OR melanoma vaccine OR "clinical trial" biotech',
    },
    {
        "category": "지정학",
        "query": 'Iran ceasefire OR "Middle East" peace OR Taiwan defense OR Strait',
    },
    {
        "category": "매크로/중국",
        "query": 'China industrial production retail sales unemployment fixed asset investment',
    },
    {
        "category": "외환/금리",
        "query": 'BOJ OR RBA OR FOMC OR "dollar yen" OR "Treasury yields"',
    },
    {
        "category": "에너지/해운",
        "query": 'oil prices OR Hormuz shipping OR tanker OR PEMEX OR energy market',
    },
    {
        "category": "원자재/금속",
        "query": '"gold prices" OR "copper prices" OR "lithium carbonate" OR 금값 OR 구리 OR 탄산리튬',
    },
    {
        "category": "실적/대장주",
        "query": 'TSMC revenue OR Oracle earnings OR Adobe earnings OR "AI demand" OR "earnings beat" OR "earnings miss"',
    },
    {
        "category": "우주/항공",
        "query": 'SpaceX OR Starlink OR satellite OR aerospace',
    },
    {
        "category": "정책/규제",
        "query": 'EU carbon border adjustment OR tech regulation OR banking regulation',
    },
    {
        "category": "금융·은행",
        "query": 'Morgan Stanley OR CFTC OR banking regulation OR crypto trust OR financial markets',
    },
    {
        "category": "암호화폐",
        "query": 'Bitcoin OR Ethereum OR crypto ETF OR Franklin Templeton bitcoin ETF OR K33',
    },
    {
        "category": "건설·인프라",
        "query": 'Hyundai Rotem OR railway contract OR infrastructure order OR Morocco rail maintenance',
    },
]


TODAY_BREAKING_STORY_RSS_PLAN = [
    {
        "category": "핵심 속보",
        "query": '"무역수지" OR "반도체 수출" OR "exports" semiconductor Korea',
    },
    {
        "category": "핵심 속보",
        "query": '"호르무즈" OR "Hormuz" OR "Iran" oil shipping',
    },
    {
        "category": "핵심 속보",
        "query": '"CPI" OR "FOMC" OR "Federal Reserve" OR "ECB" OR "BOJ"',
    },
    {
        "category": "핵심 속보",
        "query": 'TSMC revenue OR Oracle earnings OR Adobe earnings OR "AI demand"',
    },
    {
        "category": "핵심 속보",
        "query": '"SK하이닉스" "자사주" "소각"',
    },
    {
        "category": "핵심 속보",
        "query": '"SK Hynix" ("share cancellation" OR buyback OR "shareholder return")',
    },
    {
        "category": "핵심 속보",
        "query": 'Moderna melanoma vaccine OR "Moderna skin cancer vaccine" OR "mRNA cancer vaccine"',
    },
    {
        "category": "핵심 속보",
        "query": '"모더나" "피부암" "백신" OR "모더나" "임상"',
    },
    {
        "category": "핵심 속보",
        "query": '"Nasdaq" rally catalyst OR "Nasdaq" positive catalyst OR "뉴욕증시" "나스닥" "호재"',
    },
    {
        "category": "핵심 속보",
        "query": '"Treasury buyback" "long-dated" OR "장기 국채" "바이백"',
    },
    {
        "category": "핵심 속보",
        "query": '"Micron" rebound OR "memory stocks" rebound OR "메모리주" "반등"',
    },
]


def market_story_title_key(title, publisher="") -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip().lower())
    text = re.sub(r"\s+-\s+[^-]{2,80}$", "", text)
    pub = re.sub(r"\s+", " ", str(publisher or "").strip().lower())
    return f"{text}|{pub}"


def market_story_pub_dt(item):
    raw = item.findtext("pubDate", "") or item.findtext("published", "")
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        return None


def format_market_story_pub_dt(dt) -> str:
    if dt is None:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst_dt = dt.astimezone(timezone(timedelta(hours=9)))
        return kst_dt.strftime("%m/%d %H:%M")
    except Exception:
        return ""


def _fetch_google_news_rss_rows(plans, selected_categories=(), per_plan=2, days=2, default_category="시장") -> list[dict]:
    selected = set(selected_categories or [])
    per_plan = max(1, min(int(per_plan or 2), 4))
    days = max(1, min(int(days or 2), 7))
    rows = []
    seen = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for plan in plans:
        category = str(plan.get("category", default_category))
        if selected and category not in selected:
            continue
        query = f"{plan.get('query', '')} when:{days}d"
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        accepted = 0
        try:
            req = urllib.request.Request(url, headers=headers)
            root = ET.fromstring(urllib.request.urlopen(req, timeout=5).read())
            items = root.findall("./channel/item")
        except Exception:
            items = []

        for item in items:
            title = html.unescape(str(item.findtext("title", "") or "").strip())
            link = str(item.findtext("link", "") or "").strip()
            publisher = html.unescape(str(item.findtext("source", "구글 뉴스") or "구글 뉴스").strip())
            key = market_story_title_key(title, publisher)
            if not title or key in seen:
                continue
            seen.add(key)
            pub_dt = market_story_pub_dt(item)
            source_node = item.find("source")
            candidate = {
                "market_category": category,
                "title": title,
                "link": link,
                "publisher": publisher,
                "published": format_market_story_pub_dt(pub_dt),
                "published_at": pub_dt.isoformat() if pub_dt else "",
                "publisher_url": source_node.attrib.get("url", "") if source_node is not None else "",
                "source": "Google News RSS",
            }
            from stock_lab_core.report_evidence import curate_news
            checked = curate_news([candidate], limit=1)
            if not checked:
                continue
            candidate["market_category"] = checked[0]["category"]
            rows.append(candidate)
            accepted += 1
            if accepted >= per_plan:
                break
    return rows


def fetch_today_market_story_news(selected_categories=(), per_category=2, days=2) -> list[dict]:
    return _fetch_google_news_rss_rows(
        TODAY_MARKET_STORY_RSS_PLAN,
        selected_categories=selected_categories,
        per_plan=per_category,
        days=days,
        default_category="시장",
    )


def fetch_today_breaking_story_news(days=2, per_query=1) -> list[dict]:
    return _fetch_google_news_rss_rows(
        TODAY_BREAKING_STORY_RSS_PLAN,
        selected_categories=(),
        per_plan=per_query,
        days=days,
        default_category="핵심 속보",
    )


_NEWS_KST = timezone(timedelta(hours=9))
_SESSION_MARKETS = {
    "US": {
        "timezone": "America/New_York", "open": time(9, 30), "close": time(16),
        "query": '("U.S. stocks" OR "Wall Street" OR Nasdaq OR "S&P 500")',
        "wrap": '("stocks close" OR "Wall Street closes" OR "market wrap" OR "closing bell")',
        "locale": "hl=en-US&gl=US&ceid=US:en",
    },
    "KR": {
        "timezone": "Asia/Seoul", "open": time(9), "close": time(15, 30),
        "query": '(코스피 OR 코스닥 OR "한국 증시" OR "국내 증시")',
        "wrap": '("증시 마감" OR "코스피 마감" OR "코스닥 마감" OR "마감 시황")',
        "locale": "hl=ko&gl=KR&ceid=KR:ko",
    },
}
_SESSION_QUERY_LIMIT = 16
_SESSION_RSS_TIMEOUT = 5
_SESSION_RSS_MAX_BYTES = 512 * 1024
_SESSION_ROW_LIMIT = 60
_CLOSE_WRAP = re.compile(
    r"(?:증시|코스피|코스닥).{0,60}마감|마감.{0,20}(?:시황|증시|코스피|코스닥)|"
    r"\[마켓뷰\].{0,100}(?:코스피|코스닥).{0,30}(?:반등 성공|하락 종료)|"
    r"\b(?:stocks?|markets?|wall street|nasdaq|s&p).{0,80}\bclos(?:e[sd]?|ing)\b|"
    r"\bmarket wrap\b|\bclosing bell\b", re.I,
)
_KR_HEADLINE_SUBJECT = re.compile(
    r"^\s*(?:(?:\[[^]]+\]|\([^)]*\))\s*)*"
    r"(?:코스피|코스닥|\bKOSPI\b|\bKOSDAQ\b|(?:한국|국내)\s*(?:증시|주식시장))"
    r"(?=\s|[,，:·…]|$|[은는이가]\s)", re.I,
)


def _news_timestamp(value):
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        # A date alone or a UI label such as 10/17 04:00 cannot locate an event.
        if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", raw):
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt.replace(tzinfo=_NEWS_KST) if dt.tzinfo is None else dt


def _news_now(now):
    if now is None:
        return datetime.now(_NEWS_KST)
    dt = _news_timestamp(now)
    if dt is None:
        raise ValueError("now must be an ISO timestamp or datetime")
    return dt


def _split_news_sessions(sessions, current_sessions):
    if not isinstance(sessions, Mapping):
        return sessions, current_sessions
    closed = dict(sessions)
    active = {}
    for market, session in sessions.items():
        if isinstance(session, Mapping) and session.get("is_active") is True:
            active[market] = session
            closed.pop(market)
    if current_sessions is not None and not isinstance(current_sessions, Mapping):
        return closed, current_sessions
    active.update(current_sessions or {})
    return closed, active or None


def _session_news_windows(sessions, now):
    windows, missing = [], []
    if not isinstance(sessions, Mapping) or not sessions:
        return windows, ["시장별 기준 거래일과 이전 거래일 미제공"]
    for market, session in sessions.items():
        if market not in _SESSION_MARKETS:
            missing.append("지원하지 않는 시장의 뉴스 시간창 제외")
            continue
        if not isinstance(session, Mapping):
            missing.append(f"{market}: date/previous_date가 있는 세션 정보 필요")
            continue
        try:
            current = date.fromisoformat(str(session.get("date", "")))
            previous = date.fromisoformat(str(session.get("previous_date", "")))
            if previous >= current or current.weekday() >= 5 or previous.weekday() >= 5:
                raise ValueError
        except (ValueError, TypeError):
            missing.append(f"{market}: 기준일/이전 거래일 누락 또는 유효하지 않은 거래일 순서")
            continue
        spec = _SESSION_MARKETS[market]
        zone = ZoneInfo(spec["timezone"])
        start = datetime.combine(previous, spec["close"], zone)
        close = datetime.combine(current, spec["close"], zone)
        if close > now:
            missing.append(f"{market}: 기준 거래일 정규장 미마감")
            continue
        # Capture the full following calendar day, not the next trading day.
        capture_end = datetime.combine(current + timedelta(days=2), time(), zone)
        windows.append({
            "market": market, "date": current.isoformat(), "previous_date": previous.isoformat(),
            "timezone": spec["timezone"], "start": start.isoformat(), "end": close.isoformat(),
            "capture_end": capture_end.isoformat(), "next_session_end": now.astimezone(zone).isoformat(),
        })
    return windows, missing


def _current_news_windows(sessions, now):
    windows, missing = [], []
    if sessions is None:
        return windows, missing
    if not isinstance(sessions, Mapping):
        return windows, ["진행 세션은 시장별 date/previous_date 정보 필요"]
    for market, session in sessions.items():
        try:
            spec = _SESSION_MARKETS[market]
            current = date.fromisoformat(str(session["date"]))
            previous = date.fromisoformat(str(session["previous_date"]))
            if previous >= current or current.weekday() >= 5 or previous.weekday() >= 5:
                raise ValueError
            zone = ZoneInfo(spec["timezone"])
            start = datetime.combine(previous, spec["close"], zone)
            opening = (_news_timestamp(session["open_at"]) if session.get("open_at")
                       else datetime.combine(current, spec["open"], zone))
            close = (_news_timestamp(session["close_at"]) if session.get("close_at")
                     else datetime.combine(current, spec["close"], zone))
            if (opening is None or close is None or not start < opening <= now < close
                    or opening.astimezone(zone).date() != current or close.astimezone(zone).date() != current):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            missing.append(f"{market}: 유효한 진행 중 거래일/이전 거래일/개폐장 시각 필요")
            continue
        windows.append({"market": market, "date": current.isoformat(),
                        "previous_date": previous.isoformat(), "timezone": spec["timezone"],
                        "start": start.isoformat(), "open_at": opening.isoformat(),
                        "scheduled_close": close.isoformat(), "end": now.astimezone(zone).isoformat(),
                        "capture_end": now.astimezone(zone).isoformat(),
                        "session_status": "in_progress", "is_closed": False})
    return windows, missing


def _publication_timing(row, published, market):
    zone = _SESSION_MARKETS[market]["timezone"]
    local = published.astimezone(ZoneInfo(zone))
    minute = local.hour * 60 + local.minute
    opening, closing = (540, 930) if market == "KR" else (570, 960)
    row.update(published_at_kst=published.astimezone(_NEWS_KST).isoformat(),
               market_local_published_at=local.isoformat(), news_timing_market=market,
               news_timing_timezone=zone,
               news_timing="장전 보도" if minute < opening else "장중 보도" if minute < closing else "마감 후 보도")
    # Display layers may explicitly discuss the Korean session even when a
    # semiconductor article concerns US issuers. Keep both clocks available.
    kst = published.astimezone(_NEWS_KST)
    kr_minute = kst.hour * 60 + kst.minute
    row["kr_news_timing"] = "장전 보도" if kr_minute < 540 else "장중 보도" if kr_minute < 930 else "마감 후 보도"


def _news_sort_key(row):
    from stock_lab_core.news_priority import market_news_priority
    prefer_wrap = row["news_bucket"] == "session_news" and row["is_close_wrap"]
    return (-market_news_priority(row), not prefer_wrap, -_news_timestamp(row["published_at"]).timestamp())


def _us_close_recap(title, published, window):
    """Allow an explicit US recap until the next weekday open, not new causes."""
    if (not window or _KR_HEADLINE_SUBJECT.search(title)
            or not re.search(r"(?:美|미국)\s*(?:증시|주식시장)|"
                             r"(?:美|미국)\s*(?:AI|반도체)(?:[·ㆍ/\s]+(?:AI|반도체))*주?\s*(?:중심\s*)?(?:급락|하락|급등|상승|반등|쇼크|약세|강세)|"
                             r"뉴욕|월가|Wall Street|\bU\.?S\.?\b|Nasdaq", title, re.I)):
        return False
    if re.search(r"시간외|장후|after.hours|extended (?:trading|hours)|post.(?:close|market)|선물|예정|다음주", title, re.I):
        return False
    from stock_lab_core.report_presentation import is_preopen_outlook
    if is_preopen_outlook({"title": title, "market": "US"}):
        return False
    close = datetime.fromisoformat(window["end"])
    explicit = bool(re.search(r"마감|급락 쇼크|\bclos(?:e[sd]?|ing)\b|market wrap|(?:美|미국|뉴욕)\s*증시\s*덮친.{0,25}AI\s*차입\s*우려", title, re.I))
    # A regular-session price recap need not contain the word 'close'. Only
    # accept such titles immediately after this supplied, confirmed close.
    near_close = close < published <= close + timedelta(hours=2)
    market_prices = bool(re.search(r"\bstocks?\b|\bshares\b|Nasdaq|Wall Street|나스닥|증시", title, re.I)
                         and re.search(r"반등|급등|급락|하락|상승|혼조|%[↑↓]|\bmixed\b|\brebound|\brecover|\bbounc|\brall|\bgain|\bclimb|\bfall|\bdeclin|\bslump|\bplung|\btumbl|\bhigher|\blower", title, re.I))
    # A named US market move is a recap even when publication is delayed.
    # Do not apply this to a single company's newly released earnings.
    market_subject = bool(re.search(r"(?:\bUS|\bU\.S\.)\s+(?:stocks?|equities|equity markets?)\s+(?:slump|fall|slide|drop|rise|rall|end|clos)|\bWall Street\s+(?:slump|fall|slide|drop|rise|rall|end|clos)", title, re.I))
    if not explicit and not ((near_close or market_subject) and market_prices):
        return False
    next_day = close.date() + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    next_open = datetime.combine(next_day, time(9, 30), ZoneInfo("America/New_York"))
    return close < published < next_open


_HEADLINE_MARKETS = {
    "EU": re.compile(r"\bEurope(?:an)?(?:'s)?\s+(?:stocks?|shares?|markets?|earnings)|유럽\s*증시", re.I),
    "JP": re.compile(r"日\s*증시|일본\s*증시|닛케이|Japan(?:ese)?\s+(?:shares|stocks)|\bNikkei\b", re.I),
    "CN": re.compile(r"中\s*증시|중국\s*증시|Chinese\s+(?:shares|stocks)", re.I),
    "KR": re.compile(r"코스피|코스닥|\bKOSPI\b|\bKOSDAQ\b|(?:한국|국내)\s*(?:증시|주식시장)|한국은행|금융통화위원회|\bBank of Korea\b", re.I),
    "US": re.compile(r"(?:미국|뉴욕|美)\s*증시|나스닥|\bNasdaq\b|\bWall Street\b|"
                     r"S&P\s*500|\bU\.?S\.?\s+(?:(?:energy|consumer|healthcare|health care|biotech|technology|tech|software|"
                     r"semiconductor|chip|memory|communication services|utilities|bank|financial|industrial)\s+)?"
                     r"(?:stocks?|shares?|equities|stock market)\b|\bCoreWeave\b|코어위브", re.I),
}


def _session_article_keys(row):
    title = str(row.get("title") or "").strip()
    publisher = str(row.get("publisher") or "").strip()
    if publisher:
        title = re.sub(r"\s+[-|–—]\s*" + re.escape(publisher) + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).casefold()
    raw_link = str(row.get("link") or "")
    try:
        link = urllib.parse.urlsplit(raw_link)
    except ValueError:
        return raw_link, title
    query = urllib.parse.urlencode([(key, value) for key, value in urllib.parse.parse_qsl(link.query, keep_blank_values=True)
                                   if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}])
    return urllib.parse.urlunsplit((link.scheme, link.netloc.lower(), link.path, query, "")), title


def _resolve_query_news_market(raw, windows):
    """A search region is provenance, not the subject of a returned article."""
    row = dict(raw)
    query_market = str(row.get("query_market") or "").strip().upper()
    if not query_market and row.get("source") != "Google News RSS":
        return row
    row["query_market"] = query_market or str(row.get("market") or "")
    title = str(row.get("title") or row.get("제목") or "")
    publisher = str(row.get("publisher") or "").strip()
    if publisher:
        title = re.sub(r"\s+[-|–—]\s*" + re.escape(publisher) + r"\s*$", "", title, flags=re.I)
    if (row.get("query_topics") or str(row.get("market_category") or "").startswith("섹터:")
            or row.get("market_category") == "기업 재료"):
        from stock_lab_core.report_presentation import sector_news_topics
        # Search packs describe retrieval, not evidence about this headline.
        topics = sector_news_topics("", sector_name=title)
        row["market_category"] = "섹터:" + ",".join(sorted(topics)) if topics else "시장"
    published = _news_timestamp(row.get("published_at") or row.get("published"))
    markets = [market for market, pattern in _HEADLINE_MARKETS.items() if pattern.search(title)]
    if re.match(r"^Asia(?:n)?(?:[- ]Pacific)?\s+(?:shares|stocks|markets)\b", title, re.I):
        row.update(market="ASIA", market_basis="explicit_headline_subject")
    elif _KR_HEADLINE_SUBJECT.search(title) or re.search(r"(?:美|미국)보다.{0,25}국장|국장.{0,25}(?:급락|하락|반등|상승)", title):
        row.update(market="KR", market_basis="explicit_headline_subject")
    elif published and _us_close_recap(title, published, windows.get("US")):
        row.update(market="US", market_basis="explicit_us_recap")
    elif len(markets) == 1:
        row.update(market=markets[0], market_basis="explicit_headline_market")
    elif len(markets) > 1:
        row.update(market="", market_basis="ambiguous_headline_markets")
    elif row.get("query_kind") == "issuer_catalyst":
        from stock_lab_core.catalyst_news import matches_catalyst_query
        if matches_catalyst_query(title, row):
            row.update(market="US", market_basis="explicit_issuer_catalyst")
        else:
            row.update(market="", market_basis="unconfirmed_issuer_subject")
    elif re.search(r"엔비디아|\bNvidia\b|아마존|\bAmazon\b|\bAWS\b|메타\b|\bMeta\b|마이크론|\bMicron\b", title, re.I):
        # A counterparty mention does not make a domestic supplier a US issuer.
        if re.match(r"^(?:\[[^]]+\]\s*)?(?:엔비디아|Nvidia\b|아마존|Amazon\b|AWS\b|메타\b|Meta\b|마이크론|Micron\b)", title, re.I):
            row.update(market="US", market_basis="explicit_headline_market")
        elif row["query_market"] == "US":
            row.update(market="", market_basis="unconfirmed_issuer_subject")
        else:
            row.setdefault("market_basis", "search_query_only")
    else:
        row.setdefault("market_basis", "search_query_only")
    return row


def partition_session_market_news(rows, sessions, *, now=None, current_sessions=None) -> dict:
    """Pure time partition; callers curate sources/events separately.

    ``sessions`` maps KR/US to ISO ``date`` and actual ``previous_date``.
    Windows use regular close times in each exchange timezone (including US DST).
    ``start`` is exclusive and ``end`` (the reference close) inclusive.
    ``capture_end`` is exclusive midnight after the following calendar day.
    KR same-date post-close publications are current-session context regardless
    of title. They are not automatically evidence of a pre-close cause.
    US closing wraps retain their separate retrospective window.
    Query-derived market tags are corrected by explicit index/market mentions.
    Language and publisher alone never identify the market.
    ISO timestamps without an offset use KST, matching report_evidence.curate_news.
    Optional ``current_sessions`` supplies explicit live date/previous_date pairs
    (and optional open_at/close_at). Live rows are returned in current_session_news,
    with session_status=in_progress and is_closed=False. No live date is inferred.
    A sessions entry with is_active=True is equivalent to current_sessions.
    """
    from stock_lab_core.catalyst_news import is_consumer_banking_promo

    now = _news_now(now)
    sessions, current_sessions = _split_news_sessions(sessions, current_sessions)
    windows, missing = _session_news_windows(sessions, now)
    current_windows, current_missing = _current_news_windows(current_sessions, now)
    if current_windows and not sessions:
        missing = []
    missing.extend(current_missing)
    by_market = {window["market"]: window for window in windows}
    current_by_market = {window["market"]: window for window in current_windows}
    all_markets = by_market.keys() | current_by_market.keys()
    result = {"session_news": [], "next_session_news": [], "current_session_news": [], "other_market_news": [],
              "windows": windows, "current_windows": current_windows, "missing": missing}
    rejected = Counter()
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    for raw in rows if rows is not None else ():
        if not isinstance(raw, Mapping):
            rejected["뉴스 행 형식 오류"] += 1
            continue
        if is_consumer_banking_promo(raw.get("title") or raw.get("제목")):
            rejected["소비자 예적금 판촉"] += 1
            continue
        raw = _resolve_query_news_market(raw, by_market)
        market = str(raw.get("market") or raw.get("region") or "").strip().upper()
        region = str(raw.get("region") or "").strip().upper()
        if market in {"JP", "CN", "ASIA", "EU"}:
            published = _news_timestamp(raw.get("published_at") or raw.get("published"))
            if published and now - timedelta(days=7) <= published <= now:
                result["other_market_news"].append(dict(raw, market=market, published_at=published.isoformat(),
                    session_date="", news_bucket="other_market_news", is_close_wrap=False,
                    news_timing="다른 시장 맥락 · 한국/미국 종가 원인 아님"))
            continue
        if market not in all_markets or (region and region != market):
            rejected["명시된 시장 또는 해당 시장의 유효한 세션 없음"] += 1
            continue
        published = _news_timestamp(raw.get("published_at") or raw.get("published") or raw.get("시간"))
        if published is None:
            rejected["뉴스 발행시각 누락/해석 불가"] += 1
            continue
        live = current_by_market.get(market)
        closed = by_market.get(market)
        # Prior-day Korean post-close reports keep their publication session,
        # even when their headline does not contain the word "close".
        prior_kr_close = bool(market == "KR" and closed
                              and published.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat() == closed["date"]
                              and published >= datetime.fromisoformat(closed["end"]))
        if live and not prior_kr_close and datetime.fromisoformat(live["start"]) < published <= now:
            title = str(raw.get("title") or raw.get("제목") or "")
            from stock_lab_core.report_presentation import news_theme, sector_news_topics
            targeted = set(raw.get("query_topics") or ()) & set(sector_news_topics("", sector_name=title))
            if (market == "US" and raw.get("market_basis") == "search_query_only"
                    and not targeted and not news_theme(title)
                    and not re.search(r"\b(?:AI|chip|tech|semiconductor)\s+(?:stocks|shares)|반도체|AI.{0,8}(?:주|투자)", title, re.I)):
                rejected["미국 진행 세션과 직접 관련 없는 검색 결과"] += 1
                continue
            # A Friday recap retrieved during Monday's live session still
            # belongs to Friday, when that closed session was supplied.
            # A close recap cannot describe a session that is still open,
            # including a previous close republished after today's opening bell.
            prior_wrap = bool(_CLOSE_WRAP.search(title)) or (market == "US" and _us_close_recap(title, published, by_market.get("US")))
            if not prior_wrap:
                row = dict(raw, market=market, published_at=published.isoformat(),
                           session_date=live["date"], news_bucket="current_session_news",
                           session_status="in_progress", is_closed=False,
                           is_close_wrap=False, retrospective_close_wrap=False, post_close_context=False)
                _publication_timing(row, published, market)
                if published.astimezone(ZoneInfo(live["timezone"])).date().isoformat() == live["date"]:
                    row["news_timing"] = "장중 보도" if published >= datetime.fromisoformat(live["open_at"]) else "장전 보도"
                result["current_session_news"].append(row)
                continue
        if market not in by_market:
            rejected["뉴스 시간창 밖 또는 이전 거래일 마감 회고"] += 1
            continue
        window = by_market[market]
        title = str(raw.get("title") or raw.get("제목") or "")
        us_recap = _us_close_recap(title, published, by_market.get("US"))
        if us_recap:
            market, window = "US", by_market["US"]
        start = datetime.fromisoformat(window["start"])
        close = datetime.fromisoformat(window["end"])
        if published <= start or published > now:
            rejected["뉴스 시간창 밖 또는 미래 발행시각"] += 1
            continue
        # The window starts at the supplied previous session's confirmed close.
        if market == "US" and _us_close_recap(title, published, {"end": window["start"]}):
            row = dict(raw, market=market, published_at=published.isoformat(),
                       session_date=window["previous_date"], news_bucket="other_market_news",
                       is_close_wrap=True, retrospective_close_wrap=True,
                       post_close_context=False, session_status="closed", is_closed=True)
            _publication_timing(row, published, market)
            row["news_timing"] = "이전 미국장 마감 회고 · 현재 종가 원인 아님"
            result["other_market_news"].append(row)
            continue
        wrap = bool(_CLOSE_WRAP.search(str(raw.get("title") or raw.get("제목") or "")))
        title = str(raw.get("title") or raw.get("제목") or "")
        if re.search(r"post.(?:close|market)|after.hours|extended (?:trading|hours)|시간외|장후|마감 후", title, re.I):
            wrap = False
        same_date = published.astimezone(ZoneInfo(window["timezone"])).date().isoformat() == window["date"]
        if wrap and published <= close and not same_date:
            rejected["이전 거래일 마감 회고"] += 1
            continue
        retrospective = us_recap or (wrap and same_date and close < published <= close + timedelta(hours=2))
        kr_after_close = market == "KR" and same_date and published >= close
        bucket = "session_news" if published <= close or retrospective or kr_after_close else "next_session_news"
        row = dict(raw, market=market, published_at=published.isoformat(),
                   session_date=window["date"], news_bucket=bucket,
                   is_close_wrap=wrap or us_recap, retrospective_close_wrap=retrospective,
                   post_close_context=kr_after_close, session_status="closed", is_closed=True)
        _publication_timing(row, published, market)
        if us_recap:
            row["news_timing"] = "미국장 마감 회고 · 기사 주장"
        if us_recap and region:
            row["region"] = "US"
        result[bucket].append(row)
    for bucket in ("session_news", "next_session_news"):
        result[bucket].sort(key=_news_sort_key)
        for market in by_market:
            if not any(row["market"] == market for row in result[bucket]):
                missing.append(f"{market}: {'기준 세션' if bucket == 'session_news' else '종가 이후'} 뉴스 없음")
    missing.extend(f"{reason}: {count}건 제외" for reason, count in rejected.items())
    result["current_session_news"].sort(key=_news_sort_key)
    result["other_market_news"].sort(key=_news_sort_key)
    for market in current_by_market:
        if not any(row["market"] == market for row in result["current_session_news"]):
            missing.append(f"{market}: 진행 세션 뉴스 없음")
    return result


def _session_query_specs(windows, categories, now, *, sector_rows=(), held_exposures=()):
    from stock_lab_core.report_presentation import sector_news_query, sector_news_topics
    from stock_lab_core.catalyst_news import exposure_catalyst_specs

    topics = {"KR": [], "US": []}
    exposures = []
    for collection in (held_exposures, sector_rows):
        if hasattr(collection, "to_dict"):
            collection = collection.to_dict("records")
        for row in collection or ():
            exposures.append(row)
            ticker = str(row.get("Ticker") or row.get("ticker") or row.get("티커") or "").strip().upper()
            market = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
            name = str(row.get("섹터") or row.get("종목명") or row.get("name") or "")
            for topic in sector_news_topics(ticker, sector_name=name):
                if topic not in topics[market]:
                    topics[market].append(topic)
    requested = tuple(dict.fromkeys(categories or ()))
    available = {plan["category"]: plan["query"] for plan in TODAY_MARKET_STORY_RSS_PLAN}
    selected = [(category, available[category]) for category in requested if category in available][:3]
    plans = [("마감 시황", None)] + (selected if requested else [("시장", "")])
    groups = []
    for window in windows:
        specs = []
        market = window["market"]
        market_spec = _SESSION_MARKETS[market]
        start = datetime.fromisoformat(window["start"])
        capture_end = datetime.fromisoformat(window["capture_end"])
        ranges = [(start, min(capture_end, now))]
        if window.get("is_closed") is False:
            # A broad Friday-to-Monday search can fill all 80 RSS slots with
            # Friday selloff recaps. Give the active exchange day its own query.
            local_midnight = now.astimezone(ZoneInfo(window["timezone"])).replace(hour=0, minute=0, second=0, microsecond=0)
            ranges = [(max(start, local_midnight), now)]
        if now > capture_end:
            ranges.append((capture_end, now))
        for lower, upper in ranges:
            if lower >= upper:
                continue
            market_plans = plans
            if market == "KR":
                market_plans = [("마감 시황", "코스피 마감"), ("바이오/화장품", "(바이오 OR 화장품) (급등 OR 강세)"), *plans[1:]]
            else:
                market_plans = [("마감 시황", "미국증시 마감"), *plans]
                if window.get("is_closed") is False:
                    market_plans = [("장중 시황", "Wall Street stocks"),
                                    ("반도체·AI", "AI stocks"),
                                    ("반도체·AI", "semiconductor stocks"), *market_plans]
            if topics[market]:
                # Packs share a request, leaving every market/session a turn
                # within the global budget even when many exposures are held.
                pack_size = max(3, (len(topics[market]) + 2) // 3)
                packs = [topics[market][index:index + pack_size] for index in range(0, len(topics[market]), pack_size)]
                common = ('(AI OR CoreWeave OR neocloud) (credit OR debt OR financing OR rebound) OR "Treasury yields" OR "oil prices"'
                          if market == "US" else '"AI 신용" OR "AI 차입" OR "외국인 기관" OR 금리 OR 환율')
                company_plans = []
                if market == "US" and set(topics[market]) & {"semiconductor", "memory", "technology", "software"}:
                    company_plans = [("기업 재료", "(엔비디아 OR 아마존 OR AWS OR 메타 OR 마이크론 OR 코어위브) (칩 OR 공급 OR 자금조달 OR 실적)")]
                market_plans = [("장중 시황" if window.get("is_closed") is False else "마감 시황",
                                 "Wall Street stocks" if market == "US" and window.get("is_closed") is False
                                 else "미국증시 마감" if market == "US" else "코스피 마감"),
                                ("시장 공통 배경", common),
                                *[("섹터:" + ",".join(pack), " OR ".join("(" + sector_news_query(topic, market) + ")" for topic in pack))
                                  for pack in packs], *company_plans, *selected]
            for category, query in market_plans:
                terms = market_spec["wrap"] if query is None else query
                # Google date predicates have calendar precision. Pad boundaries
                # and apply exact timestamps after retrieval, including midnight.
                after = (lower.astimezone(ZoneInfo(window["timezone"])).date() - timedelta(days=1)).isoformat()
                before = (upper.astimezone(ZoneInfo(window["timezone"])).date() + timedelta(days=1)).isoformat()
                korean_wrap = terms in {"코스피 마감", "미국증시 마감"}
                company_material = category == "기업 재료"
                active_direct = window.get("is_closed") is False and terms in {"Wall Street stocks", "AI stocks", "semiconductor stocks"}
                if category.startswith("섹터:") or category == "시장 공통 배경":
                    subject = '(한국 OR 국내 OR 코스피 OR 코스닥)' if market == "KR" else '(US OR "U.S." OR "Wall Street")'
                    query_text = f"{subject} ({terms})"
                else:
                    query_text = terms if korean_wrap or active_direct or company_material else f"{market_spec['query']} ({terms})" if terms else market_spec["query"]
                query_text += f" after:{after} before:{before}"
                url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query_text})
                locale = "hl=ko&gl=KR&ceid=KR:ko" if korean_wrap or company_material else market_spec["locale"]
                specs.append({"market": market, "category": category, "url": url + "&" + locale,
                              "query_topics": category.removeprefix("섹터:").split(",") if category.startswith("섹터:") else []})
        groups.append(specs)
    # Give every explicit window a turn before spending the remaining budget
    # on extra categories or the historical/latest split for one market.
    interleaved = [group[index] for index in range(max((len(group) for group in groups), default=0))
                   for group in groups if index < len(group)]
    catalysts = exposure_catalyst_specs(exposures, now=now) if any(w["market"] == "US" for w in windows) else []
    ordered = interleaved[:len(groups)] + catalysts + interleaved[len(groups):]
    unique = {}
    for spec in ordered:
        unique.setdefault(spec["url"], spec)
    return list(unique.values())[:_SESSION_QUERY_LIMIT]


def _fetch_session_rss(spec):
    from stock_lab_core.report_presentation import sector_news_topics
    from stock_lab_core.catalyst_news import matches_catalyst_query, is_consumer_banking_promo

    rows = []
    try:
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "Mozilla/5.0 StockLab"})
        with urllib.request.urlopen(request, timeout=_SESSION_RSS_TIMEOUT) as response:
            data = response.read(_SESSION_RSS_MAX_BYTES + 1)
        if len(data) > _SESSION_RSS_MAX_BYTES:
            raise ValueError("RSS response too large")
        root = ET.fromstring(data)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("not an RSS response")
        for item in root.findall("./channel/item")[:80]:
            pub_dt = market_story_pub_dt(item)
            source = item.find("source")
            title = html.unescape(str(item.findtext("title", "") or "").strip())
            publisher = html.unescape(str(item.findtext("source", "") or "").strip())
            subject = re.sub(r"\s+[-|–—]\s*" + re.escape(publisher) + r"\s*$", "", title, flags=re.I) if publisher else title
            if is_consumer_banking_promo(subject) or (spec.get("query_kind") == "issuer_catalyst" and not matches_catalyst_query(subject, spec)):
                continue
            matched_topics = set(spec.get("query_topics") or ()) & set(sector_news_topics("", sector_name=title))
            category = "섹터:" + ",".join(sorted(matched_topics)) if matched_topics else spec["category"]
            rows.append({
                "title": title,
                "link": str(item.findtext("link", "") or "").strip(),
                "publisher": html.unescape(str(item.findtext("source", "") or "").strip()),
                "publisher_url": source.attrib.get("url", "") if source is not None else "",
                "published_at": pub_dt.isoformat() if pub_dt else "",
                "published": format_market_story_pub_dt(pub_dt),
                "source": "Google News RSS", "market_category": category,
                "market": spec["market"],
                "query_market": spec["market"], "market_basis": "search_query_only",
                "query_topics": list(spec.get("query_topics") or ()),
                **({"query_kind": spec["query_kind"], "query_issuers": list(spec.get("query_issuers", ())) }
                   if spec.get("query_kind") else {}),
            })
        return rows, ""
    except Exception:
        return [], f"{spec['market']}: RSS 수집 실패"


@cache_result(ttl=300, failure_ttl=30, is_success=lambda result: bool(result[0]) and not result[1])
def _cached_session_rss(spec):
    return _fetch_session_rss(spec)


def _retrieve_session_rss(specs, *, use_cache):
    rows, failures, complete = [], Counter(), bool(specs)
    def retrieve(spec):
        # Issuer lookups are shared with precision news even in uncached reports.
        loader = _cached_session_rss if use_cache or spec.get("query_kind") == "issuer_catalyst" else _fetch_session_rss
        return loader(spec)
    with ThreadPoolExecutor(max_workers=4) as executor:
        for candidates, error in executor.map(retrieve, specs):
            rows.extend(candidates)
            complete = complete and bool(candidates) and not error
            if error:
                failures[error] += 1
    return {"rows": rows, "failures": failures, "complete": bool(complete)}


@cache_result(ttl=60, failure_ttl=0, is_success=lambda result: result["complete"])
def _cached_session_rss_batch(specs, session_key, time_bucket):
    # Cache raw retrieval only. No market classification or time-filtered rows.
    # Empty/partial batches are not retained; per-query failures still cool down.
    return _retrieve_session_rss(specs, use_cache=True)


def _session_retrieval_key(windows):
    return tuple((window["market"], window["date"], window["previous_date"], window["timezone"],
                  window["start"], window.get("open_at", ""),
                  window.get("scheduled_close", window["end"]), window.get("is_closed", True))
                 for window in windows)


def clear_session_market_news_cache():
    """Clear both RSS layers and public article caches for explicit refresh."""
    from stock_lab_core.article_context import _article, _feed

    for loader in (_cached_session_rss_batch, _cached_session_rss, _feed, _article):
        loader.clear()


def fetch_session_market_news(sessions, *, now=None, categories=(), per_category=3,
                              current_sessions=None, sector_rows=(), held_exposures=(), use_cache=False,
                              include_article_bodies=False, watched_exposures=()) -> dict:
    """Bounded market-specific RSS retrieval plus source/event curation.

    Returns the same payload as partition_session_market_news. Queries include
    absolute after/before dates, with separate historical and latest retrieval.
    At most 16 requests run with four workers, five-second socket timeouts and
    512 KiB responses. Exposure topic packs share the budget with categories.
    Cached retrieval is opt-in; time partitioning always uses the supplied now.
    Complete raw RSS batches are reused for up to 60 seconds, keyed by explicit
    market/session windows, query specs and the supplied UTC minute. Existing
    per-query 300s successes/30s failures remain underneath; no disk persistence.
    Explicit market headlines correct query tags before cross-query deduplication.
    Ambiguous cross-market results remain excluded. No sending/storage.
    current_sessions is optional and has the same contract as the pure partitioner.
    """
    from stock_lab_core.report_evidence import curate_news, _close_recap_key

    now = _news_now(now)
    sessions, current_sessions = _split_news_sessions(sessions, current_sessions)
    windows, _ = _session_news_windows(sessions, now)
    current_windows, _ = _current_news_windows(current_sessions, now)
    query_windows = current_windows + windows
    specs = _session_query_specs(query_windows, categories, now,
                                 sector_rows=sector_rows,
                                 held_exposures=[*held_exposures, *watched_exposures])
    try:
        per_category = max(1, min(int(per_category), 5))
    except (TypeError, ValueError):
        per_category = 3
    retrieved = (_cached_session_rss_batch(specs, _session_retrieval_key(query_windows),
                                          int(now.timestamp()) // 60)
                 if use_cache else _retrieve_session_rss(specs, use_cache=False))
    rows, failures = retrieved["rows"], retrieved["failures"]
    if include_article_bodies:
        from stock_lab_core.article_context import publisher_news
        # Direct publisher links permit public-body verification without decoding
        # a Google redirect or trying to access subscription-only articles.
        rows = publisher_news(sessions, now) + rows
    by_market = {window["market"]: window for window in windows}
    rows = [_resolve_query_news_market(row, by_market) for row in rows]
    from stock_lab_core.catalyst_news import constituent_links, prioritize_issuer_news, _tickers
    has_cibr = "CIBR" in _tickers(held_exposures) or "CIBR" in _tickers(sector_rows)
    if has_cibr:
        for row in rows:
            row["constituent_links"] = constituent_links(row.get("title"), "CIBR", now=now,
                                                          published_at=row.get("published_at")) if row.get("market") == "US" else []
    origins = {}
    for row in rows:
        for key in _session_article_keys(row):
            if key:
                origins.setdefault(key, set()).add(row["market"])
    for row in rows:
        if any(len(origins.get(key, ())) > 1 for key in _session_article_keys(row)):
            row.pop("market", None)
    result = partition_session_market_news(rows, sessions, now=now, current_sessions=current_sessions)
    query_issuers = {issuer for spec in specs for issuer in spec.get("query_issuers", ())}
    for bucket in ("session_news", "next_session_news", "current_session_news", "other_market_news"):
        accepted, seen, seen_links, seen_titles, counts = [], set(), set(), set(), Counter()
        recap_keys = set()
        candidates = []
        for row in result[bucket]:
            # Exact time filtering already ran. Validate each source with the
            # existing curator even for holiday windows longer than seven days.
            checked = curate_news([row], now=_news_timestamp(row["published_at"]), limit=1)
            if not checked or not checked[0].get("link"):
                continue
            candidates.append(checked[0])
        # Validate first, then reserve distinct issuer coverage before category caps.
        for clean in prioritize_issuer_news(candidates, query_issuers=query_issuers):
            # Different closing stories may name different participants/causes.
            # Deduplicate the article, not every closing story for the session.
            article_link, article_title = _session_article_keys(clean)
            event_key = article_title if clean.get("is_close_wrap") else clean["event_key"]
            event = (clean["market"], event_key)
            category = (clean["market"], clean["category"])
            link_key = (clean["market"], article_link)
            title_key = (clean["market"], article_title)
            recap = _close_recap_key(clean, clean["title"], _news_timestamp(clean["published"]))
            repeated_recap = recap is not None and recap in recap_keys
            if event in seen or link_key in seen_links or title_key in seen_titles or (counts[category] >= per_category and not repeated_recap) or len(accepted) >= _SESSION_ROW_LIMIT:
                continue
            seen.add(event)
            seen_links.add(link_key)
            seen_titles.add(title_key)
            if not repeated_recap:
                counts[category] += 1
            if recap:
                recap_keys.add(recap)
            accepted.append(clean)
        result[bucket] = accepted
        for window in current_windows if bucket == "current_session_news" else windows:
            market = window["market"]
            if not any(row["market"] == market for row in accepted):
                result["missing"].append(f"{market}: {bucket} 출처·날짜·중복 검증 후 채택 뉴스 없음")
    result["missing"].extend(f"{reason}: {count}개 쿼리" for reason, count in failures.items())
    result["news_retrieval"] = {"query_count": len(specs), "query_limit": _SESSION_QUERY_LIMIT,
                                "catalyst_query_count": sum(spec.get("query_kind") == "issuer_catalyst" for spec in specs),
                                "max_workers": 4, "cached": bool(use_cache),
                                "queried_topics": sorted({topic for spec in specs for topic in spec.get("query_topics", ())})}
    if include_article_bodies:
        from stock_lab_core.article_context import enrich_article_context
        enrich_article_context(result, now)
    available = {plan["category"] for plan in TODAY_MARKET_STORY_RSS_PLAN}
    if any(category not in available for category in categories or ()):
        result["missing"].append("알 수 없는 뉴스 카테고리 제외")
    if len(set(categories or ()) & available) > 3:
        result["missing"].append("수집 한도로 요청 카테고리 중 앞의 3개만 조회")
    return result


TODAY_ACTION_NEWS_SOURCE_SCORES = {
    "reuters": 10,
    "로이터": 10,
    "연합인포맥스": 9,
    "연합뉴스": 8,
    "서울경제": 8,
    "매일경제": 8,
    "한국경제": 8,
    "머니투데이": 7,
    "아시아경제": 7,
    "nvidia": 7,
    "yahoo finance": 6,
    "benzinga": 6,
    "벤징가": 6,
    "벤장가": 6,
    "barchart": 6,
    "the motley fool": 5,
    "글로벌이코노믹": 5,
    "경향신문": 5,
}

TODAY_ACTION_NEWS_LOW_QUALITY_SOURCES = (
    "99bitcoins",
    "tokenpost",
    "tmgm",
    "stock traders daily",
    "키즈맘",
    "news.sbs.co.kr",
)

TODAY_ACTION_NEWS_NOISE_WORDS = (
    "알바생",
    "식당 안내문",
    "1인당 30만",
    "줬다 빼앗",
    "커버드콜 etf, 함께 담으면",
    "yearly dividends",
    "rule-based strategy",
    "price-driven insight",
    "robinhood token",
    "convert 1",
    "to usd",
    "bybit",
    "roughnecks",
    "롤 통계사이트",
    "게임 용어",
    "구리문화재단",
    "재단 신임",
    "대표이사에",
    "시장 상위 20개 기업",
    "spherical insights",
)

TODAY_ACTION_NEWS_RELEVANCE_TERMS = {
    "국채/유동성": ("treasury", "yield", "bond", "국채", "채권", "금리", "유동성", "바이백", "buyback", "refunding"),
    "외환/금리": ("fomc", "fed", "ecb", "boj", "rate", "yield", "dollar", "환율", "금리", "달러", "엔화", "cpi"),
    "반도체·AI": ("nvidia", "tsmc", "micron", "hynix", "dram", "hbm", "semiconductor", "ai", "반도체", "하이닉스", "마이크론"),
    "반도체·AI 리스크": ("nvidia", "tsmc", "micron", "hynix", "dram", "hbm", "cxmt", "semiconductor", "반도체", "메모리"),
    "바이오·헬스케어": ("moderna", "vaccine", "clinical", "trial", "fda", "바이오", "임상", "백신", "헬스케어"),
    "에너지/해운": ("oil", "wti", "brent", "hormuz", "shipping", "tanker", "유가", "원유", "호르무즈", "해운"),
    "원자재/금속": ("gold", "copper", "lithium", "commodity", "금", "금값", "구리", "리튬", "탄산리튬", "원자재"),
    "실적/대장주": ("earnings", "revenue", "sales", "guidance", "profit", "실적", "매출", "영업이익", "가이던스"),
}

TODAY_ACTION_NEWS_NAME_OVERRIDES = {
    "CIBR": "사이버보안 ETF",
    "CRWD": "크라우드스트라이크",
    "PANW": "팔로알토 네트웍스",
    "379800.KS": "S&P500",
    "379810.KS": "나스닥",
}


def clean_today_action_news_asset_name(name: object, ticker: object = "") -> str:
    ticker_text = str(ticker or "").strip().upper()
    if ticker_text in TODAY_ACTION_NEWS_NAME_OVERRIDES:
        return TODAY_ACTION_NEWS_NAME_OVERRIDES[ticker_text]
    text = html.unescape(str(name or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-–—:;,，、")
    text = re.sub(
        r"\b(Co\.,?\s*Ltd\.?|Corporation|Corp\.?|Inc\.?|Incorporated|Limited|PLC|LLC)\b\.?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-–—:;,，、")
    return text


def today_action_news_checkpoint(title: str, category: str = "") -> str:
    text = f"{title or ''} {category or ''}".lower()
    if re.search(r"nasdaq|s&p|s & p|뉴욕증시|미국 증시|나스닥|sp500|s&p500", text):
        return "미국지수/나스닥"
    if re.search(r"treasury|buyback|repurchase|refunding|국채|바이백|유동성", text):
        return "장기금리/유동성"
    if re.search(r"share buyback|cancellation|자사주|소각|주주환원", text):
        return "자사주·주주환원"
    if re.search(r"moderna|vaccine|melanoma|skin cancer|clinical|임상|백신|피부암", text):
        return "바이오 임상/백신"
    if re.search(r"meta|apple|cxmt|memory|dram|hbm|micron|sk hynix|semiconductor|반도체|메모리", text):
        return "반도체·AI 재료"
    if re.search(r"fomc|fed|rate|yield|dollar|금리|환율|달러", text):
        return "금리·환율"
    if re.search(r"oil|hormuz|energy|유가|호르무즈", text):
        return "유가·지정학"
    return "확인 필요"


def today_action_news_source_score(source: str) -> int:
    source_l = str(source or "").strip().lower()
    for key, score in TODAY_ACTION_NEWS_SOURCE_SCORES.items():
        if key in source_l:
            return int(score)
    if any(key in source_l for key in TODAY_ACTION_NEWS_LOW_QUALITY_SOURCES):
        return 1
    return 4


def today_action_news_reading_bucket(title: str, category: str, checkpoint: str, source_group: str = "") -> str:
    text = f"{title or ''} {category or ''} {checkpoint or ''} {source_group or ''}".lower()
    if re.search(r"cpi|fomc|fed|ecb|boj|rate|yield|dollar|환율|금리|달러|엔화|국채", text):
        return "환율/금리"
    if re.search(r"oil|wti|brent|hormuz|iran|shipping|유가|원유|호르무즈|이란", text):
        return "원자재/지정학"
    if re.search(r"gold|copper|lithium|commodity|금값|구리|리튬|탄산리튬|원자재", text):
        return "원자재/금속"
    if re.search(r"tsmc|oracle|adobe|earnings|revenue|실적|매출|영업이익", text):
        return "실적"
    if re.search(r"export|trade balance|무역수지|수출|세수|국채통합|재정", text):
        return "경제"
    if re.search(r"kospi|kosdaq|s&p|nasdaq|증시|코스피|코스닥|나스닥|s&p500", text):
        return "시황"
    if re.search(r"nvidia|micron|hynix|dram|hbm|semiconductor|ai|반도체|하이닉스|마이크론", text):
        return "반도체/AI"
    if source_group == "내 종목":
        return "내 종목"
    return "기타"


def today_action_news_beginner_summary(row: dict) -> str:
    bucket = str(row.get("읽기분류", "") or "")
    checkpoint = str(row.get("체크", "") or "")
    title = str(row.get("제목", "") or "")
    if bucket == "환율/금리":
        return "금리·달러 방향을 보는 뉴스입니다. 성장주와 레버리지에는 부담/완화 신호로 읽습니다."
    if bucket == "원자재/지정학":
        return "유가·전쟁/해운 리스크 뉴스입니다. 인플레, 운송비, 원자재 관련주에 영향을 봅니다."
    if bucket == "원자재/금속":
        return "금·구리·리튬 가격 뉴스입니다. FCX/NEM 같은 원자재 종목의 배경 흐름으로 봅니다."
    if bucket == "실적":
        return "기업 실적 뉴스입니다. 같은 업종의 수요가 좋은지 나쁜지 확인합니다."
    if bucket == "경제":
        return "경기 체력 뉴스입니다. 수출·세수·무역수지가 좋아지면 시장 하방을 줄이는 재료입니다."
    if bucket == "시황":
        return "시장 분위기 뉴스입니다. 매수 판단보다 오늘 위험선호가 강한지 약한지 확인합니다."
    if bucket == "반도체/AI":
        return "AI·반도체 수요/공급 뉴스입니다. 내 반도체 비중이 크면 가장 먼저 확인합니다."
    if checkpoint == "확인 필요" or "확인 필요" in title:
        return "제목만으로 방향성이 약합니다. 원문 확인 전에는 매수 재료로 쓰지 않습니다."
    return "제목과 출처를 확인한 뒤 내 종목·섹터와 연결되는지만 봅니다."


def score_today_action_news_row(row: dict) -> dict:
    out = dict(row or {})
    title = str(out.get("제목", "") or "")
    source = str(out.get("출처", "") or "")
    category = str(out.get("카테고리", "") or "")
    checkpoint = str(out.get("체크", "") or "")
    source_group = str(out.get("구분", "") or "")
    text_l = f"{title} {category} {checkpoint}".lower()
    source_l = source.lower()

    score = 3 + min(today_action_news_source_score(source), 10) * 0.45
    if source_group == "핵심속보":
        score += 0.8
    if source_group == "내 종목":
        score += 0.4
    if any(word.lower() in text_l for word in TODAY_ACTION_NEWS_NOISE_WORDS):
        score -= 4.0
    if any(key in source_l for key in TODAY_ACTION_NEWS_LOW_QUALITY_SOURCES):
        score -= 2.0
    if checkpoint == "확인 필요":
        score -= 1.0

    for cat_key, terms in TODAY_ACTION_NEWS_RELEVANCE_TERMS.items():
        if cat_key in category:
            if any(term.lower() in text_l for term in terms):
                score += 1.2
            else:
                score -= 3.0
            break

    if re.search(r"속보|전망|인상|하락|급등|폭등|수출|실적|매출|영업이익|cpi|fomc|rate|yield|oil|revenue|earnings", text_l):
        score += 1.0

    bucket = today_action_news_reading_bucket(title, category, checkpoint, source_group)
    score = max(0.0, min(10.0, score))
    out["읽기분류"] = bucket
    out["중요도"] = round(score, 1)
    out["초보요약"] = today_action_news_beginner_summary(out)
    return out


def rank_today_action_news_rows(rows: list[dict], limit: int = 18) -> list[dict]:
    scored = [score_today_action_news_row(row) for row in rows or []]
    filtered = [row for row in scored if float(row.get("중요도") or 0) >= 4.0]
    if not filtered:
        filtered = scored
    filtered.sort(
        key=lambda row: (
            -float(row.get("중요도") or 0),
            0 if row.get("구분") == "핵심속보" else (1 if row.get("구분") == "시장/속보" else 2),
            str(row.get("시간", "")),
        )
    )
    return filtered[:limit]


def build_today_action_news_brief(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    buckets = {str(row.get("읽기분류", "") or "") for row in rows}
    lines = []
    if {"환율/금리", "원자재/지정학"} & buckets:
        lines.append("오늘은 금리·유가·지정학을 먼저 봅니다. 성장주/레버리지는 이 조합이 부담이면 추격보다 대기가 맞습니다.")
    if "원자재/금속" in buckets:
        lines.append("금·구리·리튬 뉴스는 FCX/NEM 같은 원자재 종목의 배경입니다. 가격 방향과 달러/금리를 같이 봅니다.")
    if "반도체/AI" in buckets or "실적" in buckets:
        lines.append("반도체·AI는 수요와 실적 확인 뉴스가 핵심입니다. 단순 제목보다 TSMC·오라클·엔비디아 같은 대장축을 우선 봅니다.")
    if "경제" in buckets:
        lines.append("수출·무역수지·세수 뉴스는 시장 체력 확인용입니다. 단기 매수 신호보다 시장 하방 완충 재료로 봅니다.")
    if not lines:
        lines.append("오늘 뉴스는 방향성이 약합니다. 제목만 보고 매수하지 말고 정밀관측소 가격위치와 함께 확인하세요.")
    return lines[:3]


def normalize_today_action_news_row(row: dict, source_group: str = "시장") -> dict:
    title = str((row or {}).get("title", "") or "").strip()
    category = str((row or {}).get("market_category", "") or (row or {}).get("category", "") or source_group)
    publisher = str((row or {}).get("publisher", "") or (row or {}).get("source", "") or "-")
    published = str((row or {}).get("published", "") or (row or {}).get("providerPublishTime", "") or "")
    link = str((row or {}).get("link", "") or "")
    ticker = str((row or {}).get("ticker", "") or "")
    name = clean_today_action_news_asset_name((row or {}).get("name", "") or ticker, ticker)
    return {
        "구분": source_group,
        "체크": today_action_news_checkpoint(title, category),
        "카테고리": category,
        "종목": f"{name}({ticker})" if ticker and name else ticker,
        "제목": title,
        "출처": publisher,
        "시간": published,
        "링크": link,
    }
