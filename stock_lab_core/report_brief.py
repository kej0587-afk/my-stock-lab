"""Reader-facing news selection from dated evidence, never invented catalysts."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, MARKET_TERMS, _cell, citation, curate_news, first, is_held, records, safe_link, stamp, text
from stock_lab_core.report_presentation import is_preopen_outlook, is_preopen_price_recap, news_theme, sector_news_topics

register_loaded_source(__name__, __file__)

ENTITIES = (
    ("NVDA", r"NVIDIA|엔비디아"), ("AMZN", r"Amazon|아마존|\bAWS\b|Trainium|트레이니엄"),
    ("META", r"\bMeta\b|메타"), ("MU", r"\bMicron\b|마이크론"),
    ("CRWV", r"CoreWeave|코어위브"), ("MSFT", r"Microsoft|마이크로소프트"),
    ("GOOGL", r"Alphabet|알파벳|Google|구글"),
    ("FFIV", r"\bF5\b|\bFFIV\b"), ("FTNT", r"Fortinet|포티넷|\bFTNT\b"),
    ("PANW", r"Palo Alto|팔로알토|\bPANW\b"), ("CRWD", r"CrowdStrike|크라우드스트라이크|\bCRWD\b"),
    ("TSLA", r"\bTesla\b|테슬라"), ("RTX", r"\bRTX\b|Raytheon|레이시온"),
    ("BAE", r"BAE Systems|BAE시스템"), ("MSCI", r"\bMSCI\b"),
)


def brief_theme(row, *, comprehensive=False):
    if comprehensive:
        return _comprehensive_theme(row)
    title = text(row.get("title"))
    if row.get("is_close_wrap") and re.search(r"코스피|코스닥|뉴욕증시|Wall Street|U\.S\. Stocks", title, re.I):
        return "한국 시황" if row.get("market") == "KR" else "미국 시황"
    if re.search(r"사이버|cyber|Fortinet|포티넷|\bF5\b|\bFFIV\b|Palo Alto|팔로알토|CrowdStrike|크라우드스트라이크", title, re.I):
        return "사이버보안"
    if re.search(r"Alphabet|알파벳|Google|구글", title, re.I):
        return "빅테크·기업실적"
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


def _comprehensive_theme(row):
    """Display taxonomy from named issuers/businesses, never a price cause."""
    from stock_lab_core.earnings_discovery import issuer_catalog, _name_match

    title = text(row.get("title"))
    legacy = brief_theme(row)
    if row.get("is_close_wrap") or legacy in {"사이버보안", "자동차·모빌리티", "방산·군수", "암호화폐"}:
        return legacy
    # Central-bank speakers are policy subjects, not bank/issuer aliases.
    if re.search(r"\b(?:Fed|FOMC|ECB|BOJ|PBOC|Federal Reserve|central bank|Bank of Japan|Bank of Korea)\b|연준|연은|한국은행|일본은행|중앙은행", title, re.I):
        return "금리·경제지표"
    for label, pattern in (
        ("반도체", r"Trainium|트레이니엄|TSMC|삼성전자|SK\s*하이닉스"),
        ("클라우드·소프트웨어", r"CoreWeave|코어위브|\bAWS\b|\bAzure\b|Google Cloud|클라우드|\bcloud\b|\bneoclouds?\b"),
        ("전력·산업재", r"Constellation Energy|콘스텔레이션|NextEra Energy|넥스트에라"),
    ):
        if re.search(pattern, title, re.I):
            return label
    labels = {"반도체": "반도체", "소프트웨어·보안": "클라우드·소프트웨어", "소비재": "소비·유통",
              "금융": "금융", "헬스케어": "헬스케어·바이오", "바이오": "헬스케어·바이오",
              "에너지·소재": "에너지·소재", "산업·전력": "전력·산업재", "전력·기계": "전력·산업재",
              "자동차": "자동차·모빌리티", "인터넷": "플랫폼·통신"}
    sectors = sorted({labels.get(entry["sector"], entry["sector"]) for entry in issuer_catalog().values()
                      if _name_match(title, entry)})
    if sectors:
        return " / ".join(sectors)
    for label, pattern in (
        ("금융", r"금융|은행|증권|보험|\bbanks?\b|\bbanking\b|\binsurance\b|\bMSCI\b"),
        ("소비·유통", r"소비재|소매|유통|\bretail\b|\bconsumer\b"),
        ("헬스케어·바이오", r"제약|바이오|임상|의료|\bhealthcare\b|\bpharma\b|\bbiotech\b|clinical trial|\bFDA\b"),
        ("클라우드·소프트웨어", r"소프트웨어|\bsoftware\b"),
        ("반도체", r"반도체|메모리|\bsemiconductors?\b|\bchips?\b"),
    ):
        if re.search(pattern, title, re.I):
            return label
    return legacy


_MATERIAL_TERMS = re.compile(
    r"실적|매출|영업이익|순이익|가이던스|수주|계약|공급|출시|인수|합병|조달|부채|채무|투자|규제|정책|"
    r"금리|환율|국채|물가|고용|증시|코스피|코스닥|나스닥|주가|급등|급락|상승|하락|유가|원유|"
    r"관세|제재|전쟁|타격|휴전|사임|사퇴|퇴진|경영진|파업|교섭|상장|임상|허가|발표|경고|"
    r"\b(?:earnings|revenues?|profits?|EPS|guidance|results|contracts?|supply|launch\w*|acquisition|merger|"
    r"debt|credit|financing|funding|investment|capex|capital expenditur\w*|capital spending|dividends?|buybacks?|"
    r"regulation|restrictions?|tariffs?|sanctions?|rates?|inflation|yields?|jobs|sales|stocks?|shares?|markets?|"
    r"rall\w*|gains?|falls?|rises?|oil|resigns?|succession|IPO|approv\w*|trial|announc\w*|warn\w*|policy|speech|liquidity)\b", re.I)
_BRIEF_TERMS = re.compile(MARKET_TERMS.pattern + "|" + _MATERIAL_TERMS.pattern + r"|\b(?:cloud|software|options?|central bank)\b", re.I)


def material_news(row):
    """Main-path editorial filter only; the collected appendix stays untouched.

    No issuer list, count quota or source promotion. Explicit promotional/history
    formats stay in the appendix; generic valuation questions need body evidence.
    """
    from stock_lab_core.article_context import verified_body_facts
    title = text(row.get("title"))
    if re.search(r"폐(?:전자제품|가전).{0,25}재활용|임직원.{0,20}(?:봉사|나눔)|상속\s*서비스|비대면\s*상속|"
                 r"이런 펀드 어때요|채권투자 길라잡이|캠퍼스\s*인접|모델하우스|분양\s*(?:혜택|홍보)|"
                 r"인물열전|급등주 지금은|화제의 바이오人|기자수첩|\((?:기고|칼럼)\)|"
                 r"\b(?:historical profile|sponsored content|banking rewards|how to open an account)\b", title, re.I):
        return False
    facts = verified_body_facts(row)
    if not facts and re.search(r"\b(?:cheap(?:er)?|bargain|investment case|bull case|fair value|undervalued narrative)\b|"
                              r"\bvaluation\b.{0,30}\bfocus\b|\bHow .{0,60}\b(?:impact|affect)\b.{0,30}\binvestors\b", title, re.I):
        return False
    return bool(facts or _MATERIAL_TERMS.search(title))


def explicit_news_market(row):
    """Known subject identity, independent of query locale or article language."""
    from stock_lab_core.earnings_discovery import issuer_catalog, _name_match
    from stock_lab_core.today_news import _HEADLINE_MARKETS
    title = text(row.get("title"))
    markets = {market for market, pattern in _HEADLINE_MARKETS.items() if pattern.search(title)}
    if len(markets) == 1:
        return next(iter(markets))
    if markets:
        return ""
    markets = {entry["market"] for entry in issuer_catalog().values() if _name_match(title, entry)}
    # Existing domestic semiconductor universe (money_flow) includes this issuer;
    # keep the identity local without loading the price/flow collector.
    if re.search(r"제주반도체|\bJeju Semiconductor\b", title, re.I):
        markets.add("KR")
    return next(iter(markets)) if len(markets) == 1 else ""


def news_session_bounds(context, market, day):
    """Exchange schedule only. A news window's end is not a closing timestamp."""
    if market not in {"KR", "US"}:
        return None, None
    zone = ZoneInfo("Asia/Seoul" if market == "KR" else "America/New_York")
    try:
        session_day = datetime.fromisoformat(day)
    except (ValueError, TypeError):
        return None, None
    specs = [context.get(name, {}).get(market, {}) for name in ("current_news_sessions", "news_sessions")]
    specs += records(context.get("current_windows")) + records(context.get("windows"))
    specs = [spec for spec in specs if spec.get("date") == day and spec.get("market", market) == market]

    def scheduled(*fields):
        for spec in specs:
            value = stamp(first(spec, *fields))
            if value and value.astimezone(zone).date() == session_day.date():
                return value
        return None

    opening = scheduled("open_at", "scheduled_open") or session_day.replace(hour=9, minute=0 if market == "KR" else 30, tzinfo=zone)
    close = scheduled("scheduled_close", "close_at") or session_day.replace(hour=15 if market == "KR" else 16, minute=30 if market == "KR" else 0, tzinfo=zone)
    return opening, close


def news_observation(row, context):
    """Publication-time label and display order, never a reconstructed price cause."""
    market, day = row.get("market"), text(row.get("session_date"))
    published = stamp(first(row, "published_at", "published"))
    subject = explicit_news_market(row)
    if subject and market in {"KR", "US"} and subject != market:
        return 0, f"{subject} 기업·시장 재료 · 수집시장 {market} · 해당 종가 귀속 미확인"
    if market not in {"KR", "US"} or not day or published is None:
        scope = "국내·공통 맥락" if subject == "KR" else "해외·공통 맥락"
        return 0, f"{subject or market or '시장 미확인'} · 발행시각 기준 {scope}"
    zone = ZoneInfo("Asia/Seoul" if market == "KR" else "America/New_York")
    local = published.astimezone(zone)
    opening, close = news_session_bounds(context, market, day)
    if opening is None or close is None:
        return 0, f"{market} · 발행시각 기준 · 거래일 귀속 미확인"
    title = text(row.get("title"))
    wrap = bool(row.get("is_close_wrap") or re.search(r"마감|장종료|\bclose[ds]?\b|\bend\b.{0,30}\b(?:higher|lower|week)\b", title, re.I))
    reference = max(day, text(context.get("sessions", {}).get(market)))
    if local.date().isoformat() < reference:
        prior_close = wrap or (local.hour >= 16 and market == "US" and re.search(r"나스닥|뉴욕증시|Wall Street|S&P|Nasdaq", title, re.I))
        label = "이전 종가 관측" if prior_close else "이전 거래일 보도·장전 재료"
        return 0, f"{market} {local:%Y-%m-%d} {label} · {reference} 종가 원인 미확인"
    if published < opening:
        return 1, f"{market} {day} 장전 보도 · 종가 원인 미확인"
    if published < close:
        return 1, f"{market} {day} 장중 관측 · 종가와 구분"
    if local.date().isoformat() == day and wrap:
        return 3, f"{market} {day} 마감 보도 · 기사 주장"
    return 2, f"{market} {day} 마감 후 보도 · 해당 종가 원인 미확인"


def _validated_brief_row(row, context, now, *, other=False):
    """Recheck existing source/time evidence, without collecting any new data."""
    from stock_lab_core.today_news import _news_timestamp, partition_session_market_news

    published = _news_timestamp(first(row, "published_at", "published"))
    if published is None or published > now or (other and published < now - timedelta(days=7)):
        return None
    checked = curate_news([row], now=published, limit=1, title_pattern=_BRIEF_TERMS)
    if not checked or not safe_link(checked[0].get("link")):
        return None
    clean = checked[0]
    subject = explicit_news_market(clean)
    if not other and subject and subject != clean.get("market"):
        return None
    if other:
        return clean
    market = clean.get("market")
    closed, current = context.get("news_sessions") or {}, context.get("current_news_sessions") or {}
    if market in closed or market in current:
        partitioned = partition_session_market_news([clean], closed, now=now, current_sessions=current)
        bucket = clean.get("news_bucket") or "session_news"
        candidates = partitioned.get(bucket, [])
        if not any(candidate.get("market") == market and candidate.get("session_date") == clean.get("session_date")
                   for candidate in candidates):
            # Keep a validated previous close as explicitly dated context, never
            # as the new session's return/cause. Do not invent a previous day.
            previous = closed.get(market, {}).get("previous_date")
            if not (clean.get("session_date") == closed.get(market, {}).get("date") and any(
                    candidate.get("market") == market and candidate.get("session_date") == previous
                    and candidate.get("is_close_wrap") for candidate in partitioned.get("other_market_news", []))):
                return None
    else:
        # Older saved contexts lack previous-session windows. Do not invent one
        # or accept a previous-day story merely because its UI label was changed.
        local = published.astimezone(ZoneInfo("Asia/Seoul" if market == "KR" else "America/New_York"))
        if local.date().isoformat() != clean.get("session_date"):
            return None
        if market == "US" and (local.hour, local.minute) > (16, 0):
            if not clean.get("is_close_wrap") or (local.hour, local.minute) > (18, 0):
                return None
    return clean


def _topics(title, entities):
    topics = set(sector_news_topics("", sector_name=title))
    if set(entities) & {"NVDA", "AMZN", "META", "MU", "CRWV", "MSFT"}:
        topics.update(("technology", "semiconductor", "memory", "software"))
    if re.search(r"(?:AI|인공지능).{0,20}(?:차입|신용|부채|투자|수요)|AI Debt", title, re.I):
        topics.update(("technology", "semiconductor", "memory", "software"))
    return topics


def _holding_links(held, title, entities, theme, market, *, constituent_evidence=()):
    from stock_lab_core.report_holdings import UNDERLYINGS

    topics = _topics(title, entities)
    names, cross_market = [], []
    for row in held:
        ticker = text(first(row, "티커", "ticker", "Ticker")).upper()
        name = text(first(row, "종목명", "자산명", "name"))
        # A broad AI/semiconductor story is not direct cybersecurity ETF exposure.
        if ticker == "CIBR":
            linked = [item for item in constituent_evidence if item.get("etf") == ticker]
            if linked and market == "US":
                members = ", ".join(dict.fromkeys(item["constituent"] for item in linked))
                source = linked[0]
                names.append(f"CIBR({members} 편입·{source['holdings_as_of']} 구성, 기여도 미확인)"
                             f" [구성 출처]({source['source_url']})")
            elif theme == "사이버보안" or ticker in entities:
                (names if market == "US" else cross_market).append("CIBR(보안업종 간접)")
            continue
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


def build_news_brief(context, news, summary_rows, now, *, limit=6, exclude_keys=(), compact=False,
                     comprehensive=False, include_other_markets=False):
    """Read existing news only. Default selection retains the legacy caps.

    comprehensive=True (or limit=None) retains distinct material articles,
    without row/theme quotas or broad topic clustering. Explicit exclusions are
    final. Opt-in other-market rows retain their own publication context; pass
    those rows separately to render a global-context section, not KR/US causes.
    """
    from stock_lab_core.report_session import market_session_states
    from stock_lab_core.news_priority import editorial_priority, market_news_priority

    states = context.get("market_states") or market_session_states(now, context.get("sessions"))
    held = [row for row in records(summary_rows) if is_held(row)]
    excluded = set(exclude_keys)
    comprehensive = comprehensive or limit is None
    candidates = []
    for row in records(news):
        market = row.get("market")
        other = comprehensive and include_other_markets and market in {"GLOBAL", "JP", "CN", "ASIA", "EU"}
        if comprehensive:
            if not material_news(row):
                continue
            if market not in states and not other:
                continue
            if text(first(row, "link", "url")) in excluded:
                continue
            row = _validated_brief_row(row, context, now, other=other)
            if row is None:
                continue
        published = stamp(first(row, "published_at", "published"))
        if ((market not in states and not other) or not published or published > now or is_preopen_outlook(row)
                or (not comprehensive and is_preopen_price_recap(row))):
            continue
        active = not other and row.get("news_bucket") == "current_session_news"
        if not other and states[market]["phase"] == "intraday" and not active:
            continue
        target = published.date().isoformat() if other else states[market].get("active_date") if active else context.get("sessions", {}).get(market)
        if not other and (not target or row.get("session_date") != target or row.get("news_bucket") in {"next_session_news", "other_market_news"}):
            continue
        title = text(row.get("title"))
        if re.search(r"^\s*\[표\]|순매수\s*(?:상위|순위)|순매도\s*(?:상위|순위)", title):
            continue
        from stock_lab_core.article_context import verified_body_facts
        body_facts = verified_body_facts(row)
        priority = editorial_priority(row, {
            "sessions": context.get("sessions", {}),
            "current_sessions": context.get("current_news_sessions", {}),
            "sector_rows": [*context.get("sector_rows", ()), *context.get("closed_flow_rows", ())],
        })
        # A major session event must remain visible even if its body fetch fails
        # or its headline was already cited in the opening summary.
        urgent = priority >= 100 and market_news_priority(row) >= 25
        if text(first(row, "link", "url")) in excluded and (comprehensive or (not body_facts and not urgent)):
            continue
        entities = [symbol for symbol, pattern in ENTITIES if re.search(pattern, title, re.I)]
        theme = brief_theme(row, comprehensive=comprehensive)
        context_title = title + " " + " ".join(fact["summary"] for fact in body_facts)
        from stock_lab_core.catalyst_news import constituent_links
        constituents = constituent_links(context_title, "CIBR", now=now, published_at=published)
        link = ("타시장·공통 맥락 · KR/US 가격 원인 미확인" if other else
                _holding_links(held, context_title, entities, theme, market, constituent_evidence=constituents))
        catalyst = bool(re.search(r"공급|계약|규제|제한|공개|출시|투자|실적|조달|인수|정책|earnings|guidance|funding|financing|contract|launch|chip|restrict|upgrade", title, re.I))
        topic = news_theme(title)
        key = ((market, target, "market_close") if row.get("is_close_wrap") else
               (market, target, topic, tuple(entities)) if topic else (market, target, row.get("event_key") or title.casefold()))
        if comprehensive:
            from stock_lab_core.today_news import _session_article_keys
            key = (market, target, *_session_article_keys(row))
        score = (priority, int(bool(body_facts)), int(not link.startswith("직접 보유")), int(catalyst), int(bool(entities)), int(bool(re.search("[가-힣]", title))))
        candidates.append((score, published, key, theme, row, link, active))
    selected, seen, counts, seen_links, seen_titles = [], set(), {}, set(), set()
    for item in sorted(candidates, key=lambda item: ((news_observation(item[4], context)[0] if comprehensive else 0), item[0], item[1]), reverse=True):
        _, _, key, theme, row, _, _ = item
        if comprehensive:
            scope, url, title_key = key[:2], key[2], key[3]
            if (*scope, url) in seen_links or (*scope, title_key) in seen_titles:
                continue
            seen_links.add((*scope, url))
            seen_titles.add((*scope, title_key))
        if key in seen or (not comprehensive and counts.get(theme, 0) >= 2):
            continue
        selected.append(item)
        seen.add(key)
        counts[theme] = counts.get(theme, 0) + 1
        if not comprehensive and len(selected) >= limit:
            break
    lines = ["분야 | " + ("확인된 재료·관측 시점" if comprehensive else "무슨 일·왜 움직였나") + " | 내 보유 영향·다음 확인", "--- | --- | ---"]
    for _, published, _, theme, row, link, active in selected:
        title = text(row.get("title"))
        ko = text(first(row, "summary_ko", "한글요약"))
        if not re.search("[가-힣]", title):
            focus = ko if re.search("[가-힣]", ko) else theme if comprehensive else news_theme(title)
            title = (focus + " · " if focus else "영문 보도 · ") + title
        basis = (f"{row['market']} · 발행시각 기준 타시장·공통 맥락" if row["market"] not in states else
                 f"{row['market']} {row['session_date']} {'진행 세션' if active else '종가 세션'}")
        if comprehensive:
            basis = news_observation(row, context)[1]
        body_facts = verified_body_facts(row)
        if compact:
            if body_facts:
                facts = body_facts if comprehensive else body_facts[:1]
                summaries = [fact["summary"] for fact in facts]
                if comprehensive:
                    summaries = list(dict.fromkeys(summaries))
                detail = "본문 근거: " + " / ".join(summaries) + " " + citation(dict(row, title="원문"))
                link += " · 해석(추정): " + " / ".join(dict.fromkeys(fact["implication"] for fact in facts))
                link += " · 다음 확인: " + " / ".join(dict.fromkeys(fact["check"] for fact in facts))
            else:
                detail = citation(dict(row, title=title)) + " (제목 확인·기사 주장)"
                link += " · 원문·후속 공시 확인"
            detail += f" · {published.astimezone(KST):%m/%d %H:%M} KST / {basis}"
            lines.append(" | ".join(_cell(value) for value in (theme, detail, link)))
            continue
        if body_facts:
            summaries = [fact["summary"] for fact in (body_facts if comprehensive else body_facts[:2])]
            if comprehensive:
                summaries = list(dict.fromkeys(summaries))
            detail = "사실(본문): " + " / ".join(summaries)
            detail += " " + citation(dict(row, title="기사 본문 확인"))
            holding_fact = next((fact for fact in body_facts if fact["topic"] in {"ai_investment", "ai_credit"}), body_facts[0])
            readings = body_facts if comprehensive else [holding_fact]
            link += " · 해석(추정): " + " / ".join(dict.fromkeys(fact["implication"] for fact in readings))
            link += " · 다음 확인: " + " / ".join(dict.fromkeys(fact["check"] for fact in readings))
        else:
            reading = ("본문 확인·자동 해석 근거 부족" if row.get("body_status") == "no_supported_context"
                       else "제목만 확인(본문 해석 보류)")
            from stock_lab_core.article_context import body_unavailable_reason
            status = ("본문 조회 성공" if row.get("body_status") == "no_supported_context" else
                      ("본문 조회 실패: " if row.get("body_status") else "본문 미시도: ") + body_unavailable_reason(row))
            detail = citation(dict(row, title=title)) + " · " + reading + " · " + status
        detail += f" · {published.astimezone(KST):%m/%d %H:%M} KST / {basis}"
        lines.append(" | ".join(_cell(value) for value in (theme, detail, link)))
    if not selected:
        return {"lines": ["한 줄 결론에 인용한 보도 외에 해당 거래일·출처 기준을 통과한 추가 핵심 재료 미확보."], "article_keys": []}
    if not compact:
        lines.extend(["", "보도 내용은 출처의 주장입니다. 해석(추정)은 경제적 전달 경로이지 가격 원인의 확정이 아닙니다. 보유 연결은 업종·기초자산 노출이며 실제 가격 기여도나 매매 허용을 뜻하지 않습니다."])
    return {"lines": lines, "article_keys": [text(first(item[4], "link", "url")) for item in selected]}


def news_brief_lines(context, news, summary_rows, now, *, limit=6):
    return build_news_brief(context, news, summary_rows, now, limit=limit)["lines"]
