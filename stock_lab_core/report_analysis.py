"""Evidence-based story selection and explicitly conditional economic readings."""

from statistics import median
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
from datetime import datetime
import re

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
        if actual is None or previous is None or metrics["delta"] is None or raw.get("status") in {"pending", "stale"}:
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
        delta = metrics["delta"]
        if row.get("indicator") in {"US_CPI", "US_CORE_CPI", "US_PPI"} and row.get("basis") == "MoM" and row.get("unit") == "%":
            subject = "생산단계 비용 압력" if row["indicator"] == "US_PPI" else "소비자 물가 압력"
            direction = subject + (" 확대: 긴축 유지·인상 압력을 높일 수 있음" if delta > 0 else " 둔화: 추가 긴축 필요성을 낮출 수 있음" if delta < 0 else "의 상승 속도는 전월과 같음")
            lines.append(f"해석(추정): {direction}. 예상치 미확보 시 시장 기대 대비 충격은 판단하지 않습니다.")
        elif row.get("indicator") == "US_NONFARM_PAYROLLS":
            lines.append("해석(추정): " + ("고용 증가 둔화는 금리 부담 완화 기대와 경기 둔화 우려가 공존합니다." if delta < 0 else "고용 증가 확대는 경기 지지와 금리 인하 지연 가능성이 공존합니다."))
        if row.get("reaction_source") and row.get("reaction"):
            lines.append("동일 발표일 관측: " + row["reaction"])
            rate = re.search(r"10Y\s+([+-]?\d+(?:\.\d+)?)bp", row["reaction"])
            if row.get("indicator") in {"US_CPI", "US_CORE_CPI", "US_PPI"} and delta > 0 and rate and float(rate.group(1)) <= -5:
                lines.append("동일일 움직임이 단순 해석과 어긋남: 물가 상승 속도는 높아졌지만 10Y는 하락. 기대 선반영·다른 재료의 기여는 미확인입니다.")
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
    kind = text(row.get("수치종류")) or ("확정 종가" if date != "기준일 미제공" else "종가/장중 미확인")
    fact = f"{ticker} 일간 {ret * 100:+.2f}% · {date}" if ret is not None else f"{ticker} 일간 자료 미수집"
    for keys, label in ((("3개월수익률", "3M"), "3M"), (("가속도",), "가속도")):
        value = number(first(row, *keys))
        if value is not None:
            fact += f" · {label} {value * 100:+.1f}" + ("%p" if label == "가속도" else "%")
    if text(row.get("상태")):
        fact += " · 중기 상태 " + text(row["상태"])
    rate = (macro_data or {}).get("10Y 금리", {})
    rate_bp = number(rate.get("day_change_bp"))
    oil = (macro_data or {}).get("유가", {})
    oil_ret = number(oil.get("day_ret"))
    reading = "직접 원인 자료 미연결"
    if ticker == "XLE" and oil_ret is not None and oil.get("as_of") == date and ret is not None:
        reading = (f"동일일 WTI {oil_ret * 100:+.2f}%와 업종이 " + ("같은 방향" if oil_ret * ret > 0 else "다른 방향") +
                   "; 에너지 가격 경로를 점검하되 선물·주식 수익률만으로 업종 이익 기여를 확정하지 않습니다")
    elif ticker in {"XLU", "XLK", "XLC"} and rate_bp is not None and rate.get("as_of") == date and ret is not None:
        reading = f"동일일 10Y {rate_bp:+.2f}bp와 업종 {ret * 100:+.2f}%"
        if abs(rate_bp) < 5:
            reading += "; 5bp 미만의 작은 변화로 업종 급등락의 금리 원인을 단정하지 않음"
        elif rate_bp > 0 and ret < 0:
            reading += "; 금리 상승에 따른 할인율 부담 가능성"
        elif rate_bp < 0 and ret > 0:
            reading += "; 금리 하락에 따른 할인율 부담 완화 가능성"
        else:
            reading += "; 단순한 금리-주가 역방향 설명과 어긋나므로 다른 요인을 확인해야 함"
        if "할인율 부담" in reading:
            reading += f" [연준 할인율 설명]({FED_VALUATIONS})"
    region = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
    related = [item for item in news if text(item.get("ticker")).upper() == ticker
               and item.get("market") == region and item.get("session_date") == date
               and item.get("news_bucket") not in {"next_session_news", "other_market_news"}]
    unconfirmed = "해당 업종 움직임의 개별 원인·기여도는 확정 자료 없음"
    if related:
        item = related[0]
        if reading == "직접 원인 자료 미연결":
            reading = ""
        from stock_lab_core.report_presentation import news_theme
        topic = ((news_theme(text(item.get("title"))) + "(기사 주장)") if news_theme(text(item.get("title"))) else
                 "AI 관련 시장 움직임" if any(re.search(r"AI|인공지능", text(r.get("title")), re.I) for r in related) else "해당 업종 움직임")
        scope = "시장 공통 맥락, 해당 업종의 직접 원인 아님" if item.get("market_context_only") else "인과 기여 미확정"
        reading += ((" · " if reading else "") + f"{topic}: " + (f"복수 기사 {len(related)}건이 거론(기사 주장). " if len(related) > 1 else "")
                    + f"제목 기준 보도(기사 주장, {scope}): " + text(item.get("title")) + " " + citation(dict(item, title="원문")))
    return {"fact": "사실: " + fact + f" [{kind}]",
            "reading": "해석(추정): " + reading,
            "unconfirmed": "미확인: " + unconfirmed}
