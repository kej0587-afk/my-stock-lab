"""Bounded public article reading; retain short evidence, never full articles."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

from lxml import etree, html
import requests

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.result_cache import cache_result

register_loaded_source(__name__, __file__)

FEEDS = ("https://www.yna.co.kr/rss/market.xml", "https://www.yna.co.kr/rss/international.xml")
BODY_HOSTS = ("yna.co.kr", "apnews.com", "cnbc.com", "aws.amazon.com", "pytorch.org")
MAX_BYTES = 750_000
MAX_ARTICLES = 4

_EARNINGS_MISS = (
    r"(?:실적|매출|이익|가이던스|향후\s*전망).{0,50}(?:(?:기대|예상|컨센서스).{0,18}"
    r"(?:미달|하회|밑돌|미치지\s*못)|부진|쇼크)|"
    r"(?:기대|예상|컨센서스).{0,18}(?:밑도는|하회하는|미달한).{0,20}실적|"
    r"\b(?:earnings|revenue|profit|guidance|outlook)\b.{0,30}\b(?:miss(?:ed|es)?|disappoint\w*|fell short)\b"
)
_AI_CONCERN = (
    r"(?:AI|인공지능|코어위브|CoreWeave).{0,80}(?:차입\s*우려|신용\s*우려|부채\s*부담|"
    r"자금조달\s*부담|투자\s*붕괴|수익성\s*우려|투자.{0,20}(?:우려|부담|회의론)|"
    r"(?:수익|생산성|성과).{0,45}(?:회의론|의문|불확실|우려))"
)
_PAST_CONTEXT = re.compile(r"과거|한때|당시|작년|지난\s*(?:해|달|분기|주)|\bpreviously\b|\blast (?:year|quarter|month|week)\b", re.I)
_NEGATED_CONTEXT = re.compile(
    r"지(?:는|도)?\s*않|아니|없(?:었|다|는)|(?:해소|완화|진정|불식)(?:됐|되었|했다)|"
    r"\b(?:not|never|unfounded|dismissed)\b", re.I)


def _context_match(paragraphs, topic, pattern):
    for paragraph in paragraphs:
        for sentence in re.split(r"[;!?\n]|\.\s+", paragraph):
            for match in re.finditer(pattern, sentence, re.I):
                if topic in {"earnings", "ai_investment", "ai_credit"}:
                    tail = re.split(r",|지만|으나|반면|면서|\bbut\b|\bwhile\b", sentence[match.end():], maxsplit=1, flags=re.I)[0][:32]
                    if (_PAST_CONTEXT.search(sentence) or _NEGATED_CONTEXT.search(tail)
                            or re.search(r"\b(?:not|never)\b", sentence[max(0, match.start()-24):match.end()], re.I)):
                        continue
                    if topic == "earnings" and re.search(r"우려|가능성|예상|기대|전망", tail):
                        continue
                    if topic == "ai_investment" and re.search(_AI_CONCERN + "|" + _EARNINGS_MISS, sentence, re.I):
                        continue
                return sentence
    return None


def _safe_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and any(parsed.hostname == host or (parsed.hostname or "").endswith("." + host) for host in BODY_HOSTS))
    except (TypeError, ValueError):
        return False


def _public_bytes(url):
    if not _safe_url(url):
        raise ValueError("unsupported_public_source")
    with requests.Session() as session:
        session.trust_env = False
        started = time.monotonic()
        for _ in range(3):
            with session.get(url, timeout=(2, 3), allow_redirects=False, stream=True,
                             headers={"User-Agent": "StockLab/1.0 (personal public-news reader)"}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get("Location", ""))
                    if not _safe_url(url):
                        raise ValueError("redirect_source_not_allowed")
                    continue
                if response.status_code != 200:
                    raise ValueError("http_" + str(response.status_code))
                kind = response.headers.get("Content-Type", "").lower()
                if not any(part in kind for part in ("html", "xml", "rss")):
                    raise ValueError("unexpected_content_type")
                data = bytearray()
                for chunk in response.iter_content(32_768):
                    if time.monotonic() - started > 6:
                        raise ValueError("article_deadline")
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("response_too_large")
                return bytes(data), url
    raise ValueError("redirect_limit")


def parse_publisher_feed(data):
    root = ET.fromstring(data)
    rows = []
    for item in root.findall("./channel/item")[:120]:
        title, link = item.findtext("title", ""), item.findtext("link", "")
        if not _safe_url(link) or not re.search(r"코스피|코스닥|뉴욕증시|나스닥|월가|코어위브|미국\s*증시", title):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                continue
        except (ValueError, TypeError):
            continue
        market = "KR" if re.search(r"코스피|코스닥", title) else "US"
        rows.append(dict(title=title, link=link, publisher="연합뉴스", publisher_url="https://www.yna.co.kr",
                         published_at=published.isoformat(), market=market, query_market=market,
                         source="Yonhap public RSS", market_category="시장"))
    return rows


@cache_result(ttl=300, failure_ttl=30, is_success=lambda result: bool(result["rows"]))
def _feed(url):
    try:
        data, _ = _public_bytes(url)
        return {"rows": parse_publisher_feed(data), "status": "available"}
    except (requests.RequestException, ValueError, ET.ParseError):
        return {"rows": [], "status": "unavailable"}


def publisher_news(sessions=None, now=None):
    # The publisher explicitly offers these feeds for non-commercial use.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(_feed, FEEDS))
    rows = [row for result in results for row in result["rows"]]
    if sessions and now:
        stored = json.loads((Path(__file__).with_name("data") / "verified_article_sources_20261021.json").read_text(encoding="utf-8"))
        if now.date().isoformat() >= stored["verified_at"]:
            for row in stored["articles"]:
                target = sessions.get(row["market"], {})
                target = target.get("date") if isinstance(target, dict) else target
                if target == row["session_date"] and _safe_url(row["link"]):
                    rows.append(dict(row))
    return rows


def _date(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def _objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        yield value
        yield from _objects(value.get("@graph", []))


def _body_facts(paragraphs):
    facts = []
    rules = (
        ("mediation", r"(?:미[·ㆍ/-]?이란|미국.{0,10}이란).{0,40}(?:중재|외교|협상)",
         "미·이란 외교·중재 가능성이 보도됐습니다",
         "지정학적 위험 프리미엄이 낮아질 수 있으나 제안 보도만으로 합의나 공급 정상화를 확정할 수 없습니다",
         "당사국의 중재안 수용 여부와 실제 원유 공급·유가 확인"),
        ("ai_investment", r"(?:AI|인공지능).{0,70}(?:호실적|투자\s*확대|시설투자|설비투자|수요\s*기대|수요\s*증가)",
         "AI 관련 실적·투자 확대와 수요 기대가 보도됐습니다",
         "AI 수요 기대 회복은 반도체·기술주 투자심리에 우호적일 수 있지만 실제 수주·이익 개선 확인이 필요합니다",
         "AI 설비투자 계획과 다음 실적의 수요·현금흐름 확인"),
        ("ai_credit", _AI_CONCERN,
         "AI 투자 부담·성과에 대한 우려가 보도됐습니다",
         "AI 투자 지속성과 성과에 대한 경계가 반도체·성장주로 번질 수 있으나 가격 기여도는 확정할 수 없습니다",
         "AI 투자 계획·고객 계약과 투자 대비 수익·현금흐름 확인"),
        ("exports", r"수출.{0,60}(?:역대\s*최대|호조|신기록)",
         "한국 수출 호조가 투자심리 개선 배경으로 거론됐습니다",
         "수출 개선은 관련 기업의 매출 기대를 지지할 수 있으나 업종별 물량·마진은 별도 확인이 필요합니다",
         "반도체 수출과 기업 실적의 동행 여부 확인"),
        ("foreign_buying", r"외국인.{0,90}(?:유가증권시장|현물).{0,50}순매수",
         "외국인의 현물 순매수가 보도됐습니다",
         "현물 매수는 당일 수급을 지지한 정황입니다. 선물·환율 방향까지 일치하는지는 별도 확인해야 합니다",
         "다음 거래일 외국인 현물·선물과 원화 방향 확인"),
        ("earnings", r"(?:예상|기대).{0,25}(?:웃도|넘는|상회).{0,25}실적|실적\s*호조|strong (?:profit|earnings)|earnings.{0,15}(?:beat|exceed)",
         "일부 기업의 호실적이 보도됐습니다",
         "실적 기대가 지수를 지지해도 AI 업종과 시장 전체의 방향은 다를 수 있습니다",
         "예정 실적의 매출·가이던스와 업종별 확산 확인"),
    )
    for topic, pattern, summary, implication, check in rules:
        # Prefer an explicit miss over unrelated earnings beats in the same wrap.
        missed = _context_match(paragraphs, topic, _EARNINGS_MISS) if topic == "earnings" else None
        matched = missed or _context_match(paragraphs, topic, pattern)
        if matched:
            fact = dict(topic=topic, summary=summary, implication=implication, check=check,
                        evidence=matched[:140] + ("…" if len(matched) > 140 else ""))
            if missed:
                fact.update(polarity="negative", summary="기업 실적·전망 부진이 보도됐습니다",
                            implication="실적·전망 부진은 관련 업종 투자심리에 부담이 될 수 있으나 시장 전체 하락의 단독 원인으로 확정할 수 없습니다",
                            check="공식 실적·가이던스와 시장 기대치 비교 확인")
            facts.append(fact)
    from stock_lab_core.article_price_facts import oil_price_fact
    oil = oil_price_fact(paragraphs)
    if oil:
        facts.insert(0, oil)
    # Consumers show only the first two facts; retain supported adverse context.
    facts.sort(key=lambda fact: 0 if fact.get("polarity") == "negative" else 1 if fact["topic"] == "ai_credit" else 2)
    return facts[:4]


def parse_article(data, url, expected_title):
    if not _safe_url(url):
        return {"body_status": "unsupported_source"}
    root = html.fromstring(data, parser=html.HTMLParser(no_network=True))
    articles = []
    for script in root.xpath('//script[@type="application/ld+json"]')[:12]:
        try:
            articles.extend(obj for obj in _objects(json.loads(script.text or ""))
                            if obj.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle"))
        except (ValueError, TypeError):
            continue
    if len(articles) != 1:
        return {"body_status": "article_metadata_unavailable"}
    meta = articles[0]
    if meta.get("isAccessibleForFree") in (False, "false", "False"):
        return {"body_status": "restricted_article"}
    title = re.sub(r"\s+", "", str(meta.get("headline") or "")).casefold()
    expected = re.sub(r"\s+", "", expected_title).casefold()
    if not title or not expected or not (title in expected or expected in title):
        return {"body_status": "headline_mismatch"}
    published = _date(meta.get("datePublished"))
    modified = _date(meta.get("dateModified")) or published
    if not published or not modified:
        return {"body_status": "article_timestamp_unavailable"}
    if "yna.co.kr" in (urlsplit(url).hostname or ""):
        paragraphs = root.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," story-news ")]/p')
        paragraphs = [" ".join(p.text_content().split()) for p in paragraphs]
    else:
        body = meta.get("articleBody")
        paragraphs = re.split(r"\n+|(?<=[.!?])\s+", body) if isinstance(body, str) else []
    paragraphs = [p for p in paragraphs if len(p) >= 25 and not re.search(r"무단\s*(?:전재|복제)|재배포\s*금지|저작권|구독|광고", p)]
    from stock_lab_core.catalyst_news import catalyst_body_facts, catalyst_entities
    issuer_context = bool(catalyst_entities(expected_title))
    issuer_facts = catalyst_body_facts(paragraphs, expected_title) if issuer_context else []
    # An issuer's capex/FCF discussion is not evidence that AI lifted the index.
    facts = issuer_facts if issuer_context else _body_facts(paragraphs)
    return dict(body_status="verified" if facts else "no_supported_context", body_facts=facts,
                body_published_at=published.isoformat(), body_modified_at=modified.isoformat(), body_source_url=url,
                body_sha256=hashlib.sha256("\n".join(paragraphs).encode()).hexdigest(),
                body_checked_at=datetime.now(timezone.utc).isoformat())


@cache_result(ttl=21_600, failure_ttl=30, is_success=lambda result: result.get("body_status") == "verified")
def _article(url, title):
    # v4: sentence-scoped earnings/AI context and adverse-context priority.
    try:
        data, final_url = _public_bytes(url)
        return parse_article(data, final_url, title)
    except (requests.RequestException, ValueError, TypeError, etree.LxmlError):
        return {"body_status": "fetch_unavailable"}


def enrich_article_context(result, now):
    """Read at most four direct public URLs after session/source curation."""
    buckets = ("current_session_news", "session_news", "next_session_news")
    rows = [row for bucket in buckets for row in result.get(bucket, []) if _safe_url(row.get("link", ""))]
    from stock_lab_core.catalyst_news import catalyst_entities, catalyst_topics
    rows.sort(key=lambda row: (not (row.get("news_bucket") == "next_session_news"
                                   and catalyst_entities(row.get("title")) and catalyst_topics(row.get("title"))),
                               not row.get("is_close_wrap"), row.get("market") != "KR"))
    selected, market_counts, seen = [], {}, set()
    for row in rows:
        market, link = row.get("market"), row.get("link")
        if link in seen or market_counts.get(market, 0) >= 2:
            continue
        selected.append(row)
        seen.add(link)
        market_counts[market] = market_counts.get(market, 0) + 1
        if len(selected) >= MAX_ARTICLES:
            break
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = [executor.submit(_article, row["link"], row["title"]) for row in selected]
        for row, future in zip(selected, pending):
            evidence = future.result()
            published, modified = _date(evidence.get("body_published_at")), _date(evidence.get("body_modified_at"))
            if evidence.get("body_status") == "verified" and (not published or not modified or max(published, modified) > now):
                evidence = {"body_status": "article_version_after_report"}
            source_date = _date(row.get("published_at"))
            if (evidence.get("body_status") == "verified" and source_date
                    and min(abs((source_date - published).total_seconds()), abs((source_date - modified).total_seconds())) > 3600):
                evidence = {"body_status": "article_timestamp_mismatch"}
            row.update(evidence)
    result.setdefault("news_retrieval", {}).update(article_feed_count=len(FEEDS), article_body_limit=MAX_ARTICLES,
        article_body_attempted=len(selected), article_body_verified=sum(row.get("body_status") == "verified" for row in selected))
    return result


def verified_body_facts(row):
    return row.get("body_facts", []) if row.get("body_status") == "verified" else []


def body_context_sentence(row):
    labels = {"mediation": "미·이란 중재 기대", "ai_investment": "AI 실적·투자 확대와 수요 기대",
              "exports": "한국 수출 호조", "foreign_buying": "외국인 현물 순매수", "earnings": "기업 호실적",
              "oil_easing": "유가 하락", "oil_rising": "유가 상승", "oil_mixed": "기간·유종별 유가 방향 혼재"}
    facts = verified_body_facts(row)
    backgrounds = ["기업 실적·전망 부진" if fact.get("polarity") == "negative" and fact["topic"] == "earnings"
                   else labels[fact["topic"]] for fact in facts if fact["topic"] in labels and not fact.get("subject_ticker")]
    sentence = "기사에서는 " + "·".join(backgrounds[:3]) + " 등을 시장 배경으로 짚었습니다." if backgrounds else ""
    for fact in facts:
        if fact["topic"] == "ai_credit" and not fact.get("subject_ticker"):
            sentence += (" " if sentence else "") + fact["summary"] + "."
    issuer_facts = [fact["summary"] for fact in facts if fact.get("subject_ticker")]
    if issuer_facts:
        sentence += (" " if sentence else "") + "; ".join(issuer_facts[:3]) + "."
    return sentence
