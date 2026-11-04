"""Read-only, source-bound cross-announcement interpretation; no I/O or scores."""

from datetime import timedelta
import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, curate_news, records, safe_link, stamp, text

register_loaded_source(__name__, __file__)

# Economic relationships, not company lists or dated stories.
_FAMILIES = (
    ("AI·반도체 공급망", r"반도체|메모리|데이터센터|\b(?:AI|semiconductors?|memory|chips?|data centers?|datacenters?|servers?|compute)\b"),
    ("에너지·운송", r"유가|원유|해운|항공유|운임|\b(?:oil|crude|fuel|shipping|freight|energy)\b"),
    ("신용·금융", r"대출|은행|신용|국채|\b(?:banks?|loans?|credit|treasur\w*|lending)\b"),
)
_CHANNELS = (
    ("원가·마진", r"원가|비용|마진|가격|\b(?:costs?|margins?|pricing|prices?)\b"),
    ("지출·계약", r"설비투자|자본지출|지출.{0,8}약정|구매.{0,8}약정|\b(?:capex|capital expenditure\w*|spending|commitments?)\b"),
    ("조달·현금", r"자금조달|투자유치|잉여.?현금|현금흐름|현금 흐름|\b(?:funding|financing|cash flow|FCF|debt|IPO)\b"),
    ("수요·실적", r"실적|매출|수주|수요|가이던스|\b(?:earnings|revenue|sales|orders?|demand|guidance|financial results)\b"),
)


def _classify(sentence):
    family = next((label for label, pattern in _FAMILIES if re.search(pattern, sentence, re.I)), None)
    channels = [label for label, pattern in _CHANNELS if re.search(pattern, sentence, re.I)]
    return family, channels


def _evidence(context, pipeline, news, now):
    # A release day is not an intraday timestamp. Existing verified pipeline
    # establishes publication; failed/stale results are not fresh evidence.
    for packet in pipeline.get("packets", []):
        day = stamp(packet.get("date"))
        if (not packet.get("official") or packet.get("event", {}).get("result_stale") or not day
                or not now.date() - timedelta(days=3) <= day.date() <= now.date()):
            continue
        for key, metric in (packet.get("metrics") or {}).items():
            if key not in {"revenue", "profit", "capex", "free_cash_flow", "guidance"}:
                continue
            value, url = text(metric.get("text")), safe_link(metric.get("source_url"))
            if metric.get("status") not in {"reported", "available"} or not value or not url:
                continue
            # Do not truncate evidence: a removed clause can reverse its meaning.
            if len(value) > 1200:
                continue
            family, channels = _classify(value + " " + text(packet.get("sector")))
            if not family or not channels:
                continue
            scope = "TTM·분기 아님" if metric.get("period_scope") == "trailing_twelve_months" else text(packet.get("fiscal_period"))
            yield dict(family=family, channels=channels, sentence=value, url=url,
                identity=(packet.get("ticker"), packet.get("fiscal_period"), packet.get("date")),
                label="회사 전망·실제치 아님" if key == "guidance" else "공식 발표 수치",
                basis=f"{packet.get('name', '')} · {packet.get('market', '')} · {packet.get('date', '')} 발표 · {scope}",
                at=day, official=True)
    corpus = [*records(news), *(row for key in ("session_news", "current_session_news", "next_session_news", "other_market_news")
                               for row in records(context.get(key)))]
    # Keep the existing source, URL, date and duplicate safeguards.
    topic_pattern = re.compile("|".join(pattern for _, pattern in _FAMILIES), re.I)
    for row in curate_news(corpus, now=now, limit=120, session_scoped=True, title_pattern=topic_pattern):
        at = stamp(row.get("published_at") or row.get("published"))
        title, url = text(row.get("title")), safe_link(row.get("link"))
        if not at or not now - timedelta(days=3) <= at <= now or not title or not url:
            continue
        family, channels = _classify(title)
        if not family or not channels:
            continue
        yield dict(family=family, channels=channels, sentence=title, url=url,
            identity=("news", re.sub(r"\W+", "", title).casefold()),
            label="보도 제목·주장 (본문·수치 대조 미완료)",
            basis=f"{row.get('publisher', row.get('source', ''))} · {at:%m/%d %H:%M} KST 보도 · "
                  f"{row.get('market') or '시장 미확인'} / {row.get('session_date') or '세션 미확인'}",
            at=at, official=False)


def _reading(channels):
    readings, checks = [], []
    if {"수요·실적", "원가·마진"} <= channels:
        readings.append("수요·매출과 원가·마진 자료가 함께 있습니다. 공급기업의 판매 기회와 구매기업의 비용 부담은 다를 수 있으므로 업종 전체의 같은 호재·악재로 묶지 않습니다.")
        checks.append("같은 기간의 주문·매출 증가가 원가를 뺀 이익률 개선으로 이어지는지")
    if "지출·계약" in channels:
        readings.append("지출·계약 규모는 실제 집행액이나 확보한 자금과 다릅니다. 공급망 수요로 연결될 가능성과 집행·회수 부담을 함께 점검합니다.")
        checks.append("약정의 집행 기간·취소 조건, 실제 발주와 자금조달·현금흐름")
    elif "조달·현금" in channels:
        readings.append("조달·현금 자료는 사업 확대의 재원과 지속 가능성을 점검할 근거입니다. 자금 유입이 이익이나 고객 수요를 뜻하지는 않습니다.")
        checks.append("조달 조건·만기와 영업현금흐름의 변화")
    return " ".join(readings), " / ".join(checks)


def market_connection_lines(context, pipeline, news, now):
    """Connect at most three topics, with displayed evidence backing each reading."""
    now = stamp(now)
    if now is None:
        return []
    evidence = sorted(_evidence(context, pipeline, news, now),
                      key=lambda e: (e["at"].date(), e["official"], e["at"]), reverse=True)
    groups = []
    for family, _ in _FAMILIES:
        chosen, seen, urls, channels = [], set(), set(), set()
        candidates = [e for e in evidence if e["family"] == family]
        # Prefer complementary channels; repeated stories alone cannot build a
        # cross-announcement thesis. Keep only evidence displayed below.
        for item in candidates:
            if item["identity"] in seen or item["url"] in urls or (len(chosen) >= 2 and not set(item["channels"]) - channels):
                continue
            chosen.append(item)
            seen.add(item["identity"])
            urls.add(item["url"])
            channels.update(item["channels"])
            if len(chosen) == 3:
                break
        if len(chosen) < 2 or len(channels) < 2:
            continue
        reading, check = _reading(channels)
        if reading:
            groups.append((family, chosen, reading, check))
    lines = ["", "### 주요 발표를 연결해서 보면"]
    if not groups:
        return lines + ["서로 연결해 설명할 최근 발표 근거가 부족합니다. 뉴스가 없다는 뜻은 아니며, 확인되지 않은 인과관계는 만들지 않습니다."]
    for family, chosen, reading, check in groups:
        lines += ["", f"**{family}**", "근거 구분·시점 | 원문에서 확인할 내용", "--- | ---"]
        for item in chosen:
            sentence = item["sentence"].replace("$", r"\$")
            lines.append(_cell(item["label"] + " · " + item["basis"]) + " | " + _cell(sentence) + f" [출처]({item['url']})")
        lines += ["", "**연결 해석(가설)**: " + reading, "", "**확인·반증 기준**: " + check + "."]
    return lines + ["", "최근 3일의 수집된 자료 연결입니다. 시장·발표시점이 다른 자료를 포함할 수 있어 당일 등락의 원인이나 가격 기여도로 단정하지 않습니다. 투자 판정·점수에는 반영하지 않습니다."]
