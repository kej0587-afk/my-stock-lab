"""Today dashboard news plans and beginner-friendly quality scoring."""

from __future__ import annotations

from datetime import timezone, timedelta
from email.utils import parsedate_to_datetime
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


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
            rows.append({
                "market_category": category,
                "title": title,
                "link": link,
                "publisher": publisher,
                "published": format_market_story_pub_dt(pub_dt),
                "source": "Google News RSS",
            })
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
    name = str((row or {}).get("name", "") or ticker)
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
