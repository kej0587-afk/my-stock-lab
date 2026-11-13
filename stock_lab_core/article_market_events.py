"""Short attributed events for market prose, never inputs to investment rules."""

import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

_DIPLOMACY = re.compile(r"(?:미[·ㆍ/-]?이란|미국.{0,10}이란).{0,40}(?:중재|외교|협상)", re.I)
_LEADERSHIP = re.compile(
    r"(?:CEO|최고경영자|대표이사|회장).{0,60}(?:사임|퇴진|해임|교체|resign\w*|step(?:ped|s)? down|dismiss\w*)"
    r"|(?:임시|신임|interim|new).{0,15}(?:CEO|최고경영자|대표이사).{0,35}(?:선임|임명|appoint\w*|nam\w*)", re.I)
_QUALIFIED = re.compile(
    r"과거|지난해|작년|당시|지난\s*(?:주|달|분기)|않|아니|없|부인|가능|예정|검토|관측|전망|한다면|할\s*경우"
    r"|요구|촉구|필요|논의|계획|사임설|퇴진설"
    r"|\b(?:not|never|denied|if|may|might|could|would|will|expected|rumou?rs?|consider\w*|called for|previously|last year|last month|last week)\b", re.I)


def market_event_facts(paragraphs):
    from stock_lab_core.article_events import body_sentences

    facts, seen = [], set()
    for sentence in body_sentences(paragraphs):
        # Do not cut off a later denial, attribution or conditional clause.
        if len(sentence) > 140:
            continue
        if _DIPLOMACY.search(sentence):
            topic = "mediation"
            implication = "협상의 진전·결렬·부인은 구분해야 합니다. 이 보도만으로 합의 성사나 유가 방향을 확정하지 않습니다"
            check = "당사국 공식 발표와 같은 세션의 유가·금리 반응 확인"
        elif _LEADERSHIP.search(sentence) and not _QUALIFIED.search(sentence):
            topic = "leadership"
            implication = "경영진 교체는 의사결정·사업 일정의 불확실성을 높일 수 있습니다. 생산·계약 변경이나 경쟁사 수혜가 확인된 것은 아닙니다"
            check = "공식 인사 발표와 사업 일정·고객 계약 유지 여부, 관련 기업의 같은 세션 가격 반응 확인"
        else:
            continue
        if topic in seen:
            continue
        seen.add(topic)
        facts.append(dict(topic=topic, summary="본문 보도: " + sentence,
                          implication=implication, check=check, evidence=sentence,
                          evidence_basis="body", concrete_summary=sentence))
    return ordered_market_facts(facts)


def ordered_market_facts(facts):
    """Keep explicit events ahead of generic templates, retaining stable order."""
    def priority(fact):
        if fact.get("topic") == "leadership":
            return 0
        if fact.get("polarity") == "negative":
            return 1
        return {"ai_credit": 2, "mediation": 3}.get(fact.get("topic"), 4)
    return sorted(facts, key=priority)


def event_context_sentence(facts):
    claims = [fact["summary"] for fact in ordered_market_facts(facts)
              if fact.get("topic") in {"leadership", "mediation"}]
    return " ".join(claims[:2])


def select_editorial_facts(rows, limit=3):
    """One fact per source first; then fill with distinct facts from the same wrap."""
    from stock_lab_core.article_context import verified_body_facts

    candidates = [(fact, row) for row in rows for fact in ordered_market_facts(verified_body_facts(row))
                  if all(isinstance(fact.get(k), str) and fact[k].strip()
                         for k in ("summary", "implication", "check"))]
    candidates.sort(key=lambda pair: 0 if pair[0].get("topic") == "leadership" else 1)
    selected, topics, urls = [], set(), set()
    for distinct_source in (True, False):
        for fact, row in candidates:
            topic, url = fact.get("topic"), row.get("link")
            if topic in topics or (distinct_source and url in urls):
                continue
            selected.append((fact, row))
            topics.add(topic)
            urls.add(url)
            if len(selected) >= limit:
                return selected
    return selected
