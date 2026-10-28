"""One report-only cumulative account definition; trading gates are untouched."""

from copy import deepcopy

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, stamp

register_loaded_source(__name__, __file__)


def cumulative_account_metrics(held, context, states, now):
    from stock_lab_core.report_intraday import latest_account_metrics

    result = deepcopy(latest_account_metrics(held, context, states, now))
    result["basis"] = "completed_session_to_latest"
    if result.get("error"):
        return result
    valid = {}
    for ticker, obs in result["observations"].items():
        closed = context.get("prices", {}).get(ticker, {})
        move = obs["return"]
        base = obs.get("previous_date")
        if obs["group"] == "KR" and not base:
            base = context.get("sessions", {}).get("KR")
        if obs["group"].endswith("_CLOSE") and not base:
            base = context.get("news_sessions", {}).get(obs["market"], {}).get("previous_date")
        if obs["market"] == "US" and obs["group"] != "US_CLOSE":
            # Extend the last completed regular-session interval, not just its
            # subsequent pre/after-market leg. Never sum percentage returns.
            regular = number(closed.get("return"))
            base = closed.get("previous_date")
            if (regular is None or closed.get("date") != context.get("sessions", {}).get("US")
                    or obs.get("previous_date") != closed.get("date") or closed.get("stale")):
                base = None
            else:
                move = (1 + regular) * (1 + move) - 1
                obs["regular_return"] = regular
                obs["subsequent_return"] = obs["return"]
        if not base or not stamp(base) or base >= obs["date"] or move < -1:
            result["missing"].append(ticker)
            result["missing_weight"] += obs["weight"]
            continue
        obs.update(previous_date=base, contribution=obs["weight"] * move, **{"return": move})
        valid[ticker] = obs
    result["observations"] = valid
    for key in result["groups"]:
        rows = [obs for obs in valid.values() if obs["group"] == key]
        result["groups"][key] = {
            "count": len(rows), "coverage": sum(r["weight"] for r in rows),
            "contribution": sum(r["contribution"] for r in rows) if rows else None,
            "dates": sorted({r["date"] for r in rows}),
            "previous_dates": sorted({r["previous_date"] for r in rows}),
        }
    result["coverage"] = sum(r["weight"] for r in valid.values())
    result["total"] = sum(r["contribution"] for r in valid.values()) if valid else None
    for market in ("KR", "US"):
        rows = [r for r in valid.values() if r["market"] == market]
        result["by_market"][market] = sum(r["contribution"] for r in rows) if rows else None
    return result


def cumulative_account_table(metrics, concentration=None):
    from stock_lab_core.report_intraday import _LATEST_GROUP_LABELS

    def pct(value):
        return f"{round(value, 2) or 0:+.2f}%p" if number(value) is not None else "미연결"

    lines = ["구분 | 계좌 기여(추정) | 연결 비중 | 시작 종가일 → 관측일",
             "--- | --- | --- | ---"]
    status = metrics.get("error") or ("전체 추정 보류: 연결 90% 미만" if metrics.get("coverage", 0) < 90 else "비동시 누적 관측·확정 손익 아님")
    lines.append(f"통합 누적 계좌 추정 | {pct(metrics.get('total'))} | {metrics.get('coverage', 0):.1f}% | {status}")
    for key, label in _LATEST_GROUP_LABELS.items():
        group = metrics.get("groups", {}).get(key, {})
        if group.get("count"):
            basis = ", ".join(group["previous_dates"]) + " → " + ", ".join(group["dates"])
            lines.append(f"{label} | {pct(group['contribution'])} | {group['coverage']:.1f}% | {basis}")
    if metrics.get("missing"):
        lines.append(f"미연결 | 미연결 | {metrics['missing_weight']:.1f}% | " + ", ".join(metrics["missing"]) + " · 시세/기준 종가일 확인 필요")
        if number(metrics.get("total")) is not None:
            shock = metrics["missing_weight"] * .03
            lines.append(f"미연결분 ±3% 가정 민감도 | ±{shock:.2f}%p | {metrics['missing_weight']:.1f}% | 연결분 포함 {metrics['total']-shock:+.2f}~{metrics['total']+shock:+.2f}%p · 예측 아님")
    if number(concentration) is not None:
        lines.append(f"미국 지수 ETF 집중도 | - | {concentration:.1f}% | 379810 / 379800 / 418660")
    lines += ["", "- 미국: 최근 확정 정규장의 직전 종가부터 최신 관측까지 누적(정규장 수익률과 이후 등락을 복리 연결). 한국: 당일 정규장의 직전 종가부터 최신 관측까지.",
              "- 종목당 한 번만 현재비중으로 가중합니다. 시장별 기간이 달라 하루 계좌 수익률이 아니며 환율·현금·거래 변동은 미반영입니다.",
              "- 장중·시간외는 미확정입니다. 지연 참고 시세는 제외하며 데이마켓은 거래장소별 가격·유동성이 다를 수 있습니다."]
    return lines
