"""Report estimates reuse portfolio exposure multipliers; never trade signals."""

from stock_lab_core.portfolio import infer_scenario_shock_multiplier
from stock_lab_core.report_evidence import first, number, text

UNDERLYINGS = {
    "379800": ("^GSPC",), "379810": ("QQQ", "^NDX"), "418660": ("QQQ", "^NDX"),
    "SOXL": ("SOXX",), "RAM": ("DRAM",), "TQQQ": ("QQQ",), "QLD": ("QQQ",),
    "BITX": ("BTC-US-CLOSE",), "BITU": ("BTC-US-CLOSE",),
}


def completed_scenario_comparison(row, observations, sessions, now):
    """Compare a prior-US-close scenario to KR daily close, not the opening gap."""
    ticker = text(first(row, "티커", "ticker")).upper()
    code = ticker.split(".")[0]
    own = observations.get(ticker, {})
    actual = number(own.get("return"))
    if code not in {"379800", "379810", "418660", "0167A0", "0227L0"}:
        return None
    if actual is None or own.get("date") != now.date().isoformat():
        return "당일 종가 미수집: 시나리오와 실제 비교 보류"
    if code not in UNDERLYINGS:
        return f"당일 종가 {actual * 100:+.2f}% · 구성종목 기반 수치 시나리오 미제공, 갭 위험 문구로 실제 결과를 대체하지 않음"
    for base in UNDERLYINGS[code]:
        proxy = observations.get(base, {})
        change = number(proxy.get("return"))
        if change is None or proxy.get("date") != sessions.get("US") or own.get("previous_date") != proxy.get("date"):
            continue
        mult = infer_scenario_shock_multiplier({"티커": ticker, "자산명": text(first(row, "종목명", "name"))})
        scenario = change * mult
        return (f"시나리오 {scenario * 100:+.2f}% vs 당일 종가 {actual * 100:+.2f}% · "
                f"차이(실제−시나리오) {(actual - scenario) * 100:+.2f}%p · {base} {proxy['date']} 기준. "
                "시가 갭 오차가 아닌 종가 등락과의 비교, 환율·선물 미반영")
    return "비교 보류: 직전 한국 거래일과 미국 기초자산 기준일 일치 미확인"


def holding_estimate(row, observations, sessions, now):
    ticker = text(first(row, "티커", "ticker")).upper()
    name = text(first(row, "종목명", "자산명", "name"))
    multiplier = infer_scenario_shock_multiplier({"티커": ticker, "자산명": name})
    bases = UNDERLYINGS.get(ticker.split(".")[0], ())
    if not bases:
        return "해당없음", abs(multiplier) > 1
    expected = sessions.get("US")
    own = observations.get(ticker, {})
    domestic = ticker.split(".")[0] in {"379800", "379810", "418660"}
    for base in bases:
        obs = observations.get(base, {})
        value = number(obs.get("return"))
        if value is None or not expected or obs.get("date") != expected:
            continue
        if not domestic and own.get("date") and obs.get("date") != own["date"]:
            continue
        label = "BTC(미국장 마감→마감)" if base == "BTC-US-CLOSE" else base
        prefix = ("월요일 갭 예상 영향(추정)" if now.weekday() == 6 else "다음 한국장 갭 예상 영향(추정)") if domestic else "일간 배수 환산(추정)"
        if domestic and now.weekday() < 5 and now.hour >= 9:
            prefix = "개장 전 기준 갭 시나리오(추정, 실제 등락 아님)"
        note = "환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님" if domestic else "대용 기초자산, 보수·선물 베이시스·추적오차 미반영"
        return (f"{prefix}: {label} {value * 100:+.2f}% × {multiplier:g} = "
                f"{value * multiplier * 100:+.2f}% · {expected} · {note}"), abs(multiplier) > 1
    return "추정 보류: 기준 미국장 마감 시점 기초자산 자료 미수집", abs(multiplier) > 1
