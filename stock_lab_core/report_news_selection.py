"""Explicit report preferences and title-based topic coverage (no causal inference)."""

import re

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

DEFAULT_CATEGORIES = ("반도체·AI", "지정학", "매크로/중국", "외환/금리", "조선", "에너지/해운",
                      "금융·은행", "암호화폐", "건설·인프라", "국채/유동성", "바이오·헬스케어")
SEARCH_TERMS = {
    "반도체·AI": ("반도체", "AI 투자"), "반도체·AI 리스크": ("AI 부채", "메모리 급락"),
    "지정학": ("이란", "휴전"), "매크로/중국": ("중국 경제", "중국 부양책"),
    "외환/금리": ("환율", "금리"), "조선": ("조선주", "한화오션"),
    "에너지/해운": ("유가", "해운"),
    "금융·은행": ("은행주", "금융주", "금융지주", "KB금융", "신한지주", "하나금융",
                  "우리금융", "기업은행", "카카오뱅크", "bank stocks", "JPMorgan"),
    "암호화폐": ("비트코인", "이더리움"), "건설·인프라": ("건설주", "인프라 투자"),
    "국채/유동성": ("국채", "유동성"), "바이오·헬스케어": ("바이오", "임상"),
    "원자재/금속": ("금값", "구리"), "실적/대장주": ("실적", "가이던스"),
    "우주/항공": ("우주항공", "스페이스X"), "정책/규제": ("관세", "금융 규제"),
}
TOPIC_CHECKS = {
    "반도체·AI": "반도체·기술주 보유자는 수요 기대가 실제 주문·이익으로 이어지는지 확인",
    "반도체·AI 리스크": "반도체·기술주 보유자는 투자 부담과 실제 주문 취소를 구분해 확인",
    "지정학": "에너지 공급·물류 차질과 유가 반응 확인; 협상 보도는 합의 확정과 구분",
    "매크로/중국": "한국 수출·소재·소비 업종에 연결될 실제 중국 수요와 정책 집행 확인",
    "외환/금리": "성장주 할인율과 해외자산 원화 평가 영향 확인; 환헤지 여부 구분",
    "조선": "수주 금액만 보지 말고 수익성·인도 시점 확인; 업종 반등과 개별 기업 실적 구분",
    "에너지/해운": "유가와 운임을 분리해 정유·해운·운송 업종별 비용/매출 영향 확인",
    "금융·은행": "대출 성장·이자마진과 연체율·충당금 부담을 함께 확인",
    "암호화폐": "현물과 레버리지 상품 변동을 구분하고 ETF 자금 흐름의 실제 집계 확인",
    "건설·인프라": "수주가 매출·현금흐름으로 이어지는 시점과 원가·자금조달 부담 확인",
    "국채/유동성": "국채 공급·매입과 금리 반응 확인; 국채 거래를 주식 순유입으로 간주하지 않음",
    "바이오·헬스케어": "임상 단계·주요 평가변수·허가 여부 확인; 개별 임상 결과를 업종 전체로 일반화하지 않음",
}
TOPICS = {
    "반도체·AI": r"반도체|인공지능|엔비디아|메모리|\b(?:AI|Nvidia|semiconductor|HBM|DRAM|Micron)\b",
    "반도체·AI 리스크": r"(?:AI|반도체|메모리).{0,30}(?:위험|우려|부채|과잉|급락)|(?:AI|chip|memory).{0,30}(?:risk|debt|excess|slump)",
    "지정학": r"지정학|중동|이란|휴전|전쟁|호르무즈|우크라이나|\b(?:Iran|ceasefire|geopolitic\w*|war|Hormuz|Ukraine)\b",
    "매크로/중국": r"중국|中\s|\b(?:China|Chinese|PBOC)\b",
    "외환/금리": r"환율|달러|엔화|금리|연준|\b(?:dollar|yen|yields?|rates?|FOMC|BOJ|Fed)\b",
    "조선": r"조선(?:주|업|사|소|업종)|조선\s*(?:강세|급등|상승|하락)|한국조선해양|현대중공업|삼성중공업|한화오션|\b(?:shipbuild\w*|shipyard\w*)\b",
    "에너지/해운": r"유가|원유|에너지|해운|운임|유조선|\b(?:oil|WTI|Brent|OPEC|shipping|tanker\w*|freight)\b",
    "금융·은행": (r"은행(?!나무|잎)|금융\s*지주|금융주|보험주|증권주|(?:KB|하나|우리|BNK|JB|DGB|iM)\s*금융|"
                  r"신한\s*(?:지주|금융)|카카오뱅크|제이피모건|JP모건|골드만삭스|모[건간]스탠리|"
                  r"\b(?:banks?|banking|insurers?|financials|financial\s+(?:groups?|holdings?|stocks?|institutions?)|"
                  r"J\.?\s*P\.?\s*Morgan|Citigroup|"
                  r"Goldman\s+Sachs|Morgan\s+Stanley|Wells\s+Fargo|HSBC)\b"),
    "암호화폐": r"비트코인|이더리움|가상자산|암호화폐|\b(?:Bitcoin|Ethereum|crypto|BTC|ETH)\b",
    "건설·인프라": r"건설|인프라|철도|전력망|\b(?:construction|infrastructure|railway|power grid)\b",
    "국채/유동성": r"국채|유동성|양적긴축|양적완화|\b(?:Treasur\w*|liquidity|QT|QE|refunding|repo)\b",
    "바이오·헬스케어": r"바이오|제약|백신|임상|헬스케어|\b(?:biotech|healthcare|pharma\w*|vaccine|clinical trial|Moderna)\b",
    "원자재/금속": r"원자재|금값|구리|리튬|\b(?:gold|copper|lithium|metals?)\b",
    "실적/대장주": r"실적|가이던스|\b(?:earnings|guidance|revenue)\b",
    "우주/항공": r"우주|항공|위성|\b(?:SpaceX|Starlink|satellite|aerospace)\b",
    "정책/규제": r"정책|규제|관세|\b(?:policy|regulation|tariff)\b",
}


_CENTRAL_BANKS = re.compile(
    r"한국은행|일본은행|중국인민은행|인민은행|(?:유럽)?중앙은행|세계은행|"
    r"\b(?:(?:European\s+)?central\s+banks?|(?:Federal\s+)?Reserve\s+Bank(?:\s+of\s+\w+)?|"
    r"Bank\s+of\s+(?:Korea|Japan|England|Canada)|People['’]s\s+Bank\s+of\s+China|World\s+Bank)\b", re.I)
_FINANCE_MATERIAL = re.compile(
    r"실적|순이익|순익|이자마진|순이자|충당금|연체율|부실|자본비율|배당|자사주|주주환원|"
    r"규제|의결요건|지배구조|회장.{0,16}연임|지분.{0,16}(?:매각|인수)|"
    r"\b(?:earnings|profits?|dividends?|buybacks?|CET1|NIM|defaults?|provisions?|regulat\w*)\b", re.I)
_FINANCE_PROMO = re.compile(
    r"연탄|김장|봉사활동|장학금|금융특강|금융교육|사회공헌|경품|쿠폰|캐시백|특판|"
    r"관광.{0,30}(?:협약|협력|맞손)|"
    r"가입.{0,12}(?:혜택|이벤트)|계좌.{0,12}개설.{0,20}(?:혜택|이벤트)|"
    r"\b(?:cashback|giveaway|sweepstakes|sign.up\s+bonus|charity\s+event|food\s+banks?)\b", re.I)


def _matches_finance(title):
    # Central-bank policy alone is macro evidence, not listed-bank coverage.
    subject = _CENTRAL_BANKS.sub("", title)
    if not re.search(TOPICS["금융·은행"], subject, re.I):
        return False
    # Keep earnings/regulatory reporting about promotions or deposit competition.
    return not _FINANCE_PROMO.search(subject) or bool(_FINANCE_MATERIAL.search(subject))


def matching_categories(title, categories=None):
    # Query membership alone must never label unrelated search results.
    title = str(title or "")
    return [category for category in (TOPICS if categories is None else categories)
            if category in TOPICS and (_matches_finance(title) if category == "금융·은행"
                                       else re.search(TOPICS[category], title, re.I))]


def report_news_options(state):
    saved = state.get("_report_news_preferences", {})
    def value(key, default):
        return state.get("today_market_memo_" + key, saved.get(key, default))
    return {"include_market": bool(value("include_market_rss", True)),
            "categories": tuple(value("story_categories", DEFAULT_CATEGORIES)),
            "per_category": max(1, min(4, int(value("story_per_category", 2)))),
            "include_stocks": bool(value("include_rss", False)),
            "stock_count": max(1, min(8, int(value("news_count", 4))))}


def save_news_preferences(state):
    keys = ("include_market_rss", "story_categories", "story_per_category", "include_rss", "news_count")
    saved = dict(state.get("_report_news_preferences", {}))
    saved.update({key: state["today_market_memo_" + key] for key in keys if "today_market_memo_" + key in state})
    state["_report_news_preferences"] = saved


def restore_news_preferences(state):
    for key, value in state.get("_report_news_preferences", {}).items():
        state.setdefault("today_market_memo_" + key, value)


def selected_category_lines(context, now):
    """Make every requested topic's result visible, including honest empty results."""
    from stock_lab_core.report_evidence import _cell, citation, stamp, curate_news
    from stock_lab_core.article_context import verified_body_facts
    categories = context.get("news_retrieval", {}).get("requested_categories", [])
    if not categories:
        return []
    per_category = context["news_retrieval"].get("per_category", 2)
    rows = [row for bucket in ("session_news", "current_session_news", "next_session_news", "other_market_news")
            for row in context.get(bucket, [])]
    rows = curate_news(rows, now=now, limit=240, session_scoped=True)
    rows.sort(key=lambda row: stamp(row.get("published_at") or row.get("published")) or now, reverse=True)
    lines = ["", "## 선택 분야별 뉴스", "분야 | 확인된 재료·의미 | 시점·연결 상태", "--- | --- | ---"]
    seen = {}
    for category in categories:
        selected, keys = [], set()
        # Stable sort preserves recency within each group and other topic order.
        candidates = (sorted(rows, key=lambda row: not bool(_FINANCE_MATERIAL.search(str(row.get("title") or ""))))
                      if category == "금융·은행" else rows)
        for row in candidates:
            at = stamp(row.get("published_at") or row.get("published"))
            key = row.get("link")
            if not at or at > now or not key or key in keys or not matching_categories(row.get("title"), [category]):
                continue
            keys.add(key)
            selected.append((row, at, key))
            if len(selected) >= per_category:
                break
        if not selected:
            diagnostics = context["news_retrieval"]
            status = ("RSS 수집 실패·재조회 필요" if category in diagnostics.get("failed_categories", []) else
                      "조회할 시장 세션 미확보" if "queried_categories" in diagnostics and category not in diagnostics["queried_categories"] else
                      "조회했으나 미확보 · 사건이 없다는 뜻 아님")
            lines.append(f"{category} | 날짜·출처·주제 검증을 통과한 기사 없음 | {status}")
        for row, at, key in selected:
            if key in seen:
                detail = f"{seen[key]} 행과 같은 기사(중복 본문 생략) " + citation(dict(row, title="관련 기사"))
            else:
                seen[key] = category
                facts = verified_body_facts(row)
                detail = citation(row)
                if facts:
                    detail += " · 사실(본문): " + facts[0]["summary"] + " · 해석(추정): " + facts[0]["implication"]
                else:
                    body_times = [stamp(row.get(field)) for field in ("body_published_at", "body_modified_at")]
                    checked = (row.get("body_status") == "no_supported_context"
                               and row.get("body_source_url") == key
                               and all(value and value <= now for value in body_times)
                               and min(abs((at - value).total_seconds()) for value in body_times) <= 3600)
                    detail += (" · 본문 확인·자동 해석 근거 부족" if checked else " · 제목 확인·본문 원인 해석 보류")
                    reading = row.get("reading_ko") or ""
                    if reading and not re.search("[가-힣]", row.get("title", "")):
                        detail += " · " + reading
                if category in TOPIC_CHECKS:
                    detail += " · 보유 검토: " + TOPIC_CHECKS[category]
            bucket = row.get("news_bucket")
            basis = ("다음 세션 재료·현재 종가 원인 아님" if bucket == "next_session_news" else
                     "해외·공통 맥락·한국/미국 등락 원인 미확정" if bucket == "other_market_news" else
                     f"{row.get('market', '')} {row.get('session_date', '')} {'장중' if bucket == 'current_session_news' else '종가 세션'}")
            lines.append(" | ".join(_cell(v) for v in (category, detail, f"{at:%m/%d %H:%M} KST · {basis}")))
    return lines
