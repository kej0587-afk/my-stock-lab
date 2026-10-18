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
        "timezone": "America/New_York", "close": time(16),
        "query": '("U.S. stocks" OR "Wall Street" OR Nasdaq OR "S&P 500")',
        "wrap": '("stocks close" OR "Wall Street closes" OR "market wrap" OR "closing bell")',
        "locale": "hl=en-US&gl=US&ceid=US:en",
    },
    "KR": {
        "timezone": "Asia/Seoul", "close": time(15, 30),
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
    r"\b(?:stocks?|markets?|wall street|nasdaq|s&p).{0,80}\bclos(?:e[sd]?|ing)\b|"
    r"\bmarket wrap\b|\bclosing bell\b", re.I,
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


def _news_sort_key(row):
    prefer_wrap = row["news_bucket"] == "session_news" and row["is_close_wrap"]
    return (not prefer_wrap, -_news_timestamp(row["published_at"]).timestamp())


def partition_session_market_news(rows, sessions, *, now=None) -> dict:
    """Pure time partition; callers curate sources/events separately.

    ``sessions`` maps KR/US to ISO ``date`` and actual ``previous_date``.
    Windows use regular close times in each exchange timezone (including US DST).
    ``start`` is exclusive and ``end`` (the reference close) inclusive.
    ``capture_end`` is exclusive midnight after the following calendar day.
    Same-date closing wraps within two hours of close are retrospective session
    reporting, not pre-close causes. Other post-close news is next-session material.
    Only explicit ``market``/``region`` metadata is used; language is not a market.
    ISO timestamps without an offset use KST, matching report_evidence.curate_news.
    """
    now = _news_now(now)
    windows, missing = _session_news_windows(sessions, now)
    by_market = {window["market"]: window for window in windows}
    result = {"session_news": [], "next_session_news": [], "windows": windows, "missing": missing}
    rejected = Counter()
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")
    for raw in rows if rows is not None else ():
        if not isinstance(raw, Mapping):
            rejected["뉴스 행 형식 오류"] += 1
            continue
        market = str(raw.get("market") or raw.get("region") or "").strip().upper()
        region = str(raw.get("region") or "").strip().upper()
        if market not in by_market or (region and region != market):
            rejected["명시된 시장 또는 해당 시장의 유효한 세션 없음"] += 1
            continue
        published = _news_timestamp(raw.get("published_at") or raw.get("published") or raw.get("시간"))
        if published is None:
            rejected["뉴스 발행시각 누락/해석 불가"] += 1
            continue
        window = by_market[market]
        start = datetime.fromisoformat(window["start"])
        close = datetime.fromisoformat(window["end"])
        if published <= start or published > now:
            rejected["뉴스 시간창 밖 또는 미래 발행시각"] += 1
            continue
        wrap = bool(_CLOSE_WRAP.search(str(raw.get("title") or raw.get("제목") or "")))
        title = str(raw.get("title") or raw.get("제목") or "")
        if re.search(r"post.close|after.hours|시간외|장후|마감 후", title, re.I):
            wrap = False
        same_date = published.astimezone(ZoneInfo(window["timezone"])).date().isoformat() == window["date"]
        if wrap and published <= close and not same_date:
            rejected["이전 거래일 마감 회고"] += 1
            continue
        retrospective = wrap and same_date and close < published <= close + timedelta(hours=2)
        bucket = "session_news" if published <= close or retrospective else "next_session_news"
        row = dict(raw, market=market, published_at=published.isoformat(),
                   session_date=window["date"], news_bucket=bucket,
                   is_close_wrap=wrap, retrospective_close_wrap=retrospective)
        result[bucket].append(row)
    for bucket in ("session_news", "next_session_news"):
        result[bucket].sort(key=_news_sort_key)
        for market in by_market:
            if not any(row["market"] == market for row in result[bucket]):
                missing.append(f"{market}: {'기준 세션' if bucket == 'session_news' else '종가 이후'} 뉴스 없음")
    missing.extend(f"{reason}: {count}건 제외" for reason, count in rejected.items())
    return result


def _session_query_specs(windows, categories, now):
    requested = tuple(dict.fromkeys(categories or ()))
    available = {plan["category"]: plan["query"] for plan in TODAY_MARKET_STORY_RSS_PLAN}
    selected = [(category, available[category]) for category in requested if category in available][:3]
    plans = [("마감 시황", None)] + (selected if requested else [("시장", "")])
    specs = []
    for window in windows:
        market = window["market"]
        market_spec = _SESSION_MARKETS[market]
        start = datetime.fromisoformat(window["start"])
        capture_end = datetime.fromisoformat(window["capture_end"])
        ranges = [(start, min(capture_end, now))]
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
            for category, query in market_plans:
                terms = market_spec["wrap"] if query is None else query
                # Google date predicates have calendar precision. Pad boundaries
                # and apply exact timestamps after retrieval, including midnight.
                after = (lower.astimezone(ZoneInfo(window["timezone"])).date() - timedelta(days=1)).isoformat()
                before = (upper.astimezone(ZoneInfo(window["timezone"])).date() + timedelta(days=1)).isoformat()
                korean_wrap = terms in {"코스피 마감", "미국증시 마감"}
                query_text = terms if korean_wrap else f"{market_spec['query']} ({terms})" if terms else market_spec["query"]
                query_text += f" after:{after} before:{before}"
                url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query_text})
                locale = "hl=ko&gl=KR&ceid=KR:ko" if korean_wrap else market_spec["locale"]
                specs.append({"market": market, "category": category, "url": url + "&" + locale})
    return specs[:_SESSION_QUERY_LIMIT]


def _fetch_session_rss(spec):
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
            rows.append({
                "title": html.unescape(str(item.findtext("title", "") or "").strip()),
                "link": str(item.findtext("link", "") or "").strip(),
                "publisher": html.unescape(str(item.findtext("source", "") or "").strip()),
                "publisher_url": source.attrib.get("url", "") if source is not None else "",
                "published_at": pub_dt.isoformat() if pub_dt else "",
                "published": format_market_story_pub_dt(pub_dt),
                "source": "Google News RSS", "market_category": spec["category"],
                "market": spec["market"],
            })
        return rows, ""
    except Exception:
        return [], f"{spec['market']}: RSS 수집 실패"


def fetch_session_market_news(sessions, *, now=None, categories=(), per_category=3) -> dict:
    """Bounded market-specific RSS retrieval plus source/event curation.

    Returns the same payload as partition_session_market_news. Queries include
    absolute after/before dates, with separate historical and latest retrieval.
    At most 16 requests run with four workers, five-second socket timeouts and
    512 KiB responses. At most three requested categories supplement close wraps.
    An article returned by both market queries has ambiguous market provenance
    and is excluded rather than assigned to both sessions. No sending/storage.
    """
    from stock_lab_core.report_evidence import curate_news

    now = _news_now(now)
    windows, _ = _session_news_windows(sessions, now)
    specs = _session_query_specs(windows, categories, now)
    try:
        per_category = max(1, min(int(per_category), 5))
    except (TypeError, ValueError):
        per_category = 3
    rows, failures = [], Counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for candidates, error in executor.map(_fetch_session_rss, specs):
            rows.extend(candidates)
            if error:
                failures[error] += 1
    origins = {}
    for row in rows:
        for key in (row["link"], market_story_title_key(row["title"])):
            if key:
                origins.setdefault(key, set()).add(row["market"])
    for row in rows:
        if any(len(origins.get(key, ())) > 1 for key in (row["link"], market_story_title_key(row["title"]))):
            row.pop("market", None)
    result = partition_session_market_news(rows, sessions, now=now)
    for bucket in ("session_news", "next_session_news"):
        accepted, seen, seen_links, counts = [], set(), set(), Counter()
        for row in result[bucket]:
            # Exact time filtering already ran. Validate each source with the
            # existing curator even for holiday windows longer than seven days.
            checked = curate_news([row], now=_news_timestamp(row["published_at"]), limit=1)
            if not checked or not checked[0].get("link"):
                continue
            clean = checked[0]
            event_key = "close-wrap:" + clean["session_date"] if clean.get("is_close_wrap") else clean["event_key"]
            event = (clean["market"], event_key)
            category = (clean["market"], clean["category"])
            link_key = (clean["market"], clean["link"])
            if event in seen or link_key in seen_links or counts[category] >= per_category or len(accepted) >= _SESSION_ROW_LIMIT:
                continue
            seen.add(event)
            seen_links.add(link_key)
            counts[category] += 1
            accepted.append(clean)
        result[bucket] = accepted
        for window in windows:
            market = window["market"]
            if not any(row["market"] == market for row in accepted):
                result["missing"].append(f"{market}: {bucket} 출처·날짜·중복 검증 후 채택 뉴스 없음")
    result["missing"].extend(f"{reason}: {count}개 쿼리" for reason, count in failures.items())
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
