"""Read-only synthesis of validated holding evidence; no new trade rules or IO."""

import pandas as pd

from stock_lab_core.report_evidence import number, safe_link, text


def _flow_reading(rows):
    sentences = []
    for row in rows[:2]:
        five, medium = number(row.get("five")), number(row.get("medium"))
        symbol, day = row["ticker"], row["date"]
        if five is None or medium is None:
            continue
        basis = f"{symbol}({day}) 5일 {five * 100:+.2f}% · 3개월 {medium * 100:+.2f}%"
        if five < 0 < medium:
            meaning = "중기 상승 안에서 단기 흐름은 약해져, 장기 성장 기대와 당장의 보유위험을 나눠 볼 구간입니다"
        elif five > 0 > medium:
            meaning = "중기 약세 속 반등이므로 회복 시도와 추세 회복 확정을 구분해야 합니다"
        elif five < 0 and medium < 0:
            meaning = "단기·중기 흐름이 함께 약해 기존 축소 조건을 점검할 가격 근거가 있습니다"
        elif five > 0 and medium > 0:
            meaning = "단기·중기 흐름은 보유 가설을 뒷받침하지만 비중·게이트 제한을 해제하지는 않습니다"
        else:
            meaning = "이 구간의 수익률만으로 보유 방향을 확정하기 어렵습니다"
        sentence = basis + ": " + meaning + "."
        score = number(row.get("flow_score"))
        if score is not None:
            sentence += f" 돈흐름 지표 {score:+.1f}점은 실제 순매수액이 아닙니다."
            if five > 0 and score < 0:
                sentence += " 가격 반등과 돈흐름 지표가 엇갈립니다."
        sentences.append(sentence)
    return " ".join(sentences) or "같은 기준일의 5일·3개월 흐름이 부족해 추세에 근거한 보유·축소 해석은 보류합니다."


def _earnings_reading(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row["기업"], row["발표/기간"]), []).append(row)
    summaries, excerpts = [], []
    for (name, period), items in groups.items():
        confirmed = {row["항목"]: row for row in items
                     if row.get("구분") in {"공식 발표", "회사 전망 · 실제치 아님"}
                     and safe_link(row.get("출처")) and text(row.get("근거"))}
        if not confirmed:
            continue
        checks = ["설비투자(CAPEX)", "잉여현금흐름(FCF)", "회사 전망"]
        missing = [key for key in checks if key not in confirmed]
        available = "·".join(key for key in ("매출", "이익·EPS", *checks) if key in confirmed)
        summary = f"{name}({period})은 {available} 자료가 확인됐습니다."
        if missing:
            summary += " 다만 " + "·".join(missing) + "이 미연결되어 이익이 투자 후 현금으로 남는지와 앞으로의 성장 가설은 아직 충분히 검증되지 않았습니다."
        else:
            summary += " 투자·현금흐름·전망을 함께 대조할 수 있지만, 전망은 실제치가 아니며 자료 연결 자체가 실적 호조나 저평가 판정은 아닙니다."
        summaries.append(summary)
        # Keep source prose and its period intact, not a guessed sentiment score.
        for key in ("회사 전망", "잉여현금흐름(FCF)", "설비투자(CAPEX)", "매출", "이익·EPS"):
            if key in confirmed:
                row = confirmed[key]
                excerpts.append({"기업": name, "발표/기간": period, "항목": key,
                                 "확인 근거 · 원문": row["근거"], "구분": row["구분"], "출처": row["출처"]})
    return summaries, excerpts


def build_holding_evidence_commentary(ticker, review, choices=None):
    """Existing choice labels determine priority; evidence never changes a gate."""
    rows = choices.to_dict("records") if isinstance(choices, pd.DataFrame) else []
    choice_map = {row.get("검토 방향"): row for row in rows}
    keep = choice_map.get("보유 유지", {})
    reduce = choice_map.get("축소 / 손절 검토", {})
    cash = choice_map.get("현금 대기", {})
    # holding_choice_rows formats this field as '<existing label> · <valuation>'.
    existing = text(keep.get("현재 근거")).split(" · ", 1)[0]
    if existing in {"축소/교체 검토", "위성/집중 축소 검토", "비중초과 관리"}:
        headline = f"{ticker}: 기존 '{existing}'에 따라 노출 조절 조건부터 검토합니다. 기업 성장 전망을 유지하는 것과 지금 상품·비중을 그대로 유지하는 것은 별개입니다."
    elif "유지" in existing:
        headline = f"{ticker}: 기존 '{existing}'를 유지하면서 실적 가설과 비중을 점검합니다. 최신 근거가 좋아 보여도 추가매수 승인으로 바꾸지 않습니다."
    elif existing and existing not in {"미확인", "기존 보유관리 계산 전"}:
        headline = f"{ticker}: 기존 '{existing}'의 재개 조건 확인이 먼저입니다. 신규 자금의 현금 대기와 이미 보유한 물량의 축소는 별도로 검토합니다."
    else:
        headline = f"{ticker}: 연결된 자료는 설명할 수 있지만 기존 보유관리 판정이 없어 보유·축소 우선순위는 보류합니다."
    earnings, excerpts = _earnings_reading(review.get("earnings", []))
    company = " ".join(earnings[:2]) or "검증된 구성기업 실적·전망이 미연결입니다. 실적 호조나 회복을 가정해 보유 지속을 정당화하지 않습니다."
    if len(earnings) > 2:
        company += f" 그 외 {len(earnings) - 2}개 기업의 근거는 상세 표에 있습니다."
    if any("구성기업" in text(row.get("연결")) for row in review.get("earnings", [])):
        company += " 이는 연결된 일부 구성기업 근거이며 ETF 전체 실적·기여율은 아닙니다."
    flow = _flow_reading(review.get("flow_evidence", []))
    recent = [number(row.get("five")) for row in review.get("flow_evidence", [])]
    recent = [value for value in recent if value is not None]
    if recent and all(value < 0 for value in recent) and excerpts:
        connection = "공식 실적 자료는 연결됐지만 최근 가격 흐름은 약합니다. 발표 확인을 실적 호조나 주가 회복으로 바꾸어 읽지 말고, 기존 축소·비중 조건을 함께 검토할 상황입니다."
    elif recent and any(value > 0 for value in recent) and not excerpts:
        connection = "가격 반등 근거는 있지만 기업 실적·전망 대조가 비어 있습니다. 반등만으로 보유 가설을 강화하거나 신규 자금을 투입할 근거는 부족합니다."
    elif excerpts:
        connection = "기업 발표와 가격 흐름을 함께 점검할 자료는 생겼습니다. 다만 예상치 대비 실적, 투자 후 현금흐름, 상품 위험까지 확인하기 전에는 기존 보유관리 방향을 바꾼 것으로 해석하지 않습니다."
    else:
        connection = "기업 근거가 비어 있어 가격 흐름만으로 성장 가설을 검증할 수 없습니다. 확인 전 신규 자금의 현금 대기를 검토하는 것과 보유물량을 매도하는 결정은 구분합니다."
    holding_facts = [row for row in review.get("facts", []) if row.get("대상") == ticker
                     and text(row.get("근거")).startswith("보유 종목")
                     and "미연결" not in text(row.get("관측")) and "미정합" not in text(row.get("관측"))]
    live_facts = [row for row in holding_facts if " · " in text(row.get("근거"))]
    observations = live_facts or holding_facts[:1]
    current = " / ".join(f"{row['근거']}: {row['관측']} ({row['기준']})" for row in observations)
    conditions = [
        {"검토 방향": "보유", "근거를 어떻게 읽을까": "기업 실적·전망과 가격 흐름이 보유 가설을 지지하는지 함께 봅니다. 좋은 실적만으로 레버리지·집중 위험을 상쇄하지 않습니다.",
         "대응을 바꾸기 전 확인": text(keep.get("확인할 조건")) or "기존 보유관리·정밀 최종 체크 연결 필요"},
        {"검토 방향": "축소", "근거를 어떻게 읽을까": ("기존 관리 근거: " + text(reduce.get("현재 근거")) + ". " if text(reduce.get("현재 근거")) else "") + "약한 흐름이나 실적 공백은 점검 근거이지 자동 손절 신호가 아닙니다. 성장 가설과 상품 노출을 분리해 비교합니다.",
         "대응을 바꾸기 전 확인": text(reduce.get("확인할 조건")) or "기존 비중·손실 관리 조건 미연결 · 임의 손절선 제시 안 함"},
        {"검토 방향": "현금 대기", "근거를 어떻게 읽을까": "신규 투입을 보류하는 선택입니다. 보유 전량 매도나 다른 후보로 교체하라는 뜻이 아니며 미연결 자료를 정상으로 간주하지 않습니다.",
         "대응을 바꾸기 전 확인": text(cash.get("확인할 조건")) or "시장·종목 게이트 및 정밀 최종 체크 재확인 필요"},
    ]
    news = review.get("news", [])
    return {"headline": headline, "current": current, "flow": flow, "company": company, "connection": connection, "conditions": conditions,
            "evidence": excerpts, "news": news[:1]}


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
