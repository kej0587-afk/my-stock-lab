"""Evidence-based story selection and explicitly conditional economic readings."""

from statistics import median
from datetime import datetime

from stock_lab_core.report_evidence import citation, first, number, records, text

INDICATOR_NAMES = {
    "US_CPI": "미국 CPI", "US_CORE_CPI": "미국 근원 CPI", "US_PPI": "미국 PPI",
    "US_NONFARM_PAYROLLS": "미국 비농업고용 증감", "US_UNEMPLOYMENT": "미국 실업률",
    "US_RETAIL_SALES": "미국 소매판매", "KR_CPI": "한국 CPI", "KR_EXPORTS": "한국 수출",
}
BLS_CONCEPTS = "https://www.bls.gov/opub/hom/cpi/concepts.htm"
FED_VALUATIONS = "https://www.federalreserve.gov/publications/may-2021-asset-valuations.htm"
OUTLIER_SOURCE = "https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm"


def unit_label(unit, *, difference=False):
    if unit == "%":
        return "%p" if difference else "%"
    return {"thousand persons": "천 명", "unknown": "단위 미확인"}.get(unit, unit or "단위 미확인")


def prior_history(row):
    period = text(row.get("period"))
    values = {}
    for item in records(row.get("history")):
        at, value = text(item.get("period")), number(item.get("value"))
        if at and period and at < period and value is not None:
            values[at] = value
    return sorted(values.items())


def comparison_metrics(row):
    actual, previous = number(row.get("actual")), number(row.get("previous"))
    compatible = (row.get("previous_unit") in (None, "", row.get("unit"))
                  and row.get("previous_basis") in (None, "", row.get("basis")))
    delta = actual - previous if compatible and actual is not None and previous is not None else None
    history = prior_history(row)
    prior3 = None
    if len(history) >= 3:
        try:
            year, month = map(int, str(row["period"]).split("-"))
            keys = []
            for back in (1, 2, 3):
                value = year * 12 + month - 1 - back
                keys.append(f"{value // 12:04d}-{value % 12 + 1:02d}")
            mapping = dict(history)
            if all(key in mapping for key in keys):
                prior3 = sum(mapping[key] for key in keys) / 3
        except (ValueError, TypeError):
            pass
    return {"delta": delta, "prior3_mean": prior3,
            "vs_prior3": actual - prior3 if actual is not None and prior3 is not None else None}


def outlier_check(row):
    """Flag for inspection, never delete/correct an unusual official observation."""
    history = [value for _, value in prior_history(row)][-36:]
    value = number(row.get("actual"))
    if row.get("basis") != "MoM" or value is None or len(history) < 12:
        return {"flag": False, "status": "분포 점검 이력 부족", "count": len(history)}
    center = median(history)
    mad = median(abs(item - center) for item in history)
    if mad == 0:
        flag = value < min(history) or value > max(history)
        score = None
    else:
        score = 0.6745 * (value - center) / mad
        flag = abs(score) > 3.5
    return {"flag": flag, "status": "원자료 재확인 필요(통계상 이상치, 오류 확정 아님)" if flag else "분포 점검 범위 내",
            "count": len(history), "modified_z": score, "source_url": OUTLIER_SOURCE}


def select_economic_stories(rows, limit=3):
    """Rank scaled changes, one row per indicator; prefer MoM for monthly events.

    Unlike raw 104 thousand vs 0.8 percentage points, abs(delta)/abs(previous)
    is unit invariant. Zero previous uses the median historical absolute value;
    without a nonzero scale it is not cross-indicator ranked.
    """
    candidates = {}
    for raw in records(rows):
        actual, previous = number(raw.get("actual")), number(raw.get("previous"))
        metrics = comparison_metrics(raw)
        if actual is None or previous is None or metrics["delta"] is None or raw.get("status") == "pending":
            continue
        history = [abs(value) for _, value in prior_history(raw)]
        scale = abs(previous) or (median(history) if history else 0)
        if not scale:
            continue
        row = dict(raw, story_change=metrics["delta"], story_rank=abs(metrics["delta"]) / scale)
        key = text(row.get("indicator"))
        old = candidates.get(key)
        if old is None or ((row.get("basis") == "MoM", row["story_rank"]) >
                           (old.get("basis") == "MoM", old["story_rank"])):
            candidates[key] = row
    return sorted(candidates.values(), key=lambda row: (-row["story_rank"], text(row.get("indicator"))))[:limit]


def economic_story_lines(rows, limit=3):
    lines = []
    for row in select_economic_stories(rows, limit):
        metrics = comparison_metrics(row)
        basis = {"MoM": "전월비", "YoY": "전년비", "level": "수준"}.get(row.get("basis"), "비교기준 미확인")
        unit = unit_label(row.get("unit"))
        diff = unit_label(row.get("unit"), difference=True)
        line = (f"사실: {row.get('period', '')} {INDICATOR_NAMES.get(row.get('indicator'), row.get('indicator'))} {basis} "
                f"{row['actual']}{unit}, 이전 {row['previous']}{unit} → 변화 {metrics['delta']:+.2f}{diff}")
        if metrics["prior3_mean"] is not None:
            line += f" · 직전 3개월 평균 {metrics['prior3_mean']:.2f}{unit} 대비 {metrics['vs_prior3']:+.2f}{diff}"
        if row.get("forecast") is None:
            line += " · 이전/추세 비교이며 컨센서스 서프라이즈 아님"
        checked = outlier_check(row)
        if checked["flag"]:
            line += f" · {checked['status']} [분포 점검]({OUTLIER_SOURCE})"
        lines.append(line + ". " + citation(row))
    return lines


def inflation_reading(rows, context):
    monthly = {row.get("indicator"): row for row in records(rows)
               if row.get("basis") == "MoM" and row.get("unit") == "%" and number(row.get("actual")) is not None}
    headline, core = monthly.get("US_CPI"), monthly.get("US_CORE_CPI")
    if not headline or not core or headline.get("period") != core.get("period"):
        return "미확인: 같은 관측월·전월비의 헤드라인/근원 CPI 쌍이 없어 격차 해석을 보류합니다."
    if headline.get("seasonal_adjustment", "unknown") != core.get("seasonal_adjustment", "unknown"):
        return "미확인: CPI 계절조정 기준이 달라 격차 해석을 보류합니다."
    gap = float(headline["actual"]) - float(core["actual"])
    detail = f"헤드라인 {headline['actual']}% − 근원 {core['actual']}% = 격차 {gap:+.2f}%p"
    previous_h, previous_c = number(headline.get("previous")), number(core.get("previous"))
    if previous_h is not None and previous_c is not None:
        change = gap - (previous_h - previous_c)
        detail += f" (이전 격차 {previous_h - previous_c:+.2f}%p, 변화 {change:+.2f}%p)"
    monthly_oil = context.get("macro_monthly_changes", {}).get(headline.get("period"), {})
    oil_value = number(monthly_oil.get("WTI"))
    oil_text = (f" · 같은 관측월 WTI {oil_value:+.2f}%와 " +
                ("방향 일치" if gap * oil_value > 0 else "방향 불일치/중립")) if oil_value is not None else " · 같은 관측월 WTI 자료 미연결로 방향 비교 보류"
    return (f"해석(추정): {detail}. 식품·에너지를 제외하는 근원과의 차이는 식품/에너지 가격 영향 가능성을 시사하지만 가중치·개별 기여도는 확정할 수 없습니다"
            f"{oil_text}. [BLS 지표 정의]({BLS_CONCEPTS}) " + citation(headline))


def sector_evidence(row, macro_data, news):
    ticker = text(first(row, "Ticker", "ticker", "티커"))
    ret = number(first(row, "1일수익률", "1D"))
    date = text(first(row, "기준일", "date", "as_of")) or "기준일 미제공"
    fact = f"{ticker} 일간 {ret * 100:+.2f}% · {date}" if ret is not None else f"{ticker} 일간 자료 미수집"
    rate = (macro_data or {}).get("10Y 금리", {})
    rate_bp = number(rate.get("day_change_bp"))
    oil = (macro_data or {}).get("유가", {})
    oil_ret = number(oil.get("day_ret"))
    reading = "수집된 업종 가격만으로 금리·실적 등 경제적 경로를 구분할 수 없습니다"
    if ticker == "XLE" and oil_ret is not None and oil.get("as_of") == date and ret is not None:
        reading = (f"동일일 WTI {oil_ret * 100:+.2f}%와 업종이 " + ("같은 방향" if oil_ret * ret > 0 else "다른 방향") +
                   "; 에너지 가격 경로를 점검하되 선물·주식 수익률만으로 업종 이익 기여를 확정하지 않습니다")
    elif ticker in {"XLU", "XLK", "XLC"} and rate_bp is not None and rate.get("as_of") == date and ret is not None:
        reading = f"동일일 10Y {rate_bp:+.2f}bp와 업종 {ret * 100:+.2f}%"
        if rate_bp > 0 and ret < 0:
            reading += "; 금리 상승에 따른 할인율 부담 가능성"
        elif rate_bp < 0 and ret > 0:
            reading += "; 금리 하락에 따른 할인율 부담 완화 가능성"
        else:
            reading += "; 단순한 금리-주가 역방향 설명과 어긋나므로 다른 요인을 확인해야 함"
        reading += f" [연준 할인율 설명]({FED_VALUATIONS})"
    related = [item for item in news if text(item.get("ticker")).upper() == ticker]
    unconfirmed = "해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음"
    if related:
        unconfirmed += " · 관련 보도(인과 아님): " + citation(related[0])
    return {"fact": "사실: " + fact + " [공급처 일봉 종가]",
            "reading": "해석(추정): " + reading,
            "unconfirmed": "미확인: " + unconfirmed}
