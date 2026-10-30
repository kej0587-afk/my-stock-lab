"""Report-only matching of scheduled fiscal periods to released evidence.

Elapsed time is not proof of a release. Official results and attributed news
are separate confirmation levels; neither changes investment decisions.
"""

from copy import deepcopy
import re
from zoneinfo import ZoneInfo

from stock_lab_core.catalyst_news import extended_stock_reaction
from stock_lab_core.earnings_result_sources import is_official_result_url
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import curate_news, number, records, stamp

register_loaded_source(__name__, __file__)

METRIC_LABELS = {
    "revenue": "매출", "profit": "이익·EPS", "capex": "설비투자(CAPEX)",
    "free_cash_flow": "잉여현금흐름(FCF)", "guidance": "회사 전망", "price_reaction": "주가 반응",
}
_NAMES = {
    "GOOGL": r"\b(?:Alphabet|Google|GOOG|GOOGL)\b|알파벳|구글",
    "MSFT": r"\b(?:Microsoft|MSFT)\b|마이크로소프트",
    "META": r"\b(?:Meta|Facebook|META)\b|메타",
    "TSLA": r"\b(?:Tesla|TSLA)\b|테슬라",
    "NVDA": r"\b(?:Nvidia|NVDA)\b|엔비디아",
    "000660.KS": r"\bSK\s*hynix\b|SK하이닉스|에스케이하이닉스",
    "005930.KS": r"Samsung Electronics|삼성전자",
    "AMZN": r"\b(?:Amazon|AMZN)\b|아마존",
    "INTC": r"\b(?:Intel|INTC)\b|인텔",
    "SNDK": r"\b(?:Sandisk|SNDK)\b|샌디스크",
}
_PREVIEW = re.compile(r"\b(?:will|to report|preview|scheduled|expected to|ahead of|estimates? for|release date)\b|발표\s*예정|실적\s*전망|실적\s*앞두|예상\s*실적", re.I)
_RESULT = re.compile(r"\b(?:reports?|reported|announces?|announced).{0,65}(?:results|earnings|revenue)|\bearnings.{0,45}(?:beat|miss|top|results|metrics)|\bresults\b|실적\s*발표|매출.{0,35}(?:기록|발표)|영업이익.{0,35}(?:기록|발표)", re.I)
_QUARTERS = (r"first|1st|1", r"second|2nd|2", r"third|3rd|3", r"fourth|4th|4")


def _ticker(value):
    value = str(value or "").strip().upper()
    return {"GOOG": "GOOGL", "005930": "005930.KS", "005935.KS": "005930.KS", "000660": "000660.KS"}.get(value, value)


def _issuer_matches(title, ticker):
    # A multi-company headline cannot donate one issuer's financial result to another.
    matched = [symbol for symbol, pattern in _NAMES.items() if re.search(pattern, title, re.I)]
    return matched == [ticker]


def _period_matches(title, period):
    match = re.fullmatch(r"(?:FY)?(20\d{2})Q([1-4])", str(period))
    if not match:
        return False
    year, quarter = match.groups()
    years = re.findall(r"(?<!\d)(?:FY\s*)?(20\d{2})(?!\d)", title, re.I)
    if years and set(years) != {year}:
        return False
    found = set()
    for index, words in enumerate(_QUARTERS, 1):
        if re.search(rf"\bQ{index}\b|\b(?:{words})[- ]quarter\b|{index}\s*분기", title, re.I):
            found.add(str(index))
    return found == {quarter}


def _result_claim_matches(title, event):
    ticker = _ticker(event.get("ticker"))
    pattern = _NAMES.get(ticker)
    if not pattern:
        return False
    subject = (r"(?:" + pattern + r")(?:['’]s)?\s*(?:\([^)]{1,35}\))?\s+"
               r"(?:reports?|reported|announces?|announced|Q[1-4]\b|(?:first|second|third|fourth)[- ]quarter\b|(?:20\d{2}년?\s*)?[1-4]\s*분기)")
    for clause in re.split(r"[;!?]|,\s+(?=[A-Z])", title):
        match = re.search(subject, clause, re.I)
        if match:
            claim = clause[match.start():]
            if (_RESULT.search(claim) and not _PREVIEW.search(claim)
                    and _period_matches(claim, event.get("fiscal_period"))):
                return True
    return False


def _empty_metrics():
    return {key: {"status": "missing", "text": "미연결", "source_url": ""} for key in METRIC_LABELS}


def _event_day(event):
    return stamp(event.get("date"))


def _eligible_news(event, news, now):
    day = _event_day(event)
    if day is None:
        return []
    zone = ZoneInfo(event.get("timezone") or ("Asia/Seoul" if event.get("market") == "KR" else "America/New_York"))
    ticker = _ticker(event.get("ticker"))
    accepted = []
    for raw in news[:160]:
        title = str(raw.get("title") or "")
        published = stamp(raw.get("published_at") or raw.get("published"))
        if (not published or published > now or not 0 <= (published.astimezone(zone).date() - day.date()).days <= 3
                or raw.get("market") not in {None, "", event.get("market")}
                or not _issuer_matches(title, ticker)):
            continue
        # Validate independently so a category quota cannot hide a result release.
        accepted.extend(curate_news([raw], now=now, limit=1))
    return accepted


def _official_result(event, results, now):
    ticker = _ticker(event.get("ticker"))
    day = _event_day(event)
    for item in results:
        published = stamp(item.get("release_at") or item.get("release_date"))
        checked = stamp(item.get("checked_at"))
        if (_ticker(item.get("ticker")) != ticker or item.get("fiscal_period") != event.get("fiscal_period")
                or item.get("status") != "official_result" or not published or not checked
                or checked > now or not is_official_result_url(ticker, item.get("source_url")) or day is None):
            continue
        zone = ZoneInfo(event.get("timezone") or "America/New_York")
        release_day = str(item.get("release_date") or "")[:10]
        if not release_day or release_day > now.astimezone(zone).date().isoformat():
            continue
        if item.get("release_precision") == "datetime" and (published > now or published > checked):
            continue
        # The source's fiscal period is mandatory; date proximity is an additional guard.
        actual = stamp(release_day)
        if actual and abs((actual.date() - day.date()).days) <= 7:
            return deepcopy(item)
    return None


def _price_reaction(event, result, context, news, now):
    ticker = _ticker(event.get("ticker"))
    day = stamp(result.get("release_date") or event.get("date"))
    release_at = stamp(result.get("release_at")) if result.get("release_precision") == "datetime" else None
    zone = ZoneInfo(event.get("timezone") or "America/New_York")
    for bucket, label in (("extended_prices", "시간외"), ("intraday_prices", "정규장 장중")):
        quote = next((row for symbol, row in (context.get(bucket) or {}).items() if _ticker(symbol) == ticker), {})
        observed = stamp(quote.get("as_of") or quote.get("observed_at") or quote.get("timestamp") or quote.get("quote_at"))
        value = number(quote.get("return"))
        if (not observed or not 0 <= (now - observed).total_seconds() <= 1200 or not day or value is None
                or quote.get("stale") or quote.get("delayed") or not quote.get("previous_date")
                or not 0 <= (observed.astimezone(zone).date() - day.date()).days <= 2
                or (release_at and observed < release_at)):
            continue
        phase = str(quote.get("phase") or quote.get("session") or "")
        session = {"pre": "프리마켓", "pre_market": "프리마켓", "post": "애프터마켓", "post_market": "애프터마켓",
                   "day_market": "데이마켓", "overnight": "데이마켓"}.get(phase, "시간외" if bucket == "extended_prices" else label)
        if quote.get("kind") in {"데이마켓(야간)", "프리마켓", "애프터마켓"}:
            session = quote["kind"]
        timing = "발표 이후 시세" if release_at or observed.astimezone(zone).date() > day.date() else "발표일 시세·발표 전후 순서 미확인"
        return dict(status="observed_quote", text=f"{session} {value * 100:+.2f}% · {timing} · 직전 정규장 종가 대비, 실적만의 영향 아님",
                    source_url="", observed_at=observed.isoformat(), source=quote.get("source", "시세 제공처 미확인"))
    for row in news:
        title = row.get("title", "")
        published = stamp(row.get("published_at") or row.get("published"))
        if release_at and (not published or published < release_at):
            continue
        if re.search(r"\bQ[1-4]\b|\b(?:first|second|third|fourth)[- ]quarter\b|[1-4]\s*분기", title, re.I) and not _period_matches(title, event.get("fiscal_period")):
            continue
        reaction = extended_stock_reaction(title)
        if reaction in {"reported_extended_decline", "reported_extended_rise"}:
            direction = "하락" if reaction.endswith("decline") else "상승"
            ordering = " · 발표 전후 순서 미확인" if not release_at and published and day and published.astimezone(zone).date() == day.date() else ""
            return dict(status="reported", text=f"시간외 {direction} 보도 · 기사 주장, 가격 수치 미연결" + ordering,
                        source_url=row.get("link", ""), observed_at=row.get("published_at") or row.get("published"))
    return dict(status="missing", text="발표 전후 정규장·시간외 가격 미연결 · 실적 수치로 주가 방향을 추정하지 않음", source_url="")


def reconcile_earnings(context, now):
    """Return copied calendar rows; raw price/decision/context inputs stay untouched."""
    now = stamp(now)
    if now is None:
        raise ValueError("now is required")
    news = [row for key in ("current_session_news", "session_news", "next_session_news") for row in records(context.get(key))]
    results = records(context.get("earnings_results"))
    events = deepcopy(records(context.get("calendar_events")))
    for event in events:
        if not event.get("event_status") or not event.get("fiscal_period"):
            continue
        matching = _eligible_news(event, news, now)
        official = _official_result(event, results, now)
        reports = [row for row in matching if _result_claim_matches(row["title"], event)]
        already_released = event.get("event_status") == "released"
        if not official and not reports and not already_released:
            continue
        event.update(scheduled_date=event.get("scheduled_date", event.get("date")),
                     scheduled_event_kind=event.get("scheduled_event_kind", event.get("event_kind")),
                     schedule_source_url=event.get("schedule_source_url", event.get("source_url")), next_schedule_status="unconfirmed")
        metrics = _empty_metrics()
        if official:
            for key in METRIC_LABELS:
                if key != "price_reaction" and isinstance(official.get("metrics", {}).get(key), dict):
                    metrics[key] = deepcopy(official["metrics"][key])
            event.update(event_status="released", status="released", event_kind="results",
                         date=official["release_date"], release_at=official.get("release_at") or official["release_date"],
                         release_precision=official.get("release_precision", "date"), release_date_confirmed=True,
                         release_time_confirmed=official.get("release_precision") == "datetime",
                         result_source_url=official["source_url"], result_confirmation="official_result",
                         result_checked_at=official["checked_at"], result_stale=bool(official.get("stale")),
                         result_collection_reason=official.get("collection_reason", ""))
        elif already_released:
            # A failed detail fetch does not erase existing verified release evidence.
            event.update(result_confirmation="official_snapshot", result_source_url=event.get("source_url", ""),
                         result_checked_at=event.get("source_verified_at", ""))
            for metric in metrics.values():
                metric["text"] = "공식 발표 확인 · 세부 수치 미연결"
        else:
            report = sorted(reports, key=lambda row: row.get("published_at") or row.get("published") or "", reverse=True)[0]
            event.update(event_status="reported_results", status="reported_results", result_confirmation="news_report",
                         result_source_url=report["link"], result_headline=report["title"],
                         result_checked_at=now.isoformat())
            for metric in metrics.values():
                metric["text"] = "실적 보도 확인 · 공식 수치 대조 미완료"
        metrics["price_reaction"] = _price_reaction(event, official or {}, context, matching, now)
        event["result_metrics"] = metrics
    return events
