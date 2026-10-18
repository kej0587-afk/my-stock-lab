"""Report estimates reuse portfolio exposure multipliers; never trade signals."""

from stock_lab_core.portfolio import infer_scenario_shock_multiplier
from stock_lab_core.report_evidence import first, number, text

UNDERLYINGS = {
    "379800": ("^GSPC",), "379810": ("QQQ", "^NDX"), "418660": ("QQQ", "^NDX"),
    "SOXL": ("SOXX",), "RAM": ("DRAM",), "TQQQ": ("QQQ",), "QLD": ("QQQ",),
    "BITX": ("BTC-US-CLOSE",), "BITU": ("BTC-US-CLOSE",),
}


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
        note = "환율·선물·추적오차 미반영, 확정 갭/가격 예측 아님" if domestic else "대용 기초자산, 보수·선물 베이시스·추적오차 미반영"
        return (f"{prefix}: {label} {value * 100:+.2f}% × {multiplier:g} = "
                f"{value * multiplier * 100:+.2f}% · {expected} · {note}"), abs(multiplier) > 1
    return "추정 보류: 기준 미국장 마감 시점 기초자산 자료 미수집", abs(multiplier) > 1
