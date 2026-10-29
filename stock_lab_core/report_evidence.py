"""Deterministic report evidence. No inferred prices, forecasts or causality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

KST = timezone(timedelta(hours=9))
SOURCE_NAMES = (
    "reuters", "로이터", "associated press", "연합뉴스", "연합인포맥스", "한국경제",
    "매일경제", "서울경제", "서울파이낸스", "조선비즈", "조선일보", "한겨레",
    "경향신문", "머니투데이", "아시아경제", "이데일리", "뉴시스", "cnbc", "bloomberg",
    "financial times", "wall street journal", "yahoo finance", "bls", "federal reserve",
    "한국은행", "통계청", "산업통상", "boj", "nikkei", "한경", "axios",
)
SOURCE_DOMAINS = (
    "reuters.com", "apnews.com", "yna.co.kr", "yonhapnewstv.co.kr", "einfomax.co.kr",
    "hankyung.com", "mk.co.kr", "sedaily.com", "chosun.com", "edaily.co.kr",
    "mt.co.kr", "asiae.co.kr", "newsis.com", "cnbc.com", "bloomberg.com", "ft.com",
    "wsj.com", "finance.yahoo.com", "bls.gov", "federalreserve.gov", "bok.or.kr",
    "kostat.go.kr", "motie.go.kr", "boj.or.jp", "census.gov", "nikkei.com", "axios.com",
    "aws.amazon.com", "pytorch.org", "nvidianews.nvidia.com", "investor.atmeta.com", "ir.tesla.com", "investors.coreweave.com",
)
EVENT_CLUSTERS = (
    ("cxmt", ("cxmt", "창신", "창신메모리")),
    ("boj", ("boj", "일본은행", "일은 ")),
    ("fomc", ("fomc", "fed rate decision", "연준 금리", "기준금리 동결")),
)
MARKET_TERMS = re.compile(
    r"주식|증시|코스피|코스닥|나스닥|주가|반도체|금리|연준|물가|수출|환율|국채|인플레|고용|소매판매|실적|은행|원유|유가|달러|엔화|관세|무역|휴전|중동|투자|경제|자산|전력|바이오|메모리|코인|이더리움|비트코인|엔비디아|아마존|마이크론|코어위브|트레이니엄|파이토치|수주|가이던스|"
    r"\b(stocks?|shares?|equities|market|earnings|fed|fomc|cpi|ppi|jobs|rates?|boj|oil|wti|brent|bitcoin|ethereum|eth|btc|crypto|cxmt|nvidia|semiconductors?|technology|tech|coreweave|neoclouds?|credit|debt|financing|borrowing|inflation|tariff|treasury|ceasefire|amazon|aws|trainium|pytorch|micron|guidance)\b",
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
    if re.search(r"CoreWeave|코어위브|Trainium|트레이니엄", title, re.I):
        return "반도체/AI"
    if re.search(r"\bMSCI\b", title, re.I):
        return "금융/기업실적"
    if re.search(r"\bTesla\b|테슬라|Roadster|로드스터", title, re.I):
        return "자동차/모빌리티"
    if re.search(r"\bRTX\b|BAE Systems|BAE시스템|APKWS|방산", title, re.I):
        return "방산/군수"
    if re.match(r"^(?:\[[^]]+\]\s*)?(?:코스피|코스닥)\s*[,，]", title):
        return "시장 시황"
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
        (r"\bAI.{0,15}(?:stocks|shares)", "미국 AI 관련주"),
        (r"\bchip stocks|semiconductor", "반도체주"),
        (r"\bnvidia\b", "엔비디아"), (r"\bboj\b|bank of japan", "일본은행"),
        (r"\bfed\b|fomc", "미국 연준"), (r"\bppi\b", "미국 생산자물가"),
        (r"\bcpi\b", "미국 소비자물가"), (r"ethereum|\beth\b", "이더리움"),
        (r"bitcoin|\bbtc\b", "비트코인"), (r"oil|\bwti\b|brent", "원유"),
        (r"middle east|ceasefire", "중동 휴전 협상"),
    )
    subject = next((label for pattern, label in subjects if re.search(pattern, lower)), "")
    if subject == "원유":
        from stock_lab_core.article_price_facts import oil_price_fact
        oil = oil_price_fact([title])
        return ("제목 표현 요약: " + oil["summary"] + "(본문·인과 미확인)") if oil else ""
    actions = (
        (r"rebound|recover|bounc", "반등 관련 보도"),
        (r"cuts? rates|rate cut", "금리 인하 관련 보도"),
        (r"raises? rates|rate hike", "금리 인상 관련 보도"),
        (r"holds? rates|unchanged", "금리 동결 관련 보도"),
        (r"outflows?", "자금 유출 관련 보도"), (r"inflows?", "자금 유입 관련 보도"),
        (r"falls?|drops?|declines?|slumps?", "하락 관련 보도"),
        (r"rises?|gains?|surges?", "상승 관련 보도"),
    )
    action = next((label for pattern, label in actions if re.search(pattern, lower)), "관련 소식")
    if action == "관련 소식" or not subject:
        return ""
    return f"제목 표현 요약: {subject} {action}(본문·인과 미확인)"


def _close_recap_key(row, title, published):
    """Group an exact closing move, not merely articles about the same theme."""
    if (row.get("market") == "US" and row.get("session_date") and row.get("is_close_wrap")
            and row.get("news_bucket") != "current_session_news"
            and text(first(row, "publisher", "source")).startswith("연합뉴스")
            and re.search(r"뉴욕증시.{0,60}혼조\s*마감", title)):
        # One publisher's same-session market recaps; retain all article claims.
        return ("US", row["session_date"], "연합뉴스", "뉴욕증시 혼조 마감")
    if row.get("market") != "KR" or not row.get("session_date") or row.get("news_bucket") == "current_session_news":
        return None
    index = re.search(r"코스피|코스닥", title)
    if not index:
        return None
    # The lead index owns the move; stop before another index's percentage.
    segment = re.split(r"코스피|코스닥", title[index.end():], maxsplit=1)[0]
    recap = re.search(r"(\d+\.\d+)\s*%\)?\s*(하락|급락|상승|급등|내린|밀린|떨어진|오른|올랐|↑|↓)", segment[:100])
    local = published.astimezone(KST)
    after_close = local.date().isoformat() == row["session_date"] and (local.hour, local.minute) >= (15, 30)
    from stock_lab_core.report_presentation import is_preopen_outlook
    if not recap or is_preopen_outlook(row) or not (after_close or row.get("is_close_wrap") or "마감" in title):
        return None
    return ("KR", row["session_date"], index[0], float(recap[1]),
            "down" if recap[2] in {"하락", "급락", "내린", "밀린", "떨어진", "↓"} else "up")


def curate_news(rows, *, now=None, limit=5, session_scoped=False):
    from stock_lab_core.today_news import _session_article_keys
    now = now or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    accepted, seen, seen_articles, seen_links, close_recaps = [], set(), set(), set(), {}
    source_rows = records(rows)
    # During KR trading, current-session articles precede yesterday's recaps.
    if now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) < (15, 30):
        source_rows.sort(key=lambda row: not (row.get("market") == "KR" and row.get("session_date") == now.date().isoformat()))
    for raw in source_rows:
        title = text(first(raw, "title", "제목"))
        publisher = text(first(raw, "publisher", "출처", "source"))
        link = safe_link(first(raw, "link", "링크", "url"))
        domain = urlparse(safe_link(raw.get("publisher_url")) or link).hostname or ""
        lower = f"{title} {publisher} {domain}".lower()
        if re.search(r"^\s*\[표\].*(?:시세|종가|주가|증시|순매수|순매도)|시세표", title):
            continue
        if not title or not MARKET_TERMS.search(title) or any(word in lower for word in (
            "coinmarketcap", "tmgm", "prnewswire", "businesswire", "보도자료", "press release",
            "price today", "live price", "to usd", "rbc", "commerzbank", "일일 운세",
        )):
            continue
        if re.search(r"계좌.{0,16}(?:만들|개설).{0,25}(?:받으세요|이벤트|혜택)|주식\s*받으세요", title):
            continue
        if not (any(name in publisher.lower() for name in SOURCE_NAMES) or
                any(domain == item or domain.endswith("." + item) for item in SOURCE_DOMAINS)):
            continue
        published = text(first(raw, "published_at", "published", "시간"))
        dt = stamp(published)
        if dt is None or not now - timedelta(days=7) <= dt <= now + timedelta(minutes=5):
            continue
        clean = re.sub(r"\s+[-|]\s+" + re.escape(publisher) + r"$", "", title, flags=re.I).strip() if publisher else title
        canonical_link, canonical_title = _session_article_keys(dict(raw, title=clean, link=link))
        article_key = (text(raw.get("market")), text(raw.get("session_date")), publisher, canonical_title)
        if article_key in seen_articles or (canonical_link and canonical_link in seen_links):
            continue
        seen_articles.add(article_key)
        if canonical_link:
            seen_links.add(canonical_link)
        recap_key = _close_recap_key(raw, clean, dt)
        if recap_key and recap_key in close_recaps:
            previous = close_recaps[recap_key]
            related = [dict(title=clean, publisher=publisher, link=link, published=dt.isoformat()),
                       *raw.get("related_articles", [])]
            known = {news_article_key(item) for item in [previous, *previous.get("related_articles", [])]}
            for item in related:
                item_key = news_article_key(item)
                if item_key not in known:
                    previous.setdefault("related_articles", []).append(dict(item))
                    known.add(item_key)
            previous["duplicate_count"] = 1 + len(previous.get("related_articles", []))
            continue
        key = next((key for key, words in EVENT_CLUSTERS if any(w in clean.lower() for w in words)),
                   re.sub(r"[\W_]+", "", clean.lower()))
        seen_key = (text(raw.get("market")), text(raw.get("session_date")), key) if session_scoped else key
        if seen_key in seen:
            continue
        seen.add(seen_key)
        row = dict(raw, title=clean, publisher=publisher, link=link, published=dt.isoformat() if dt else published,
                   category=news_category(clean, text(first(raw, "market_category", "카테고리")) or "시장"),
                   event_key=key)
        if raw.get("related_articles"):
            row["related_articles"] = [dict(item) for item in raw["related_articles"]]
        row["reading_ko"] = korean_headline_reading(row)
        accepted.append(row)
        if recap_key:
            close_recaps[recap_key] = row
    return accepted[:limit]


def citation(row):
    label = text(first(row, "title", "indicator", "지표"))
    publisher = text(first(row, "publisher", "source", "출처"))
    label = (publisher + " · " if publisher else "") + label
    label = label.replace("[", "(").replace("]", ")")
    link = safe_link(first(row, "link", "source_url", "링크"))
    return f"[{label}]({link})" if link else f"[{label} · 원문 URL 미제공]"


def story_news_citation(row):
    timing = text(row.get("news_timing"))
    if row.get("kr_news_timing") and row.get("news_timing_market") != "KR":
        timing = f"한국 {row['kr_news_timing']} / {row.get('news_timing_market', '원시장')} {timing}"
    published = stamp(first(row, "published", "published_at"))
    parts = ([f"[{timing}]"] if timing else []) + [citation(row)]
    if published:
        parts.append(published.astimezone(KST).strftime("%m/%d %H:%M KST"))
    if row.get("related_articles"):
        parts.append(f" · 같은 시장·거래일 마감 등락 보도 {row.get('duplicate_count', 1 + len(row['related_articles']))}건 묶음 · 함께 묶인 제목: "
                     + " / ".join(citation(item) for item in row["related_articles"]))
    return " ".join(parts)


def reported_cause(row, sessions):
    """Attribute explicit headline causality, never promote a late article to a cause."""
    from stock_lab_core.report_presentation import is_preopen_outlook
    if is_preopen_outlook(row):
        return ""
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
    return f"기사 제목은 ‘{title}’라고 배경을 설명합니다(보도 해석이며 인과 확정 아님). {story_news_citation(dict(row, title='원문'))}"


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
    # Match the report's 15:30 KR close; 15:40 is off-hours trading, not the close.
    closed_today = not crypto and local.weekday() < 5 and (local.hour, local.minute) >= ((15, 30) if kr else (16, 15))
    mask = (dates <= end) if closed_today else (dates < end)
    pending = frame.attrs.get("report_close_pending_date")
    if pending:
        mask &= frame.index.strftime("%Y-%m-%d") != pending
    out = frame.loc[mask].sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    close = pd.to_numeric(out["Close"], errors="coerce")
    return out.loc[close.gt(0) & close.map(math.isfinite)]


def price_observation(frame, ticker, now=None):
    frame = closed_daily_frame(frame, ticker, now)
    if len(frame) < 2:
        return {"ticker": ticker, "date": "", "return": None, "source": "종가 이력 미수집"}
    close = frame["Close"].astype(float)
    falls = 0
    changes = list(close.pct_change().iloc[1:][::-1])
    for change in changes:
        if change >= 0:
            break
        falls += 1
    rises = 0
    for change in changes:
        if change <= 0:
            break
        rises += 1
    prior_falls = 0
    for change in changes[rises:]:
        if change >= 0:
            break
        prior_falls += 1
    return {"ticker": ticker, "date": str(frame.index[-1].date()),
            "return": float(close.iloc[-1] / close.iloc[-2] - 1), "price": float(close.iloc[-1]),
            "return_5d": float(close.iloc[-1] / close.iloc[-6] - 1) if len(close) >= 6 else None,
            "previous_return": float(close.iloc[-2] / close.iloc[-3] - 1) if len(close) >= 3 else None,
            "down_days": falls, "up_days": rises, "prior_down_days": prior_falls,
            "previous_date": str(frame.index[-2].date()), "source": frame.attrs.get("source", "공급처 일봉 종가"), "kind": "확정 종가"}


def intraday_observation(frame, ticker, now):
    from stock_lab_core.market_board import completed_close_series
    from stock_lab_core.report_session import kst_now, market_session_states
    now = kst_now(now)
    market = "KR" if ticker.endswith((".KS", ".KQ")) or ticker in {"^KS11", "^KQ11"} else "US"
    local = now.astimezone(KST if market == "KR" else ZoneInfo("America/New_York"))
    if market_session_states(now)[market]["phase"] != "intraday":
        return {}
    close, _ = completed_close_series(frame, market, now=now, include_current=True)
    if len(close) < 2 or close.index[-1].date() != local.date() or local.weekday() >= 5:
        return {}
    if not math.isfinite(close.iloc[-1]) or not math.isfinite(close.iloc[-2]) or close.iloc[-2] <= 0:
        return {}
    return {"date": local.date().isoformat(), "return": float(close.iloc[-1] / close.iloc[-2] - 1),
            "price": float(close.iloc[-1]), "retrieved_at": now.isoformat(), "kind": "장중 진행·확정 아님",
            "source": "공급처 당일 일봉(지연 가능, 시세 시각 미제공)"}


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


def comparison_lines(current, previous, *, previous_date="", current_date="", same_session=False, previous_run_at=""):
    from stock_lab_core.report_comparison import history_comparison_lines

    return history_comparison_lines(current, [{"previous": previous, "previous_date": previous_date,
        "current_date": current_date, "same_session": same_session, "previous_run_at": previous_run_at}])


def news_article_key(row):
    from stock_lab_core.today_news import _session_article_keys
    link, _ = _session_article_keys(dict(row, link=safe_link(first(row, "link", "url"))))
    return link or re.sub(r"\W+", "", text(row.get("title"))).casefold()


def participant_news_rows(news, session_date):
    """Keep distinct participant stories; do not infer net flows from titles."""
    from stock_lab_core.report_presentation import is_preopen_outlook

    selected, seen_titles, seen_links = [], set(), set()
    for row in news:
        title = " / ".join(text(item.get("title")) for item in [row, *row.get("related_articles", [])])
        if row.get("market") != "KR" or row.get("session_date") != session_date or is_preopen_outlook(row):
            continue
        if not re.search(r"外人|외국인|외인|기관|연기금|개인", title) or not re.search(r"매수|매도|수급", title):
            continue
        key = re.sub(r"\W+", "", title).casefold()
        link = text(first(row, "link", "url"))
        if key in seen_titles or (link and link in seen_links):
            continue
        seen_titles.add(key)
        if link:
            seen_links.add(link)
        selected.append(row)
    return selected


def participant_news_lines(news, session_date, *, limit=3):
    selected = participant_news_rows(news, session_date)
    if not selected:
        return []
    count = sum(row.get("duplicate_count", 1) for row in selected)
    grouping = f" · {len(selected)}개 묶음" if count > len(selected) else ""
    return [f"- 수급 주체 보도 {count}건{grouping}(제목 기준·기사 주장, 순매수액 미검증): "
            + " / ".join(story_news_citation(row) for row in selected[:limit])
            + (f" · 나머지 {len(selected) - limit}건 생략" if len(selected) > limit else "")]


def _pct(value):
    return "미수집" if value is None else f"{value * 100:+.2f}%"


def _cell(value):
    return text(value).replace("|", "/").replace("\n", " ") or "미제공"


def report_sections(*, context, news, flow_rows, event_rows, summary_rows, now):
    """Return report front matter and explicit missing-data reasons."""
    context = context or {}
    from stock_lab_core.report_analysis import comparison_metrics, economic_reaction_text, economic_story_dates, economic_story_lines, recent_economic_releases, outlier_check, sector_evidence
    from stock_lab_core.report_economic_reading import economic_reading_with_reaction
    from stock_lab_core.report_holdings import holding_estimate, completed_scenario_comparison, hedge_policy_line, hedge_source_lines
    from stock_lab_core.report_presentation import account_metrics, account_headline, candidate_fields, compact_holding_reference, is_preopen_outlook, is_preopen_price_recap, kst_time, market_cause_candidates, sector_related_news, korean_market_catalysts
    from stock_lab_core.report_session import report_mode, market_session_states, kst_now, MODE_LABELS, next_check, us_extended_session
    from stock_lab_core.economic_cache import collection_status
    from stock_lab_core.report_scenario import latest_futures_line, scenario_observation_line
    observations = context.get("prices", {})
    sessions = context.get("sessions", {})
    now = kst_now(now)
    states = context.get("market_states") or market_session_states(now, sessions)
    mode = report_mode(now, is_trading_day=context.get("kr_is_trading_day"))
    outlook_count = sum(is_preopen_outlook(row) for row in news) if mode == "closed" else 0
    if mode == "closed":
        news = [row for row in news if not is_preopen_outlook(row)]
    else:
        news = [dict(row, news_timing="장전전망(결과와 다름)") if is_preopen_outlook(row) else row for row in news]
    story_news = [row for row in news if not is_preopen_outlook(row) and not is_preopen_price_recap(row)
                  and row.get("news_bucket") not in {"next_session_news", "other_market_news"}]
    scenario_context = context.get("scenario_observations") or context.get("scenario_context")
    futures_line = latest_futures_line(scenario_context)
    missing = list(context.get("missing", []))
    lines = ["## 기준일", f"생성 {now:%Y-%m-%d %H:%M} KST"]
    lines.append(f"- 보고서 모드: {states['KR']['label']} · 한국 정규장 시간대 기준, 특별 휴장·거래시간 변경은 별도 확인")
    lines.extend(["", "시장·확정 종가 기준 | 생성 시점 상태 | 진행 중 세션 | 달력 확인", "--- | --- | --- | ---"])
    for market, name in (("KR", "한국"), ("US", "미국")):
        session = sessions.get(market, "")
        state = states[market]
        basis = f"{name}: {session} 정규장 종가 기준" if session else f"{name}: 종가 기준일 미수집(날짜를 추정하지 않음)"
        extended_window = us_extended_session(now) if market == "US" else {}
        label = state["label"] + (" · " + extended_window["label"] + " 시간대" if extended_window else "")
        active = state.get("active_date") or (extended_window.get("date", "") + " 별도 세션" if extended_window else "없음")
        lines.append(" | ".join(_cell(value) for value in (basis, label, active, state["calendar_note"])))
        if not session:
            missing.append(f"{name} 종가 기준일")
    kr, us = sessions.get("KR"), sessions.get("US")
    lines.append("")
    lines.append("- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.")
    if kr and us:
        lines.append(f"  비교하는 거래일: 한국 {kr} / 미국 {us}. 동시 거래 결과가 아닙니다.")
    lines.append("진행 중 세션의 장중 수치는 확정 종가 표와 별도이며 해당 세션 종가가 아닙니다.")
    counts = context.get("queue_input_counts") or {}
    if counts:
        lines.append("입력 집계(같은 측정ID): " + " / ".join(
            f"{label} {int(counts[key])}개" for key, label in (("registered", "등록 원천"), ("auto_flow_candidates", "자동 돈흐름 후보"), ("calculated", "최종 계산"))
            if number(counts.get(key)) is not None))
    lines.append("‘관심’ 건수는 최종 계산 목록의 미보유 종목 수로, 직접 등록 종목 수와 다릅니다. 등록·자동 후보는 중복/보유 포함 가능하며 종목별 입력 출처가 없으면 분리 추정하지 않습니다.")
    from stock_lab_core.report_comparison import history_comparison_lines
    history_baselines = [{"previous": context.get("previous_summary"), "previous_date": context.get("previous_date", ""),
                          "current_date": context.get("summary_date", "")}]
    if context.get("previous_run_summary"):
        history_baselines.append({"previous": context["previous_run_summary"], "previous_date": context.get("previous_run_date", ""),
                     "current_date": context.get("summary_date", ""), "same_session": True,
                     "previous_run_at": context.get("previous_run_at", "")})
    history_lines = ["", "## 판정 이력 비교", *history_comparison_lines(summary_rows, history_baselines)]
    if context.get("previous_generated_at"):
        history_lines.append("이전 저장 생성 시각: " + kst_time(context["previous_generated_at"]))
    if context.get("previous_summary") and not context.get("previous_source_provenance"):
        history_lines.append("이전 저장본에는 지수별 출처·수집 시각이 없어 날짜 지연 원인을 확정할 수 없습니다. 현재 기준일은 UTC 날짜 계산이 아니라 각 지수의 확인된 종가 날짜이며, 새 이력부터 원자료 기준일·출처를 함께 저장합니다.")
    if not context.get("previous_run_summary") and not context.get("previous_summary"):
        history_lines.append("같은 거래일 직전 생성 이력도 없습니다. 매크로 변화와 종목 판정 비교는 별도 저장 자료를 사용합니다.")
    if context.get("history_status"):
        history_lines.extend(["", context["history_status"] + ("" if context.get("history_durable") else " · 로컬 저장은 재배포 시 초기화될 수 있습니다.")])
    index_rows = [(ticker, observations[ticker]) for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")
                  if observations.get(ticker, {}).get("return") is not None]
    names = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500", "^IXIC": "나스닥", "^DJI": "다우"}
    conclusion = ", ".join(f"{names[t]} {_pct(row['return'])}({row.get('date', '미수집')} 확정 종가)" for t, row in index_rows) or "종가 자료 부족으로 시장 방향 결론을 보류합니다"
    held = [row for row in records(summary_rows) if is_held(row)]
    portfolio = account_metrics(held, observations, sessions) if held else {}
    sector_facts = [f"{name} {_pct(observations[t]['return'])}({us} 확정 종가)" for t, name in (("SOXX", "미국 반도체"), ("IGV", "소프트웨어"))
                    if number(observations.get(t, {}).get("return")) is not None and observations[t].get("date") == us]
    live = context.get("intraday_prices", {})
    from stock_lab_core.report_intraday import intraday_account_metrics, layered_market_headline, valid_live_observation, extended_quote_text, account_overview_lines, latest_account_metrics
    live_metrics = intraday_account_metrics(held, live, context.get("extended_prices"), states=states,
                                            now=max(now, stamp(context.get("quote_checked_at")) or now))
    from stock_lab_core.report_account import cumulative_account_metrics
    latest_metrics = cumulative_account_metrics(held, context, states, max(now, stamp(context.get("quote_checked_at")) or now))
    current_kr = live.get("^KS11", {})
    kr_close = observations.get("^KS11", {})
    from stock_lab_core.report_market_summary import market_summary, evidence_table
    synthesis = market_summary(context, news, flow_rows, states, now, futures_line=futures_line)
    from stock_lab_core.report_catalysts import post_close_brief
    post_close = post_close_brief(context, news, summary_rows, now)
    if post_close["overview"]:
        synthesis["overview"] += "\n\n" + post_close["overview"]
    headline = layered_market_headline(context, flow_rows, states, now, live_metrics,
                                      synthesis=synthesis, latest_metrics=latest_metrics)
    if states["US"]["phase"] == "preopen" and futures_line:
        headline += ".\n\n미국 개장 전 참고: " + futures_line
    lines.extend(["", "## 한 줄 결론"])
    from stock_lab_core.report_brief import build_news_brief
    brief = build_news_brief(context, news, summary_rows, now,
                            exclude_keys=[news_article_key(row) for row in synthesis.get("background_news", [])
                                          + participant_news_rows(news, kr)])
    lines.extend([headline + ".", "", "## 오늘의 핵심 재료",
                  *post_close["lines"], "", *brief["lines"], "", "## 오늘의 시장 스토리"])
    story_start = len(lines) - 2
    lines.extend(["", *evidence_table(synthesis), ""])
    if outlook_count:
        lines.append(f"장전전망 {outlook_count}건은 마감 결과 설명에서 제외했습니다(장전전망은 실제 결과와 다름).")
    kr_summary = "기준일 지수 미연결"
    if number(kr_close.get("return")) is not None:
        period_label = "당일" if kr_close.get("date") == now.date().isoformat() else "직전"
        kr_summary = f"{period_label} 코스피 {_pct(kr_close['return'])}, 5D {_pct(kr_close.get('return_5d'))} ({kr_close.get('date', '미수집')} 확정 종가)"
    reversal = next((row for row in story_news if row.get("market") == "KR" and row.get("session_date") == kr
                     and re.search(r"반전|반등 성공|급락 출발", text(row.get("title")))), None)
    participant_rows = participant_news_rows(news, kr)
    used_story_news = ({news_article_key(row) for row in participant_rows[:3]}
                       | set(brief["article_keys"]) | set(post_close["article_keys"]))
    if reversal and news_article_key(reversal) not in used_story_news:
        kr_summary += f" · 제목 기준(기사 주장): {story_news_citation(reversal)}"
        used_story_news.add(news_article_key(reversal))
    releases = records(context.get("economic_releases"))
    story_releases = recent_economic_releases(releases, context, now)
    economic_summary = []
    for indicator, name in (("US_PPI", "미국 PPI"), ("KR_EXPORTS", "한국 수출")):
        row = next((r for r in story_releases if r.get("indicator") == indicator and r.get("basis") == ("MoM" if indicator == "US_PPI" else "YoY")
                    and number(r.get("actual")) is not None and r.get("status") not in {"pending", "stale"}), None)
        if row:
            delta = comparison_metrics(row)["delta"]
            economic_summary.append(f"{name} {row.get('period', '')} {'전월비' if indicator == 'US_PPI' else '전년비'} {row['actual']}%"
                                    + (f" · 이전 대비 {delta:+.2f}%p" if delta is not None else "")
                                    + (" (수동 보완값)" if row.get("status") == "verified_snapshot" else ""))
    lines.extend(["", "관측 축 | 확인된 수치·범위", "--- | ---",
                  "미국 업종 종가 | " + _cell(" · ".join(sector_facts) or "업종 종가 미연결"),
                  "한국 지수 종가 | " + _cell(kr_summary),
                  "최근 발표 지표 | " + _cell(" / ".join(economic_summary) or "최근 3거래일 이내 발표일이 확인된 주요 발표치 없음/미연결"), ""])
    candidates = []
    candidate_keys = set(used_story_news)
    for row in synthesis.get("background_news", []) + [item for market in ("KR", "US") for item in market_cause_candidates(news, market, sessions.get(market))]:
        key = news_article_key(row)
        if key not in candidate_keys:
            candidates.append(row)
            candidate_keys.add(key)
    if candidates:
        lines.extend(["보도상 배경 후보 | 대상 거래일 | 출처·보도 시각", "--- | --- | ---"])
        for row in candidates:
            lines.append(" | ".join(_cell(value) for value in (
                row["title"], f"{row['market']} {row['session_date']}", story_news_citation(dict(row, title="원문")))))
            used_story_news.add(news_article_key(row))
        lines.append("")
        lines.append("보도 해석의 후보이며 인과·기여도는 미확정입니다. 마감 후 회고는 당일 사건을 설명하는 사후 주장으로 구분합니다. 신용 충격의 파급 범위는 같은 세션 신용 스프레드·개별 채권·수급 자료 없이는 확정하지 않습니다.")
    lines.append("지표 서사 기준: 생성시각의 해당 시장 현지 날짜를 포함한 최근 3거래일 이내 발표일만 사용(미국 개장 전에도 현지 당일 포함). 오래된·미래·발표일 미상·비거래일 지표는 경제지표 표에 유지합니다.")
    for market, name in (("KR", "한국"), ("US", "미국")):
        dates = economic_story_dates(context, market, now)
        lines.append(f"- {name} 발표일 범위: {dates[0]}~{dates[-1]}" +
                     (" (거래일 이력 부족, 확인된 거래일만 적용)" if len(dates) < 3 else
                      " (미국 정규장 달력, 특별 휴장 별도 확인)" if market == "US" else " (확인된 한국 거래일)")
                     if dates else f"- {name} 발표일 범위 미확인: 현지 최근 거래일 미연결, 지표 서사 보류")
    lines.extend(participant_news_lines(news, kr))
    if states["US"]["phase"] == "intraday":
        live_items = [f"{names.get(t, t)} {_pct(live[t]['return'])} ({kst_time(live[t].get('as_of', live[t].get('retrieved_at')))})"
                      for t in ("^IXIC", "SOXX", "SOXL", "RAM") if number(live.get(t, {}).get("return")) is not None]
        lines.append(f"- 사실: 미국 {states['US']['active_date']} 장중 진행·확정 아님: " + (" / ".join(live_items) or "시각 확인 가능한 시세 미수집") + ". [근거: 정규장 5분봉·직전 확정 종가]")
        rebound = next((r for r in story_news if r.get("market") == "US" and r.get("session_date") == states["US"]["active_date"]
                        and r.get("news_bucket") == "current_session_news" and not is_preopen_outlook(r)
                        and re.search(r"반등|회복|rebound|recover|bounce", text(r.get("title")), re.I)), None)
        if rebound:
            lines.append("- 장중 배경(기사 주장·인과 미확정): " + korean_headline_reading(rebound) + " · " + story_news_citation(rebound))
            used_story_news.add(news_article_key(rebound))
    held_tickers = {text(first(row, "티커", "ticker")) for row in records(summary_rows) if is_held(row)}
    if held_tickers & {"SOXL", "RAM", "SOXX", "SMH", "DRAM", "0167A0.KS"}:
        semis = [(ticker, observations.get(ticker, {})) for ticker in ("SOXX", "DRAM", "XLK", "SOXL", "RAM")]
        detail = ", ".join(f"{ticker} {_pct(obs.get('return'))}({obs.get('date', '미수집')} 확정 종가)" for ticker, obs in semis if obs.get("return") is not None)
        if detail:
            lines.append("- 사실: 보유 반도체 노출부터 확인: " + detail + ". 해석(추정): 동일 업종 중첩과 레버리지가 계좌 변동을 확대할 수 있습니다. 미확인: 개별 하락 원인의 기여도. [근거: 기준 거래일 일봉·보유목록]")
    us_index_facts = ", ".join(f"{names[t]} {_pct(row['return'])}({row.get('date', '미수집')} 확정 종가)"
                               for t, row in index_rows if t in {"^GSPC", "^IXIC", "^DJI"})
    if us_index_facts:
        lines.append("- 미국 지수: " + us_index_facts + ". [근거: 시장별 정규장 일봉]")
    kq = observations.get("^KQ11", {})
    if number(kq.get("return")) is not None:
        lines.append(f"- 코스닥: {_pct(kq['return'])}({kq.get('date', '미수집')} 확정 종가)")
    for ticker in ("^KS11", "^KQ11"):
        obs = observations.get(ticker, {})
        details = []
        if number(obs.get("previous_return")) is not None:
            details.append(f"직전 거래일 {_pct(obs['previous_return'])}")
        if number(obs.get("return_5d")) is not None:
            details.append(f"5D {_pct(obs['return_5d'])}")
        if obs.get("down_days") is not None:
            details.append(f"연속 하락 {obs['down_days']}거래일")
        if obs.get("up_days"):
            details.append(f"{obs['up_days']}거래일 연속 상승" + (f"(그 전 {obs['prior_down_days']}거래일 연속 하락)" if obs.get("prior_down_days") else ""))
        if details:
            lines.append(f"- 한국 다일 맥락({obs.get('date', '')}): {names[ticker]} " + " · ".join(details))
    live = context.get("intraday_prices", {})
    if mode == "closed":
        actuals = [f"{names[t]} {_pct(observations[t]['return'])} ({observations[t]['date']})"
                   for t in ("^KS11", "^KQ11") if observations.get(t, {}).get("date") == now.date().isoformat()
                   and number(observations[t].get("return")) is not None]
        if not actuals:
            lines.append("- 당일 종가 미수집. 직전 종가를 오늘 종가로 대체하지 않습니다.")
    elif mode == "intraday":
        actuals = [f"{names[t]} {_pct(live[t]['return'])} ({kst_time(live[t].get('as_of') or live[t].get('retrieved_at'))} 조회, 지연 가능)"
                   for t in ("^KS11", "^KQ11") if live.get(t, {}).get("date") == now.date().isoformat()
                   and number(live[t].get("return")) is not None]
        lines.append("- 개장 후 당일 등락: " + (" / ".join(actuals) or "미수집. 위 과거 종가 등락을 오늘의 움직임으로 해석하지 않습니다."))
    unused_news = [row for row in story_news if news_article_key(row) not in used_story_news]
    cause_row = next((row for row in unused_news if reported_cause(row, sessions)), None)
    cause = reported_cause(cause_row, sessions) if cause_row else ""
    releases = records(context.get("economic_releases"))
    selected = economic_story_lines(story_releases, limit=3)
    if selected:
        lines.extend("- " + line for line in selected)
        lines.append("지표 선정: 단위가 다른 지표를 비교하기 위해 이전치 대비 변화 비율 순, 지표별 1개(전월비 우선). 컨센서스 순위가 아닙니다.")
    elif not news:
        lines.append("- 공식 발표치와 출처 기준을 통과한 최근 시장 보도가 부족합니다.")
    if cause:
        lines.append("- 사실(보도 내용): " + cause)
        used_story_news.add(news_article_key(cause_row))
    elif unused_news:
        lines.append("- 제목 기준 보도(기사 주장): " + story_news_citation(unused_news[0]))
        used_story_news.add(news_article_key(unused_news[0]))
    elif not news:
        lines.append("- 미확인: 가격 움직임의 원인 자료가 없습니다. 확인되지 않은 원인을 채우지 않습니다.")
        missing.append("허용 출처 핵심 뉴스")
    kr_context = next((row for row in sorted(story_news, key=lambda row: not bool(re.search(r"전날|직전|거래일 만", row["title"]))) if news_article_key(row) not in used_story_news and row.get("market") == "KR" and
                       re.search(r"전날|직전|거래일 만|순매수 전환", row["title"])), None)
    if kr_context:
        lines.append("- 한국 맥락 보도(기사 주장): " + story_news_citation(kr_context))
        used_story_news.add(news_article_key(kr_context))
    lines.append("- 다음 체크: " + next_check(mode) + " · " + futures_line)
    lines.extend(["", "## 경제지표",
                  "해석은 발표치의 경제적 의미이며 오늘 등락의 원인 확정이나 매수 신호가 아닙니다. 실제 반응은 오른쪽 열과 별도로 비교합니다.", "",
                  "지표 | 발표치 | 예상/대체 비교 | 이전 | 해석(조건부) | 시장 반응(금리·달러·지수)", "--- | --- | --- | --- | --- | ---"])
    if not releases:
        missing.append("공식 경제지표 발표치·예상·이전")
        lines.append("CPI/PPI·고용·소매판매·FOMC·한국 수출/물가 | 미수집 | 미제공 | 미수집 | 발표치 미확인으로 해석 보류 | 이벤트 전후 동시점 자료 없음")
    release_notes = []
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
        if state == "stale":
            actual_text += f" · 수집 실패, 마지막 성공: {row.get('period', '')} ({kst_time(row.get('last_success_at'))})"
            missing.append(f"{indicator_names.get(row.get('indicator'), row.get('indicator'))}: {collection_status(row)} · 마지막 성공값 표시")
        elif state == "verified_snapshot":
            actual_text += f" · 수동 보완값: 공식 문서 확인({row.get('verified_at')}, 실시간 API 조회 아님, 만료 {row.get('expires_at', '미제공')})"
            missing.append(f"{indicator_names.get(row.get('indicator'), row.get('indicator'))}: API 최신값 미연결 · 공식 문서 확인값 보완")
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
            label += " · 발표 " + (release_at + " (시각 미제공)" if row.get("release_precision") == "date" else kst_time(release_at))
        if row.get("actual_minus_forecast") is not None:
            surprise = number(row["actual_minus_forecast"])
            actual_text += f" (예상대비 {surprise:+.2f}{' %p' if unit == '%' else ' ' + unit})"
        reaction = economic_reaction_text(row)
        if any(token in reaction for token in ("미수집", "미연결", "보류", "종가 없음")):
            missing.append(f"{label}: 시장 반응 비교 보류/일부 결측")
        label += f" {citation(row)}"
        if row.get("forecast_source"):
            forecast += " " + citation(dict(title=row["forecast_source"], source_url=row.get("forecast_source_url")))
            if row.get("forecast_verified_at"):
                forecast += " · 확인 " + text(row["forecast_verified_at"])
        if row.get("forecast") is None:
            metrics = comparison_metrics(row)
            forecast = "컨센서스 미연결"
            if row.get("indicator") == "US_FED_TARGET_UPPER":
                forecast = "예상치 비교 대상 아님(일별 목표금리 상단)"
            if metrics["delta"] is not None:
                forecast += f" · 이전 대비 {metrics['delta']:+.2f}" + ("%p" if unit == "%" else unit)
            if metrics["prior3_mean"] is not None:
                forecast += f" · 직전 3개월 평균 {metrics['prior3_mean']:.2f}{unit}"
        checked = outlier_check(row)
        if checked["flag"]:
            actual_text += " · " + checked["status"]
        if row.get("verification"):
            actual_text += " · " + row["verification"]
        lines.append(" | ".join(_cell(v) for v in (label, actual_text, forecast, previous, economic_reading_with_reaction(row), reaction)))
        if actual is None and state not in {"scheduled", "pending", "예정"}:
            configured = row.get("api_key_configured")
            reason = collection_status(row) + (" · 키 감지됨" if configured is True else " · 키 미감지" if configured is False else "")
            missing.append(indicator_names.get(text(row.get("indicator")), text(row.get("indicator"))) + ": " + reason)
        if row.get("indicator") == "KR_EXPORTS" and number(row.get("raw_actual")) is not None:
            release_notes.append(f"수출 원자료 검산: {row.get('period')} {row['raw_actual']:,.1f} / {row.get('raw_year_ago_period')} {row.get('raw_year_ago')} {row.get('raw_unit', '')}; (당월/전년동월−1)×100. 위 출처의 수록월·수정치 기준이며 속보치와 별도입니다.")
        if row.get("indicator") == "US_RETAIL_SALES":
            meta = row.get("request_metadata") or {}
            allowed_params = {key: value for key, value in (meta.get("parameters") or {}).items()
                              if key in {"get", "time", "category_code", "data_type_code", "seasonally_adj", "error_data", "for"}}
            release_notes.append("소매판매 수집 진단: HTTP " + str(meta.get("http_status") or "응답 상태 미기록")
                                 + " · 응답 " + text(meta.get("response_status") or "미기록")
                                 + " · 발표 자료 " + text(row.get("publication_status") or "미확인")
                                 + " · 요청 " + str(allowed_params) + " · " + collection_status(row))
            if meta.get("response_summary") or meta.get("rejected_rows"):
                release_notes.append("소매판매 응답 점검(허용 항목만): " + str(meta.get("response_summary") or {})
                                     + " · 제외 사유별 행수 " + str(meta.get("rejected_rows") or {}))
        if row.get("indicator") == "KR_EXPORTS":
            meta = row.get("bulletin_request_metadata") or {}
            statuses = [f"{part}: {item.get('origin', '과거 진단 미저장')} · "
                        + (f"HTTP {item['http_status']}" if item.get('http_status') else
                           "요청 시도·HTTP 응답 없음" if item.get('attempted') else "이번 HTTP 요청 안 함")
                        + (f" · {item['exception_type']}" if item.get('exception_type') else "")
                        + (f" · 실패단계 {item['failure_stage']}" if item.get('failure_stage') else "")
                        for part, item in meta.items() if isinstance(item, dict)]
            release_notes.append("한국 수출 자동 수집: " + (" / ".join(statuses) or "이번 응답 진단 미기록")
                                 + " · " + collection_status(row)
                                 + (" · 마지막 자동 성공값 표시" if row.get("last_success_at") else ""))
    if release_notes:
        lines.extend(["", *release_notes])
    consensus_status = context.get("consensus_diagnostics") or {}
    if consensus_status:
        lines.extend(["", f"컨센서스 연결: {consensus_status.get('attached_count', 0)}개 · "
                      + text(consensus_status.get("verified_survey_coverage")),
                      "예상치는 설문 출처별로 다를 수 있습니다. 기사 확인값은 해당 대상월·발표일에만 연결하며 다음 달로 넘겨 쓰지 않습니다."])
        if consensus_status.get("reason") == "api_key_required":
            lines.append("향후 자동 컨센서스 API: 키 미설정 · [경제지표용 설정 안내](https://docs.tradingeconomics.com/get_started/). 확인된 발표 당시 설문과 별도입니다.")
    if releases:
        lines.append("\n지표는 최신 수정치 기준입니다. 전월비·전년비/계절조정 기준이 다른 수치는 서로 비교하지 않습니다. 발표일 미제공은 관측월로 대체하지 않습니다.")
    exports = [row for row in releases if row.get("indicator") == "KR_EXPORTS" and row.get("basis") == "YoY"
               and row.get("unit") == "%" and number(row.get("actual")) is not None
               and row.get("status") in {"released", "verified_snapshot"} and text(row.get("period"))
               and text(row["period"]) < now.strftime("%Y-%m")
               and (not row.get("release_at") or (stamp(row["release_at"]) and stamp(row["release_at"]) <= now))]
    if exports and kr_close.get("date") == kr and number(kr_close.get("return_5d")) is not None:
        export = max(exports, key=lambda row: text(row["period"]))
        lines.extend(["", "월간 실물·단기 가격 비교 | 관측 | 기준", "--- | --- | ---",
                      "한국 수출 | " + _cell(f"전년비 {float(export['actual']):+.1f}%" + (" (수동 보완값)" if export.get("status") == "verified_snapshot" else ""))
                      + " | " + _cell(f"관측월 {export['period']} · 발표 {export.get('release_at') or '발표일 미연결'} · {citation(export)}"),
                      f"코스피 | 5D {_pct(kr_close['return_5d'])} | {_cell(kr)} 확정 종가 기준",
                      "",
                      "관측월·비교 기간이 달라 월간 수출 증가와 단기 주가 하락은 함께 나타날 수 있습니다. 수출만으로 당일 가격·수급 원인을 확정하지 않습니다."])
    lines.extend(["", "## 업종별 왜"])
    theme_news = curate_news(news, now=now, limit=60, session_scoped=True)
    sectors = []
    # Prefer session-aligned base sectors; never include a leveraged sector proxy.
    aligned_flow = records(context.get("closed_flow_rows", flow_rows))
    flow_by_ticker = {text(first(r, "Ticker", "티커")): r for r in aligned_flow
                      if text(first(r, "기준일", "date", "as_of"))}
    sector_inputs = []
    for row in records(context.get("sector_rows")):
        prior = flow_by_ticker.get(text(first(row, "Ticker", "티커")), {})
        if text(first(prior, "기준일", "date", "as_of")) != text(first(row, "기준일", "date", "as_of")):
            prior = {}
        sector_inputs.append(dict(prior, **row))
    sector_inputs += aligned_flow
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
    picks += [pair for pair in sectors if text(first(pair[1], "Ticker", "티커")) in {"XLK", "XLC", "XLE", "XLU", "SOXX", "IGV", "396500.KS"}]
    picks += sorted((pair for pair in sectors if abs(pair[0]) >= .05 and any(token in text(pair[1].get("구분")) for token in ("한국", "국내"))), key=lambda pair: abs(pair[0]), reverse=True)[:2]
    seen = set()
    seen_sector_exposures = set()
    lines.append("미확인: 공통 한계로 기사 내용은 보도 주장입니다. 업종 등락의 개별 원인·기여도는 확정하지 않습니다.")
    lines.append("보고용 구분 기준: 시장 대비 초과수익 = 업종 일간 − 동일 시장·동일 종가일 지수 일간(KR ^KS11 / US ^GSPC). 절대 초과폭 1.00%p 미만은 시장 공통 맥락, 이상은 직접 업종 기사를 별도 확인합니다. 매매 임계값은 변경하지 않습니다.")
    lines.append("[3M 중기] 상태는 당일 방향과 별도입니다. 상태 분류에는 3M·6M·가속도·가격위치를 함께 쓰므로 3M·가속도가 비슷해도 상태는 다를 수 있습니다. 신생 ETF는 실제 관측 이력과 비교 구간을 별도 확인해야 합니다.")
    lines.extend(["", "업종 | 일간 실제·기준일 | 장중(참고·미확정) | 3M 중기·직전 3M 대비 가속도 | 시장 대비 초과수익 | 해석(추정)", "--- | --- | --- | --- | --- | ---"])
    for value, row in picks:
        ticker = text(first(row, "Ticker", "티커"))
        exposure = "US_SEMICONDUCTORS" if ticker in {"SOXX", "SMH"} else ticker
        if ticker in seen or exposure in seen_sector_exposures:
            continue
        seen.add(ticker)
        seen_sector_exposures.add(exposure)
        from stock_lab_core.report_presentation import sector_display_name
        label = sector_display_name(row)
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        linked = sector_related_news(ticker, text(first(row, "기준일", "date", "as_of")), theme_news, sector_name=label)
        evidence = sector_evidence(row, context.get("macro_data", {}), [dict(item, ticker=ticker) for item in linked], observations=observations)
        reading = evidence["reading"].replace("해석(추정): 직접 원인 자료 미연결", "해석(추정): 원인 기사 미연결")
        live_obs = live.get(ticker, {})
        checked = max(now, stamp(context.get("quote_checked_at")) or now)
        live_cell = (_pct(live_obs["return"]) + " · " + kst_time(live_obs["as_of"])
                     if valid_live_observation(live_obs, region, checked, states=states) else
                     extended_quote_text(context, ticker, checked) if region == "US" and states["US"]["phase"] != "intraday" else "")
        if not live_cell:
            live_cell = ("장중 시세 미수집" if states[region]["phase"] == "intraday" else
                         "데이마켓·시간외 시세 미확보" if region == "US" and us_extended_session(checked) else "정규장 외 · 종가 참조")
        lines.append(" | ".join(_cell(v) for v in (f"{label}({ticker})", evidence["daily"], live_cell, evidence["medium"], evidence["excess"], reading)))
    if not seen:
        lines.append("- 당일 업종 등락 자료 미수집. 3개월 순위를 당일 상승/하락으로 대체하지 않습니다.")
    holding_start = len(lines)
    holdings_header = ("종목 | 최신 종가 일간(실제·기준일) | 실제 누적 vs 기초자산 누적 / 일간 참고 | 상태/사유"
                       if mode == "closed" else "종목 | 기준일 일간(확정 종가) | 실제 누적 vs 기초자산 누적 / 일간 참고 | 당일 현재(장중·미확정) | 상태/사유"
                       if mode == "intraday" else "종목 | 기준일 일간(실제) | 개장 전 갭 시나리오/배수 참고(추정) | 당일 현재(실제) | 상태/사유")
    account_lines = account_overview_lines(live_metrics, portfolio, sessions, mode, latest_metrics=latest_metrics)
    from stock_lab_core.report_fx import portfolio_fx_lines
    account_lines.extend(portfolio_fx_lines(held, context, states, max(now, stamp(context.get("quote_checked_at")) or now)))
    lines.extend(["", "## 내 보유 종목 영향", *account_lines,
                  "재현 기준: 통합행은 현재비중(%) × 위에서 정의한 종목별 누적 수익률(%) ÷ 100입니다. 아래 종가 일간·시나리오 표는 별도 참고이며 통합행에 다시 합산하지 않습니다.",
                  "", holdings_header, "--- | --- | --- | ---" if mode == "closed" else "--- | --- | --- | --- | ---"])
    held = [row for row in records(summary_rows) if is_held(row)]
    for row in held:
        ticker = text(first(row, "티커", "ticker"))
        obs = observations.get(ticker, {})
        value = obs.get("return")
        estimate = "해당없음"
        reasons = holding_reasons(row)
        estimate, leveraged = holding_estimate(row, observations, sessions, now, intraday_prices=live)
        if estimate != "해당없음":
            estimate = "일간 참고(누적 비교 아님): " + estimate
        if mode == "closed" or (mode == "intraday" and ticker.split(".")[0] in {"379800", "379810", "418660"}):
            estimate = completed_scenario_comparison(row, observations, sessions,
                                                     max(now, stamp(context.get("quote_checked_at")) or now) if mode == "intraday" else now,
                                                     price_frames=context.get("price_frames"),
                                                     intraday_prices=live if mode == "intraday" else None,
                                                     scenario_frames=context.get("scenario_frames")) or estimate
            if ticker.split(".")[0] not in {"379800", "379810", "418660"}:
                estimate += scenario_observation_line(row, scenario_context)
        elif ticker == "0167A0.KS":
            semi = live.get("SOXX") or observations.get("SOXX", {})
            if number(semi.get("return")) is not None:
                kind = "장중 진행·확정 아님" if live.get("SOXX") else "확정 종가 참고(과거 영향 재계상 안 함)"
                estimate = f"미국 반도체 SOXX {_pct(semi['return'])} · {semi.get('date', '미확인')} {kind} · 구성·환율 차이로 이 한국 ETF의 갭 수치 산출 안 함"
        if ticker.split(".")[0] in {"379800", "379810", "418660"}:
            estimate = compact_holding_reference(estimate)
            hedge = hedge_policy_line(row)
            if hedge and hedge not in estimate:
                estimate += " · " + hedge
        current = live.get(ticker, {})
        actual_now = "해당없음"
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        if states[region]["phase"] == "intraday":
            actual_now = (_pct(current["return"]) + f" ({current['date']} 장중 진행·확정 아님; {kst_time(current.get('as_of', current.get('retrieved_at')))})"
                          if current.get("date") == states[region]["active_date"] and number(current.get("return")) is not None else "시각 확인 가능한 시세 미수집")
        elif region == "US":
            extended = context.get("extended_prices", {}).get(ticker, {})
            actual_now = (extended_quote_text(context, ticker, max(now, stamp(context.get("quote_checked_at")) or now))
                          or "정규장 외 · 데이마켓/시간외 시세 미연결: " + context.get("extended_quote_status", {}).get(ticker, "제공처 응답·시각 미확인"))
            if mode == "closed" and (extended or context.get("extended_reference_prices", {}).get(ticker)):
                reasons.append("별도 세션 " + actual_now)
        if leveraged:
            reasons = [reason for reason in reasons if reason != "개별 위험사유 없음"]
            if "레버리지 보유" not in reasons:
                reasons.append("레버리지 보유")
        weight = number(first(row, "현재비중", "current_w"))
        if weight is not None and 0 <= weight <= 100:
            reasons.append(f"현재비중 {weight:.2f}%")
            if number(value) is not None and obs.get("date") == sessions.get(region) and not portfolio.get("error"):
                reasons.append(f"일간 기여 {round(weight * number(value), 2) or 0.0:+.2f}%p(내부 추정)")
            else:
                reasons.append("일간 기여 미확인")
        else:
            reasons.append("현재비중·일간 기여 미연결")
        close_cell = _pct(value) + (f" ({obs['date']} 확정 종가)" if obs.get("date") else "")
        if obs.get("stale"):
            close_cell = "최신 종가 미수집 · 과거 참고 " + close_cell
        cells = [f"{text(first(row, '종목명', 'name'))}({ticker})", close_cell, estimate]
        if mode != "closed":
            cells.append(actual_now)
        lines.append(" | ".join(_cell(v) for v in [*cells, ", ".join(reasons)]))
        if value is None:
            missing.append(ticker + " 보유 일간 종가등락")
    if not held:
        cells = ["보유목록 미연결", "미수집", "해당없음"]
        if mode != "closed":
            cells.append("미수집")
        lines.append(" | ".join([*cells, "보유 여부를 추정하지 않음"]))
        missing.append("보유목록")
    if any(text(first(row, "티커", "ticker")).split(".")[0] in {"379800", "379810", "418660"} for row in held):
        lines.extend(["", "보유표 공통 각주(379800/379810/418660)",
                      "- 비교 기준: 직전 한국 종가 15:30→당일 종가 15:30 또는 한국 ETF·선물의 같은 시각 완료 5분봉. 동일 끝값이 없으면 비교를 보류합니다.",
                      "- 원/달러는 같은 구간 관측을 별도로 표시합니다. 단순 차이는 환율·보수·베이시스를 조정한 추적오차가 아니며 레버리지의 배수 잔차는 산출하지 않습니다.",
                      "- 아래 미국 종가 이후 선물 관측은 별도 참고 구간입니다. 위 차이에 더하지 않습니다. 같은 시각 NAV/iNAV 미연결로 괴리율은 미확인입니다."])
        for codes, label in (({"379810", "418660"}, "나스닥 ETF 379810/418660 공유(NQ=F)"),
                             ({"379800"}, "S&P500 ETF 379800(ES=F)")):
            group = next((row for row in held if text(first(row, "티커", "ticker")).split(".")[0] in codes), None)
            if group is not None:
                observation = compact_holding_reference(scenario_observation_line(group, scenario_context))
                lines.append("- " + label + " 잔차 설명참고: 누적 비교 잔차와 별개인 장중 선물/환율 관측구간이며 인과분해·기여도 합산 아님" + observation)
        lines.extend(hedge_source_lines(held))
    holding_end = len(lines)
    watches = [row for row in records(summary_rows) if not is_held(row)]
    watches.sort(key=lambda row: (number(first(row, "Adj점수", "adj")) or 0), reverse=True)
    lines.extend(["", "## 관심 후보 상위 3개"])
    lines.append("선정 기준: 오늘점검 미보유 목록의 Adj점수 상위 3개. 개별 신호 품질과 시장·종목 실행 게이트는 분리 표시하며 매수 허용 목록이 아닙니다.")
    lines.append("S/A 등급과 추세훼손 보류는 함께 표시될 수 있습니다. 품질 등급이 시장·추세·가격·비중 게이트를 해제하지 않습니다. 수치 해제 조건·진입가·손절·목표·제안비중이 입력에 없으면 이 보고서에서 생성하지 않습니다.")
    if watches:
        lines.extend(["", "후보·개별 신호·실행 상태 | 게이트 근거 | 해제 조건", "--- | --- | ---"])
    for row in watches[:3]:
        lines.append(" | ".join(_cell(value) for value in candidate_fields(row)))
    if not watches:
        lines.append("- 관심 후보 미연결/없음")
    lines.extend(["", "## 다가오는 일정"])
    lines.append("기업 실적 일정은 연결·확인된 IR 공지만 포함합니다. 전체 보유·관심종목의 일정이 아니므로 목록에 없다고 미발표/일정 없음으로 판단하지 않습니다.")
    scheduled = []
    calendar_rows = records(context.get("calendar_events", event_rows))
    next_monthly = {}
    for row in calendar_rows:
        indicator = row.get("indicator")
        day = text(row.get("date"))
        if indicator in {"US_CPI", "US_PPI", "US_NONFARM_PAYROLLS"} and day >= now.date().isoformat():
            if indicator not in next_monthly or day < next_monthly[indicator]:
                next_monthly[indicator] = day
    for row in calendar_rows:
        date_text = text(first(row, "date", "날짜", "일자", "시작일", "발표일"))
        if row.get("event_status"):
            continue
        dt = stamp(date_text)
        title = text(first(row, "이벤트", "event", "title"))
        is_next_monthly = next_monthly.get(row.get("indicator")) == date_text
        horizon = 90 if is_next_monthly else 45 if "FOMC" in title.upper() else 7
        if dt and text(first(row, "source", "출처")) != "fallback" and now.date() <= dt.date() <= (now + timedelta(days=horizon)).date():
            scheduled.append((date_text, row))
    if scheduled:
        lines.extend(["일정·남은 일수 | 발표·콜 시각 | 공식 출처", "--- | --- | ---"])
    for date_text, row in sorted(scheduled, key=lambda item: item[0]):
        title = text(first(row, '이벤트', 'event', 'title'))
        source = text(first(row, '출처', 'source')) or '출처 미제공'
        link = safe_link(row.get("source_url"))
        days = (stamp(date_text).date() - now.date()).days
        release_at = text(row.get("release_at")) or date_text
        display = kst_time(release_at) if "T" in release_at or " " in release_at else date_text + " (발표 시각 미제공)"
        if row.get("indicator") == "US_FED_RATE_DECISION" and len(release_at) == 10:
            # Regular FOMC statement convention; not an individually confirmed timestamp.
            standard = datetime.fromisoformat(release_at + "T14:00:00").replace(tzinfo=ZoneInfo("America/New_York"))
            display = kst_time(standard.isoformat()) + " (미국 14:00 ET 표준 적용, 예외 시각 미확인)"
            days = (standard.astimezone(KST).date() - now.date()).days
        if row.get("session_timing") == "after_market_close":
            local_close = datetime.fromisoformat(date_text + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(KST)
            display = f"미국 {date_text} 장 마감 후 / 한국 {local_close:%Y-%m-%d} 새벽(발표 분 시각 미확정)"
            days = (local_close.date() - now.date()).days
            if row.get("conference_call_at"):
                display += " · 실적 콜 " + kst_time(row["conference_call_at"])
        if row.get("release_precision") == "schedule_rule":
            display += " (BLS 표준 08:30 ET 적용, 예외 시각 미확인)"
        lines.append(" | ".join(_cell(value) for value in (f"{title} · D-{days}", display, f"[{source}]({link})" if link else source)))
    if not scheduled:
        sources = records(context.get("calendar_sources"))
        connected = [row["name"] for row in sources if row.get("status") == "connected"]
        lines.append("- 연결된 일정 범위에서 향후 7일 항목 미수집(일정 없음으로 단정하지 않음): " + ", ".join(connected) if connected else "- 일정 미연결: 공식 캘린더 수집 실패/자료 미제공. 일정 없음으로 판단하지 않습니다.")
        if not connected:
            missing.append("향후 7일 확정 일정 미연결")
    failed_bls = []
    for source in records(context.get("calendar_sources")):
        if source.get("status") == "connected" and source.get("provider") == "FRED":
            continue
        elif source.get("status") != "connected":
            if text(source.get("name")).startswith("BLS "):
                failed_bls.append(source["name"])
                continue
            lines.append(f"- 일정 미연결: {source['name']} · {source.get('reason', '응답 없음')}")
            missing.append(f"공식 일정: {source['name']} · {source.get('reason', '응답 없음')}")
            if source.get("fallback_reason"):
                lines.append(f"- FRED 일정 보완 실패: {source['name']} · {source['fallback_reason']}")
    if failed_bls:
        note = "미국 CPI·PPI·고용 중 일부 다음 확정 발표일 미연결: 공식 캘린더/FRED 보완 미확보(일정 없음이 아님)"
        lines.append("- " + note)
        missing.append(note)
    from stock_lab_core.report_calendar import earnings_calendar_lines
    lines.extend(earnings_calendar_lines(context, now))
    additional_news = [row for row in news if news_article_key(row) not in used_story_news]
    lines.extend(["", "## 추가 핵심 뉴스"])
    lines.append("당일 한국 장전·장중 기사 우선, 이전 마감 회고는 별도 맥락입니다." if mode == "intraday" else
                 "기준 거래일 마감시황 우선. 이전 거래일의 마감 회고는 제외하며, 마감 후 회고는 사후보도로 표시합니다.")
    lines.append("뉴스 분류: ‘추가 핵심 뉴스’는 기준 세션 기사·마감 후 회고, ‘다음 세션 재료’는 별도 분류된 후속 기사입니다. 다음 세션 재료가 비어 있어도 마감 후 회고는 있을 수 있습니다.")
    article_count = sum(row.get("duplicate_count", 1) for row in news)
    lines.append(f"출처·중복 제거 기준 통과 기사 {article_count}건 · 표시 단위 {len(news)}개(같은 사건 묶음 포함). 스토리에서 다룬 {len(news) - len(additional_news)}개는 재출력하지 않습니다. 추가 {min(len(additional_news), 5)}개 표시.")
    if additional_news:
        lines.extend(["", "분류·보도 시각 | 기사·출처 | 제목 해석·한계", "--- | --- | ---"])
    for index, row in enumerate(additional_news[:5], 1):
        timing = " · 마감 후 회고(인과 확정 아님)" if row.get("retrospective_close_wrap") else ""
        timing_label = row.get("news_timing")
        if is_preopen_price_recap(row):
            timing_label = "개장 전 가격회고·대상 거래일 미확정"
        if row.get("kr_news_timing") and row.get("news_timing_market") != "KR":
            timing_label = f"한국 {row['kr_news_timing']} / {row.get('news_timing_market', '원시장')} {timing_label}"
        category = row["category"]
        if category in {"장중 시황", "마감 시황", "장전 시황"}:
            category = "시장 시황"
        labels = list(dict.fromkeys(label for label in (timing_label, category) if label))
        reading = "제목 기준·세부 내용 미확인" if row["reading_ko"].startswith("제목 기준:") else row["reading_ko"]
        if row.get("duplicate_count", 1) > 1:
            reading += f" · 같은 시장·거래일 마감 등락 보도 {row['duplicate_count']}건 묶음"
            reading += " · 함께 묶인 제목: " + " / ".join(citation(item) for item in row.get("related_articles", []))
        lines.append(" | ".join(_cell(value) for value in (
            f"뉴스 {index} · {' · '.join(labels)} · {kst_time(row['published'])}{timing}",
            row["title"] + " " + citation(dict(row, title="원문")), reading)))
    if not news:
        lines.append("허용 출처·중복 제거 기준을 통과한 뉴스 없음.")
    elif not additional_news:
        lines.append("추가 기사 없음. 채택 기사는 위 스토리에 모두 표시했습니다.")
    lines.extend(["", "가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다."])
    # Move the single holdings section, without duplicating it in the story.
    lines = lines[:story_start] + lines[holding_start:holding_end] + lines[story_start:holding_start] + lines[holding_end:]
    calendar_start = lines.index("## 다가오는 일정")
    calendar_end = lines.index("## 추가 핵심 뉴스", calendar_start)
    calendar_block = lines[calendar_start:calendar_end]
    del lines[calendar_start:calendar_end]
    holding_at = lines.index("## 내 보유 종목 영향")
    lines[holding_at:holding_at] = calendar_block
    lines.extend(history_lines)
    from stock_lab_core.report_observation_panel import observation_report_lines
    lines.extend(observation_report_lines(context, summary_rows, news, now))
    return lines, list(dict.fromkeys(missing))
