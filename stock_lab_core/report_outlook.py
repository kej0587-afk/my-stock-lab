"""Render long-term company plans and conditional implications without signals."""

from datetime import datetime, timedelta

from stock_lab_core.official_outlook import TOPICS, official_oracle_url
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell
from stock_lab_core.report_presentation import kst_time

register_loaded_source(__name__, __file__)


def official_outlook_lines(context, now):
    payload = context.get("official_outlooks")
    if payload is None:
        return []
    lines = ["", "## 공식 중장기 전망", "분기 실적(실현값)과 별도인 회사 계획입니다. 발표일 기준이며 이후 수정 여부와 당일 주가의 인과관계는 별도 확인이 필요합니다.", ""]
    events = []
    for event in payload.get("events", []):
        try:
            observed = datetime.fromisoformat(event["observed_at"])
            age = now.date() - datetime.fromisoformat(event["published_date"]).date()
            valid = (observed.tzinfo is not None and observed <= now and now - observed <= timedelta(days=1)
                     and timedelta(0) <= age <= timedelta(days=90))
        except (KeyError, TypeError, ValueError):
            valid = False
        if (valid and event.get("evidence_kind") == "company_outlook" and event.get("event_kind") == "investor_day"
                and event.get("ticker") == "ORCL" and official_oracle_url(event.get("source_url"))):
            events.append(event)
    if not events:
        reason = next((r.get("reason") for r in payload.get("sources", []) if r.get("reason")), "stale_or_missing_evidence")
        lines.append("Oracle Investor Day 미연결 · " + _cell(reason) + " · 전망 부재가 아니라 수집/검증 미완료이며 추정값으로 채우지 않습니다.")
        return lines
    for event in events[:1]:
        metrics = event.get("metrics", {})
        lines.extend([f"**Oracle · Investor Day · 발표 {event['published_date']}**", "구분 | 확인 내용", "--- | ---"])
        for key, label in TOPICS.items():
            metric = metrics.get(key, {})
            lines.append(_cell(label) + " | " + _cell(metric.get("text") or "미확인"))
        if metrics.get("capex", {}).get("status") == "confirmed":
            lines.append("반도체 영향 · 조건부 해석 | 실제 GPU·서버 발주와 구축량도 줄면 공급업체 주문 성장에 부담일 수 있습니다. 현금 CAPEX만으로 수요 감소를 확정하지 않습니다.")
            lines.append("반증·확인할 자료 | 고객 제공 하드웨어·금융 방식에 따른 지출 이전인지, 총 장비 발주·데이터센터 인도량 감소인지 구분하고 다른 고객의 투자가 상쇄하는지 확인합니다.")
        lines.extend([f"[Oracle 공식 IR]({event['source_url']}) · 수집 확인 {kst_time(event['observed_at'])} · 최신 60건 중 최근 90일 Investor Day 범위", ""])
    return lines
