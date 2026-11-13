"""Render the holdings block from one prepared report snapshot; no fetching."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, text, number, stamp, holding_reasons, _pct, _cell
from stock_lab_core.report_presentation import compact_holding_reference, kst_time
from stock_lab_core.report_intraday import account_overview_lines, extended_quote_text, valid_live_observation
from stock_lab_core.report_scenario import scenario_observation_line

register_loaded_source(__name__, __file__)


def holdings_impact_lines(*, context, held, observations, sessions, states, mode, now,
                         live, live_metrics, portfolio, latest_metrics, scenario_context,
                         summary_available=True):
    if not summary_available:
        from stock_lab_core.report_input_status import MISSING_ACCOUNT
        return ["", "## 내 보유 종목 영향", MISSING_ACCOUNT], ["보유목록 입력 미수집"]
    from stock_lab_core.report_holdings import holding_estimate, completed_scenario_comparison, hedge_policy_line, hedge_source_lines
    lines, missing = [], []
    checked = max(now, stamp(context.get("quote_checked_at")) or now)
    holdings_header = ("종목 | 최신 종가 일간(실제·기준일) | 실제 누적 vs 기초자산 누적 / 일간 참고 | 상태/사유"
                       if mode == "closed" else "종목 | 기준일 일간(확정 종가) | 실제 누적 vs 기초자산 누적 / 일간 참고 | 당일 현재(장중·미확정) | 상태/사유"
                       if mode == "intraday" else "종목 | 기준일 일간(실제) | 개장 전 갭 시나리오/배수 참고(추정) | 당일 현재(실제) | 상태/사유")
    account_lines = account_overview_lines(live_metrics, portfolio, sessions, mode, latest_metrics=latest_metrics)
    from stock_lab_core.report_fx import portfolio_fx_lines
    account_lines.extend(portfolio_fx_lines(held, context, states, max(now, stamp(context.get("quote_checked_at")) or now)))
    lines.extend(["", "## 내 보유 종목 영향", *account_lines,
                  "재현 기준: 통합행은 현재비중(%) × 위에서 정의한 종목별 누적 수익률(%) ÷ 100입니다. 아래 종가 일간·시나리오 표는 별도 참고이며 통합행에 다시 합산하지 않습니다.",
                  "", holdings_header, "--- | --- | --- | ---" if mode == "closed" else "--- | --- | --- | --- | ---"])
    for row in held:
        ticker = text(first(row, "티커", "ticker"))
        obs = observations.get(ticker, {})
        value = obs.get("return")
        estimate = "해당없음"
        reasons = holding_reasons(row)
        estimate, leveraged = holding_estimate(row, observations, sessions, now, intraday_prices=live)
        if estimate != "해당없음":
            estimate = "일간 참고(누적 비교 아님): " + estimate
        if mode == "closed" or (mode == "intraday" and ticker.split(".")[0] in {"379800", "379810", "418660"}):
            estimate = completed_scenario_comparison(row, observations, sessions,
                                                     max(now, stamp(context.get("quote_checked_at")) or now) if mode == "intraday" else now,
                                                     price_frames=context.get("price_frames"),
                                                     intraday_prices=live if mode == "intraday" else None,
                                                     scenario_frames=context.get("scenario_frames")) or estimate
            if ticker.split(".")[0] not in {"379800", "379810", "418660"}:
                estimate += scenario_observation_line(row, scenario_context)
        elif ticker == "0167A0.KS":
            semi_live = live.get("SOXX", {})
            use_live = valid_live_observation(semi_live, "US", checked, states=states)
            semi = semi_live if use_live else observations.get("SOXX", {})
            if number(semi.get("return")) is not None:
                kind = "장중 진행·확정 아님" if use_live else "확정 종가 참고(과거 영향 재계상 안 함)"
                estimate = f"미국 반도체 SOXX {_pct(semi['return'])} · {semi.get('date', '미확인')} {kind} · 구성·환율 차이로 이 한국 ETF의 갭 수치 산출 안 함"
        if ticker.split(".")[0] in {"379800", "379810", "418660"}:
            estimate = compact_holding_reference(estimate)
            hedge = hedge_policy_line(row)
            if hedge and hedge not in estimate:
                estimate += " · " + hedge
        current = live.get(ticker, {})
        actual_now = "해당없음"
        region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        if states[region]["phase"] == "intraday":
            actual_now = (_pct(current["return"]) + f" ({current['date']} 장중 진행·확정 아님; {kst_time(current.get('as_of', current.get('retrieved_at')))})"
                          if valid_live_observation(current, region, checked, states=states) else "시각 확인 가능한 시세 미수집")
        elif region == "US":
            extended = context.get("extended_prices", {}).get(ticker, {})
            actual_now = (extended_quote_text(context, ticker, max(now, stamp(context.get("quote_checked_at")) or now))
                          or "정규장 외 · 데이마켓/시간외 시세 미연결: " + context.get("extended_quote_status", {}).get(ticker, "제공처 응답·시각 미확인"))
            if mode == "closed" and (extended or context.get("extended_reference_prices", {}).get(ticker)):
                reasons.append("별도 세션 " + actual_now)
        if leveraged:
            reasons = [reason for reason in reasons if reason != "개별 위험사유 없음"]
            if "레버리지 보유" not in reasons:
                reasons.append("레버리지 보유")
        weight = number(first(row, "현재비중", "current_w"))
        if weight is not None and 0 <= weight <= 100:
            reasons.append(f"현재비중 {weight:.2f}%")
            if number(value) is not None and obs.get("date") == sessions.get(region) and not portfolio.get("error"):
                reasons.append(f"일간 기여 {round(weight * number(value), 2) or 0.0:+.2f}%p(내부 추정)")
            else:
                reasons.append("일간 기여 미확인")
        else:
            reasons.append("현재비중·일간 기여 미연결")
        close_cell = _pct(value) + (f" ({obs['date']} 확정 종가)" if obs.get("date") else "")
        if obs.get("stale"):
            close_cell = "최신 종가 미수집 · 과거 참고 " + close_cell
        cells = [f"{text(first(row, '종목명', 'name'))}({ticker})", close_cell, estimate]
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
    if any(text(first(row, "티커", "ticker")).split(".")[0] in {"379800", "379810", "418660"} for row in held):
        lines.extend(["", "보유표 공통 각주(379800/379810/418660)",
                      "- 비교 기준: 직전 한국 종가 15:30→당일 종가 15:30 또는 한국 ETF·선물의 같은 시각 완료 5분봉. 동일 끝값이 없으면 비교를 보류합니다.",
                      "- 원/달러는 같은 구간 관측을 별도로 표시합니다. 단순 차이는 환율·보수·베이시스를 조정한 추적오차가 아니며 레버리지의 배수 잔차는 산출하지 않습니다.",
                      "- 아래 미국 종가 이후 선물 관측은 별도 참고 구간입니다. 위 차이에 더하지 않습니다. 같은 시각 NAV/iNAV 미연결로 괴리율은 미확인입니다."])
        for codes, label in (({"379810", "418660"}, "나스닥 ETF 379810/418660 공유(NQ=F)"),
                             ({"379800"}, "S&P500 ETF 379800(ES=F)")):
            group = next((row for row in held if text(first(row, "티커", "ticker")).split(".")[0] in codes), None)
            if group is not None:
                observation = compact_holding_reference(scenario_observation_line(group, scenario_context))
                lines.append("- " + label + " 잔차 설명참고: 누적 비교 잔차와 별개인 장중 선물/환율 관측구간이며 인과분해·기여도 합산 아님" + observation)
        lines.extend(hedge_source_lines(held))
    return lines, missing
