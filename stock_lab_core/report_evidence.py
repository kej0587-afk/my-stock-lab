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
        (r"\bAI.{0,15}(?:stocks|shares)", "미국 AI 관련주"),
        (r"\bchip stocks|semiconductor", "반도체주"),
        (r"\bnvidia\b", "엔비디아"), (r"\bboj\b|bank of japan", "일본은행"),
        (r"\bfed\b|fomc", "미국 연준"), (r"\bppi\b", "미국 생산자물가"),
        (r"\bcpi\b", "미국 소비자물가"), (r"ethereum|\beth\b", "이더리움"),
        (r"bitcoin|\bbtc\b", "비트코인"), (r"oil|\bwti\b|brent", "원유"),
        (r"middle east|ceasefire", "중동 휴전 협상"),
    )
    subject = next((label for pattern, label in subjects if re.search(pattern, lower)), row["category"])
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
    return f"제목 단서 해석: {subject} {action}. 세부 내용·가격 영향은 미확인"


def curate_news(rows, *, now=None, limit=5, session_scoped=False):
    now = now or datetime.now(KST)
    now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    accepted, seen, seen_links = [], set(), set()
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
        seen_key = (text(raw.get("market")), text(raw.get("session_date")), key) if session_scoped else key
        if seen_key in seen or (link and link in seen_links):
            continue
        seen.add(seen_key)
        if link:
            seen_links.add(link)
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


def story_news_citation(row):
    timing = text(row.get("news_timing"))
    if row.get("kr_news_timing") and row.get("news_timing_market") != "KR":
        timing = f"한국 {row['kr_news_timing']} / {row.get('news_timing_market', '원시장')} {timing}"
    published = stamp(first(row, "published", "published_at"))
    parts = ([f"[{timing}]"] if timing else []) + [citation(row)]
    if published:
        parts.append(published.astimezone(KST).strftime("%m/%d %H:%M KST"))
    return " ".join(parts)


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
    valid = previous_date == current_date if same_session else previous_date < current_date
    if not previous_date or not current_date or not valid:
        return ["전일 비교 없음: 이전 거래일의 저장된 점검이 없습니다."]
    old = {text(first(row, "티커", "ticker")): row for row in records(previous) if text(first(row, "티커", "ticker"))}
    current_rows = records(current)
    keys = {text(first(row, "티커", "ticker")) for row in current_rows if text(first(row, "티커", "ticker"))}
    changes = {"held": [], "watch": []}
    compared = {"held": 0, "watch": 0}
    def label(row, fallback=None):
        ticker = text(first(row, "티커", "ticker"))
        name = text(first(row, "종목명", "name", "자산명")) or text(first(fallback or {}, "종목명", "name", "자산명"))
        return f"{name}({ticker})" if name and name != ticker else f"{ticker}(종목명 미저장)"

    def reasons(row):
        value = row.get("저장사유", holding_reasons(row))
        return sorted(text(item) for item in value) if isinstance(value, (list, tuple)) else [text(value)]
    for row in current_rows:
        ticker = text(first(row, "티커", "ticker"))
        if ticker not in old:
            continue
        before = text(first(old[ticker], "최종읽기", "🔥기술적 타점", "판정코드"))
        after = text(first(row, "최종읽기", "🔥기술적 타점", "판정코드"))
        if not before or not after:
            continue
        group = "held" if is_held(row) else "watch"
        compared[group] += 1
        old_reasons = reasons(old[ticker])
        new_reasons = reasons(row)
        old_gate = text(first(old[ticker], "게이트상태", "gate_state"))
        new_gate = text(first(row, "게이트상태", "gate_state"))
        if (before, old_reasons, old_gate) != (after, new_reasons, new_gate):
            changes[group].append(f"{label(row, old[ticker])}: {before} / {', '.join(old_reasons)} → {after} / {', '.join(new_reasons)}" +
                           (f" (게이트 {old_gate or '미제공'} → {new_gate or '미제공'})" if old_gate != new_gate else ""))
    prefix = f"같은 거래일 직전 생성({previous_run_at or '시각 미확보'})" if same_session else f"이전 점검({previous_date})"
    details = [prefix + " 대비:"]
    for group, heading in (("held", "보유"), ("watch", "관심·미보유")):
        total = sum(is_held(row) == (group == "held") for row in current_rows)
        change = changes[group]
        status = f"변경 {len(change)}개" if change else "변경 없음" if compared[group] else "비교 가능한 공통 종목 판정 없음"
        details.append(f"- {heading} {total}개: {status} · 비교 {compared[group]}개 / 미비교 {total - compared[group]}개")
        details.extend("  " + item for item in change[:10])
        if len(change) > 10:
            details.append(f"  나머지 변경 {len(change) - 10}개는 검토용 CSV 확인")
    if not any(changes.values()) and any(compared.values()):
        details.append("- 공통 종목 판정 변경 없음")
    current_map = {text(first(row, "티커", "ticker")): row for row in current_rows}
    if keys - old.keys():
        added = sorted(keys - old.keys())
        details.append(f"- 점검 입력 목록 추가 {len(added)}개: " + ", ".join(label(current_map[t]) for t in added))
    if old.keys() - keys:
        removed = sorted(old.keys() - keys)
        details.append(f"- 점검 입력 목록 이탈 {len(removed)}개: " + ", ".join(label(old[t]) for t in removed)
                       + " · 보고서 상위 10개 변화가 아닌 입력 목록 차이이며 관심등록 삭제 여부는 미확인")
    return details


def news_article_key(row):
    return safe_link(first(row, "link", "url")) or re.sub(r"\W+", "", text(row.get("title"))).casefold()


def participant_news_rows(news, session_date):
    """Keep distinct participant stories; do not infer net flows from titles."""
    selected, seen_titles, seen_links = [], set(), set()
    for row in news:
        title = text(row.get("title"))
        if row.get("market") != "KR" or row.get("session_date") != session_date:
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
    return [f"- 수급 주체 보도 {len(selected)}건(제목 기준·기사 주장, 순매수액 미검증): "
            + " / ".join(story_news_citation(row) for row in selected[:limit])
            + (f" · 나머지 {len(selected) - limit}건 생략" if len(selected) > limit else "")]


def _pct(value):
    return "미수집" if value is None else f"{value * 100:+.2f}%"


def _cell(value):
    return text(value).replace("|", "/").replace("\n", " ") or "미제공"


def report_sections(*, context, news, flow_rows, event_rows, summary_rows, now):
    """Return report front matter and explicit missing-data reasons."""
    context = context or {}
    from stock_lab_core.report_analysis import comparison_metrics, economic_story_lines, outlier_check, sector_evidence
    from stock_lab_core.report_holdings import holding_estimate, completed_scenario_comparison
    from stock_lab_core.report_presentation import account_estimate, account_metrics, account_headline, account_live_estimate, candidate_line, kst_time, sector_related_news, korean_market_catalysts
    from stock_lab_core.report_session import report_mode, market_session_states, kst_now, MODE_LABELS, next_check
    from stock_lab_core.economic_cache import collection_status
    from stock_lab_core.report_scenario import latest_futures_line, scenario_observation_line
    observations = context.get("prices", {})
    sessions = context.get("sessions", {})
    now = kst_now(now)
    states = context.get("market_states") or market_session_states(now, sessions)
    mode = report_mode(now, is_trading_day=context.get("kr_is_trading_day"))
    missing = list(context.get("missing", []))
    lines = ["## 기준일", f"생성 {now:%Y-%m-%d %H:%M} KST"]
    lines.append(f"- 보고서 모드: {states['KR']['label']} · 한국 정규장 시간대 기준, 특별 휴장·거래시간 변경은 별도 확인")
    for market, name in (("KR", "한국"), ("US", "미국")):
        session = sessions.get(market, "")
        lines.append(f"- {name}: {session} 정규장 종가 기준" if session else f"- {name}: 종가 기준일 미수집(날짜를 추정하지 않음)")
        state = states[market]
        lines.append(f"  현재 상태: {state['label']} · 마지막 확정 종가 {session or '미수집'} · 진행 중 세션 {state.get('active_date') or '없음'} · {state['calendar_note']}")
        if not session:
            missing.append(f"{name} 종가 기준일")
    kr, us = sessions.get("KR"), sessions.get("US")
    lines.append("- 시차: 한국장은 같은 날짜 미국장보다 먼저 마감합니다. 한국 마감 후 미국 뉴스·가격은 다음 거래일 갭 리스크입니다.")
    if kr and us:
        lines.append(f"  비교하는 거래일: 한국 {kr} / 미국 {us}. 동시 거래 결과가 아닙니다.")
    lines.extend(["", "## 판정 이력 비교"])
    lines.extend(comparison_lines(summary_rows, context.get("previous_summary"),
                                  previous_date=context.get("previous_date", ""),
                                  current_date=context.get("summary_date", "")))
    if context.get("previous_run_summary"):
        lines.extend(comparison_lines(summary_rows, context["previous_run_summary"],
                     previous_date=context.get("previous_run_date", ""),
                     current_date=context.get("summary_date", ""), same_session=True,
                     previous_run_at=context.get("previous_run_at", "")))
    elif not context.get("previous_summary"):
        lines.append("같은 거래일 직전 생성 이력도 없습니다. 매크로 변화와 종목 판정 비교는 별도 저장 자료를 사용합니다.")
    if context.get("history_status"):
        lines.append(context["history_status"] + ("" if context.get("history_durable") else " · 로컬 저장은 재배포 시 초기화될 수 있습니다."))
    index_rows = [(ticker, observations[ticker]) for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")
                  if observations.get(ticker, {}).get("return") is not None]
    names = {"^KS11": "코스피", "^KQ11": "코스닥", "^GSPC": "S&P500", "^IXIC": "나스닥", "^DJI": "다우"}
    conclusion = ", ".join(f"{names[t]} {_pct(row['return'])}({row.get('date', '미수집')} 확정 종가)" for t, row in index_rows) or "종가 자료 부족으로 시장 방향 결론을 보류합니다"
    us_returns = [row["return"] for ticker, row in index_rows if ticker in {"^GSPC", "^IXIC", "^DJI"}]
    kr_returns = [row["return"] for ticker, row in index_rows if ticker in {"^KS11", "^KQ11"}]
    headline = ("미국 주요지수 동반 하락" if len(us_returns) == 3 and max(us_returns) < 0 else
                "미국 주요지수 동반 상승" if len(us_returns) == 3 and min(us_returns) > 0 else "주요지수 혼조/자료 부족")
    if kr_returns and min(kr_returns) > 0 and us_returns and max(us_returns) < 0:
        headline += ", 앞서 마감한 한국 반등과 시차가 있어 한국장 반영을 별도로 확인"
    held = [row for row in records(summary_rows) if is_held(row)]
    portfolio = account_metrics(held, observations, sessions) if held else {}
    sector_facts = [f"{name} {_pct(observations[t]['return'])}({us} 확정 종가)" for t, name in (("SOXX", "미국 반도체"), ("IGV", "소프트웨어"))
                    if number(observations.get(t, {}).get("return")) is not None and observations[t].get("date") == us]
    if sector_facts:
        headline = " · ".join(sector_facts)
    live = context.get("intraday_prices", {})
    current_kr = live.get("^KS11", {})
    kr_close = observations.get("^KS11", {})
    headline_kr = {}
    if mode != "intraday" and kr_close.get("date") == kr and number(kr_close.get("return")) is not None:
        headline_kr = kr_close
        label = "당일" if kr == now.date().isoformat() else "최신 확정"
        headline += f" / 코스피 {label} 종가 {_pct(kr_close['return'])}({kr_close['date']})"
    elif mode == "intraday" and current_kr.get("date") == now.date().isoformat() and number(current_kr.get("return")) is not None:
        headline_kr = current_kr
        headline += f" / 코스피 당일 {_pct(current_kr['return'])}({kst_time(current_kr.get('retrieved_at'))} 조회)"
    else:
        headline += " / 한국 당일 반영 미확인(직전 종가와 구분)"
    kr_catalysts = korean_market_catalysts(news, headline_kr.get("date"))
    if kr_catalysts and number(headline_kr.get("return")) is not None and headline_kr["return"] < 0:
        headline += " · 배경 보도(제목 기준·기사 주장): " + kr_catalysts
    live_semis = [f"{t} {_pct(live[t]['return'])}" for t in ("SOXX", "SOXL", "RAM") if number(live.get(t, {}).get("return")) is not None]
    if states["US"]["phase"] == "intraday" and live_semis:
        headline += f" / 미국 {states['US']['active_date']} 장중(확정 아님): " + ", ".join(live_semis)
    if portfolio and not portfolio.get("error"):
        headline += " / " + account_headline(portfolio, sessions, mode)
    if states["US"]["phase"] == "intraday" and live_semis:
        headline = (account_headline(portfolio, sessions, mode) + " / " if portfolio else "")
        if number(kr_close.get("return")) is not None:
            headline += f"코스피 {_pct(kr_close['return'])}({kr_close.get('date', '미확인')} 확정 종가) / "
        headline += f"미국 {states['US']['active_date']} 장중(확정 아님): " + ", ".join(live_semis)
    lines.extend(["", "## 한 줄 결론", headline + ".", "", "## 오늘의 시장 스토리"])
    story_start = len(lines) - 2
    kr_summary = "기준일 지수 미연결"
    if number(kr_close.get("return")) is not None:
        period_label = "당일" if kr_close.get("date") == now.date().isoformat() else "직전"
        kr_summary = f"{period_label} 코스피 {_pct(kr_close['return'])}, 5D {_pct(kr_close.get('return_5d'))} ({kr_close.get('date', '미수집')} 확정 종가)"
    reversal = next((row for row in news if row.get("market") == "KR" and row.get("session_date") == kr
                     and re.search(r"반전|반등 성공|급락 출발", text(row.get("title")))), None)
    participant_rows = participant_news_rows(news, kr)
    used_story_news = {news_article_key(row) for row in participant_rows[:3]}
    if reversal and news_article_key(reversal) not in used_story_news:
        kr_summary += f" · 제목 기준(기사 주장): {story_news_citation(reversal)}"
        used_story_news.add(news_article_key(reversal))
    releases = records(context.get("economic_releases"))
    economic_summary = []
    for indicator, name in (("US_PPI", "미국 PPI"), ("KR_EXPORTS", "한국 수출")):
        row = next((r for r in releases if r.get("indicator") == indicator and r.get("basis") == ("MoM" if indicator == "US_PPI" else "YoY")
                    and number(r.get("actual")) is not None and r.get("status") not in {"pending", "stale"}), None)
        if row:
            delta = comparison_metrics(row)["delta"]
            economic_summary.append(f"{name} {row.get('period', '')} {'전월비' if indicator == 'US_PPI' else '전년비'} {row['actual']}%"
                                    + (f" · 이전 대비 {delta:+.2f}%p" if delta is not None else "")
                                    + (" (수동 보완값)" if row.get("status") == "verified_snapshot" else ""))
    lines.extend(["- 미국: " + (" · ".join(sector_facts) or "업종 종가 미연결"),
                  "- 한국: " + kr_summary,
                  "- 지표: " + (" / ".join(economic_summary) or "비교 가능한 주요 발표치 미연결")])
    lines.extend(participant_news_lines(news, kr))
    if states["US"]["phase"] == "intraday":
        live_items = [f"{names.get(t, t)} {_pct(live[t]['return'])} ({kst_time(live[t].get('as_of', live[t].get('retrieved_at')))})"
                      for t in ("^IXIC", "SOXX", "SOXL", "RAM") if number(live.get(t, {}).get("return")) is not None]
        lines.append(f"- 사실: 미국 {states['US']['active_date']} 장중 진행·확정 아님: " + (" / ".join(live_items) or "시각 확인 가능한 시세 미수집") + ". [근거: 정규장 5분봉·직전 확정 종가]")
        rebound = next((r for r in news if r.get("market") == "US" and r.get("session_date") == states["US"]["active_date"]
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
        actuals = [f"{names[t]} {_pct(live[t]['return'])} ({kst_time(live[t].get('retrieved_at'))} 조회, 지연 가능)"
                   for t in ("^KS11", "^KQ11") if live.get(t, {}).get("date") == now.date().isoformat()
                   and number(live[t].get("return")) is not None]
        lines.append("- 개장 후 당일 등락: " + (" / ".join(actuals) or "미수집. 위 과거 종가 등락을 오늘의 움직임으로 해석하지 않습니다."))
    unused_news = [row for row in news if news_article_key(row) not in used_story_news]
    cause_row = next((row for row in unused_news if reported_cause(row, sessions)), None)
    cause = reported_cause(cause_row, sessions) if cause_row else ""
    releases = records(context.get("economic_releases"))
    selected = economic_story_lines(releases, limit=3)
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
    kr_context = next((row for row in sorted(news, key=lambda row: not bool(re.search(r"전날|직전|거래일 만", row["title"]))) if news_article_key(row) not in used_story_news and row.get("market") == "KR" and
                       re.search(r"전날|직전|거래일 만|순매수 전환", row["title"])), None)
    if kr_context:
        lines.append("- 한국 맥락 보도(기사 주장): " + story_news_citation(kr_context))
        used_story_news.add(news_article_key(kr_context))
    lines.append("- 다음 체크: " + next_check(mode) + " · " + latest_futures_line(context.get("scenario_observations")))
    lines.extend(["", "## 경제지표", "지표 | 발표치 | 예상/대체 비교 | 이전 | 시장 반응(금리·달러·지수)", "--- | --- | --- | --- | ---"])
    if not releases:
        missing.append("공식 경제지표 발표치·예상·이전")
        lines.append("CPI/PPI·고용·소매판매·FOMC·한국 수출/물가 | 미수집 | 미제공 | 미수집 | 이벤트 전후 동시점 자료 없음")
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
        reaction = text(row.get("reaction")) if row.get("reaction_source") else "이벤트 전후 동시점 반응 미수집"
        if any(token in reaction for token in ("미수집", "미연결", "보류", "종가 없음")):
            missing.append(f"{label}: 시장 반응 비교 보류/일부 결측")
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
            configured = row.get("api_key_configured")
            reason = collection_status(row) + (" · 키 감지됨" if configured is True else " · 키 미감지" if configured is False else "")
            missing.append(indicator_names.get(text(row.get("indicator")), text(row.get("indicator"))) + ": " + reason)
        if row.get("indicator") == "KR_EXPORTS" and number(row.get("raw_actual")) is not None:
            release_notes.append(f"수출 원자료 검산: {row.get('period')} {row['raw_actual']:,.1f} / {row.get('raw_year_ago_period')} {row.get('raw_year_ago')} {row.get('raw_unit', '')}; (당월/전년동월−1)×100. 위 출처의 수록월·수정치 기준이며 속보치와 별도입니다.")
    if release_notes:
        lines.extend(["", *release_notes])
    if releases:
        lines.append("\n지표는 최신 수정치 기준입니다. 전월비·전년비/계절조정 기준이 다른 수치는 서로 비교하지 않습니다. 발표일 미제공은 관측월로 대체하지 않습니다.")
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
    lines.append("미확인(공통 한계): 기사 내용은 보도 주장입니다. 업종 등락의 개별 원인·기여도는 확정하지 않습니다.")
    lines.extend(["업종 | 사실 | 해석(추정) | 미확인", "--- | --- | --- | ---"])
    for value, row in picks:
        ticker = text(first(row, "Ticker", "티커"))
        exposure = "US_SEMICONDUCTORS" if ticker in {"SOXX", "SMH"} else ticker
        if ticker in seen or exposure in seen_sector_exposures:
            continue
        seen.add(ticker)
        seen_sector_exposures.add(exposure)
        label = text(row.get("섹터"))
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        linked = sector_related_news(ticker, text(first(row, "기준일", "date", "as_of")), theme_news, sector_name=label)
        evidence = sector_evidence(row, context.get("macro_data", {}), [dict(item, ticker=ticker) for item in linked])
        reading = evidence["reading"].replace("해석(추정): 직접 원인 자료 미연결", "해석(추정): 원인 기사 미연결")
        lines.append(" | ".join(_cell(v) for v in (f"{label}({ticker})", evidence["fact"], reading, evidence["unconfirmed"])))
    if not seen:
        lines.append("- 당일 업종 등락 자료 미수집. 3개월 순위를 당일 상승/하락으로 대체하지 않습니다.")
    holding_start = len(lines)
    holdings_header = ("종목 | 최신 종가 일간(실제·기준일) | 시나리오 vs 실제 종가 / 배수 참고 | 상태/사유"
                       if mode == "closed" else "종목 | 기준일 일간(실제) | 개장 전 갭 시나리오/배수 참고(추정) | 당일 현재(실제) | 상태/사유")
    live_account = account_live_estimate(held, live)
    lines.extend(["", "## 내 보유 종목 영향", account_estimate(held, observations, sessions, mode=mode) if held else "계좌 합계: 보유목록 미연결",
                  *([live_account] if live_account else []),
                  "", holdings_header, "--- | --- | --- | ---" if mode == "closed" else "--- | --- | --- | --- | ---"])
    held = [row for row in records(summary_rows) if is_held(row)]
    for row in held:
        ticker = text(first(row, "티커", "ticker"))
        obs = observations.get(ticker, {})
        value = obs.get("return")
        estimate = "해당없음"
        reasons = holding_reasons(row)
        estimate, leveraged = holding_estimate(row, observations, sessions, now, intraday_prices=live)
        if mode == "closed":
            estimate = completed_scenario_comparison(row, observations, sessions, now) or estimate
            estimate += scenario_observation_line(row, context.get("scenario_observations"))
        elif ticker == "0167A0.KS":
            semi = live.get("SOXX") or observations.get("SOXX", {})
            if number(semi.get("return")) is not None:
                kind = "장중 진행·확정 아님" if live.get("SOXX") else "확정 종가 참고(과거 영향 재계상 안 함)"
                estimate = f"미국 반도체 SOXX {_pct(semi['return'])} · {semi.get('date', '미확인')} {kind} · 구성·환율 차이로 이 한국 ETF의 갭 수치 산출 안 함"
        current = live.get(ticker, {})
        actual_now = "해당없음"
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        if states[region]["phase"] == "intraday":
            actual_now = (_pct(current["return"]) + f" ({current['date']} 장중 진행·확정 아님; {kst_time(current.get('as_of', current.get('retrieved_at')))})"
                          if current.get("date") == states[region]["active_date"] and number(current.get("return")) is not None else "시각 확인 가능한 시세 미수집")
        if leveraged:
            reasons = [reason for reason in reasons if reason != "개별 위험사유 없음"]
            if "레버리지 보유" not in reasons:
                reasons.append("레버리지 보유")
        cells = [f"{text(first(row, '종목명', 'name'))}({ticker})", _pct(value) + (f" ({obs['date']} 확정 종가)" if obs.get("date") else ""), estimate]
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
    holding_end = len(lines)
    watches = [row for row in records(summary_rows) if not is_held(row)]
    watches.sort(key=lambda row: (number(first(row, "Adj점수", "adj")) or 0), reverse=True)
    lines.extend(["", "## 관심 후보 상위 3개"])
    lines.append("선정 기준: 오늘점검 미보유 목록의 Adj점수 상위 3개. 개별 신호 품질과 시장·종목 실행 게이트는 분리 표시하며 매수 허용 목록이 아닙니다.")
    for row in watches[:3]:
        lines.append(candidate_line(row))
    if not watches:
        lines.append("- 관심 후보 미연결/없음")
    lines.extend(["", "## 다가오는 일정"])
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
        dt = stamp(date_text)
        title = text(first(row, "이벤트", "event", "title"))
        is_next_monthly = next_monthly.get(row.get("indicator")) == date_text
        horizon = 90 if is_next_monthly else 45 if "FOMC" in title.upper() else 7
        if dt and text(first(row, "source", "출처")) != "fallback" and now.date() <= dt.date() <= (now + timedelta(days=horizon)).date():
            scheduled.append((date_text, row))
    for date_text, row in sorted(scheduled, key=lambda item: item[0]):
        title = text(first(row, '이벤트', 'event', 'title'))
        source = text(first(row, '출처', 'source')) or '출처 미제공'
        link = safe_link(row.get("source_url"))
        days = (stamp(date_text).date() - now.date()).days
        release_at = text(row.get("release_at")) or date_text
        display = kst_time(release_at) if "T" in release_at or " " in release_at else date_text + " (발표 시각 미제공)"
        if row.get("session_timing") == "after_market_close":
            local_close = datetime.fromisoformat(date_text + "T16:00:00").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(KST)
            display = f"미국 {date_text} 장 마감 후 / 한국 {local_close:%Y-%m-%d} 새벽(발표 분 시각 미확정)"
            days = (local_close.date() - now.date()).days
            if row.get("conference_call_at"):
                display += " · 실적 콜 " + kst_time(row["conference_call_at"])
        if row.get("release_precision") == "schedule_rule":
            display += " (BLS 표준 08:30 ET 적용, 예외 시각 미확인)"
        lines.append(f"- {display}: {title} · D-{days} · " + (f"[{source}]({link})" if link else source))
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
    additional_news = [row for row in news if news_article_key(row) not in used_story_news]
    lines.extend(["", "## 추가 핵심 뉴스"])
    lines.append("기준 거래일 마감시황 우선. 이전 거래일의 마감 회고는 제외하며, 마감 후 회고는 사후보도로 표시합니다.")
    lines.append(f"출처·중복 제거 기준 통과 {len(news)}건 · 스토리에서 다룬 {len(news) - len(additional_news)}건은 재출력하지 않습니다. 추가 {min(len(additional_news), 5)}건 표시.")
    for index, row in enumerate(additional_news[:5], 1):
        timing = " · 마감 후 회고(인과 확정 아님)" if row.get("retrospective_close_wrap") else ""
        timing_label = row.get("news_timing")
        if row.get("kr_news_timing") and row.get("news_timing_market") != "KR":
            timing_label = f"한국 {row['kr_news_timing']} / {row.get('news_timing_market', '원시장')} {timing_label}"
        labels = list(dict.fromkeys(label for label in (timing_label, row["category"]) if label))
        lines.append(f"{index}. [{' · '.join(labels)}] {row['title']} · {kst_time(row['published'])}{timing} {citation(dict(row, title='원문'))}")
        if not row["reading_ko"].startswith("제목 기준:"):
            lines.append("   " + row["reading_ko"])
    if not news:
        lines.append("허용 출처·중복 제거 기준을 통과한 뉴스 없음.")
    elif not additional_news:
        lines.append("추가 기사 없음. 채택 기사는 위 스토리에 모두 표시했습니다.")
    lines.extend(["", "가격·거래량 흐름은 실제 자금 유입액이 아닙니다. 가속도는 최근 3개월 수익률과 직전 3개월 수익률 차이(%p), 다이버전스는 가격과 흐름 지표 방향이 엇갈리는 상태입니다."])
    # Move the single holdings section, without duplicating it in the story.
    lines = lines[:story_start] + lines[holding_start:holding_end] + lines[story_start:holding_start] + lines[holding_end:]
    return lines, list(dict.fromkeys(missing))
