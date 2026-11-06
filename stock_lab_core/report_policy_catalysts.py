"""Source-labelled policy calendar and conditional news, never gate inputs."""

from datetime import timedelta
import json
from pathlib import Path
import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, curate_news, first, is_held, records, stamp, text
from stock_lab_core.report_presentation import kst_time

register_loaded_source(__name__, __file__)

CALENDAR_PATH = Path(__file__).with_name("data") / "verified_policy_calendar_20261104.json"
_POLICY = re.compile(r"중간선거|개표|상원|하원|midterm|election|IPO|기업공개|상장|이란|Iran|refunding|재무부|발행계획|임시예산|입찰", re.I)
_US_CONTEXT = re.compile(r"미국|美|(?<![가-힣])미(?=[·ㆍ\s-])|\b(?:U\.?S\.?|United States)\b", re.I)
# Partial display-only exposure map; broad index ownership is not sector weight.
_EXPOSURES = {
    "AI·반도체": {"SOXX", "SMH", "SOXL", "SOXS", "DRAM", "RAM", "NVDA", "AMD", "GOOGL", "GOOG", "MSFT", "396500.KS", "0167A0.KS", "000660.KS", "005930.KS"},
    "방산": {"ITA", "XAR", "449450.KS", "LMT", "RTX", "NOC"},
    "헬스케어": {"XLV", "IBB", "XBI", "LLY", "JNJ", "UNH", "TMO", "DHR", "CRL"},
    "금융": {"XLF", "KBE", "KRE", "JPM", "BAC", "139270.KS"},
}


def policy_news(context, news, now):
    corpus = [*records(news), *(row for key in ("current_session_news", "session_news", "next_session_news", "other_market_news")
                               for row in records(context.get(key)))]
    candidates = curate_news(corpus, now=now, limit=100, session_scoped=True, title_pattern=_POLICY)
    return sorted((r for r in candidates if (at := stamp(r.get("published_at") or r.get("published")))
                   and now - timedelta(days=3) <= at <= now),
                  key=lambda r: stamp(r.get("published_at") or r.get("published")), reverse=True)


def policy_calendar_lines(context, news, now, *, calendar=None):
    now = stamp(now)
    if now is None:
        return []
    try:
        saved = calendar if calendar is not None else json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    verified = stamp(saved.get("verified_at"))
    lines = ["", "**정책·정치·발행 촉매**", "일정·촉매 | 시점·상태 | 확인 수준·출처", "--- | --- | ---"]
    active = []
    if verified and verified <= now:
        for event in saved.get("events", []):
            expires = stamp(event.get("expires_on"))
            day = stamp(event.get("date"))
            expired = expires is not None and now.date() > expires.date()
            if (not expires or (expired and (not day or day.date() < now.date()))
                    or (day and not -3 <= (day.date() - now.date()).days <= 45)):
                continue
            active.append(event)
            at = stamp(event.get("release_at"))
            if at:
                timing = kst_time(at.isoformat()) + (" · 예정" if at > now else " · 예정시각 경과, 결과는 별도 확인")
            else:
                timing = (event.get("date") or event.get("period") or "일정 미확정") + " · 현지 날짜/기간, 분 시각 미확인"
            source = f"{event['level']} · [{event['source']}]({event['source_url']})"
            if expired:
                source = "재확인 필요·현재 유효성 미확인 · " + source
            if event.get("time_source_url"):
                source += f" · [일부 지역 투표시간]({event['time_source_url']})"
            lines.append(" | ".join(_cell(v) for v in (event["name"], timing + " · " + event["note"], source)))
    candidates = policy_news(context, news, now)
    ipo = next((r for r in candidates if re.search(r"IPO|기업공개|상장", r.get("title", ""), re.I)
                and not re.search(r"상장폐지|delist", r.get("title", ""), re.I)), None)
    if ipo:
        lines.append("최근 IPO 보도 | " + _cell(ipo["title"]) + " · 제목 기준, 확정 상장일과 별도 | " + citation(ipo))
    negotiations = next((r for r in candidates if re.search(r"이란|Iran", r.get("title", ""), re.I)
                         and _US_CONTEXT.search(r.get("title", ""))
                         and re.search(r"협상|회담|중재|talks|negotiat|mediat", r.get("title", ""), re.I)), None)
    lines.append("미국·이란 협상 | " + (_cell(negotiations["title"]) + " · 보도 기준, 합의·회담일 확정 아님 | " + citation(negotiations)
                 if negotiations else "일정·결과 미연결 | 수집된 최근 보도 근거 없음"))
    auctions = next((r for r in candidates if _US_CONTEXT.search(r.get("title", ""))
                     and re.search(r"국채.{0,12}입찰|Treasury.{0,30}auction", r.get("title", ""), re.I)), None)
    lines.append("미 국채 개별 입찰 | " + (_cell(auctions["title"]) + " · 보도 기준 | " + citation(auctions)
                 if auctions else "날짜·만기·규모 미연결 | 분기 발행계획과 개별 입찰은 별도"))
    lines += ["", "공식 일정은 출처 확인 보관값이며 실시간 재조회가 아닙니다. 확인 " + (kst_time(verified.isoformat()) if verified else "미확인")
              + ". 유효기간이 지난 미래 일정은 재확인 필요로 표시합니다. 보도 후보는 확정 일정·결과로 승격하지 않습니다."]
    if not active:
        lines.append("유효한 정책 일정 보관값 미연결(확인 전 또는 만료). 일정이 없다는 뜻은 아닙니다.")
    return lines


def election_context_lines(context, news, summary_rows, now):
    now = stamp(now)
    if now is None:
        return []
    candidates = policy_news(context, news, now)
    elections = [r for r in candidates if re.search(r"중간선거|미국.{0,6}선거|미\s*선거|midterm|US election|U\.S\. election", r.get("title", ""), re.I)]
    if not elections:
        return []
    lines = ["", "### 선거·정책 조건별 쟁점", "기사의 조건부 주장입니다. 의석 결과·업종 방향·매수 신호로 확정하지 않습니다."]
    seen, scenarios = set(), []
    for row in elections:
        if row.get("body_status") != "verified":
            continue
        body_at, modified = stamp(row.get("body_published_at")), stamp(row.get("body_modified_at"))
        if not body_at or not modified or max(body_at, modified) > now:
            continue
        for scenario in row.get("body_scenarios", []):
            key = (scenario.get("condition"), scenario.get("evidence"))
            if not all(key) or key in seen:
                continue
            seen.add(key)
            scenarios.append((scenario, row))
    lines += ["조건(서로 겹칠 수 있음) | 기사 주장·출처 | 업종·보유 연결(부분 매핑)", "--- | --- | ---"]
    for scenario, row in scenarios[:3]:
        sectors = [s for s in scenario.get("sectors", []) if s in _EXPOSURES]
        tickers = {text(first(r, "티커", "ticker", "Ticker")).upper() for r in records(summary_rows) if is_held(r)}
        matched = sorted(tickers & set().union(*(_EXPOSURES[s] for s in sectors))) if sectors else []
        exposures = ", ".join(sectors) if sectors else "해당 문장에서 업종 미확인"
        exposures += " · 보유 " + (", ".join(matched) if matched else "직접/기초자산 연결 미확인")
        lines.append(" | ".join((_cell(scenario["condition"]), _cell(scenario["evidence"]) + " · " + citation(row), _cell(exposures))))
    if not scenarios:
        lines.append("시나리오별 업종 영향 | 검증된 본문 조건 미연결 | 제목만으로 민주·공화 승리의 수혜 업종을 채우지 않음")
    covered = {s for scenario, _ in scenarios for s in scenario.get("sectors", [])}
    missing = [s for s in _EXPOSURES if s not in covered]
    if missing:
        lines += ["", "조건별 근거 미연결 업종: " + ", ".join(missing)]
    # Preserve claims and time; do not convert projections into certified outcomes.
    progress = [r for r in elections if re.search(r"개표|당선|의석|승리|results|wins?|seats?|counting", r.get("title", ""), re.I)
                and not re.search(r"시청률|개표방송|시청자|방송.{0,8}(?:순위|1위)|ratings|viewership", r.get("title", ""), re.I)
                and not re.search(r"시나리오|경우|만약|전망|예상|확률|scenario|could|would|polls", r.get("title", ""), re.I)
                and stamp(r.get("published_at") or r.get("published")) >= now - timedelta(hours=24)]
    lines += ["", "**개표 관련 최신 보도**"]
    for row in progress[:2]:
        lines.append("- " + citation(row) + " · " + kst_time(row.get("published_at") or row.get("published")) + " · 기사 주장, 공식 인증 결과 아님")
    if not progress:
        lines.append("개표 진행·의석 결과 미연결. 선거 일정 경과만으로 승패를 추정하지 않습니다.")
    return lines
