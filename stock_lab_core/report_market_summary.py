"""Evidence-bound market synthesis, separate from portfolio P/L and trade gates."""

import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, first, macro_stress, number, records, text
from stock_lab_core.report_presentation import is_preopen_outlook, is_preopen_price_recap, korean_market_catalysts, market_cause_candidates, news_theme

register_loaded_source(__name__, __file__)


def _pct(value):
    return f"{value * 100:+.2f}%"


def _market_fact(context, market, states, now):
    sessions, prices = context.get("sessions", {}), context.get("prices", {})
    state = states[market]
    live = state["phase"] == "intraday"
    target = state.get("active_date") if live else sessions.get(market)
    observations = context.get("intraday_prices", {}) if live else prices
    symbols = (("^KS11", "코스피"),) if market == "KR" else (("SOXX", "미국 반도체"), ("^IXIC", "나스닥"), ("^GSPC", "S&P500"))
    for ticker, label in symbols:
        row = observations.get(ticker, {})
        change = number(row.get("return"))
        if not target or row.get("date") != target or change is None:
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
    label = "반도체" if ticker in {"SOXX", "SMH"} else ticker
    return detail + " · 가격·거래량 기반, 실제 자금 유출입액 아님", f"{label} 중기 {'약세' if change < 0 else '강세' if change > 0 else '보합'}"


def market_summary(context, news, flow_rows, states, now, *, futures_line=""):
    """Market moves -> reported background -> macro/medium-term interpretation."""
    facts = [_market_fact(context, market, states, now) for market in ("KR", "US")]
    claims, market_claims, selected_news = [], {}, {}
    for fact in facts:
        if fact["change"] is None:
            continue
        eligible = [row for row in news if row.get("market") == fact["market"]
                    and row.get("session_date") == fact["date"] and not is_preopen_outlook(row) and not is_preopen_price_recap(row)
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
                if (fact["market"] == "KR" and re.search(r"코스피|코스닥", title)
                        and re.search(r"(?:국제)?유가[·ㆍ/\s]+금리\s*(?:동반\s*)?안정", title)):
                    topic = "유가·금리 안정"
                if topic and re.search(r"반등|회복|상승|강세|\brebound|\brecover|\bbounc|\brall|\brise|\brises|\bgain|\bclimb|\bhigher", title, re.I):
                    local_claims.append(topic)
                    local_news.append(row)
                    break
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
        sentences.append(sentence + fact["narrative"] + (" " + " ".join(sources[:2]) if sources else ""))
    headline = ". ".join(sentences)
    if inference:
        caution = burden or "약세" in flow_condition
        check = "반등 지속성을" if any((fact["change"] or 0) > 0 for fact in facts) else "약세 확산 여부를"
        ending = (f" 환경에서는 {check} 확인할 국면입니다(종합 해석)" if caution else
                  "와 당일 방향의 동행 여부를 확인할 국면입니다(종합 해석)")
        headline += (". 다만 " if caution else ". ") + "과 ".join(inference) + ending
    if states["US"]["phase"] == "preopen" and futures_line:
        headline += ". 미국 개장 전 참고: " + futures_line
    macro_text = (f"스트레스 {stress['score']} {stress['label']} · " +
                  (" / ".join(f"{row['name']} {row['value']:.2f}({row['state']})" for row in burdens[:2]) or "확인 지표의 추가 스트레스 기여 없음") +
                  f" · 미국 {context['sessions']['US']} 종가 기준") if stress["score"] is not None else "기준일 정렬 매크로 자료 미연결"
    evidence = [("시장", " / ".join(fact["phrase"] for fact in facts)),
                ("배경 보도", " · ".join(claims) + "(기사 주장·기여도 미확정)" if claims else "당일 시장 방향과 연결할 배경 보도 미확보"),
                ("매크로", macro_text), ("중기 가격·거래량", flow_text)]
    return {"headline": headline, "evidence": evidence, "market_claims": market_claims,
            "background_news": [row for rows in selected_news.values() for row in rows]}


def evidence_table(summary):
    return ["종합 판단 근거 | 확인 내용", "--- | ---",
            *(" | ".join(_cell(value) for value in row) for row in summary["evidence"])]
