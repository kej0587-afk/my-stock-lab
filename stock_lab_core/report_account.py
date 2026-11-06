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
    # Decompose only the observations admitted to the unchanged cumulative total.
    us = [r for r in valid.values() if r["market"] == "US"]
    later = [r for r in us if "subsequent_return" in r]
    result["components"] = {
        "US_REGULAR": sum(r["weight"] * r.get("regular_return", r["return"]) for r in us) if us else None,
        "US_SUBSEQUENT": sum(r["weight"] * (1 + r["regular_return"]) * r["subsequent_return"]
                             for r in later) if later else None,
        "KR": result["by_market"]["KR"],
    }
    result["regular_dates"] = sorted({context.get("prices", {}).get(ticker, {}).get("date")
                                      for ticker, row in valid.items() if row["market"] == "US"
                                      and context.get("prices", {}).get(ticker, {}).get("date")})
    return result


def cumulative_account_decomposition(metrics):
    """Display the same connected total, never fill a missing leg with zero."""
    components = metrics.get("components") or {}
    if metrics.get("error") or not components or number(metrics.get("total")) is None:
        return ""
    regular_basis = ", ".join(metrics.get("regular_dates") or []) or "기준일 미연결"
    labels = {"US_REGULAR": f"미국 {regular_basis} 정규장", "US_SUBSEQUENT": "미국 야간·시간외 증분", "KR": "한국"}
    if metrics.get("groups", {}).get("US", {}).get("count"):
        labels["US_SUBSEQUENT"] = "미국 이후 정규장·시간외 증분"
    values = {key: number(components.get(key)) for key in labels}
    rounded = {key: round(value, 2) for key, value in values.items() if value is not None}
    total = round(metrics["total"], 2)
    adjustment = round(total - sum(rounded.values()), 2)
    if adjustment and rounded:
        # Reconcile displayed cents only; all stored contributions stay unchanged.
        key = max(rounded, key=lambda key: (values[key] - rounded[key]) * adjustment)
        rounded[key] = round(rounded[key] + adjustment, 2)
    parts = [f"{label} {rounded[key] or 0:+.2f}%p" if key in rounded else label + " 미연결(합산 제외)"
             for key, label in labels.items()]
    return (" / ".join(parts) + f" = 연결분 합계 {total or 0:+.2f}%p"
            + (" · 표시 반올림 조정" if adjustment else ""))


def cumulative_account_table(metrics, concentration=None):
    from stock_lab_core.report_intraday import _LATEST_GROUP_LABELS, _account_coverage_text

    def pct(value):
        return f"{round(value, 2) or 0:+.2f}%p" if number(value) is not None else "미연결"

    lines = ["구분 | 계좌 기여(추정) | 연결 비중 | 시작 종가일 → 관측일",
             "--- | --- | --- | ---"]
    status = metrics.get("error") or ("전체 추정 보류: 연결 90% 미만" if metrics.get("coverage", 0) < 90 else "비동시 누적 관측·확정 손익 아님")
    label = "통합 누적 계좌 추정" if metrics.get("coverage", 0) >= 90 else "연결분 기여(전체 추정 아님)"
    lines.append(f"{label} | {pct(metrics.get('total'))} | {_account_coverage_text(metrics.get('coverage', 0))} | {status}")
    for key, label in _LATEST_GROUP_LABELS.items():
        group = metrics.get("groups", {}).get(key, {})
        if group.get("count"):
            basis = ", ".join(group["previous_dates"]) + " → " + ", ".join(group["dates"])
            if key in {"US", "US_EXT"}:
                label += " 관측까지 누적"
            lines.append(f"{label} | {pct(group['contribution'])} | {group['coverage']:.1f}% | {basis}")
    if metrics.get("missing"):
        lines.append(f"미연결 | 미연결 | {metrics['missing_weight']:.1f}% | " + ", ".join(metrics["missing"]) + " · 시세/기준 종가일 확인 필요")
        if number(metrics.get("total")) is not None:
            shock = metrics["missing_weight"] * .03
            lines.append(f"미연결분 ±3% 가정 민감도 | ±{shock:.2f}%p | {metrics['missing_weight']:.1f}% | 연결분 포함 {metrics['total']-shock:+.2f}~{metrics['total']+shock:+.2f}%p · 예측 아님")
    if number(concentration) is not None:
        lines.append(f"미국 지수 ETF 집중도 | - | {concentration:.1f}% | 379810 / 379800 / 418660")
    decomposition = cumulative_account_decomposition(metrics)
    if decomposition:
        lines += ["", "**통합행 분해** · " + decomposition,
                  "- 같은 연결분의 재표현이며 위 관측별 누적행과 다시 합산하지 않습니다. 미국 증분은 현재비중 × (1+정규장 수익률) × 이후 수익률로, 복리 교차항을 포함합니다.",
                  "- 미국 종가만 연결된 종목은 정규장분만 포함하며 이후 시세 미연결을 0%로 추정하지 않습니다."]
    lines += ["", "- 미국: 최근 확정 정규장의 직전 종가부터 최신 관측까지 누적(정규장 수익률과 이후 등락을 복리 연결). 한국: 당일 정규장의 직전 종가부터 최신 관측까지.",
              "- 비중 기준은 점검 입력의 현재 평가비중(기간 시작 비중 아님)입니다. 가격 기준시각과 비중 산출시각은 다를 수 있습니다. 현재비중 × 누적 등락은 노출 참고값이며 실제 기간 손익이 아닙니다.",
              "- 시작 비중은 시작 총자산·수량·현금·환율·중간 거래가 있어야 복원됩니다. 현재비중 ÷ (1+수익률)만으로는 시작 총자산 분모가 복원되지 않아 시작비중 기여도를 추정해 채우지 않습니다.",
              "- 종목당 한 번만 현재비중으로 가중합니다. 시장별 기간이 달라 하루 계좌 수익률이 아니며 환율·현금·거래 변동은 미반영입니다.",
              "- 장중·시간외는 미확정입니다. 지연 참고 시세는 제외하며 데이마켓은 거래장소별 가격·유동성이 다를 수 있습니다."]
    return lines
