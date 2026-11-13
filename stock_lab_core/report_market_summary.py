"""Evidence-bound market synthesis, separate from portfolio P/L and trade gates."""

import re
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, first, macro_stress, number, records, stamp, text
from stock_lab_core.report_presentation import is_preopen_outlook, is_preopen_price_recap, korean_market_catalysts, market_cause_candidates, news_theme

register_loaded_source(__name__, __file__)


def _pct(value):
    return f"{value * 100:+.2f}%"


def _news_matches_date(row, fact):
    published = stamp(first(row, "published_at", "published"))
    if not published or not fact.get("date"):
        return False
    zone = ZoneInfo("Asia/Seoul" if fact["market"] == "KR" else "America/New_York")
    if published.astimezone(zone).date().isoformat() == fact["date"]:
        return True
    if fact["market"] == "US" and row.get("retrospective_close_wrap"):
        from stock_lab_core.today_news import _us_close_recap
        from datetime import datetime
        close = datetime.fromisoformat(fact["date"]).replace(hour=16, tzinfo=zone)
        return _us_close_recap(text(row.get("title")), published, {"end": close.isoformat()})
    return False


def _market_fact(context, market, states, now):
    from stock_lab_core.report_intraday import valid_live_observation
    sessions, prices = context.get("sessions", {}), context.get("prices", {})
    state = states[market]
    live = state["phase"] == "intraday"
    target = state.get("active_date") if live else sessions.get(market)
    observations = context.get("intraday_prices", {}) if live else prices
    symbols = (("^KS11", "코스피"),) if market == "KR" else (("^GSPC", "S&P500"), ("^IXIC", "나스닥"), ("^DJI", "다우"), ("SOXX", "미국 반도체"))
    for ticker, label in symbols:
        row = observations.get(ticker, {})
        change = number(row.get("return"))
        if not target or row.get("date") != target or change is None:
            continue
        if live and not valid_live_observation(row, market, max(now, stamp(context.get("quote_checked_at")) or now), states=states):
            continue
        kind = "장중·확정 아님" if live else "확정 종가"
        if live and row.get("as_of"):
            from stock_lab_core.report_presentation import kst_time
            kind += "; " + kst_time(row["as_of"])
        if market == "KR":
            prefix = "당일 " if target == now.date().isoformat() else "최신 확정 "
            price_text = f"{label} {prefix}{'' if live else '종가 '}{_pct(change)}"
        else:
            price_text = f"{label} {_pct(change)}"
        if live:
            prior = prices.get(ticker, {})
            prior_change = number(prior.get("return"))
            prior_5d = number(prior.get("return_5d"))
            weak_prior = (prior_change is not None and prior_change < 0) or (prior_5d is not None and prior_5d < 0)
            action = ("반등 시도" if change > 0 and weak_prior else
                      "상승" if change > 0 else "하락" if change < 0 else "보합")
        else:
            medium = number(row.get("return_5d"))
            action = ("반등" if change > 0 and medium is not None and medium < 0 else
                      "약세 지속" if change < 0 and (number(row.get("down_days")) or 0) >= 2 else
                      "상승" if change > 0 else "하락" if change < 0 else "보합")
        verbs = {"약세 지속": "약세를 이어갔습니다", "반등": "반등했습니다", "반등 시도": "반등을 시도 중입니다",
                 "상승": "상승 중입니다" if live else "상승했습니다", "하락": "하락 중입니다" if live else "하락했습니다",
                 "보합": "보합권입니다"}
        return dict(phrase=f"{price_text}({target} {kind}) · {action}", change=change,
                    narrative=f"{label}{'은' if label in {'나스닥', 'S&P500'} else '는'} {verbs[action]}({_pct(change)}, {target} {kind})",
                    market=market, date=target, ticker=ticker, live=live)
    label = "한국" if market == "KR" else "미국"
    phrase = f"{label} {target or '기준일 미확보'} {'장중 시세 미수집(종가로 대체 안 함)' if live else '종가 미수집'}"
    return dict(phrase=phrase, narrative=phrase, change=None, market=market, date=target, live=live)


def _flow_evidence(context, flow_rows):
    sessions = context.get("sessions", {})
    source = records(context.get("closed_flow_rows")) + records(context.get("sector_rows")) + records(flow_rows)
    known = {"SOXX", "SMH", "IGV", "XLK", "XLE", "XLF", "XLU", "XLC", "XLV", "XLP", "XLY", "XLI"}
    selected = {}
    for row in source:
        ticker = text(first(row, "Ticker", "티커"))
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        date = text(first(row, "기준일", "date", "as_of"))
        ret = number(first(row, "3개월수익률", "3M"))
        if (not ticker or not date or date != sessions.get(region) or ret is None
                or (ticker not in known and not (region == "KR" and "섹터" in text(row.get("구분"))))):
            continue
        exposure = "US_SEMICONDUCTORS" if ticker in {"SOXX", "SMH"} else ticker
        if exposure not in selected:
            selected[exposure] = (ticker, date, ret)
    ordered = sorted(selected.values(), key=lambda item: (item[0] not in {"SOXX", "SMH"}, item[0] != "IGV", item[2]))
    if not ordered:
        return "같은 기준일의 업종 3M 자료 미연결", ""
    ticker, _, change = ordered[0]
    detail = " / ".join(f"{symbol} 3M {_pct(ret)}({date} 종가)" for symbol, date, ret in ordered[:2])
    labels = {"SOXX": "반도체", "SMH": "반도체", "IGV": "소프트웨어"}
    conditions = [f"{labels.get(symbol, symbol)} 중기 {'약세' if ret < 0 else '강세' if ret > 0 else '보합'}"
                  for symbol, _, ret in ordered[:2]]
    return detail + " · 가격·거래량 기반, 실제 자금 유출입액 아님", "·".join(conditions)


def _leader_news(leaders, change, fact, news, now):
    """One attributed, dated headline about a leader; never an index cause."""
    from stock_lab_core.report_evidence import curate_news, safe_link

    patterns = []
    for ticker, name in leaders:
        patterns.append(r"조선(?:주|업|사|소)|한국조선해양|현대중공업|삼성중공업|한화오션" if ticker == "494670.KS"
                        else re.escape(re.sub(r"^한국\s*", "", name)))
    direction = (r"강세|급등|상승|반등|수주|호실적|↑" if change > 0 else
                 r"약세|급락|하락|부진|적자|계약\s*취소|↓" if change < 0 else r"보합")
    for row in sorted(records(news), key=lambda r: stamp(first(r, "published_at", "published")) or now, reverse=True):
        at = stamp(first(row, "published_at", "published"))
        title = text(row.get("title"))
        if (row.get("market") != "KR" or row.get("session_date") != fact.get("date")
                or not at or at > now or not _news_matches_date(row, fact)
                or row.get("news_bucket") not in {"session_news", "current_session_news"}
                or (fact["live"] and row.get("news_bucket") != "current_session_news")
                or is_preopen_outlook(row) or is_preopen_price_recap(row)
                or not safe_link(first(row, "link", "url")) or len(title) > 140):
            continue
        # A broad index rise elsewhere in the headline is not sector evidence.
        if not any(re.search(f"(?:{pattern})[^,;…。.！!?]{{0,35}}(?:{direction})", title, re.I) for pattern in patterns):
            continue
        if not curate_news([row], now=now, limit=1):
            continue
        return "관련 보도(제목 확인·기사 주장): " + citation(row)
    return ""


def korean_sector_reading(context, fact, states, now, news=(), *, concise=False):
    """Strongest daily return in the supplied sector ETF subset, never a census."""
    from stock_lab_core.report_intraday import valid_live_observation

    day = fact.get("date")
    if not day:
        return ""
    selected = {}
    for row in records(context.get("closed_flow_rows")) + records(context.get("sector_rows")):
        ticker = text(first(row, "Ticker", "티커"))
        name = text(row.get("섹터"))
        if (not ticker.endswith((".KS", ".KQ")) or ticker in {"069500.KS", "229200.KS"}
                or "미국" in name or ticker in selected or not name or name == ticker
                or "섹터" not in text(row.get("구분")) or row.get("stale") or row.get("is_mock")):
            continue
        if fact["live"]:
            obs = context.get("intraday_prices", {}).get(ticker, {})
            if obs.get("date") != day or not valid_live_observation(
                    obs, "KR", max(now, stamp(context.get("quote_checked_at")) or now), states=states):
                continue
            value = number(obs.get("return"))
        else:
            if text(first(row, "기준일", "date")) != day or row.get("수치종류", "확정 종가") != "확정 종가":
                continue
            value = number(first(row, "1일수익률", "1D"))
        if value is not None:
            selected[ticker] = (value, name)
    if not selected:
        return ""
    high = max(value for value, _ in selected.values())
    leaders = sorted((ticker, name) for ticker, (value, name) in selected.items() if value == high)
    names = " / ".join(f"{name}({ticker})" for ticker, name in leaders)
    kind = "장중·미확정" if fact["live"] else "확정 종가"
    ranking = "관측 표본" if len(selected) == 1 else "관측 표본 내 당일 수익률 공동 상위" if len(leaders) > 1 else "관측 표본 내 당일 수익률 최상위"
    if concise:
        names = "·".join(name for _, name in leaders[:2]) + (f" 외 {len(leaders) - 2}개" if len(leaders) > 2 else "")
        reading = f"관측 업종 ETF {len(selected)}개 중 상대 상위는 {names}({_pct(high)}, {kind})" if len(selected) > 1 else f"관측 업종 ETF는 {names}({_pct(high)}, {kind}) 1개"
    else:
        reading = (f"한국 업종 대용 ETF {len(selected)}개 {ranking}: {names} {_pct(high)}({day} {kind}). "
                   "관측 범위의 가격 비교이며 시장 전체 업종 순위·지수 상승 기여도·순매수액은 아닙니다")
    source = _leader_news(leaders, high, fact, news, now)
    return reading + ("; " + source if source else "")


def korean_investor_reading(context, fact, *, concise=False, programs_connected=False):
    from stock_lab_core.public_market_data import validated_investor_flows
    from stock_lab_core.report_evidence import safe_link

    rows = validated_investor_flows(context.get("public_market_evidence"), session_date=fact.get("date"),
                                    checked_at=context.get("market_evidence_checked_at"))
    if concise:
        readings = {}
        for market in ("KOSPI", "KOSDAQ"):
            local = [row for row in rows if row["market"] == market]
            if not local:
                continue
            groups = [(label, [row["label"] for row in local if compare(row["value"])])
                      for label, compare in (("순매수", lambda v: v > 0), ("순매도", lambda v: v < 0), ("순매수 0", lambda v: v == 0))]
            readings[market] = "·".join("·".join(names) + " " + label for label, names in groups if names)
            if groups[0][1] and groups[1][1]:
                readings[market] += "로 엇갈림"
        if len(readings) == 2 and readings["KOSPI"] == readings["KOSDAQ"]:
            return "잠정 수급은 KOSPI·KOSDAQ 모두 " + readings["KOSPI"]
        return "잠정 수급은 " + "; ".join(market + " " + value for market, value in readings.items()) if readings else ""
    parts = []
    for market in ("KOSPI", "KOSDAQ"):
        local = [row for row in rows if row["market"] == market]
        if not local:
            continue
        amounts = "·".join(f"{row['label']} 순매수 {row['value']:+,.2f}억원" for row in local)
        parts.append(f"{market} {amounts} ({fact['date']}, 잠정·정정 가능; 조회 {local[0]['fetched_at']})"
                     f" [공개 수급 출처]({safe_link(local[0]['source_url'])})")
    if not parts:
        return ""
    return (" / ".join(parts) + ". KRX 시장 전체 투자자별 수급(NXT 제외)이며 업종 매수액·상승 원인·매수 동기는 확인되지 않습니다. "
            "프로그램은 투자자 구분이 아닌 거래 방식으로, "
            + ("프로그램 수치는 별도 근거 행에 표시합니다" if programs_connected else "별도 프로그램 수치는 미연결입니다"))


def korean_program_reading(context, fact):
    from stock_lab_core.public_market_data import validated_program_flows
    from stock_lab_core.report_evidence import safe_link

    rows = validated_program_flows(context.get("public_market_evidence"), session_date=fact.get("date"),
                                   checked_at=context.get("market_evidence_checked_at"))
    return " / ".join(
        f"{row['market']} 차익 {row['arbitrage']:+,.2f}억원 · 비차익 {row['non_arbitrage']:+,.2f}억원 · 합계 {row['value']:+,.2f}억원 "
        f"({row['asof']}; 조회 {row['fetched_at']}) · {row['limitation']} "
        f"[프로그램 출처]({safe_link(row['source_url'])})" for row in rows)


def korean_flow_tables(context, fact):
    """Compact, independently validated identity and method tables for the report."""
    from stock_lab_core.public_market_data import validated_investor_flows, validated_program_flows
    from stock_lab_core.report_evidence import safe_link

    options = dict(session_date=fact.get("date"), checked_at=context.get("market_evidence_checked_at"))
    evidence = context.get("public_market_evidence")
    investors = validated_investor_flows(evidence, **options)
    programs = validated_program_flows(evidence, **options)
    if not investors and not programs:
        if "public_flow_backfill" in context:
            from stock_lab_core.public_market_flow_history import public_flow_history_lines
            return public_flow_history_lines(context, session_date=fact.get("date"))
        return []
    lines = []
    if investors:
        lines += ["", "**한국 투자자별 순매수 · 억원(잠정)**", "시장 | 개인 | 외국인 | 기관 | 기준일", "--- | --- | --- | --- | ---"]
        for market in ("KOSPI", "KOSDAQ"):
            local = {row["identity"]: row for row in investors if row["market"] == market}
            if local:
                amounts = [f"{local[key]['value']:+,.2f}" if key in local else "—" for key in ("individual", "foreign", "institution")]
                lines.append(" | ".join(_cell(value) for value in (market, *amounts, fact["date"])))
    if programs:
        lines += ["", "**한국 프로그램 순매수 · 억원(잠정)**", "시장 | 차익 | 비차익 | 합계 | 기준일", "--- | --- | --- | --- | ---"]
        for row in programs:
            lines.append(" | ".join(_cell(value) for value in (row["market"],
                *(f"{row[key]:+,.2f}" for key in ("arbitrage", "non_arbitrage", "value")), row["asof"])))
    else:
        lines += ["", "프로그램 자료 미연결: 같은 기준일의 검증 통과 자료 없음."]
    rows = investors + programs
    sources = list(dict.fromkeys(safe_link(row["source_url"]) for row in rows))
    from stock_lab_core.report_presentation import kst_time
    fetched = list(dict.fromkeys(kst_time(row["fetched_at"]) for row in rows))
    lines += ["", "출처: " + " / ".join(f"[Npay 증권 공개 데이터]({url})" for url in sources)
              + " · 조회 " + " / ".join(fetched),
              "KRX 시장 전체·NXT 제외·잠정/정정 가능. —는 미확인으로 0과 다릅니다. 업종 매수액·가격 원인·매수 동기를 뜻하지 않습니다."]
    if programs:
        lines.append("프로그램은 투자자 신분이 아닌 거래 방식으로, 투자자별 순매수와 합산하거나 기관 매수액으로 해석하지 않습니다. "
                     "프로그램 자체 기준시각이 없어 같은 응답의 투자자 수급 기준일을 함께 표시합니다.")
    if investors or "public_flow_backfill" in context:
        from stock_lab_core.public_market_flow_history import public_flow_history_lines

        lines.extend(public_flow_history_lines(context, session_date=fact.get("date")))
    return lines


def _korean_positive_drivers(title):
    drivers = []
    if re.search(r"반도체.{0,15}(?:반등|강세|급등|상승)", title):
        drivers.append("반도체주 반등")
    if re.search(r"삼전닉스.{0,18}(?:쌍끌이|↑|급등|반등|강세|상승)", title):
        drivers.append("삼성전자·SK하이닉스 강세")
    if re.search(r"조선(?:주|업종|업|섹터)?(?:가|는|이|은)?\s*(?:동반\s*)?(?:반등|강세|급등|상승|↑)", title):
        drivers.append("조선주 강세")
    # Stop at another investor or program method; do not give their buys to
    # the preceding investor (e.g. '외국인 매도, 기관 순매수').
    for match in re.finditer(r"(외국인|기관|개인)((?:(?!외국인|기관|개인|프로그램|[,;…]).){0,24})", title):
        identity, clause = match.groups()
        if (re.search(r"순매수|매수\s*전환|매수세", clause)
                and not re.search(r"순매도|매도세|실패|아니|않|부인", clause)):
            drivers.append(identity + " 매수")
    return list(dict.fromkeys(drivers))


def market_summary(context, news, flow_rows, states, now, *, futures_line=""):
    """Market moves -> reported background -> macro/medium-term interpretation."""
    facts = [_market_fact(context, market, states, now) for market in ("KR", "US")]
    from stock_lab_core.article_context import verified_body_facts, body_context_sentence
    from stock_lab_core.article_market_events import event_context_sentence
    claims, market_claims, selected_news, body_sources = [], {}, {}, {}
    for fact in facts:
        if fact["change"] is None:
            continue
        eligible = [row for row in news if row.get("market") == fact["market"]
                    and row.get("session_date") == fact["date"] and not is_preopen_outlook(row) and not is_preopen_price_recap(row)
                    and _news_matches_date(row, fact)
                    and row.get("news_bucket") not in {"next_session_news", "other_market_news"}]
        if fact["live"]:
            eligible = [row for row in eligible if row.get("news_bucket") == "current_session_news"]
        candidates = market_cause_candidates(eligible, fact["market"], fact["date"])
        local_claims, local_news = [], []
        if fact["market"] == "KR" and fact["change"] < 0:
            for row in candidates + eligible:
                catalysts = korean_market_catalysts([row], fact["date"])
                topic = news_theme(text(row.get("title")))
                if topic and catalysts and topic not in catalysts:
                    catalysts = topic + " · " + catalysts
                if catalysts and catalysts not in local_claims:
                    local_claims.append(catalysts)
                    local_news.append(row)
                if len(local_claims) >= 2:
                    break
        elif fact["change"] < 0:
            local_claims = list(dict.fromkeys(news_theme(text(row.get("title"))) for row in candidates))
            local_news = candidates
        elif fact["change"] > 0:
            # A rise must not inherit a decline explanation from another story.
            for row in eligible:
                title = text(row.get("title"))
                topic = news_theme(title)
                korean_rebound = False
                if (fact["market"] == "KR" and re.search(r"코스피|코스닥", title)
                        and re.search(r"(?:국제)?유가[·ㆍ/\s]+금리\s*(?:동반\s*)?안정", title)):
                    topic = "유가·금리 안정"
                if fact["market"] == "KR" and re.search(r"코스피|코스닥", title):
                    drivers = _korean_positive_drivers(title)
                    if drivers:
                        topic = "·".join(drivers)
                        korean_rebound = True
                earnings_offset = bool(re.search(r"strong earnings offset AI credit fears", title, re.I))
                if earnings_offset:
                    topic = "실적 호조·AI 신용우려 교차"
                if topic and (earnings_offset or korean_rebound or re.search(r"반등|회복|상승|강세|\brebound|\brecover|\bbounc|\brall|\brise|\brises|\bgain|\bclimb|\bhigher", title, re.I)):
                    local_claims.append(topic)
                    local_news.append(row)
                    break
        body_row = next((row for row in eligible if row.get("is_close_wrap") and verified_body_facts(row)), None)
        if body_row:
            body_sources[fact["market"]] = [body_row]
            local_claims = [item["summary"] for item in verified_body_facts(body_row)[:2]]
            local_news = [body_row]
        elif fact["market"] == "US" and fact["change"] < 0:
            from stock_lab_core.catalyst_news import issuer_reported_issue
            for row in candidates + eligible:
                issue = issuer_reported_issue(text(row.get("title")))
                if issue:
                    local_claims = [issue, *local_claims[:1]]
                    local_news = [row, *local_news[:1]]
                    break
        # A separate verified event in this same session must not disappear just
        # because a broad wrap already supplied a generic commodity explanation.
        event_row = next((row for row in eligible if row is not body_row
                          and any(f.get("topic") == "leadership" for f in verified_body_facts(row))), None)
        if event_row and not (body_row and any(f.get("topic") == "leadership" for f in verified_body_facts(body_row))):
            body_sources.setdefault(fact["market"], []).insert(0, event_row)
            local_news = [event_row, *local_news]
            local_claims = [event_context_sentence(verified_body_facts(event_row)), *local_claims]
        market_claims[fact["market"]] = local_claims
        selected_news[fact["market"]] = local_news
        claims.extend(local_claims)
    aligned_macro = {key: row for key, row in context.get("macro_data", {}).items()
                     if context.get("sessions", {}).get("US") and row.get("as_of") == context["sessions"]["US"]}
    stress = macro_stress(aligned_macro)
    burdens = [row for row in stress["rows"] if row["contribution"] > 0]
    names = {"10Y 금리": "금리", "유가": "유가", "MOVE": "채권 변동성", "VIX": "주식 변동성", "환율": "환율"}
    burdens.sort(key=lambda row: (-row["contribution"], row["name"]))
    burden = "·".join(names.get(row["name"], row["name"]) for row in burdens[:2])
    flow_text, flow_condition = _flow_evidence(context, flow_rows)
    inference = []
    if burden:
        inference.append(burden + " 부담")
    if flow_condition:
        inference.append(flow_condition)
    breadth = broad_market_reading(context, states, now)
    kr_sector = korean_sector_reading(context, facts[0], states, now, news)
    kr_programs = korean_program_reading(context, facts[0])
    kr_investors = korean_investor_reading(context, facts[0], programs_connected=bool(kr_programs))
    kr_observations = ". ".join(part for part in (
        korean_sector_reading(context, facts[0], states, now, news, concise=True),
        korean_investor_reading(context, facts[0], concise=True)) if part)
    sentences = []
    for fact in facts:
        topics = market_claims.get(fact["market"], [])
        sources, seen = [], set()
        for row in selected_news.get(fact["market"], []):
            key = text(first(row, "link", "url"))
            if key and key not in seen:
                sources.append(citation(dict(row, title="배경 보도")))
                seen.add(key)
        sentence = (" · ".join(topics) + " 관련 보도가 나온 가운데(기사 주장), " if topics else "")
        narrative = breadth.rstrip(".") if fact["market"] == "US" and breadth else fact["narrative"]
        if fact["market"] == "KR" and not fact["live"] and (fact["change"] or 0) > 0:
            row = context.get("prices", {}).get(fact.get("ticker"), {})
            recent = number(row.get("return_5d"))
            if recent is not None and recent < 0:
                narrative += f". 다만 최근 5거래일은 {_pct(recent)}로, 오늘 반등이 최근 하락분을 모두 회복한 것은 아닙니다"
        if fact["market"] == "KR" and kr_observations:
            narrative += ". " + kr_observations
        if fact["market"] in body_sources:
            backgrounds = [body_context_sentence(row) + " " + citation(dict(row, title="배경 보도"))
                           for row in body_sources[fact["market"]]]
            sentences.append(narrative + ". " + " ".join(backgrounds)
                             + " (기사 본문 확인·가격 기여도 미확정)")
        else:
            sentences.append(sentence + narrative + (" " + " ".join(sources[:2]) if sources else ""))
    headline = ".\n\n".join(sentences)
    if inference:
        caution = burden or "약세" in flow_condition
        check = "반등 지속성을" if any((fact["change"] or 0) > 0 for fact in facts) else "약세 확산 여부를"
        ending = (f" 환경에서는 {check} 확인할 국면입니다(종합 해석)" if caution else
                  "와 당일 방향의 동행 여부를 확인할 국면입니다(종합 해석)")
        headline += (".\n\n다만 " if caution else ".\n\n") + "과 ".join(inference) + ending
    if states["US"]["phase"] == "preopen" and futures_line:
        headline += ".\n\n미국 개장 전 참고: " + futures_line
    incomplete = any(row.get("stress_incomplete") for row in aligned_macro.values()) or any(name not in aligned_macro for name in ("유가", "환율"))
    macro_text = (f"스트레스 {'부분합 ' if incomplete else ''}{stress['score']} {stress['label']} · " +
                  (" / ".join(f"{row['name']} {row['value']:.2f}({row['state']})" for row in burdens[:2]) or "확인 지표의 추가 스트레스 기여 없음") +
                  f" · 미국 {context['sessions']['US']} 종가 기준") if stress["score"] is not None else "기준일 정렬 매크로 자료 미연결"
    evidence = [("시장", " / ".join(fact["phrase"] for fact in facts)),
                ("배경 보도", " · ".join(claims) + "(기사 주장·기여도 미확정)" if claims else "당일 시장 방향과 연결할 배경 보도 미확보"),
                ("매크로", macro_text), ("중기 가격·거래량", flow_text)]
    if (facts[0]["live"] and (facts[0]["change"] or 0) < 0 and not market_claims.get("KR")
            and (facts[1]["change"] or 0) < 0):
        # A prior overseas session is context, never relabeled as a KR cause.
        prior = facts[1]
        candidates = [row for row in news if row.get("market") == "US"
                      and row.get("session_date") == prior.get("date") and _news_matches_date(row, prior)
                      and stamp(first(row, "published_at", "published")) is not None
                      and 0 <= (now - stamp(first(row, "published_at", "published"))).total_seconds() <= 96 * 3600
                      and re.search(r"급락|투매|하락|sell.?off|slump|plunge", text(row.get("title")), re.I)]
        if candidates:
            row = max(candidates, key=lambda r: stamp(first(r, "published_at", "published")))
            evidence.append(("해외 전이 참고(기사 주장)", citation(row)
                             + f" · 미국 {prior['date']} 세션, 한국 당일 원인 확정 아님·제목 기준"))
    if breadth:
        evidence.insert(1, ("미국 시장 전체", breadth))
    sector_text = broad_sector_reading(context)
    if sector_text:
        evidence.append(("업종 분포", sector_text))
    if kr_sector:
        evidence.append(("한국 관측 업종", kr_sector))
    if kr_investors:
        evidence.append(("한국 투자자별 수급", korean_investor_reading(context, facts[0], concise=True)
                         + " · 금액·출처는 투자자별 순매수 표 참조"))
    if kr_programs:
        evidence.append(("한국 프로그램 매매", "검증된 차익·비차익·합계는 프로그램 순매수 표 참조 · 투자자별 수급과 별도"))
    overview = facts[0]["narrative"] + ". " + (kr_observations + ". " if kr_observations else "") + (breadth or facts[1]["narrative"])
    participation = market_participation_reading(context)
    if participation:
        overview += " " + participation
        evidence.append(("지수와 내부 흐름", participation))
    for market, name in (("KR", "한국"), ("US", "미국")):
        if market_claims.get(market):
            overview += f" {name} 보도상 배경: " + "·".join(market_claims[market]) + "(기사 주장)."
            overview += " 출처는 아래 시장 스토리에 표시합니다."
    if burden:
        overview += " 다만 " + burden + " 부담이 남아, 단기 반등과 위험 해소를 같은 의미로 보기는 어렵습니다(종합 해석)."
    return {"headline": headline, "overview": overview, "evidence": evidence, "market_claims": market_claims,
            "background_news": [row for rows in selected_news.values() for row in rows]}


def broad_market_reading(context, states, now):
    from stock_lab_core.report_intraday import valid_live_observation
    live = states["US"]["phase"] == "intraday"
    day = states["US"].get("active_date") if live else context.get("sessions", {}).get("US")
    prices = context.get("intraday_prices" if live else "prices", {})
    items = [(name, number(prices.get(ticker, {}).get("return")))
             for ticker, name in (("^GSPC", "S&P500"), ("^IXIC", "나스닥"), ("^DJI", "다우"))
             if day and prices.get(ticker, {}).get("date") == day and number(prices.get(ticker, {}).get("return")) is not None
             and (not live or valid_live_observation(prices[ticker], "US", max(now, stamp(context.get("quote_checked_at")) or now), states=states))]
    if not items:
        return ""
    values = [value for _, value in items]
    reading = ("지수 1개만 연결되어 미국 전체 방향 판단은 보류" if len(items) == 1 else
               "지수 방향이 엇갈린 혼조로 미국 시장 전체의 동반 하락으로 볼 수 없습니다" if min(values) < 0 < max(values)
               else "확인된 주요지수는 동반 상승" if min(values) > 0 else "확인된 주요지수는 동반 하락" if max(values) < 0 else "지수별 등락 차이를 확인할 구간")
    return ("미국 " + " / ".join(name + " " + _pct(value) for name, value in items)
            + f"({day} {'장중' if live else '확정 종가'}). " + reading + ".")


def broad_sector_reading(context):
    from stock_lab_core.report_prices import SECTORS
    names = {**SECTORS, "XLF": "금융", "XLI": "산업재", "XLP": "필수소비", "XLV": "헬스케어", "XLY": "경기소비"}
    seen, items = set(), []
    for row in records(context.get("closed_flow_rows")) + records(context.get("sector_rows")):
        ticker = text(first(row, "Ticker", "티커"))
        value = number(first(row, "1일수익률", "1D"))
        if ticker in seen or ticker not in names or ticker.endswith((".KS", ".KQ")) or value is None:
            continue
        if text(first(row, "기준일", "date")) != context.get("sessions", {}).get("US"):
            continue
        seen.add(ticker)
        items.append((value, names[ticker], ticker))
    if len(items) < 2:
        return ""
    items.sort()
    low, high = items[0], items[-1]
    return (f"미국 관측 업종 {len(items)}개 중 상승 {sum(v > 0 for v, _, _ in items)} / 하락 {sum(v < 0 for v, _, _ in items)}. "
            f"상대 상위 {high[1]}({high[2]}) {_pct(high[0])}, 상대 하위 {low[1]}({low[2]}) {_pct(low[0])}. "
            "표본 ETF의 확정 종가 분포이며 시장 전체 종목의 확산률·자금 유입액은 아닙니다.")


def market_participation_reading(context):
    """Compare dated price observations, not inferred constituent breadth/flows."""
    prices, day = context.get("prices", {}), context.get("sessions", {}).get("US")
    def observed(ticker):
        row = prices.get(ticker, {})
        return number(row.get("return")) if day and row.get("date") == day and not row.get("stale") else None
    nasdaq, broad = observed("^IXIC"), observed("^GSPC")
    positive = [(label, value) for ticker, label in (("XLV", "헬스케어"), ("XLF", "금융"), ("IWM", "중소형주"))
                if (value := observed(ticker)) is not None and value > 0]
    if nasdaq is None or broad is None or nasdaq >= 0 or not positive:
        return ""
    return ("지수 하락과 내부 흐름은 구분해야 합니다: " + " / ".join(f"{name} {_pct(value)}" for name, value in positive)
            + f"({day} 종가). 기술주 약세와 다른 업종·규모의 강세가 공존합니다. "
              "이는 ETF 가격 비교이며 상승 종목수·실제 자금 이동 확인은 아닙니다.")


def evidence_table(summary):
    return ["종합 판단 근거 | 확인 내용", "--- | ---",
            *(" | ".join(_cell(value) for value in row) for row in summary["evidence"])]
