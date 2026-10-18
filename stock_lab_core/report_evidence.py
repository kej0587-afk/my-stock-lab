"""Deterministic report evidence. No inferred prices, forecasts or causality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
SOURCE_NAMES = (
    "reuters", "로이터", "associated press", "연합뉴스", "연합인포맥스", "한국경제",
    "매일경제", "서울경제", "서울파이낸스", "조선비즈", "조선일보", "한겨레",
    "경향신문", "머니투데이", "아시아경제", "이데일리", "뉴시스", "cnbc", "bloomberg",
    "financial times", "wall street journal", "yahoo finance", "bls", "federal reserve",
    "한국은행", "통계청", "산업통상", "boj", "nikkei", "한경",
)
SOURCE_DOMAINS = (
    "reuters.com", "apnews.com", "yna.co.kr", "yonhapnewstv.co.kr", "einfomax.co.kr",
    "hankyung.com", "mk.co.kr", "sedaily.com", "chosun.com", "edaily.co.kr",
    "mt.co.kr", "asiae.co.kr", "newsis.com", "cnbc.com", "bloomberg.com", "ft.com",
    "wsj.com", "finance.yahoo.com", "bls.gov", "federalreserve.gov", "bok.or.kr",
    "kostat.go.kr", "motie.go.kr", "boj.or.jp", "census.gov", "nikkei.com",
)
EVENT_CLUSTERS = (
    ("cxmt", ("cxmt", "창신", "창신메모리")),
    ("boj", ("boj", "일본은행", "일은 ")),
    ("fomc", ("fomc", "fed rate decision", "연준 금리", "기준금리 동결")),
)
MARKET_TERMS = re.compile(
    r"주식|증시|코스피|코스닥|나스닥|주가|반도체|금리|연준|물가|수출|환율|국채|인플레|고용|소매판매|실적|은행|원유|유가|달러|엔화|관세|무역|휴전|중동|투자|경제|자산|전력|바이오|메모리|코인|이더리움|비트코인|"
    r"\b(stock|market|earnings|fed|fomc|cpi|ppi|jobs|rates?|boj|oil|wti|brent|bitcoin|ethereum|eth|btc|crypto|cxmt|nvidia|semiconductor|inflation|tariff|treasury|ceasefire)\b",
    re.IGNORECASE,
)


def records(value):
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    return [dict(row) for row in value if isinstance(row, dict)]


def text(value):
    result = str(value if value is not None else "").strip()
    return "" if result.lower() in {"nan", "none", "<na>", "nat"} else result


def number(value):
    try:
        result = float(str(value).replace(",", "").replace("%", ""))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def first(row, *keys):
    for key in keys:
        if text(row.get(key)):
            return row[key]
    return ""


def stamp(value):
    try:
        dt = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt.astimezone(KST)
    except ValueError:
        return None


def safe_link(value):
    value = text(value)
    parsed = urlparse(value)
    return value if parsed.scheme in {"https", "http"} and parsed.hostname else ""


def news_category(title, fallback="시장"):
    lower = title.lower()
    if re.search(r"\b(eth|btc|ethereum|bitcoin|crypto)\b|이더리움|비트코인|가상자산", lower):
        return "암호화폐"
    if re.search(r"cxmt|반도체|nvidia|semiconductor|dram|hbm|엔비디아", lower):
        return "반도체/AI"
    if re.search(r"fomc|\bfed\b|cpi|ppi|고용|연준|boj|일본은행|소매판매", lower):
        return "매크로"
    if re.search(r"\boil\b|\bwti\b|brent|원유|유가|opec", lower):
        return "에너지"
    return fallback


def korean_headline_reading(row):
    """Use supplied Korean summary; otherwise a clearly limited title-level reading."""
    title = text(row["title"])
    supplied = text(first(row, "summary_ko", "한글요약"))
    if supplied and re.search("[가-힣]", supplied):
        return supplied
    if re.search("[가-힣]", title):
        return "제목 기준: " + title
    lower = title.lower()
    subjects = (
        (r"\bcxmt\b", "중국 메모리 업체 CXMT"),
        (r"\bnvidia\b", "엔비디아"), (r"\bboj\b|bank of japan", "일본은행"),
        (r"\bfed\b|fomc", "미국 연준"), (r"\bppi\b", "미국 생산자물가"),
        (r"\bcpi\b", "미국 소비자물가"), (r"ethereum|\beth\b", "이더리움"),
        (r"bitcoin|\bbtc\b", "비트코인"), (r"oil|\bwti\b|brent", "원유"),
        (r"middle east|ceasefire", "중동 휴전 협상"),
    )
    subject = next((label for pattern, label in subjects if re.search(pattern, lower)), row["category"])
    actions = (
        (r"cuts? rates|rate cut", "금리 인하 관련 보도"),
        (r"raises? rates|rate hike", "금리 인상 관련 보도"),
        (r"holds? rates|unchanged", "금리 동결 관련 보도"),
        (r"outflows?", "자금 유출 관련 보도"), (r"inflows?", "자금 유입 관련 보도"),
        (r"falls?|drops?|declines?|slumps?", "하락 관련 보도"),
        (r"rises?|gains?|surges?", "상승 관련 보도"),
    )
    action = next((label for pattern, label in actions if re.search(pattern, lower)), "관련 소식")
    return f"제목 단서 해석: {subject} {action}. 세부 내용·가격 영향은 미확인"


def curate_news(rows, *, now=None, limit=5):
    now = now or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    accepted, seen = [], set()
    for raw in records(rows):
        title = text(first(raw, "title", "제목"))
        publisher = text(first(raw, "publisher", "출처", "source"))
        link = safe_link(first(raw, "link", "링크", "url"))
        domain = urlparse(safe_link(raw.get("publisher_url")) or link).hostname or ""
        lower = f"{title} {publisher} {domain}".lower()
        if not title or not MARKET_TERMS.search(title) or any(word in lower for word in (
            "coinmarketcap", "tmgm", "prnewswire", "businesswire", "보도자료", "press release",
            "price today", "live price", "to usd", "rbc", "commerzbank", "일일 운세",
        )):
            continue
        if not (any(name in publisher.lower() for name in SOURCE_NAMES) or
                any(domain == item or domain.endswith("." + item) for item in SOURCE_DOMAINS)):
            continue
        published = text(first(raw, "published_at", "published", "시간"))
        dt = stamp(published)
        if dt is None or not now - timedelta(days=7) <= dt <= now + timedelta(minutes=5):
            continue
        clean = re.sub(r"\s+[-|]\s+" + re.escape(publisher) + r"$", "", title, flags=re.I).strip() if publisher else title
        key = next((key for key, words in EVENT_CLUSTERS if any(w in clean.lower() for w in words)),
                   re.sub(r"[\W_]+", "", clean.lower()))
        if key in seen:
            continue
        seen.add(key)
        row = dict(raw, title=clean, publisher=publisher, link=link, published=dt.isoformat() if dt else published,
                   category=news_category(clean, text(first(raw, "market_category", "카테고리")) or "시장"),
                   event_key=key)
        row["reading_ko"] = korean_headline_reading(row)
        accepted.append(row)
    return accepted[:limit]


def citation(row):
    label = text(first(row, "title", "indicator", "지표"))
    publisher = text(first(row, "publisher", "source", "출처"))
    label = (publisher + " · " if publisher else "") + label
    label = label.replace("[", "(").replace("]", ")")
    link = safe_link(first(row, "link", "source_url", "링크"))
    return f"[{label}]({link})" if link else f"[{label} · 원문 URL 미제공]"


def reported_cause(row, sessions):
    """Attribute explicit headline causality, never promote a late article to a cause."""
    title = text(row.get("title"))
    published = stamp(row.get("published"))
    if not published or not row.get("link"):
        return ""
    market = text(row.get("market")).upper()
    # A Korean article can describe the US session: require an explicit market.
    if market not in {"KR", "US"}:
        return ""
    date = sessions.get(market)
    if not date:
        return ""
    zone = KST if market == "KR" else ZoneInfo("America/New_York")
    close = datetime.fromisoformat(date).replace(hour=15 if market == "KR" else 16,
                                               minute=30 if market == "KR" else 0, tzinfo=zone)
    if not close - timedelta(hours=24) <= published <= close:
        return ""
    explicit = re.search(r"(?:때문|여파|우려로|충격에|추격에|부담에|영향으로|에 힘입어|에 급락|에 하락|because|due to)", title, re.I)
    if not explicit:
        return ""
    return f"기사 제목은 ‘{title}’라고 배경을 설명합니다(보도 해석이며 인과 확정 아님). {citation(row)}"


def closed_daily_frame(frame, ticker, now=None):
    """Discard today's unclosed bar. Do not guess a missing exchange session."""
    import pandas as pd
    if not isinstance(frame, pd.DataFrame) or "Close" not in frame or not isinstance(frame.index, pd.DatetimeIndex):
        return pd.DataFrame()
    now = now or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now
    crypto = ticker.endswith("-USD")
    kr = ticker.endswith((".KS", ".KQ")) or ticker in {"^KS11", "^KQ11"}
    local = now.astimezone(timezone.utc if crypto else KST if kr else ZoneInfo("America/New_York"))
    end = local.date()
    # Provider daily index denotes trading date, not UTC instant.
    dates = frame.index.tz_localize(None).date
    closed_today = not crypto and local.weekday() < 5 and (local.hour, local.minute) >= ((15, 40) if kr else (16, 15))
    mask = (dates <= end) if closed_today else (dates < end)
    out = frame.loc[mask].sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    close = pd.to_numeric(out["Close"], errors="coerce")
    return out.loc[close.gt(0) & close.map(math.isfinite)]


def price_observation(frame, ticker, now=None):
    frame = closed_daily_frame(frame, ticker, now)
    if len(frame) < 2:
        return {"ticker": ticker, "date": "", "return": None, "source": "종가 이력 미수집"}
    close = frame["Close"].astype(float)
    return {"ticker": ticker, "date": str(frame.index[-1].date()),
            "return": float(close.iloc[-1] / close.iloc[-2] - 1), "price": float(close.iloc[-1]),
            "previous_date": str(frame.index[-2].date()), "source": "공급처 일봉 종가"}


def macro_components(macro_data):
    weights = {"10Y 금리": 24, "VIX": 22, "MOVE": 18, "유가": 18, "환율": 18}
    thresholds = {"10Y 금리": 4.8, "VIX": 20, "유가": 100, "환율": 1500}
    rows = []
    for name, weight in weights.items():
        info = (macro_data or {}).get(name)
        if not isinstance(info, dict) or number(info.get("val")) is None:
            continue
        value, change = number(info["val"]), number(info.get("chg"))
        direction = "상승" if change is not None and change > 0 else "하락" if change is not None and change < 0 else "중립/미확인"
        high = bool(info.get("storm")) or (name in thresholds and value >= thresholds[name])
        elevated_oil = name == "유가" and value >= 90
        rising = change is not None and change > 0
        surge = name in {"VIX", "MOVE"} and change is not None and change >= 20
        contribution = weight if high or rising else -min(8, weight // 2) if direction == "하락" else 0
        if elevated_oil and not high and direction == "하락":
            contribution = 0
        state = "수준 경고" if high else "고수준 부담" if elevated_oil else "수준 경고 없음"
        if surge:
            state += " · 급등 주의"
        elif rising:
            state += " · 상승 부담"
        rows.append({"name": name, "label": "WTI 선물(CL=F)" if name == "유가" else name,
                     "value": value, "change": change, "direction": direction, "state": state,
                     "contribution": contribution, "source": info.get("source", "Yahoo 일봉"),
                     "as_of": info.get("as_of", "")})
    return rows


def macro_stress(macro_data):
    rows = macro_components(macro_data)
    if not rows:
        return {"score": None, "label": "미수집", "rows": [], "explanation": "산출 가능한 지표 없음"}
    raw = 18 + sum(row["contribution"] for row in rows)
    score = min(100, max(0, raw))
    label = "위험" if score >= 75 else "경고" if score >= 55 else "주의" if score >= 35 else "안정"
    explanation = "기본 18 " + " ".join(f"{row['name']} {row['contribution']:+d}" for row in rows)
    explanation += f" = {raw} (0~100 범위 적용)"
    return {"score": score, "label": label, "rows": rows, "explanation": explanation}


def holding_reasons(row):
    reasons = []
    current = number(first(row, "현재비중", "current_w"))
    target = number(first(row, "목표비중", "target_w"))
    code = text(first(row, "판정코드", "code"))
    label = text(first(row, "🔥기술적 타점", "최종읽기"))
    if (current is not None and target is not None and current > target) or "OVERWEIGHT" in code:
        reasons.append("비중초과")
    elif "TARGET_FILLED" in code:
        reasons.append("목표비중 충족(추가매수 제한)")
    if any(word in code + label for word in ("STRUCTURE_DAMAGE", "MTF_DAMAGE", "추세방어", "추세훼손")):
        reasons.append("추세훼손")
    if any(word in code for word in ("PRICE_DRAWDOWN", "SINGLE_DAY", "DAILY_DROP")):
        reasons.append("가격급락")
    if code.startswith("DATA_"):
        reasons.append("데이터부족")
    from stock_lab_core.portfolio import infer_scenario_shock_multiplier
    if abs(infer_scenario_shock_multiplier({"티커": first(row, "티커", "ticker"), "자산명": first(row, "종목명", "name")})) > 1:
        reasons.append("레버리지 보유")
    if not reasons:
        reasons.append("개별 위험사유 없음")
    return reasons


# Explicit product identities only; never infer leverage from a loose ticker substring.
LEVERAGE = {"SOXL": ("SOXX", 3), "TQQQ": ("QQQ", 3), "QLD": ("QQQ", 2),
            "418660.KS": ("QQQ", 2), "BITX": ("BTC-USD", 2), "BITU": ("BTC-USD", 2),
            "RAM": ("DRAM", 2)}


def is_held(row):
    qty = number(first(row, "qty", "보유량", "보유수량"))
    if qty is not None:
        return qty > 0
    value = text(first(row, "has_pos", "has_position", "보유여부")).lower()
    if value:
        return value in {"true", "1", "1.0", "보유", "yes"}
    return (number(first(row, "현재비중", "current_w")) or 0) > 0


def comparison_lines(current, previous, *, previous_date="", current_date=""):
    if not previous_date or not current_date or previous_date >= current_date:
        return ["전일 비교 없음: 이전 거래일의 저장된 점검이 없습니다."]
    old = {text(first(row, "티커", "ticker")): row for row in records(previous) if text(first(row, "티커", "ticker"))}
    current_rows = records(current)
    keys = {text(first(row, "티커", "ticker")) for row in current_rows if text(first(row, "티커", "ticker"))}
    changes = []
    compared = 0
    for row in current_rows:
        ticker = text(first(row, "티커", "ticker"))
        if ticker not in old:
            continue
        before = text(first(old[ticker], "최종읽기", "🔥기술적 타점", "판정코드"))
        after = text(first(row, "최종읽기", "🔥기술적 타점", "판정코드"))
        if not before or not after:
            continue
        compared += 1
        old_reasons = old[ticker].get("저장사유", holding_reasons(old[ticker]))
        new_reasons = row.get("저장사유", holding_reasons(row))
        old_gate = text(first(old[ticker], "게이트상태", "gate_state"))
        new_gate = text(first(row, "게이트상태", "gate_state"))
        if (before, old_reasons, old_gate) != (after, new_reasons, new_gate):
            changes.append(f"{ticker}: {before} / {', '.join(old_reasons)} → {after} / {', '.join(new_reasons)}" +
                           (f" (게이트 {old_gate or '미제공'} → {new_gate or '미제공'})" if old_gate != new_gate else ""))
    details = changes[:10] or ["공통 종목 판정 변경 없음" if compared else "비교 가능한 공통 종목 판정 없음"]
    if keys - old.keys():
        details.append("신규: " + ", ".join(sorted(keys - old.keys())))
    if old.keys() - keys:
        details.append("목록 제외: " + ", ".join(sorted(old.keys() - keys)))
    return [f"이전 점검({previous_date}) 대비: " + " / ".join(details)]


def _pct(value):
    return "미수집" if value is None else f"{value * 100:+.2f}%"


def _cell(value):
    return text(value).replace("|", "/").replace("\n", " ") or "미제공"


def report_sections(*, context, news, flow_rows, event_rows, summary_rows, now):
    """Return report front matter and explicit missing-data reasons."""
    context = context or {}
    from stock_lab_core.report_analysis import comparison_metrics, economic_story_lines, outlier_check, sector_evidence
    from stock_lab_core.report_holdings import holding_estimate
    observations = context.get("prices", {})
    sessions = context.get("sessions", {})
    missing = list(context.get("missing", []))
    lines = ["## 기준일", f"생성 {now:%Y-%m-%d %H:%M} KST"]
    for market, name in (("KR", "한국"), ("US", "미국")):
        session = sessions.get(market, "")
        lines.append(f"- {name}: {session} 정규장 종가 기준" if session else f"- {name}: 종가 기준일 미수집(날짜를 추정하지 않음)")
        if not session:
            missing.append(f"{name} 종가 기준일")
    kr, us = sessions.get("KR"), sessions.get("US")
    lines.append("- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.")
    if kr and us:
        lines.append(f"  비교하는 거래일: 한국 {kr} / 미국 {us}. 동시 거래 결과가 아닙니다.")
    lines.extend(["", "## 어제 대비 바뀐 것"])
    lines.extend(comparison_lines(summary_rows, context.get("previous_summary"),
                                  previous_date=context.get("previous_date", ""),
                                  current_date=context.get("summary_date", "")))
    if context.get("history_status"):
        lines.append(context["history_status"] + " · 서버 재배포로 로컬 파일이 소실되면 비교 이력도 사라집니다.")
    index_rows = [(ticker, observations[ticker]) for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")
                  if observations.get(ticker, {}).get("return") is not None]
    names = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500", "^IXIC": "나스닥", "^DJI": "다우"}
    conclusion = ", ".join(f"{names[t]} {_pct(row['return'])}" for t, row in index_rows) or "종가 자료 부족으로 시장 방향 결론을 보류합니다"
    us_returns = [row["return"] for ticker, row in index_rows if ticker in {"^GSPC", "^IXIC", "^DJI"}]
    kr_returns = [row["return"] for ticker, row in index_rows if ticker in {"^KS11", "^KQ11"}]
    headline = ("미국 주요지수 동반 하락" if len(us_returns) == 3 and max(us_returns) < 0 else
                "미국 주요지수 동반 상승" if len(us_returns) == 3 and min(us_returns) > 0 else "주요지수 혼조/자료 부족")
    if kr_returns and min(kr_returns) > 0 and us_returns and max(us_returns) < 0:
        headline += ", 앞서 마감한 한국 반등과 시차가 있어 다음 개장 갭에 주의"
    lines.extend(["", "## 한 줄 결론", headline + ".", "", "## 오늘의 시장 스토리"])
    held_tickers = {text(first(row, "티커", "ticker")) for row in records(summary_rows) if is_held(row)}
    if held_tickers & {"SOXL", "RAM", "SOXX", "SMH", "DRAM", "0167A0.KS"}:
        semis = [(ticker, observations.get(ticker, {})) for ticker in ("SOXX", "DRAM", "XLK", "SOXL", "RAM")]
        detail = ", ".join(f"{ticker} {_pct(obs.get('return'))}" for ticker, obs in semis if obs.get("return") is not None)
        if detail:
            lines.append("- 사실: 보유 반도체 노출부터 확인: " + detail + ". 해석(추정): 동일 업종 중첩과 레버리지가 계좌 변동을 확대할 수 있습니다. 미확인: 개별 하락 원인의 기여도. [근거: 기준 거래일 일봉·보유목록]")
    lines.append("- 사실: " + conclusion + ". [근거: 시장별 정규장 일봉]")
    cause = next((reported_cause(row, sessions) for row in news if reported_cause(row, sessions)), "")
    releases = records(context.get("economic_releases"))
    selected = economic_story_lines(releases, limit=3)
    if selected:
        lines.extend("- " + line for line in selected)
        lines.append("지표 선정: 단위가 다른 지표를 비교하기 위해 이전치 대비 변화 비율 순, 지표별 1개(전월비 우선). 컨센서스 순위가 아닙니다.")
    elif news:
        lines.append(f"2. 최근 확인된 시장 보도입니다. {citation(news[0])}")
    else:
        lines.append("2. 공식 발표치와 출처 기준을 통과한 최근 시장 보도가 부족합니다.")
    if cause:
        lines.append("- 사실(보도 내용): " + cause)
    elif news:
        lines.append(f"- 미확인: 관련 보도는 있으나 이 종가 움직임의 직접 원인·기여도는 확정하지 않습니다. {citation(news[0])}")
    else:
        lines.append("- 미확인: 가격 움직임의 원인 자료가 없습니다. 확인되지 않은 원인을 채우지 않습니다.")
        missing.append("허용 출처 핵심 뉴스")
    held_moves = [(text(first(row, '티커', 'ticker')), observations.get(text(first(row, '티커', 'ticker')), {}).get('return'))
                  for row in records(summary_rows) if is_held(row)]
    observed_held = [(ticker, move) for ticker, move in held_moves if move is not None]
    if observed_held:
        worst, move = min(observed_held, key=lambda item: item[1])
        lines.append(f"- 사실: 연결된 보유목록에서 일간 수익률 하위는 {worst} {_pct(move)}입니다. 손익과 비중초과·레버리지 보유 사유는 별개입니다. [근거: {worst} 정규장 일봉]")
    else:
        lines.append("- 미확인: 보유 종가 자료가 연결되지 않아 내 계좌 영향을 정량화하지 않았습니다.")
    lines.append("- 다음 체크: 한국 마감 뒤 미국 움직임의 국내 미국자산 ETF 반영 여부와 개장 갭입니다(시차에 따른 추정 리스크). [근거: 한국·미국 거래시간 차이]")
    lines.extend(["", "## 경제지표", "지표 | 발표치 | 예상/대체 비교 | 이전 | 시장 반응(금리·달러·지수)", "--- | --- | --- | --- | ---"])
    if not releases:
        missing.append("공식 경제지표 발표치·예상·이전")
        lines.append("CPI/PPI·고용·소매판매·FOMC·한국 수출/물가 | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 자료 없음")
    for row in releases:
        indicator_names = {"US_CPI": "미국 CPI", "US_CORE_CPI": "미국 근원 CPI", "US_PPI": "미국 PPI",
                           "US_NONFARM_PAYROLLS": "미국 비농업고용 증감", "US_UNEMPLOYMENT": "미국 실업률",
                           "US_RETAIL_SALES": "미국 소매판매", "US_FED_TARGET_UPPER": "연준 목표금리 상단(결정문 아님)",
                           "KR_CPI": "한국 소비자물가", "KR_EXPORTS": "한국 수출"}
        basis_names = {"MoM": "전월비", "YoY": "전년비", "level": "수준", "unknown": "비교기준 미확인"}
        label = " ".join((indicator_names.get(text(row.get("indicator")), text(row.get("indicator"))),
                          text(row.get("period")), basis_names.get(text(row.get("basis")), text(row.get("basis")))))
        unit = text(row.get("unit"))
        unit = {"thousand persons": "천 명", "unknown": "(단위 미확인)"}.get(unit, unit)
        actual = row.get("actual")
        state = text(row.get("status"))
        actual_text = f"{actual}{unit}" if actual is not None else "발표 예정" if state in {"scheduled", "pending", "예정"} else "미수집"
        forecast_unit = text(row.get("forecast_unit")) or unit
        previous_unit = text(row.get("previous_unit")) or unit
        forecast_unit = {"thousand persons": "천 명", "unknown": "(단위 미확인)"}.get(forecast_unit, forecast_unit)
        previous_unit = {"thousand persons": "천 명", "unknown": "(단위 미확인)"}.get(previous_unit, previous_unit)
        forecast = f"{row['forecast']}{forecast_unit}" if row.get("forecast") is not None else "미제공"
        previous = f"{row['previous']}{previous_unit}" if row.get("previous") is not None else "미수집"
        if row.get("forecast_basis") and row["forecast_basis"] != row.get("basis"):
            forecast += " (" + basis_names.get(row["forecast_basis"], row["forecast_basis"]) + ")"
        release_at = text(row.get("release_at"))
        if release_at:
            label += " · 발표 " + release_at
        if row.get("actual_minus_forecast") is not None:
            surprise = number(row["actual_minus_forecast"])
            actual_text += f" (예상대비 {surprise:+.2f}{' %p' if unit == '%' else ' ' + unit})"
        reaction = text(row.get("reaction")) if row.get("reaction_source") else "이벤트 전후 동시점 반응 미수집"
        label += f" {citation(row)}"
        if row.get("forecast_source"):
            forecast += " (" + text(row["forecast_source"]) + ")"
        if row.get("forecast") is None:
            metrics = comparison_metrics(row)
            forecast = "컨센서스 미연결"
            if metrics["delta"] is not None:
                forecast += f" · 이전 대비 {metrics['delta']:+.2f}" + ("%p" if unit == "%" else unit)
            if metrics["prior3_mean"] is not None:
                forecast += f" · 직전 3개월 평균 {metrics['prior3_mean']:.2f}{unit}"
        checked = outlier_check(row)
        if checked["flag"]:
            actual_text += " · " + checked["status"]
        if row.get("verification"):
            actual_text += " · " + row["verification"]
        lines.append(" | ".join(_cell(v) for v in (label, actual_text, forecast, previous, reaction)))
        if actual is None and state not in {"scheduled", "pending", "예정"}:
            reason = text(row.get("missing_reason"))
            reason = "공식 API 키 미설정/응답 없음" if "API_KEY" in reason else "공식 발표치 미연결"
            missing.append(indicator_names.get(text(row.get("indicator")), text(row.get("indicator"))) + ": " + reason)
    if releases:
        lines.append("\n지표는 최신 수정치 기준입니다. 전월비·전년비/계절조정 기준이 다른 수치는 서로 비교하지 않습니다. 발표일 미제공은 관측월로 대체하지 않습니다.")
    lines.extend(["", "## 업종별 왜"])
    sectors = []
    # Prefer session-aligned base sectors; never include a leveraged sector proxy.
    sector_inputs = records(context.get("sector_rows")) + records(flow_rows)
    sector_seen = set()
    for row in sector_inputs:
        value = number(first(row, "1일수익률", "1D"))
        ticker = text(first(row, "Ticker", "티커"))
        name = text(first(row, "섹터", "ETF 이름"))
        if ticker in sector_seen:
            continue
        if value is not None and "섹터" in text(row.get("구분")) and ticker not in LEVERAGE and not re.search(r"레버리지|인버스|[23][xX배]", name):
            sector_seen.add(ticker)
            sectors.append((value, row))
    picks = sorted(sectors, key=lambda pair: pair[0], reverse=True)[:2] + sorted(sectors, key=lambda pair: pair[0])[:2]
    picks += [pair for pair in sectors if text(first(pair[1], "Ticker", "티커")) in {"XLK", "XLC", "XLE", "XLU"}]
    picks += sorted((pair for pair in sectors if abs(pair[0]) >= .05 and any(token in text(pair[1].get("구분")) for token in ("한국", "국내"))), key=lambda pair: abs(pair[0]), reverse=True)[:2]
    seen = set()
    seen_sector_exposures = set()
    lines.extend(["업종 | 사실 | 해석(추정) | 미확인", "--- | --- | --- | ---"])
    for value, row in picks:
        ticker = text(first(row, "Ticker", "티커"))
        exposure = "US_SEMICONDUCTORS" if ticker in {"SOXX", "SMH"} else ticker
        if ticker in seen or exposure in seen_sector_exposures:
            continue
        seen.add(ticker)
        seen_sector_exposures.add(exposure)
        label = text(row.get("섹터"))
        linked = [item for item in news if (any(token in label for token in ("반도체", "메모리")) and item["category"] == "반도체/AI") or
                  (label and label in item["title"])]
        evidence = sector_evidence(row, context.get("macro_data", {}), [dict(item, ticker=ticker) for item in linked])
        lines.append(" | ".join(_cell(v) for v in (f"{label}({ticker})", evidence["fact"], evidence["reading"], evidence["unconfirmed"])))
    if not seen:
        lines.append("- 당일 업종 등락 자료 미수집. 3개월 순위를 당일 상승/하락으로 대체하지 않습니다.")
    lines.extend(["", "## 내 보유 종목 영향", "종목 | 일간 등락 | 레버리지 환산 | 상태/사유", "--- | --- | --- | ---"])
    held = [row for row in records(summary_rows) if is_held(row)]
    for row in held:
        ticker = text(first(row, "티커", "ticker"))
        obs = observations.get(ticker, {})
        value = obs.get("return")
        estimate = "해당없음"
        reasons = holding_reasons(row)
        estimate, leveraged = holding_estimate(row, observations, sessions, now)
        if leveraged:
            reasons = [reason for reason in reasons if reason != "개별 위험사유 없음"]
            if "레버리지 보유" not in reasons:
                reasons.append("레버리지 보유")
        lines.append(" | ".join(_cell(v) for v in (f"{text(first(row, '종목명', 'name'))}({ticker})", _pct(value) + (f" ({obs['date']})" if obs.get("date") else ""), estimate, ", ".join(reasons))))
        if value is None:
            missing.append(ticker + " 보유 일간 종가등락")
    if not held:
        lines.append("보유목록 미연결 | 미수집 | 해당없음 | 보유 여부를 추정하지 않음")
        missing.append("보유목록")
    watches = [row for row in records(summary_rows) if not is_held(row)]
    watches.sort(key=lambda row: (number(first(row, "Adj점수", "adj")) or 0), reverse=True)
    lines.extend(["", "## 관심 후보 상위 3개"])
    for row in watches[:3]:
        ticker = text(first(row, "티커", "ticker"))
        condition = text(first(row, "해제조건", "다음확인", "실행메모", "게이트근거")) or "기존 게이트 재통과 + 눌림/종가 타점 확인"
        lines.append(f"- {ticker} · {text(first(row, '📌후보등급', '후보등급')) or '등급 미제공'} · 해제 조건: {condition}")
    if not watches:
        lines.append("- 관심 후보 미연결/없음")
    lines.extend(["", "## 이번 주 일정"])
    scheduled = []
    for row in records(context.get("calendar_events", event_rows)):
        date_text = text(first(row, "date", "날짜", "일자", "시작일", "발표일"))
        dt = stamp(date_text)
        if dt and text(first(row, "source", "출처")) != "fallback" and now.date() <= dt.date() <= (now + timedelta(days=7)).date():
            scheduled.append((date_text, row))
    for date_text, row in sorted(scheduled, key=lambda item: item[0]):
        title = text(first(row, '이벤트', 'event', 'title'))
        source = text(first(row, '출처', 'source')) or '출처 미제공'
        link = safe_link(row.get("source_url"))
        lines.append(f"- {date_text}: {title} · " + (f"[{source}]({link})" if link else source))
    if not scheduled:
        sources = records(context.get("calendar_sources"))
        connected = [row["name"] for row in sources if row.get("status") == "connected"]
        lines.append("- 향후 7일 일정 없음(연결된 공식 일정: " + ", ".join(connected) + ")" if connected else "- 일정 미연결: 공식 캘린더 수집 실패/자료 미제공. 일정 없음으로 판단하지 않습니다.")
        if not connected:
            missing.append("향후 7일 확정 일정 미연결")
    for source in records(context.get("calendar_sources")):
        if source.get("status") != "connected":
            lines.append(f"- 일정 미연결: {source['name']} · {source.get('reason', '응답 없음')}")
    lines.extend(["", "## 핵심 뉴스 5건"])
    lines.append("기준 거래일 마감시황 우선. 이전 거래일의 마감 회고는 제외하며, 마감 후 회고는 사후보도로 표시합니다.")
    if len(news) < 5:
        lines.append(f"출처·중복 제거 기준 통과 {len(news)}건. 부족한 {5 - len(news)}건은 무관한 기사로 채우지 않았습니다.")
    for index, row in enumerate(news[:5], 1):
        timing = " · 마감 후 회고(인과 확정 아님)" if row.get("retrospective_close_wrap") else ""
        lines.append(f"{index}. [{row['category']}] {row['title']} · {row['published'] or '기사시각 미제공'}{timing} {citation(dict(row, title='원문'))}")
        lines.append("   " + row["reading_ko"])
    if not news:
        lines.append("허용 출처·중복 제거 기준을 통과한 뉴스 없음.")
    lines.extend(["", "가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다."])
    return lines, list(dict.fromkeys(missing))
