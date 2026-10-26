"""Conservative subject-bound price facts; no inference from other assets."""

import re
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


_SUBJECT = re.compile(r"(?:국제\s*)?유가(?!증권)|(?<![A-Za-z])WTI(?![A-Za-z])|브렌트유|\bBrent(?:\s+crude)?\b|\boil\s+prices?\b", re.I)
_OTHER_ASSET = re.compile(r"증시|주가지수|주가|주식|금값|국채|금리|다우|나스닥|S&P|\bstocks?\b|\bshares\b|\bequities\b|\bgold\b|\byields?\b", re.I)
_CLAUSE_END = re.compile(r"속에서|속에|여파로|영향으로|때문에|가운데|에도\s|(?<=급등)으로|(?<=상승)으로|(?<=급락)으로|(?<=하락)으로")
_DIRECTION = re.compile(r"(?P<up>급등|상승|올랐|오른|올라|\brose\b|\brisen\b|\brises?\b|\brallied\b|\bsurges?\b|\bsurged\b|\bclimbed\b)"
                        r"|(?P<down>급락|하락|내렸|내린|떨어졌|떨어진|\bfell\b|\bfallen\b|\bfalls?\b|\bdrops?\b|\beased\b|\bretreated\b|\bdropped\b)", re.I)
_UNCERTAIN = re.compile(r"않|아니|못했|가능|예상|전망|우려|기대|예측|가정|진정|둔화|완화|\b(?:not|never|may|might|could|expected|forecast|fears?)\b", re.I)


def oil_price_fact(paragraphs):
    """Only a local oil predicate counts; mixed/forecast directions stay unknown."""
    directions = {}
    for paragraph in paragraphs:
        for sentence in re.split(r"[;!?\n]|\.\s+", paragraph):
            for subject in _SUBJECT.finditer(sentence):
                tail = sentence[subject.end():subject.end() + 70]
                tail = _OTHER_ASSET.split(tail, maxsplit=1)[0]
                tail = _CLAUSE_END.split(tail, maxsplit=1)[0]
                for move in _DIRECTION.finditer(tail):
                    if move.start() > 45:
                        continue
                    # Keep reversals, but not forecasts, negations or an easing of a rise.
                    local = tail[:move.end() + 16]
                    if _UNCERTAIN.search(local) or _UNCERTAIN.search(sentence[max(0, subject.start()-20):subject.start()]):
                        continue
                    directions.setdefault("up" if move.group("up") else "down", sentence)
    if not directions:
        return None
    if len(directions) > 1:
        topic, summary, implication = ("oil_mixed", "유가의 상승·하락이 함께 언급돼 단일 방향 해석을 보류합니다",
                                       "다른 기간·유종의 움직임일 수 있어 기사 속 비교 기준을 확인해야 합니다")
    elif "up" in directions:
        topic, summary, implication = ("oil_rising", "유가 상승이 보도됐습니다",
                                       "유가 상승은 비용·물가 및 금리 부담을 높일 수 있으나 주가 하락의 단독 원인이나 기여도는 확정할 수 없습니다")
    else:
        topic, summary, implication = ("oil_easing", "유가 하락이 보도됐습니다",
                                       "유가 하락은 비용·물가 부담을 덜 수 있지만 가격 수준이 여전히 높다면 부담 해소로 단정할 수 없습니다")
    evidence = next(iter(directions.values()))
    return dict(topic=topic, summary=summary, implication=implication,
                check="WTI·브렌트의 기준일·가격 수준과 공급·지정학 뉴스 확인",
                evidence=evidence[:140] + ("…" if len(evidence) > 140 else ""))
