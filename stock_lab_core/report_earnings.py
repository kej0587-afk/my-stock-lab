"""Present the shared earnings pipeline: facts, questions and coverage apart."""

from datetime import timedelta
import re

from stock_lab_core.earnings_discovery import TOPICS
from stock_lab_core.earnings_reconciliation import METRIC_LABELS
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, citation, safe_link, stamp, text

register_loaded_source(__name__, __file__)


def _available_metrics(packet):
    return {key for key, metric in packet["metrics"].items()
            if metric.get("status") in {"reported", "available"}
            and safe_link(metric.get("source_url")) and text(metric.get("text"))}


def _fact_keys(packet):
    available = _available_metrics(packet)
    return ([key for key in ("free_cash_flow", "capex", "revenue", "profit") if key in available][:2]
            + (["guidance"] if "guidance" in available else []))


def _metric_facts(packet):
    facts = []
    for key in _fact_keys(packet):
        metric = packet["metrics"][key]
        scope = "TTM·분기값 아님" if metric.get("period_scope") == "trailing_twelve_months" else packet["fiscal_period"]
        if key == "guidance":
            scope = f"{packet['fiscal_period']} 발표에서 제시 · 전망 대상 기간은 원문 기준 · 실제치 아님"
        # Keep the complete source sentence; truncating can remove a sign or unit.
        evidence = text(metric["text"]).replace("$", r"\$")
        facts.append(f"{METRIC_LABELS[key]} ({scope}): {evidence} "
                     + f"[원문]({safe_link(metric['source_url'])})")
    return facts


def _latest_article(packet, now):
    if now is None:
        return None
    articles = [(at, row) for row in packet["articles"]
                if (at := stamp(row.get("published_at") or row.get("published"))) is not None
                and now - timedelta(days=7) <= at <= now and safe_link(row.get("link"))]
    return max(articles, key=lambda item: item[0])[1] if articles else None


def _packet_dates(packet):
    dates = f"{packet['date']} {packet['date_basis']}"
    if packet.get("latest_evidence_basis") == "보도일·발표일 아님":
        at = stamp(packet.get("latest_evidence_at"))
        if at:
            dates += f" / 최신 보도 {at:%Y-%m-%d %H:%M} KST · 발표일 아님"
    return dates


def _packet_facts(packet, now):
    facts = _metric_facts(packet)
    article = _latest_article(packet, now)
    if article:
        facts.append("제목 기준·기사 주장: " + citation(article).replace("$", r"\$"))
    if not facts:
        url = safe_link(packet.get("source_url"))
        facts = [packet["release_status"] + (f" · [출처]({url})" if url else " · 출처 미연결")]
    if packet.get("event", {}).get("result_stale"):
        facts.append("원문 재조회 실패·마지막 확인값 사용")
    return facts


def _catalyst_reading(packet, now):
    """Conditional economic channels backed by the facts displayed in this row."""
    available = _available_metrics(packet)
    supported = set(_fact_keys(packet))
    article = _latest_article(packet, now)
    if article:
        title = text(article.get("title"))
        supported.update(key for key, _, pattern in TOPICS if re.search(pattern, title, re.I))
        for key, pattern in (("revenue", r"\b(?:revenue|sales)\b|매출"),
                             ("profit", r"\b(?:profit|EPS|margin)\b|영업이익|순이익|이익률|마진")):
            if re.search(pattern, title, re.I):
                supported.add(key)
    readings, topic_checks, checks = [], [], []
    if "guidance" in supported:
        readings.append("전망 변화가 실제 매출·이익률로 이어진다면 향후 수요·수익성 기대가 달라질 수 있습니다.")
        checks.append("전망 대상 기간·매출/이익률 범위와 이전 전망 비교" if "guidance" in available
                      else "회사 전망 원문·전망 대상 기간·매출/이익률 범위 확인")
    elif packet["stages"].get("guidance") == "콜 대기":
        checks.append("컨퍼런스콜의 회사 전망·대상 기간 확인")
    if {"capex", "free_cash_flow"} <= supported:
        readings.append("투자 지출이 현금 창출보다 빨리 늘면 자금 부담이 커질 수 있고, 현금 회수가 동반되면 부담이 완화될 수 있습니다.")
        topic_checks.append("동일 기간 CAPEX·영업현금흐름·FCF 변화와 투자 회수 시점 대조")
    elif "capex" in supported:
        readings.append("설비투자가 현금 창출보다 빨리 늘면 자금 부담이 커질 수 있습니다.")
        topic_checks.append("같은 기간 FCF·영업현금흐름과 CAPEX 집행액 확인")
    elif "free_cash_flow" in supported:
        readings.append("현금흐름 변화가 반복 영업에서 비롯됐다면 투자·차입 상환 여력이 달라질 수 있습니다.")
        topic_checks.append("CAPEX·운전자본·일회성 현금 유출입과 FCF의 분기/TTM 범위 확인")
    if "revenue" in supported:
        readings.append("매출 변화가 가격·환율보다 판매량 변화에서 왔다면 수요의 강약을 보여줄 수 있습니다.")
        topic_checks.append("매출 전년비와 판매량·가격·환율 기여, 이익률 동행 여부 확인")
    if "profit" in supported:
        readings.append("이익률 변화가 일회성 항목보다 영업활동에서 왔다면 수익성의 지속 가능성이 달라질 수 있습니다.")
        topic_checks.append("이익·EPS의 회계기준, 영업이익률과 일회성 항목 대조")
    if not readings and "comparison" in supported:
        readings.append("기사의 예상 대비 차이가 같은 분기 실제치로 확인된다면 실적 기대를 재평가할 계기가 될 수 있습니다.")
        topic_checks.append("같은 분기·회계기준의 실제치와 발표 당시 예상치 원문 대조")
    missing_actuals = [METRIC_LABELS[key] for key in ("revenue", "profit") if key not in available]
    if missing_actuals:
        checks.append("같은 기업·분기의 " + "·".join(missing_actuals) + " 실제치 원문 확인")
    checks.extend(topic_checks)
    if not checks:
        checks.append("회사 전망의 대상 기간·매출·이익률 범위 확인")
    why = "해석(추정): " + (" ".join(readings[:2]) if readings else "세부 실적·전망 근거가 없어 수요·수익성 방향의 해석은 보류합니다.")
    return why, " / ".join(checks[:2])


def earnings_story_lines(pipeline):
    selected = pipeline["highlights"]
    if not selected:
        return []
    lines = ["", "**실적에서 확인할 시장 쟁점**",
             "기업·확인된 사실 | 해석과 남은 확인", "--- | ---"]
    for packet in selected:
        facts = _packet_facts(packet, stamp(pipeline.get("generated_at")))
        target = f"{packet['name']}({packet['ticker']}) · {packet['sector']} · {packet['relationship']}"
        target += " · " + _packet_dates(packet)
        reading = packet["commentary"] + " " + packet["consensus_status"] + "."
        lines.append(" | ".join(_cell(v) for v in (f"**{target}** " + " / ".join(facts), reading)))
    lines.extend(["", "최근 7일의 수집된 발표·보도에서 기업 중복을 줄이고 업종을 분산한 최대 3개입니다. 시장 영향도 순위나 매수 후보가 아니며, 근거가 없는 업종은 채우지 않습니다.", ""])
    return lines


def compact_catalyst_lines(pipeline, market) -> list[str]:
    """At most four collected issuers for one market; no I/O or new evidence.

    Recent results retain the pipeline's 30-day window; news retains seven days.
    Confirmed upcoming schedules are separate from released results. Holdings
    and registered issuers precede other issuers, then latest evidence wins.
    """
    now = stamp(pipeline.get("generated_at"))
    if market not in {"KR", "US"} or now is None:
        return []
    candidates = []
    for packet in pipeline["packets"]:
        day = stamp(packet["date"])
        if packet["market"] != market or day is None or not -30 <= (day.date() - now.date()).days <= 45:
            continue
        scheduled = packet.get("event", {}).get("event_status") == "scheduled"
        article = _latest_article(packet, now)
        source = safe_link(packet.get("source_url"))
        evidence = stamp(packet.get("latest_evidence_at") or packet["date"])
        if scheduled:
            if not source or day.date() < now.date():
                continue
        elif ("예정" in packet["release_status"] or day.date() > now.date()
              or evidence is None or evidence > now or not (source or article or _metric_facts(packet))):
            continue
        elif not packet["official"] and not article:
            # A schedule date alone cannot make an undated report a fresh lead.
            continue
        relation = {"보유": 2, "관심·점검": 1}.get(packet["relationship"], 0)
        # Upcoming schedules have no future publication evidence. Rank them by
        # proximity, without relabeling their event dates as announcement times.
        recency = -(day - now).total_seconds() if scheduled else (evidence - now).total_seconds()
        fresh = (day.date() <= (now + timedelta(days=7)).date() if scheduled
                 else evidence >= now - timedelta(days=7))
        candidates.append((fresh, relation, recency, packet["official"], packet["ticker"], packet, scheduled))
    candidates.sort(key=lambda item: item[:5], reverse=True)
    chosen, seen = [], set()
    for *_, packet, scheduled in candidates:
        if packet["ticker"] not in seen:
            chosen.append((packet, scheduled))
            seen.add(packet["ticker"])
        if len(chosen) == 4:
            break
    if not chosen:
        return []
    lines = ["", "**수집된 실적 촉매 · " + market + "**",
             "기업·날짜 | 확인 구분 | 사실·출처 | 왜 중요한가 | 다음 확인", "--- | --- | --- | --- | ---"]
    for packet, scheduled in chosen:
        identity = f"**{packet['name']}({packet['ticker']})** · {packet['relationship']} · " + _packet_dates(packet)
        if scheduled:
            status = "공식 일정·결과 미확인"
            kind = "콜 예정 · 결과 공개일은 별도 미확인" if packet["event"].get("event_kind") == "conference_call" else "실적 발표 예정 · 결과 미확인"
            facts = kind + f" · [공식 일정]({safe_link(packet['source_url'])})"
            why = "해석(추정): 발표에서 수요·이익률 전망이 달라지면 향후 실적 기대를 재평가할 계기가 될 수 있습니다."
            check = "발표 매출·이익과 회사 전망의 대상 기간 확인; 콜과 결과 공개는 구분"
        else:
            status = "공식 발표 확인" if packet["official"] else "기사 주장·공식 대조 대기"
            facts = " / ".join(_packet_facts(packet, now))
            why, check = _catalyst_reading(packet, now)
        lines.append(" | ".join(_cell(value) for value in (identity, status, facts, why, check)))
    lines.append("")
    return lines


def earnings_coverage_lines(pipeline):
    coverage = pipeline["coverage"]
    lines = ["", "**실적 연결 상태**",
             f"점검 기업 {coverage['registered']}개 · 공식 발표 확인 기업 {coverage['official']}개 · 기존 뉴스에서 발견 {coverage['discovered']}개(서로 중복 가능). "
             "전시장 실적 캘린더가 아니라 기존 수집자료의 연결 범위입니다.",
             "기업·분기 | 일정·발표 확인 | 실제치·현금흐름 | 예상치·전망·반응", "--- | --- | --- | ---"]
    for packet in pipeline["packets"]:
        stage = packet["stages"]
        actual = " / ".join(METRIC_LABELS[key] + " " + stage[key] for key in ("revenue", "profit", "capex", "free_cash_flow"))
        pending = packet["consensus_status"] + " / 회사 전망 " + stage["guidance"] + " / 주가 반응 " + stage["price_reaction"]
        if packet["gaps"]:
            pending += " · " + packet["gaps"][0]
        lines.append(" | ".join(_cell(v) for v in (
            f"{packet['name']}({packet['ticker']}) · {packet['fiscal_period'] or '분기 미확인'}",
            f"{packet['release_status']} · {packet['date']} {packet['date_basis']}", actual, pending)))
    if not pipeline["packets"]:
        lines.append("기업 실적 | 연결 자료 없음 | 미연결 | 미발표·일정 없음으로 해석하지 않음")
    excluded = pipeline["discovery"]["excluded"]
    if excluded:
        lines.extend(["", "보도 연결 보류: " + " / ".join(f"{reason} {count}건" for reason, count in excluded.items())])
    if coverage["missing"]:
        lines.extend(["", "기업 | 연결되지 않은 단계", "--- | ---"])
        lines.extend(" | ".join(_cell(v) for v in (f"{row['name']}({row['ticker']})", row["reason"])) for row in coverage["missing"])
    lines.extend(["", "미연결은 0·미발표·실적 부진이 아닙니다. 회사 전망, 현재 예상치, 발표 당시 예상치는 서로 대체하지 않습니다.", ""])
    return lines
