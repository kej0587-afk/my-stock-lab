"""Display-only FX sensitivity from already aligned observations; no collection."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, number, text

register_loaded_source(__name__, __file__)


def adjusted_reference(comparison, code):
    # A daily-reset leveraged fund cannot be replicated by scaling one future.
    if code not in {"379800", "379810"}:
        return ""
    base, fx = number(comparison.get("reference")), number(comparison.get("fx_return"))
    if base is None or fx is None:
        return ""
    result = ((1 + base) * (1 + fx) - 1) * 100
    return f" · 환율 조정 참고값 {result:+.2f}%(선물×원/달러 복리 환산, NAV·추적오차 아님)"


def portfolio_fx_lines(held, context, states, now):
    from stock_lab_core.report_holdings import HEDGE_POLICIES, cumulative_holding_comparison
    from stock_lab_core.report_presentation import kst_time

    held = list(held)
    checked, total_weight = set(), 0.0
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        weight = number(first(row, "현재비중", "current_w", "current_weight"))
        if not ticker or ticker in checked or weight is None or not 0 <= weight <= 100:
            return ["환율 영향 추정 보류: 중복 종목 또는 비중 결측·범위 오류."]
        checked.add(ticker)
        total_weight += weight
    if total_weight > 100.01:
        return ["환율 영향 추정 보류: 현재비중 합계가 100% 초과."]
    exposure, seen, groups, missing = 0.0, set(), {}, []
    reported = False
    for row in held:
        ticker = text(first(row, "티커", "ticker")).upper()
        code = ticker.split(".")[0]
        weight = number(first(row, "현재비중", "current_w", "current_weight"))
        if code not in HEDGE_POLICIES or not weight:
            continue
        seen.add(ticker)
        exposure += weight
        reported |= code == "418660"
        c = cumulative_holding_comparison(row, context.get("prices", {}), context.get("sessions", {}), now,
            context.get("price_frames"), scenario_frames=context.get("scenario_frames"),
            intraday_prices=context.get("intraday_prices", {}) if states["KR"]["phase"] == "intraday" else None)
        fx = number(c.get("fx_return"))
        if fx is None or c.get("error"):
            missing.append(ticker)
            continue
        key = (c["base_at"], c["as_of"])
        group = groups.setdefault(key, {"weight": 0.0, "impact": 0.0})
        group["weight"] += weight
        group["impact"] += weight * fx
    if not seen:
        return []
    lines = ["", f"환노출 확인 ETF 비중 {exposure:.1f}% ({', '.join(sorted(seen))})."]
    if reported:
        lines.append("418660은 운용사 인용 보도 기준 환노출이며 최신 상품 문서 재확인이 필요합니다.")
    if groups:
        lines += ["", "동일 시각 환율 구간 | 연결 비중 | 환율 영향 근사치", "--- | --- | ---"]
        for (start, end), group in groups.items():
            impact = round(group['impact'], 2) or 0.0
            lines.append(f"{kst_time(start)}→{kst_time(end)} | {group['weight']:.1f}% | {impact:+.2f}%p")
        lines.append("현재비중×동일 시각 원/달러 변동의 단순 민감도입니다. ETF 가격에 반영된 환율 효과를 분해한 값이 아니며 계좌 추정에 다시 더하지 않습니다. 레버리지 재설정·환율과 기초자산의 교차효과는 미반영입니다.")
    if missing:
        lines.append("환율 영향 미연결: " + ", ".join(missing) + " · 동일 시각 자료 부족, 0으로 대체하지 않음.")
    return lines
