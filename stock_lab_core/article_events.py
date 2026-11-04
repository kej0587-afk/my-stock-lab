"""Extractive news metadata; neither predictions nor inferred price causes."""

from functools import lru_cache
import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def body_sentences(paragraphs):
    """Keep quoted clauses, semicolons and decimal numbers with their context."""
    for paragraph in paragraphs:
        start, quotes = 0, []
        closers = {'"': '"', "'": "'", "“": "”", "‘": "’"}
        for index, char in enumerate(paragraph):
            previous = paragraph[index - 1] if index else ""
            following = paragraph[index + 1:index + 2]
            apostrophe = (char in {"'", "’"} and previous.isascii() and following.isascii()
                          and previous.isalnum() and following.isalnum())
            if not apostrophe:
                if quotes and char == quotes[-1]:
                    quotes.pop()
                elif char in closers and not (char == "'" and previous.isalnum()):
                    quotes.append(closers[char])
            if quotes or not (char == "\n" or char in ".!?" and (not following or following.isspace())):
                continue
            sentence = paragraph[start:index + 1].strip()
            if sentence:
                yield sentence
            start = index + 1
        sentence = paragraph[start:].strip()
        if sentence:
            yield sentence


_HISTORY = re.compile(r"과거|한때|당시|작년|지난\s*(?:해|달|분기|주)|\bpreviously\b|\blast (?:year|quarter|month|week)\b", re.I)
_NEGATION = re.compile(r"지(?:는|도)?\s*않|아니|없(?:었|다|는)|\b(?:not|never|no|denied|unfounded)\b|(?:해소|완화|진정|불식)(?:됐|되었|했다)", re.I)
_CONDITIONAL = re.compile(r"경우|가능성|수\s*있|예정|예상된|전망만|다면|더라도|\b(?:if|could|might|may|would|expected to|will)\b", re.I)
_RULES = tuple((tag, re.compile(pattern, re.I)) for tag, pattern in (
    ("earnings_shock", r"(?:실적|매출|이익|가이던스|향후\s*전망).{0,50}(?:하회|미달|미치지\s*못|부진|쇼크|상회)|(?:예상|기대).{0,20}(?:웃도|밑도).{0,20}실적|\b(?:earnings|revenue|profit|guidance|outlook)\b.{0,35}\b(?:miss\w*|beat\w*|disappoint\w*|fell short)\b"),
    ("regulation", r"(?:규제|수출\s*통제|인허가|독점금지).{0,35}(?:강화|완화|도입|제한|금지|조사|지연)|\b(?:regulat\w*|export controls?|antitrust)\b.{0,40}\b(?:tighten\w*|eas\w*|restrict\w*|ban\w*|investigat\w*|announc\w*)\b"),
    ("rates", r"(?:기준금리|정책금리|국채\s*금리|금리).{0,25}(?:인하|인상|동결|상승|하락)|\b(?:interest rates?|policy rates?|treasury yields?|rates?)\b.{0,25}\b(?:cut\w*|hik\w*|held|rose|fell|ris\w*|fall\w*)\b"),
    ("credit", r"(?:차입|부채|신용|자금조달|채무).{0,30}(?:우려|부담|강등|불이행|증가|경색)|\b(?:debt|credit|borrowing|financing)\b.{0,35}\b(?:concern\w*|stress|downgrad\w*|default\w*|rose|increas\w*)\b"),
    ("geopolitics", r"(?:미[·ㆍ/-]?이란|미국.{0,10}이란).{0,40}(?:중재|외교|협상)|(?:전쟁|휴전|관세|제재).{0,30}(?:발발|합의|협상|발표|부과|강화)|\b(?:war|ceasefire|tariffs?|sanctions?)\b.{0,35}\b(?:began|agreed|announc\w*|impos\w*|talks)\b"),
    ("flows", r"(?:외국인|기관|ETF|자금).{0,50}(?:순매수|순매도|순유입|순유출)|(?:순유입|순유출)|\b(?:inflows?|outflows?|net buying|net selling|net purchases?|net sales?)\b"),
))


@lru_cache(maxsize=1)
def _subjects_catalog():
    from stock_lab_core.earnings_discovery import issuer_catalog
    from stock_lab_core.constants import (KNOWN_KR_ETF_SYMBOLS, KNOWN_US_NASDAQ_ETFS,
                                          KNOWN_US_OTHER_ETFS, KNOWN_US_SP_ETFS)
    catalog = issuer_catalog(events=[dict(ticker=ticker, name=name) for ticker, name in (
        ("INTC", "Intel"), ("SNDK", "SanDisk"), ("FFIV", "F5"),
        ("FTNT", "Fortinet"), ("CRWV", "CoreWeave"))])
    catalog["CRWV"]["aliases"].append("코어위브")
    catalog["FTNT"]["aliases"].append("포티넷")
    entries = []
    for ticker, item in catalog.items():
        names = [*item["aliases"], ticker]
        patterns = []
        for name in sorted(set(names), key=len, reverse=True):
            if name.isascii():
                prefix = r"(?:\$|NASDAQ\s*:\s*|NYSE\s*:\s*)" if name == ticker and len(ticker) < 3 else r"(?<![A-Za-z0-9])"
                patterns.append(prefix + re.escape(name) + r"(?![A-Za-z0-9])")
            else:
                patterns.append(r"(?<![가-힣])" + re.escape(name) + r"(?=$|[^가-힣]|은|는|이|가|의|과|와)")
        entries.append((dict(ticker=ticker, name=item["name"], kind="company"), re.compile("|".join(patterns), re.I)))
    for ticker in sorted(KNOWN_KR_ETF_SYMBOLS | KNOWN_US_NASDAQ_ETFS | KNOWN_US_OTHER_ETFS | KNOWN_US_SP_ETFS):
        entries.append((dict(ticker=ticker, name=ticker, kind="ETF"),
                        re.compile(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])")))
    return entries


def _subjects(sentence, start):
    # Only an explicit lead subject of this clause, never a headline, partner,
    # analyst attribution or a subject in a preceding sentence.
    prefix = re.split(r";|\b(?:while|but)\b|반면|하지만|[\"“”]", sentence[:start], flags=re.I)[-1]
    found, remainder = [], prefix
    for subject, pattern in _subjects_catalog():
        if pattern.search(prefix):
            found.append(dict(subject))
            remainder = pattern.sub("", remainder)
    remainder = re.sub(r"\b(?:and|the|reported|reports|posted|recorded|net|saw|faced|announced|ETF|fund|quarterly)\b|['’]s|은|는|이|가|의|과|와|및", "", remainder, flags=re.I)
    return found if found and not re.sub(r"[\s,:&$()\[\]-]", "", remainder) else []


def event_metadata(sentence, *, basis="body"):
    contexts = [label for label, pattern in (("historical", _HISTORY), ("negated", _NEGATION),
                                             ("conditional", _CONDITIONAL)) if pattern.search(sentence)]
    if basis == "body" and contexts:
        return []
    events = []
    for tag, pattern in _RULES:
        match = pattern.search(sentence)
        if match:
            events.append(dict(event_tag=tag, subjects=_subjects(sentence, match.start()),
                               basis=basis, claim_context=contexts or ["reported"], evidence=sentence))
    return events


def headline_events(title):
    """Headline claims are metadata only, including their qualifications."""
    return [event for sentence in body_sentences([title]) if len(sentence) <= 240
            for event in event_metadata(sentence, basis="headline")]


def enhance_facts(facts, paragraphs):
    """Keep legacy topics/summaries and add complete, short source claims."""
    sentences = list(body_sentences(paragraphs))
    result = [dict(fact) for fact in facts]
    used = set()
    for fact in result:
        evidence = fact.get("evidence", "").rstrip("…")
        sentence = next((s for s in sentences if evidence and s.startswith(evidence)), None)
        if not sentence or len(sentence) > 140:
            continue  # Never remove a trailing denial/attribution to fit the limit.
        events = event_metadata(sentence)
        fact.update(evidence_basis="body", concrete_summary=sentence, events=events,
                    event_tags=[event["event_tag"] for event in events])
        used.update(event["event_tag"] for event in events)
    additions = []
    for sentence in sentences:
        if len(sentence) > 140:
            continue
        for event in event_metadata(sentence):
            tag = event["event_tag"]
            if tag in used or (tag == "earnings_shock" and any(f["topic"] == "earnings" for f in result)):
                continue
            if any(f["topic"] == tag for f in additions):
                continue
            additions.append(dict(topic="earnings" if tag == "earnings_shock" else tag,
                summary="본문 보도: " + sentence, concrete_summary=sentence,
                implication="출처의 보도 내용이며 시장 가격의 원인이나 향후 방향을 확정하지 않습니다",
                check="공식 발표와 보도 시점·적용 대상 확인", evidence=sentence,
                evidence_basis="body", event_tags=[tag], events=[event]))
    # New concrete events precede generic AI concerns; existing facts keep order.
    split = next((i for i, f in enumerate(result) if f["topic"] == "ai_credit"), len(result))
    return (result[:split] + additions + result[split:])[:4]


_SECTORS = (
    ("AI·반도체", r"\bAI\b|인공지능|반도체|semiconductor"),
    ("방산", r"방산|방위산업|defen[cs]e"),
    ("헬스케어", r"헬스케어|제약|바이오|health\s*care|pharma"),
    ("금융", r"금융|은행|financial|banking|banks"),
)
_BOTH = r"(?:양원|상[·ㆍ/과\s-]*하원.{0,12}(?:모두|양쪽)|both (?:chambers|houses)|(?:house and senate|senate and house))"
_CONTROL = r"(?:확보|장악|다수당|유지|승리|차지|control|win|hold|retain|majorit)"


def body_scenarios(paragraphs):
    """At most three explicit source conditions, not mutually exclusive forecasts.

    Schema: {condition: Korean label, sectors: list[str], evidence: str}.
    Empty sectors are intentional: adjacent sentences cannot donate exposure.
    """
    result, seen = [], set()
    for sentence in body_sentences(paragraphs):
        if len(sentence) > 240 or _HISTORY.search(sentence):
            continue
        conditional = re.search(r"경우|[할될일]\s*때|구성되면|확보하면|장악하면|유지하면|차지하면|장악해도|확보하더라도|(?:확보|장악|승리|유지)\s*시\b|\bif\b", sentence, re.I)
        if not conditional:
            continue
        condition = None
        for party, label in ((r"민주당|Democrats?", "민주당"), (r"공화당|Republicans?", "공화당")):
            if re.search(r"(?:" + party + r").{0,25}(?:" + _BOTH + r".{0,25}" + _CONTROL
                         + "|" + _CONTROL + r".{0,25}" + _BOTH + ")", sentence, re.I):
                condition = label + " 양원"
                break
        if not condition and re.search(r"분점\s*의회|양당.{0,20}(?:나눠|나누어)|split congress|divided congress", sentence, re.I):
            condition = "분점 의회"
        if not condition and re.search(r"(?:공화당|Republicans?).{0,20}(?:(?:상원|senate).{0,25}" + _CONTROL
                                       + "|" + _CONTROL + r".{0,25}(?:상원|senate))", sentence, re.I):
            condition = "공화당 상원"
        if not condition or condition in seen:
            continue
        # Negation of the condition itself must not become the opposite branch.
        condition_text = sentence if conditional.group().lower() == "if" else sentence[:conditional.end()]
        if _NEGATION.search(condition_text) or re.search(r"지\s*못", condition_text):
            continue
        seen.add(condition)
        result.append(dict(condition=condition,
                           sectors=[label for label, pattern in _SECTORS if re.search(pattern, sentence, re.I)],
                           evidence=sentence))
        if len(result) == 3:
            break
    return result


def is_strategy_article(title):
    return bool(re.search(r"시나리오|\bscenarios?\b|(?:월가|월스트리트|Wall\s*(?:Street|St\.?)).{0,55}(?:전략|전망|strategy|strategist|outlook)", title, re.I))
