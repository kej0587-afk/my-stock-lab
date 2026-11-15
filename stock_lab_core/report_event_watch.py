"""Upcoming-event questions and conditional readings from collected evidence.

No provider calls, trading decisions, implied probabilities or invented dates.
Rebuilt at each report generation; a saved report remains an as-of snapshot.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import KST, _cell, first, is_held, number, records, safe_link as _evidence_link, stamp, text

register_loaded_source(__name__, __file__)

_EVENT_NAMES = {
    "US_RETAIL_SALES": "미국 소매판매(속보)",
    "APEC_LEADERS_MEETING": "APEC 정상회의",
    "US_VIX_LAST_TRADE": "VIX 옵션 마지막 거래일",
    "US_VIX_STANDARD_EXPIRY": "VIX 옵션 정규 만기",
    "US_AM_INDEX_OPTIONS_LAST_TRADE": "오전 결제 지수옵션 마지막 거래일",
    "US_STANDARD_OPTIONS_EXPIRY": "주식·지수·ETF·ETN 옵션 정규 만기",
}


def safe_link(value):
    try:
        return _evidence_link(value)
    except (ValueError, TypeError):
        return ""


def _unavailable(row):
    return bool(row.get("stale") or row.get("result_stale")
                or text(row.get("status")).lower() in {"stale", "unavailable", "missing", "error"})


def _same_release(row, release):
    zone = ZoneInfo(row.get("timezone") or ("Asia/Seoul" if row.get("market") == "KR" else "America/New_York"))
    at, day = stamp(release.get("release_at")), stamp(row.get("date"))
    return bool(at and day and release.get("period") and row.get("indicator")
                and release.get("indicator") == row["indicator"]
                and (not row.get("period") or row["period"] == release["period"])
                and at.astimezone(zone).date() == day.date())


def _profile(row):
    indicator, ticker = text(row.get("indicator")), text(row.get("ticker"))
    if indicator == "US_RETAIL_SALES":
        return ("소비 수요가 기업 매출과 금리 전망에 함께 영향을 줌", "헤드라인·자동차 제외·통제그룹, 이전치 수정; 명목 매출과 실질 소비 구분",
                "약한 소비와 물가·임금 둔화가 함께 확인되면 긴축 부담 완화 가능; 소비만 약하면 경기·이익 둔화 우려도 병존. 한 지표로 25/50bp나 확률을 결정하지 않음", "금리·경제지표")
    if "FED" in indicator or "RATE_DECISION" in indicator or "FOMC" in text(row.get("event")).upper():
        return ("할인율과 기업 조달비용의 기준", "결정·성명·기자회견 또는 의사록, 물가·고용 판단과 전망 변화",
                "긴축 신호 강화 시 성장주 할인율·차입 부담 확대 가능; 완화 신호도 경기 악화 때문인지 구분", "금리·경제지표")
    if any(k in indicator for k in ("CPI", "PPI", "PAYROLL", "EMPLOY", "WAGE")):
        return ("물가와 노동시장 강도가 통화정책 판단의 근거", "전월비·전년비, 근원·세부 항목, 이전치 수정과 발표 당시 예상치",
                "둔화가 여러 항목에서 이어지면 금리 부담 완화 가능; 일회성 변동·기저효과이면 다음 발표까지 판단 유보", "금리·경제지표")
    if "VIX" in indicator or "OPTION" in indicator:
        return ("만기 전후 포지션 조정이 단기 가격 움직임에 영향을 줄 수 있음", "상품별 마지막 거래일·결제일 구분, 거래량·변동성과 만기 후 정규장 흐름",
                "만기만으로 상승·하락을 예측하지 않음; 이후에도 거래량과 상대강도가 이어지는지 확인", "시장·업종")
    if "APEC" in indicator or "SUMMIT" in indicator:
        return ("무역·수출통제 변화가 매출과 공급망에 영향", "행사 개최와 개별 정상회담 성사 구분; 공동성명·규제 원문·시행일·대상 기업",
                "협상 보도보다 실제 규제 변경과 적용 범위 확인; 합의가 없으면 기대 재평가 가능", "에너지·지정학")
    if ticker == "NVDA" or "반도체" in text(row.get("sector")):
        return ("AI 주문이 반도체·메모리·서버 수요로 이어지는지 확인", "경영전략·고객 금융지원; 데이터센터 매출·GPU 주문/공급·마진; 수출 규제·건설 지연·장기계약",
                "수요 전망과 마진·현금 회수가 함께 유지되면 공급망 수요 근거 강화; 주문 지연·고객 지원 축소이면 관련 기업별 노출 재검토. 장후 움직임과 다음 정규장 종가 구분", "반도체")
    if ticker in {"MSFT", "AMZN", "GOOGL", "META", "ORCL"}:
        return ("클라우드 수익화가 투자·전력·서버 발주를 감당하는지 확인", "클라우드/광고 성장·AI 유료 매출, 영업현금·설비투자·리스·차입, 다음 분기 전망",
                "투자와 함께 매출·현금 창출이 늘면 수요 지속 근거; 투자만 늘고 회수가 늦어지면 조달 부담 확대 가능", "클라우드·소프트웨어")
    if ticker:
        return ("성장이 이익·현금과 다음 분기 전망으로 이어지는지 확인", "매출·이익·마진, 영업현금·투자, 발표 당시 컨센서스와 회사 전망",
                "예상 상회라도 전망 하향·현금 악화면 재검토; 예상 하회라도 일회성인지 구분. 발표 후 정규장 가격·거래량 확인", "시장·업종")
    return ("시장 기대가 공식 발표로 확인되는 구간", "공식 발표 내용·적용 범위·시행 시점과 시장 반응",
            "결과 확인 전 방향을 단정하지 않고 발표 후 기존 기대와 비교", "시장·업종")


def _event_state(row, context, now):
    """An elapsed calendar date is not proof of a release or its contents."""
    status = text(row.get("event_status") or row.get("status"))
    if _unavailable(row):
        return "마지막 확인값·재조회 필요"
    if status in {"cancelled", "canceled", "postponed"}:
        return "취소·연기 확인"
    zone = ZoneInfo(row.get("timezone") or ("Asia/Seoul" if row.get("market") == "KR" else "America/New_York"))
    if status in {"released", "reported_results"}:
        at = stamp(row.get("result_release_at") or row.get("release_at"))
        day = stamp(row.get("date"))
        if ((day and day.date() > now.astimezone(zone).date())
                or (at and row.get("release_precision") == "datetime" and at > now)):
            return "결과 시점 불일치·재확인 필요"
        return "공식 결과 확인" if status == "released" else "결과 보도·공식 대조 대기"
    for release in records(context.get("economic_releases")):
        if (_same_release(row, release) and not _unavailable(release)
                and release.get("status") != "pending" and number(release.get("actual")) is not None
                and (at := stamp(release.get("release_at"))) and at <= now):
            return "공식 결과 확인"
    precision = row.get("event_precision") or row.get("release_precision")
    at = stamp(row.get("event_at") or row.get("release_at") or row.get("date"))
    if status == "elapsed_unconfirmed" or (at and precision == "datetime" and at <= now):
        return "예정 시각 경과·결과 미확인"
    try:
        local_day = now.astimezone(ZoneInfo(row.get("timezone") or ("Asia/Seoul" if row.get("market") == "KR" else "America/New_York"))).date()
    except (ValueError, KeyError):
        local_day = now.date()
    day = stamp(row.get("date"))
    end = stamp(row.get("end_date"))
    if day and end and day.date() <= local_day <= end.date():
        return "예정 행사 기간·결과 미확인"
    return "예정일 경과·결과 미확인" if day and day.date() < local_day else "예정"


def _timing(row):
    zone_name = row.get("timezone") or ("Asia/Seoul" if row.get("market") == "KR" else "America/New_York")
    try:
        zone = ZoneInfo(zone_name)
    except (ValueError, KeyError):
        return text(row.get("date")) + " · 현지 시간대 미확인"
    value = row.get("event_at") if row.get("event_kind") == "conference_call" else row.get("release_at")
    precision = row.get("event_precision") if row.get("event_kind") == "conference_call" else row.get("release_precision")
    at = stamp(value)
    if at and row.get("indicator") == "US_FED_RATE_DECISION" and len(text(value)) == 10:
        # Preserve the existing report's explicitly labelled statement convention.
        at = datetime.fromisoformat(value + "T14:00:00").replace(tzinfo=zone)
        precision = "schedule_rule"
    if at and precision in {"datetime", "schedule_rule"}:
        label = "콜 " if row.get("event_kind") == "conference_call" else ""
        timing = f"{label}{at.astimezone(zone):%m/%d %H:%M %Z} / {at.astimezone(KST):%m/%d %H:%M KST}"
        return timing + (" · 표준시각·예외 미확인" if precision == "schedule_rule" else "")
    result = text(row.get("date")) + " 현지 · 시각 미확인"
    if row.get("end_date"):
        result = f"{row['date']}~{row['end_date']} 현지 · 시각 미확인"
    if row.get("session_timing") == "after_market_close":
        result = text(row.get("date")) + " 미국 장후 · 분 시각 미확인"
    if (call := stamp(row.get("conference_call_at"))):
        result += f" / 콜 {call.astimezone(zone):%m/%d %H:%M %Z} · {call:%m/%d %H:%M KST}"
    return result


def _result_summary(row, context, now):
    pieces = []
    for release in records(context.get("economic_releases")):
        at = stamp(release.get("release_at"))
        if (release.get("indicator") != row.get("indicator") or not row.get("indicator")
                or _unavailable(release) or release.get("status") == "pending"
                or not at or at > now or number(release.get("actual")) is None):
            continue
        basis = {"MoM": "전월비", "YoY": "전년비"}.get(release.get("basis"), text(release.get("basis")))
        prefix = "결과" if _same_release(row, release) else "직전 관측(이번 예상 아님)"
        piece = f"{prefix} {release.get('period', '')} {basis} {release['actual']}{release.get('unit', '')}"
        if number(release.get("previous")) is not None:
            piece += f" / 이전 {release['previous']}{release.get('unit', '')}"
        if prefix == "결과" and number(release.get("forecast")) is not None:
            piece += f" / 발표 당시 예상 {release['forecast']}{release.get('unit', '')}"
        if source := safe_link(release.get("source_url")):
            piece += f" ([수치 근거]({source}))"
        pieces.append(piece)
    return " · ".join(dict.fromkeys(pieces))


def event_watch_rows(context, summary_rows, now, *, pipeline=None):
    now = stamp(now)
    if now is None:
        return []
    from stock_lab_core.report_brief import _holding_links
    held = [row for row in records(summary_rows) if is_held(row)]
    events = [*records(context.get("calendar_events")), *records((pipeline or {}).get("events"))]
    selected = {}
    for row in events:
        day = stamp(row.get("date"))
        source = safe_link(row.get("result_source_url") or row.get("source_url"))
        if not day or not source or text(row.get("source")) == "fallback":
            continue
        if (at := stamp(row.get("source_verified_at"))) and at > now:
            continue
        if (expiry := stamp(row.get("coverage_expires_at"))) and expiry <= now:
            continue
        if row.get("schedule_status") == "unconfirmed":
            continue
        if not -7 <= (day.date() - now.date()).days <= 90:
            continue
        try:
            state = _event_state(row, context, now)
        except (ValueError, KeyError):
            continue
        why, check, conditional, theme = _profile(row)
        ticker = text(row.get("ticker"))
        title = _EVENT_NAMES.get(row.get("indicator")) or text(first(row, "event", "title", "이벤트")) or text(row.get("indicator"))
        link = _holding_links(held, title, {ticker} if ticker else set(), theme, row.get("market", "US"))
        item = dict(row, state=state, why=why, check=check, conditional=conditional,
                    exposure=link, timing=_timing(row), source_url=source, event=title,
                    observed=_result_summary(row, context, now))
        key = (ticker or row.get("indicator") or title, row["date"])
        old = selected.get(key)
        if old is None or (state == "공식 결과 확인" and old["state"] != state) or (
                state == old["state"] and row.get("release_precision") == "datetime"):
            selected[key] = item
    return sorted(selected.values(), key=lambda row: (row["date"], row["event"]))


def _table(header, rows):
    return [" | ".join(header), " | ".join("---" for _ in header),
            *(" | ".join(_cell(v) for v in row) for row in rows), ""]


def _ongoing_watch(context, now):
    prices, sessions = context.get("prices", {}), context.get("sessions", {})
    observations = []
    for ticker in ("IGV", "SOXX"):
        row = prices.get(ticker, {})
        value = number(row.get("return"))
        day = stamp(row.get("date"))
        if (day and day <= now and row.get("date") == sessions.get("US")
                and value is not None and not row.get("stale") and not row.get("is_active")
                and row.get("price_kind", "close") not in {"intraday", "live", "premarket", "postmarket"}):
            observations.append(f"{ticker} {value * 100:+.2f}% ({row['date']} 종가)")
    basis = " / ".join(observations) or "동일 거래일 소프트웨어·반도체 가격 비교 미연결"
    return _table(["계속 볼 주제", "현재 확인 범위", "다음 확인·해석 조건"], [
        ("AI 활용·생산성 확산", basis,
         "유료 고객·사용량·고객당 매출이 늘고 비용률·마진도 개선되는지. 업종 상대강도가 실적과 함께 이어질 때 확산 근거; 하루 등락만으로 차기 주도주 확정 안 함"),
        ("투자 대비 현금 회수", "기업별 실적·현금흐름 심층분석과 연결해 검토",
         "매출·영업현금 증가가 설비투자·리스·이자를 감당하는지; 고객 금융지원·차환 조건 악화가 동반되면 공급망 주문 지연 여부 확인"),
        ("금리·유가와 소비", "아래 일정의 공식 발표가 새로 들어올 때 재점검",
         "소비·임금·근원물가·유가를 함께 비교. 유가 하락이 공급 개선인지 수요 부진인지 구분하고, 금리 경로는 연준 결정·시장 기대 자료와 따로 대조"),
    ])


def event_watch_lines(context, news, summary_rows, now, *, pipeline=None):
    """Only render the richer calendar when the collector is explicitly connected."""
    if "market_watch_sources" not in context:
        return []
    now = stamp(now)
    if now is None:
        return []
    rows = event_watch_rows(context, summary_rows, now, pipeline=pipeline)
    lines = [f"기준 {now:%m/%d %H:%M KST} · 시황 생성마다 일정·발표 상태·확인 항목 갱신. 저장본은 생성 시점 기준입니다.", ""]
    if rows:
        near = [r for r in rows if (stamp(r['date']).date() - now.date()).days <= 7]
        later = [r for r in rows if r not in near]
        for label, group in (("이번 주·최근 발표", near), ("이후 확정 일정·90일 이내", later)):
            if not group:
                continue
            lines += [f"**{label}**", "", *_table(["일정·현지 / 한국 시각", "상태·근거", "확인할 핵심"], [
                (f"{r['event']} · {r['timing']}", f"{r['state']} · [{r.get('source') or '원문'}]({r['source_url']})" + (" · " + r['observed'] if r['observed'] else ""), r['check']) for r in group])]
        lines += ["**왜 중요한가 · 결과별 읽는 법(조건부 해석)**", ""]
        interpretation_rows = (near + [r for r in later if "FED" in text(r.get('indicator'))]) or later
        grouped = {}
        for row in interpretation_rows:
            key = (row['why'] + ". " + row['conditional'], row['exposure'])
            grouped.setdefault(key, []).append(row['event'])
        lines += _table(["이벤트", "의미·조건부 해석", "보유·업종 연결"], [
            (" · ".join(dict.fromkeys(names)), meaning, exposure)
            for (meaning, exposure), names in grouped.items()])
    else:
        lines += ["확인된 향후 일정·최근 결과 미연결. 일정이 없다는 뜻은 아닙니다.", ""]
    # Rumoured listings/meetings remain dated news, never become calendar events.
    from stock_lab_core.report_policy_catalysts import policy_news
    from stock_lab_core.report_brief import material_news
    import re
    tracked, seen = {}, set()
    for row in policy_news(context, news, now):
        title = text(row.get("title"))
        if not material_news(row):
            continue
        if not re.search(r"IPO|기업공개|상장|정상회담|APEC", title, re.I) or re.search(r"상장폐지|delist", title, re.I):
            continue
        family = "IPO·상장" if re.search(r"IPO|기업공개|상장", title, re.I) else "외교·규제"
        link = safe_link(row.get("link") or row.get("url"))
        if not link or link in seen:
            continue
        seen.add(link)
        check = ("공식 공모가·상장일·조달액·자금 사용처, 상장 후 공모가 유지와 추가 자금 필요를 확인"
                 if family == "IPO·상장" else "개별 회담 성사·합의문·규제 시행일 확인; 행사 개최와 합의는 별개")
        key = "anthropic_ipo" if family == "IPO·상장" and re.search(r"Anthropic|앤트로픽|앤스로픽", title, re.I) else link
        if key not in tracked:
            tracked[key] = [title, [], check]
        tracked[key][1].append(link)
    if tracked:
        lines += ["**일정 확정과 별도로 추적할 재료**", "", *_table(["최근 근거", "구분", "다음 확인"], [
            (f"[{title}]({links[0]})" + (f" · 관련 보도 {len(links)}건: " + " ".join(f"[{i}]({link})" for i, link in enumerate(links, 1)) if len(links) > 1 else ""),
             "보도·일정 확정과 별도", check) for title, links, check in tracked.values()])]
    lines += ["**계속 볼 흐름**", "", *_ongoing_watch(context, now)]
    missing = [s.get("name", "공식 일정") for s in records(context.get("market_watch_sources")) if s.get("status") != "connected"]
    if missing:
        lines += ["일정 연결 미완료: " + ", ".join(missing) + " · 확인되지 않은 날짜를 채우지 않습니다.", ""]
    return lines
