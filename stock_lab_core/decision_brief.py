"""One read-only explanation contract; never score, fetch, or authorize trades."""

from collections.abc import Mapping
from copy import deepcopy
import math

import pandas as pd

from stock_lab_core.execution_readiness import build_execution_readiness
from stock_lab_core.formatters import format_currency


def text(value, default="미확인"):
    if value is None or not pd.api.types.is_scalar(value) or pd.isna(value):
        return default
    value = str(value).strip()
    return value if value.lower() not in {"", "-", "nan", "none", "nat"} else default


def _weight(value):
    try:
        number = float(value)
        return f"{number:.1f}%" if math.isfinite(number) and 0 <= number <= 100 else "미확인"
    except (ValueError, TypeError):
        return "미확인"


def build_decision_brief(workflow, *, source, calculated_at=None, final_check=None):
    """Keep one source row intact. Conditional plans are not event detections."""
    row = deepcopy(dict(workflow)) if isinstance(workflow, Mapping) else {}
    ready = build_execution_readiness(row, final_check)
    ticker = text(row.get("티커"))
    price = text(row.get("현재가"))
    if price == "미확인":
        try:
            raw = float(row.get("현재가원값"))
            if math.isfinite(raw) and raw > 0:
                price = format_currency(raw, ticker)
        except (ValueError, TypeError):
            pass
    restrictions = text(row.get("게이트근거"))
    entry = text(row.get("1차기준"))
    entry_condition = text(row.get("1차조건"))
    stop, target = text(row.get("손절가")), text(row.get("차트목표"))
    status = "최종 체크 포함" if isinstance(final_check, Mapping) and final_check else "종목 선별 · 최종 체크 전"
    layers = [
        {"단계": "자료 기준", "상태": text(row.get("가격자료기준일")),
         "근거": text(row.get("가격반영")),
         "확인": text(row.get("가격신선도근거"), text(row.get("데이터상태")))},
        {"단계": "시장 환경", "상태": text(row.get("시장실행상태")),
         "근거": text(row.get("매크로상태")), "확인": "신규·추가 진입 제한과 보유 매도 판단은 별개"},
        {"단계": "기업·상품 자료", "상태": text(row.get("유형")),
         "근거": text(row.get("재무자료기간")),
         "확인": text(row.get("재무자료상태")) + " · 기술적 후보등급은 저평가 검증이 아님"},
        {"단계": "종목·상품", "상태": text(row.get("🔥기술적 타점"), text(row.get("기술적타점"))),
         "근거": text(row.get("핵심근거")),
         "확인": "상위 시간대: " + text(row.get("상위시간대상태"))},
        {"단계": "계좌 실행", "상태": ready["label"], "근거": ready["reason"],
         "확인": f"현재 {_weight(row.get('현재비중'))} / 목표 {_weight(row.get('목표비중'))} · {status}"},
    ]
    scenarios = [
        {"상황": "회복·진입 재검토", "조건": f"기존 1차 기준 {entry} · {entry_condition}",
         "대응": "원계획 재검토" if ready["execution_allowed"] else "현금 대기 · 제한 해소와 최종 체크를 먼저 확인",
         "재확인": restrictions + " · 가격 조건만 충족해도 시장·종목 제한은 해제되지 않음"},
        {"상황": "목표 접근·보유 관리", "조건": f"기존 차트 목표 {target}",
         "대응": "기존 익절·보유 계획 재점검" if target != "미확인" else "목표 자료 미확인 · 가격 제시 보류",
         "재확인": text(row.get("R/R출처")) + " · 실제 도달·익절 완료 여부 미확인"},
        {"상황": "이탈·악화 점검", "조건": f"기존 손절 참고선 {stop}",
         "대응": "축소·손절 조건 점검" if stop != "미확인" else "손절 자료 미확인 · 가격 제시 보류",
         "재확인": "계획의 시간봉·확인봉·갭 및 체결 지연 확인 · 참고선만으로 자동 매도하지 않음"},
    ]
    return {
        "ticker": ticker, "name": text(row.get("종목명"), text(row.get("자산명"), ticker)),
        "source": source, "calculated_at": text(calculated_at, text(row.get("계산시각"))), "price": price,
        "basis": text(row.get("가격자료기준일")), "price_basis": text(row.get("가격반영")),
        "decision": text(row.get("최종읽기")), "code": text(row.get("판정코드")),
        "gate": text(row.get("게이트상태")), "ready": ready,
        "layers": layers, "scenarios": scenarios,
        "plan": {"1차 기준": entry, "조건": entry_condition, "손절 참고선": stop,
                 "차트 목표": target, "현재가 기준 R/R": text(row.get("R/R"))},
        "workflow": row,
    }


def compare_decision_briefs(briefs):
    """Compare explicit sources without picking/merging the most positive row."""
    return [{
        "출처": brief["source"], "계산시각": brief["calculated_at"],
        "가격 기준일": brief["basis"], "가격 반영": brief["price_basis"],
        "판정가": brief["price"], "기존 판정": brief["decision"],
        "게이트": brief["gate"], "최종 체크": brief["ready"]["final_check_label"],
    } for brief in briefs]


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
