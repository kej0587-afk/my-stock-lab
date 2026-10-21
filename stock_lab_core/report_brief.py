"""Reader-facing news selection from dated evidence, never invented catalysts."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, _cell, citation, first, is_held, records, stamp, text
from stock_lab_core.report_presentation import is_preopen_outlook, is_preopen_price_recap, news_theme, sector_news_topics

register_loaded_source(__name__, __file__)

ENTITIES = (
    ("NVDA", r"NVIDIA|엔비디아"), ("AMZN", r"Amazon|아마존|\bAWS\b|Trainium|트레이니엄"),
    ("META", r"\bMeta\b|메타"), ("MU", r"\bMicron\b|마이크론"),
    ("CRWV", r"CoreWeave|코어위브"), ("MSFT", r"Microsoft|마이크로소프트"),
    ("TSLA", r"\bTesla\b|테슬라"), ("RTX", r"\bRTX\b|Raytheon|레이시온"),
    ("BAE", r"BAE Systems|BAE시스템"), ("MSCI", r"\bMSCI\b"),
)


def brief_theme(row):
    title = text(row.get("title"))
    if re.search(r"CoreWeave|코어위브|Trainium|트레이니엄|NVIDIA|엔비디아|\bMicron\b|마이크론", title, re.I):
        return "반도체·AI"
    if re.search(r"\bTesla\b|테슬라|Roadster|로드스터", title, re.I):
        return "자동차·모빌리티"
    if re.search(r"\bMSCI\b", title, re.I):
        return "금융·기업실적"
    if re.search(r"방산|군수|BAE|\bRTX\b|Raytheon|APKWS|defen[cs]e", title, re.I):
        return "방산·군수"
    if re.search(r"비트코인|이더리움|암호화폐|Bitcoin|Ethereum|\bBTC\b|\bETH\b|crypto", title, re.I):
        return "암호화폐"
    if re.search(r"(?<![A-Za-z])AI(?![A-Za-z])|반도체|소프트웨어|semiconductor|\bchips?\b|software|PyTorch", title, re.I):
        return "반도체·AI"
    if re.search(r"금리|국채|환율|연준|CPI|PPI|FOMC|Treasury|inflation|yields?|\bFed\b", title, re.I):
        return "금리·경제지표"
    if re.search(r"원유|유가|WTI|Brent|oil|OPEC|에너지", title, re.I):
        return "에너지·지정학"
    return "시장·업종"


def _topics(title, entities):
    topics = set(sector_news_topics("", sector_name=title))
    if set(entities) & {"NVDA", "AMZN", "META", "MU", "CRWV", "MSFT"}:
        topics.update(("technology", "semiconductor", "memory", "software"))
    return topics


def _holding_links(held, title, entities, theme, market):
    from stock_lab_core.report_holdings import UNDERLYINGS

    topics = _topics(title, entities)
    names, cross_market = [], []
    for row in held:
        ticker = text(first(row, "티커", "ticker", "Ticker")).upper()
        name = text(first(row, "종목명", "자산명", "name"))
        base_topics = set(sector_news_topics(ticker, sector_name=name))
        for base in UNDERLYINGS.get(ticker.split(".")[0], ()):
            base_topics.update(sector_news_topics(base))
        if ticker in entities or (topics & base_topics) or (theme == "암호화폐" and ticker in {"BITX", "BITU", "BTC-USD"}):
            region = "KR" if ticker.endswith((".KS", ".KQ")) and not UNDERLYINGS.get(ticker.split(".")[0]) else "US"
            (names if market == region else cross_market).append(ticker)
    unique = list(dict.fromkeys(names))
    if unique:
        return ", ".join(unique[:4]) + (f" 외 {len(unique) - 4}개" if len(unique) > 4 else "")
    if cross_market:
        return "타시장 동종업종 참고: " + ", ".join(dict.fromkeys(cross_market))
    if held and theme == "금리·경제지표":
        return "보유 전반의 금리·환율 민감도 확인"
    return "직접 보유 연결 없음 · 시장 참고"


def build_news_brief(context, news, summary_rows, now, *, limit=6, exclude_keys=()):
    """Balance fresh company catalysts and market stories inside existing inputs."""
    from stock_lab_core.report_session import market_session_states

    states = context.get("market_states") or market_session_states(now, context.get("sessions"))
    held = [row for row in records(summary_rows) if is_held(row)]
    excluded = set(exclude_keys)
    candidates = []
    for row in records(news):
        market = row.get("market")
        published = stamp(first(row, "published_at", "published"))
        if market not in states or not published or published > now or is_preopen_outlook(row) or is_preopen_price_recap(row):
            continue
        active = row.get("news_bucket") == "current_session_news"
        if states[market]["phase"] == "intraday" and not active:
            continue
        target = states[market].get("active_date") if active else context.get("sessions", {}).get(market)
        if not target or row.get("session_date") != target or row.get("news_bucket") in {"next_session_news", "other_market_news"}:
            continue
        title = text(row.get("title"))
        if text(first(row, "link", "url")) in excluded:
            continue
        entities = [symbol for symbol, pattern in ENTITIES if re.search(pattern, title, re.I)]
        theme = brief_theme(row)
        link = _holding_links(held, title, entities, theme, market)
        catalyst = bool(re.search(r"공급|계약|규제|제한|공개|출시|투자|실적|조달|인수|정책|earnings|guidance|funding|financing|contract|launch|chip|restrict|upgrade", title, re.I))
        topic = news_theme(title)
        key = (market, target, topic, tuple(entities)) if topic else (market, target, row.get("event_key") or title.casefold())
        score = (int(not link.startswith("직접 보유")), int(catalyst), int(bool(entities)), int(bool(re.search("[가-힣]", title))))
        candidates.append((score, published, key, theme, row, link, active))
    selected, seen, counts = [], set(), {}
    for item in sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True):
        _, _, key, theme, row, _, _ = item
        if key in seen or counts.get(theme, 0) >= 2:
            continue
        selected.append(item)
        seen.add(key)
        counts[theme] = counts.get(theme, 0) + 1
        if len(selected) >= limit:
            break
    lines = ["분야 | 확인된 핵심 재료(보도) | 보유 노출 연결", "--- | --- | ---"]
    for _, published, _, theme, row, link, active in selected:
        title = text(row.get("title"))
        ko = text(first(row, "summary_ko", "한글요약"))
        if not re.search("[가-힣]", title):
            focus = ko if re.search("[가-힣]", ko) else news_theme(title)
            title = (focus + " · " if focus else "영문 보도 · ") + title
        basis = f"{row['market']} {row['session_date']} {'진행 세션' if active else '종가 세션'}"
        detail = citation(dict(row, title=title)) + f" · {published.astimezone(KST):%m/%d %H:%M} KST / {basis}"
        lines.append(" | ".join(_cell(value) for value in (theme, detail, link)))
    if not selected:
        return {"lines": ["한 줄 결론에 인용한 보도 외에 해당 거래일·출처 기준을 통과한 추가 핵심 재료 미확보."], "article_keys": []}
    lines.extend(["", "보도 내용은 출처의 주장입니다. 보유 연결은 업종·기초자산 노출이며 실제 가격 기여도나 매매 허용을 뜻하지 않습니다."])
    return {"lines": lines, "article_keys": [text(first(item[4], "link", "url")) for item in selected]}


def news_brief_lines(context, news, summary_rows, now, *, limit=6):
    return build_news_brief(context, news, summary_rows, now, limit=limit)["lines"]
