"""Short attributed events for market prose, never inputs to investment rules."""

import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

_DIPLOMACY = re.compile(r"(?:미[·ㆍ/-]?이란|미국.{0,10}이란).{0,40}(?:중재|외교|협상)", re.I)
_LEADERSHIP = re.compile(
    r"(?:CEO|최고경영자|대표이사|회장).{0,60}(?:사임|퇴진|해임|교체|resign\w*|step(?:ped|s)? down|dismiss\w*)"
    r"|(?:임시|신임|interim|new).{0,15}(?:CEO|최고경영자|대표이사).{0,35}(?:선임|임명|appoint\w*|nam\w*)", re.I)
_BUSINESS_RISK = re.compile(
    r"(?:리더십|경영진|승계|규제).{0,30}(?:공백|불확실|우려)"
    r"|\b(?:leadership|succession|regulatory)\b.{0,30}\b(?:vacuum|uncertainty|concerns?)\b", re.I)
_LEADERSHIP_REQUEST = re.compile(
    r"(?:CEO|최고경영자|대표이사).{0,35}(?:복귀|복직|사임|퇴진|교체).{0,20}(?:요구|촉구).{0,45}(?:서한|청원|요청)"
    r"|(?:주주|투자자|직원).{0,45}(?:CEO|최고경영자|대표이사).{0,35}(?:복귀|복직|사임|퇴진|교체).{0,20}(?:요구|촉구)", re.I)
_CONFLICT_REPORT = re.compile(
    r"(?:이란|중동|바레인|호르무즈|우크라이나|러시아|미군|혁명수비대).{0,90}"
    r"(?:공격|공습|요격|격추|폭격)(?:했|한|해|하였|이.{0,10}발생).{0,35}(?:밝혔|주장했|전했|보도했|확인했)", re.I)
_MILITARY_CONTEXT = re.compile(r"군사|미군|기지|드론|미사일|발사체|레이더|방공|군대|병력|전투|유조선|군함|항로")
_PENDING_ACTION = re.compile(r"계획|예정|위협|경고했|공격하겠|보낼|제출할|전달할|요구할")
_QUALIFIED = re.compile(
    r"과거|지난해|작년|당시|지난\s*(?:주|달|분기)|않|아니|없|부인|가능|예정|검토|관측|전망|한다면|할\s*경우"
    r"|요구|촉구|필요|논의|계획|사임설|퇴진설"
    r"|\b(?:not|never|denied|if|may|might|could|would|will|expected|rumou?rs?|consider\w*|called for|previously|last year|last month|last week)\b", re.I)


def market_event_facts(paragraphs):
    from stock_lab_core.article_events import body_sentences, _HISTORY, _NEGATION, _CONDITIONAL

    facts, seen = [], set()
    for sentence in body_sentences(paragraphs):
        # Do not cut off a later denial, attribution or conditional clause.
        if len(sentence) > 140:
            continue
        if _DIPLOMACY.search(sentence):
            topic = "mediation"
            implication = "협상의 진전·결렬·부인은 구분해야 합니다. 이 보도만으로 합의 성사나 유가 방향을 확정하지 않습니다"
            check = "당사국 공식 발표와 같은 세션의 유가·금리 반응 확인"
        elif (_LEADERSHIP_REQUEST.search(sentence)
              and not any(rule.search(sentence) for rule in (_HISTORY, _NEGATION, _CONDITIONAL, _PENDING_ACTION))):
            topic = "leadership_request"
            implication = "인사 요구는 경영 불확실성이 이어지는 정황입니다. 이사회의 결정이나 실제 복귀를 뜻하지 않습니다"
            check = "이사회 공식 답변·인사 공시와 고객 계약·제품 일정 변경 여부 확인"
        elif (_CONFLICT_REPORT.search(sentence)
              and _MILITARY_CONTEXT.search(sentence)
              and not re.search(r"사이버|해커|해킹|전산망|악성코드|cyber|hacker", sentence, re.I)
              and not any(rule.search(sentence) for rule in (_HISTORY, _NEGATION, _CONDITIONAL, _PENDING_ACTION))):
            topic = "conflict_report"
            implication = "군사 충돌 보도는 에너지·물류 공급 위험을 높일 수 있습니다. 당사자 주장만으로 피해·공급 차질이나 가격 영향을 확정하지 않습니다"
            check = "상대 당사국 확인, 실제 시설·항로 피해와 같은 세션의 유가·운임 반응 확인"
        elif _LEADERSHIP.search(sentence) and not _QUALIFIED.search(sentence):
            topic = "leadership"
            implication = "경영진 교체는 의사결정·사업 일정의 불확실성을 높일 수 있습니다. 생산·계약 변경이나 경쟁사 수혜가 확인된 것은 아닙니다"
            check = "공식 인사 발표와 사업 일정·고객 계약 유지 여부, 관련 기업의 같은 세션 가격 반응 확인"
        elif _BUSINESS_RISK.search(sentence) and not re.search(
                r"과거|지난해|작년|당시|않|아니|없|부인|해소|완화|\b(?:not|never|denied|resolved|last year)\b", sentence, re.I):
            # Report the uncertainty itself, never promote it to an actual
            # resignation, restriction or cancelled customer contract.
            topic = "business_uncertainty"
            implication = "경영·규제 불확실성은 고객 발주와 공급 일정의 가시성을 낮출 수 있습니다"
            check = "공식 승계·규제 발표, 고객 계약과 제품 공급 일정의 실제 변경 여부 확인"
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
        return {"business_uncertainty": 1, "leadership_request": 2, "ai_credit": 2,
                "mediation": 3, "conflict_report": 3}.get(fact.get("topic"), 4)
    return sorted(facts, key=priority)


def event_context_sentence(facts):
    claims = [fact["summary"] for fact in ordered_market_facts(facts)
              if fact.get("topic") in {"leadership", "leadership_request", "business_uncertainty", "mediation", "conflict_report"}]
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
