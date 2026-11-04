"""Read-only oil/bond diagnostics. No downloads, price repairs or trading inputs.

Wire ``energy_basis_lines(context, news, now)`` after the report market board.
Daily observations reuse collected frames. Optional external evidence must have
verified=True, source, source_url and as_of; this module does not verify a URL
by fetching it. Missing evidence stays missing, never a daily/5m substitute.
"""

from datetime import date, timedelta
from urllib.parse import urlsplit

import pandas as pd

from stock_lab_core.article_price_facts import oil_price_fact
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import (
    SOURCE_DOMAINS, _cell, closed_daily_frame, first, number, records,
    safe_link, stamp, text,
)
from stock_lab_core.report_reference import NY, _closed_value

register_loaded_source(__name__, __file__)

REPORT_ONLY_DAILY = {"BZ=F": ("브렌트유", "USD/배럴"), "^TYX": ("미국 30년물 금리", "%")}
MISSING = "미연결"


def energy_daily_observations(frames, now):
    """Keep actual daily endpoints, including a lone price without a return."""
    result = {}
    for ticker in ("CL=F", *REPORT_ONLY_DAILY):
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if frame.empty:
            result[ticker] = {}
            continue
        current = float(frame["Close"].iloc[-1])
        previous = float(frame["Close"].iloc[-2]) if len(frame) > 1 else None
        result[ticker] = {
            "price": current, "date": str(frame.index[-1].date()),
            "previous_price": previous,
            "previous_date": str(frame.index[-2].date()) if previous is not None else "",
            "return": current / previous - 1 if previous is not None else None,
            "source": frame.attrs.get("source") or "Yahoo Finance daily",
            "basis": "공급처 일봉 · 공식 정산가 아님" if ticker.endswith("=F")
                     else "공급처 일봉 금리 수준(%)",
        }
    return result


def _price(value):
    value = number(value)
    return f"{value:,.2f}" if value is not None else MISSING


def _percent(value):
    value = number(value)
    return f"{value * 100:+.2f}%" if value is not None else MISSING


def _trusted_url(value, domains=SOURCE_DOMAINS):
    link = safe_link(value)
    host = (urlsplit(link).hostname or "").lower()
    return link if any(host == domain or host.endswith("." + domain) for domain in domains) else ""


def _day(value):
    try:
        return date.fromisoformat(text(value)).isoformat()
    except ValueError:
        return ""


def _verified(row, now, domains=SOURCE_DOMAINS):
    at = stamp(row.get("as_of"))
    return (row.get("verified") is True and bool(text(row.get("source")))
            and bool(_trusted_url(row.get("source_url"), domains))
            and at is not None and at <= now)


def _citation(row):
    return f"[{text(row.get('source'))}]({safe_link(row.get('source_url'))})"


def oil_discrepancy_warnings(context, news, now):
    """Flag dated reporting, not a proven same-contract/period price error."""
    ref = context.get("macro_data", {}).get("유가", {})
    change = number(ref.get("day_ret"))
    day = _day(ref.get("as_of"))
    if change is None or change <= 0 or not day or not _day(ref.get("previous_date")):
        return []
    anchor = pd.Timestamp(day + " 16:00", tz=NY).to_pydatetime()
    if anchor > now:
        return []
    warnings, seen = [], set()
    articles = records(news)
    for bucket in ("session_news", "next_session_news", "current_session_news", "other_market_news"):
        articles.extend(records(context.get(bucket)))
    for row in articles:
        at = stamp(first(row, "published_at", "published"))
        link = _trusted_url(first(row, "link", "source_url"))
        if not at or not anchor - timedelta(days=2) <= at <= min(now, anchor + timedelta(days=2)) or not link:
            continue
        # KR news on the next calendar day may still describe the US oil session.
        if row.get("market") == "US" and row.get("session_date") and row["session_date"] != day:
            continue
        paragraphs = [text(row.get("title"))]
        body_at = stamp(row.get("body_published_at"))
        modified = stamp(row.get("body_modified_at"))
        if (row.get("body_status") == "verified" and body_at and modified
                and abs(body_at - at) <= timedelta(hours=24) and body_at <= modified <= now
                and _trusted_url(row.get("body_source_url")) == link):
            paragraphs.extend(text(fact.get("evidence")) for fact in records(row.get("body_facts"))[:32]
                              if fact.get("topic") in {"oil_easing", "oil_rising", "oil_mixed"})
        fact = oil_price_fact(paragraphs)
        if not fact or fact["topic"] != "oil_easing" or link in seen:
            continue
        seen.add(link)
        title = text(row.get("title")).replace("[", "(").replace("]", ")")
        warnings.append(
            f"주의: 유가 방향 불일치 · WTI NY 16:00 기준값 {_percent(change)} "
            f"({ref['previous_date']} → {day}), 반면 [{title}]({link})는 유가 하락 보도 "
            f"(발행 {at.isoformat()}; 기사 주장, 가격 독립 검증 아님). "
            "유종·비교 기간·계약월·정산 기준 대조 필요. 원인 미확인: 롤오버로 단정하거나 가격을 보정하지 않습니다."
        )
    return warnings[:3]


def _contract_lines(context, now):
    lines, missing = [], []
    for ticker in ("CL=F", "BZ=F"):
        row = context.get("oil_contract_metadata", {}).get(ticker, {})
        if not _verified(row, now, (*SOURCE_DOMAINS, "cmegroup.com", "ice.com")):
            missing.append(ticker)
            continue
        rollover = {True: "확인", False: "관측 없음"}.get(row.get("rollover")) if isinstance(row.get("rollover"), bool) else None
        lines.append(f"{ticker} 계약월 {text(row.get('contract_month')) or '미확인'} · "
                     f"롤오버 {rollover or '미확인'} · {row['as_of']} {_citation(row)} · 가격 불일치 원인 확정 아님.")
    if missing:
        lines.append(" / ".join(missing) + " 계약월·롤오버 미확인(메타데이터 미연결).")
    return lines


def rate_hike_probability_line(context, now):
    """Only explicit verified probabilities, never an inference from bond yields.

    Optional rate_hike_probability requires probability_pct (0..100), meeting_date,
    basis, and the verified/source/source_url/as_of provenance contract above.
    """
    row = context.get("rate_hike_probability", {})
    value = number(row.get("probability_pct"))
    meeting = _day(row.get("meeting_date"))
    if (not _verified(row, now, (*SOURCE_DOMAINS, "cmegroup.com", "ice.com"))
            or isinstance(row.get("probability_pct"), bool) or value is None or not 0 <= value <= 100
            or not meeting or not text(row.get("basis"))
            or meeting < stamp(row.get("as_of")).astimezone(NY).date().isoformat()):
        return "금리 인상 확률: 미연결(검증된 출처 없음). 국채금리·유가로 확률을 추정하지 않습니다."
    historical = "과거 회의의 역사적 관측" if meeting < now.astimezone(NY).date().isoformat() else "해당 시점 관측"
    return (f"금리 인상 확률: {value:.2f}% · 회의 {meeting} · 관측 {row['as_of']} · "
            f"{row['basis']} · {_citation(row)} · {historical}, 현재 실시간 확률 아님.")


def energy_basis_lines(context, news, now):
    """Render audit endpoints verbatim; no mutation of macro_data or snapshots."""
    ref = context.get("macro_data", {}).get("유가", {})
    daily = context.get("energy_daily")
    if daily is None:
        daily = energy_daily_observations(context.get("price_frames", {}), now)
        daily = {ticker: obs or context.get("prices", {}).get(ticker, {}) for ticker, obs in daily.items()}
    lines = ["", "## 유가 기준 감사 (보고서 전용)",
             "기준 | 현재·이전 | 등락·날짜 | 출처", "--- | --- | --- | ---"]
    current_at = ref.get("as_of_at") or ref.get("as_of") or MISSING
    previous_at = ref.get("previous_as_of_at") or ref.get("previous_date") or MISSING
    rows = [("WTI(CL=F) NY 16:00 완료 5분봉",
             f"현재 {_price(ref.get('val'))} / 이전 {_price(ref.get('previous_val'))}",
             f"{_percent(ref.get('day_ret'))} · 현재 {current_at} / 이전 {previous_at}", ref.get("source") or MISSING)]
    for ticker in ("CL=F", "BZ=F"):
        obs = daily.get(ticker, {})
        rows.append((ticker + " 공급처 일봉",
                     f"현재 {_price(obs.get('price'))} / 이전 {_price(obs.get('previous_price'))}",
                     f"{_percent(obs.get('return'))} · 현재 {obs.get('date') or MISSING} / 이전 {obs.get('previous_date') or MISSING}",
                     obs.get("source") or MISSING))
    settlement = context.get("oil_settlements", {}).get("CL=F", {})
    settlement_day = _day(settlement.get("date"))
    settlement_end = pd.Timestamp(settlement_day + " 14:30", tz=NY) if settlement_day else None
    valid = (_verified(settlement, now, ("cmegroup.com",))
             and settlement.get("kind") == "official_settlement"
             and number(settlement.get("price")) is not None
             and not isinstance(settlement.get("price"), bool)
             and settlement_end is not None
             and settlement_end <= stamp(settlement.get("as_of")) <= now
             and settlement["date"] <= stamp(settlement.get("as_of")).astimezone(NY).date().isoformat()
             and bool(text(settlement.get("contract_month"))))
    rows.append(("WTI 공식 정산가 · CME 14:28~14:30 ET VWAP",
                 f"현재 {_price(settlement.get('price')) if valid else MISSING} / 이전 {MISSING}",
                 f"등락 {MISSING} · " + (f"{settlement['date']} · 계약월 {text(settlement['contract_month'])}" if valid else "공식 자료 미연결"),
                 _citation(settlement) if valid else MISSING))
    # Inspect only an exact, already-completed bar in existing scenario data.
    day = _day(ref.get("as_of")) or _day(context.get("sessions", {}).get("US"))
    at = pd.Timestamp(day + " 14:30", tz=NY) if day else None
    previous_day = _day(ref.get("previous_date"))
    prior_at = pd.Timestamp(previous_day + " 14:30", tz=NY) if previous_day and day and previous_day < day else None
    frame = context.get("scenario_frames", {}).get("CL=F")
    value = _closed_value(frame, at) if at is not None and at <= now else None
    previous = _closed_value(frame, prior_at) if prior_at is not None and prior_at <= now else None
    change = value / previous - 1 if value is not None and previous is not None else None
    rows.append(("WTI 14:30 완료봉 참고 · 정산가 아님", f"현재 {_price(value)} / 이전 {_price(previous)}",
                 f"{_percent(change)} · 현재 {at.isoformat() if value is not None else MISSING} / "
                 f"이전 {prior_at.isoformat() if previous is not None else MISSING}",
                 "Yahoo Finance 기존 시나리오 5분봉" if value is not None or previous is not None else MISSING))
    lines.extend(" | ".join(_cell(value) for value in row) for row in rows)
    lines += ["", "단위 USD/배럴. NY 16:00 기준값·공급처 일봉·14:25~14:30 완료봉은 공식 정산가가 아닙니다. "
              "macro_data에 없는 이전 기준가격은 역산·대체·보정하지 않습니다. "
              "[CME 정산 방식](https://www.cmegroup.com/trading/energy/files/NYMEX_Energy_Futures_Daily_Settlement_Procedure.pdf)", *_contract_lines(context, now),
              *oil_discrepancy_warnings(context, news, now), rate_hike_probability_line(context, now)]
    return lines
