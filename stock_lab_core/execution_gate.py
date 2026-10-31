"""Shared execution gate for Today Queue and precision views.

This module does not generate Korean decision wording.  It only classifies
whether an existing decision can be treated as executable today.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from stock_lab_core.formatters import clean_float, format_rr_ratio
from stock_lab_core.today_queue import (
    TODAY_QUEUE_EXECUTION_WAIT_CODES,
    TODAY_QUEUE_OVERHEAT_HARD_BLOCK_CODES,
)


GATE_EXECUTABLE = "실행가능"
GATE_WAIT = "대기/관찰"
GATE_DEFENSE = "방어우선"
GATE_DATA_CHECK = "데이터확인"
GATE_WATCH_ONLY = "관망"


_EMPTY_TEXT = {"", "-", "—", "nan", "none", "None", "NaN"}
_RE_WEIGHT_BLOCK = re.compile(r"비중\s*(?:초과|충족)|OVERWEIGHT|TARGET_FILLED|TARGET_ZERO", re.I)
_RE_DEFENSE_BLOCK = re.compile(
    r"MACRO_STORM|시장위험|추매중단|보유점검|패닉|위기|DRAWDOWN|PRICE_DRAWDOWN|"
    r"SINGLE_DAY_BREAKDOWN|STRUCTURE_DAMAGE|DOWNTREND|REVERSE_TREND|추세방어|가격방어|급락방어|방어우선",
    re.I,
)
_RE_RESISTANCE_WAIT = re.compile(r"하락패턴|하락\s*패턴|저항\s*(?:미돌파|대기)|무효선\s*미회복")
_RE_OVERHEAT_WAIT = re.compile(r"추격금지|과열|볼린상단|고점권", re.I)
_RE_GENERAL_WAIT = re.compile(r"대기|보류|관망|타점\s*탐색|탐색\s*중|눌림\s*/\s*종가\s*확인|회복\s*(?:확인|관찰)|DCA\s*조건부")
_RE_CONDITION_WAIT = re.compile(r"(?:눌림|종가)\s*확인\s*후|회복\s*후\s*재계산")
_RE_FLOW_WAIT = re.compile(r"추격금지|눌림대기|회복확인|내부확인")
_RE_FLOW_WEAK = re.compile(r"관망|제외|관찰|약모멘텀|둔화")
_RE_LEVERAGE_WAIT = re.compile(r"레버리지정찰|레버리지.*조건부|DCA\s*조건부", re.I)
_RE_PRECISION_CONFIRM = re.compile(r"정밀확인")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _has_value(value: Any) -> bool:
    return _text(value) not in _EMPTY_TEXT


def _row_get(row: Any, key: str, default: Any = "") -> Any:
    try:
        return row.get(key, default)
    except AttributeError:
        return default


def _row_text(row: Any, *keys: str) -> str:
    return " ".join(_text(_row_get(row, key, "")) for key in keys)


def _first_number(row: Any, *keys: str) -> float:
    for key in keys:
        num = clean_float(_row_get(row, key, math.nan), math.nan)
        if math.isfinite(num):
            return float(num)
    return math.nan


def _gate(state, reason, *evidence_ids):
    return {"게이트상태": state, "게이트근거": reason,
            "게이트근거ID": "|".join(dict.fromkeys(evidence_ids))}


def classify_sector_rs_state(value: Any, *, flow_context: str = "", is_etf: bool = False) -> str:
    """Return a compact data-quality label for sector RS."""
    text = _text(value)
    if not _has_value(text):
        if is_etf:
            return "ETF/광역 제외"
        return "벤치확인 필요" if _has_value(flow_context) else "미매핑"
    if any(label in text for label in ("이력부족", "가격없음", "기준일차이", "공통거래일없음", "가격기준불일치")):
        return "가격이력 확인"
    if "강함" in text:
        return "강함"
    if "약함" in text:
        return "약함"
    if "보통" in text:
        return "보통"
    return text


def classify_upside_state(value: Any, *, is_etf: bool = False) -> str:
    """Return a compact data-quality label for analyst target upside."""
    if is_etf:
        return "ETF제외"
    if not _has_value(value):
        return "결측/수동확인"
    up = clean_float(_text(value).removesuffix("%"), math.nan)
    if not math.isfinite(up):
        return "결측/수동확인"
    if up > 0:
        return "양수"
    if up < 0:
        return "음수"
    return "중립"


def build_execution_gate(row: Any) -> dict[str, str]:
    """Classify a row into an execution gate without changing decision wording."""
    if _has_value(_row_get(row, "원천최종읽기", "")):
        row = dict(row)
        row["최종읽기"] = row["원천최종읽기"]
    code = _text(_row_get(row, "판정코드", "")).upper()
    group = _text(_row_get(row, "판정분류", ""))
    rr = _first_number(row, "RR값", "R/R", "rr_ratio")
    rr_kind = _text(_row_get(row, "R/R성격", ""))
    data_state = _text(_row_get(row, "데이터상태", ""))
    final_read = _text(_row_get(row, "최종읽기", ""))
    flow_verdict = _text(_row_get(row, "돈흐름_판정", _row_get(row, "돈흐름판정", "")))
    flow_group = _text(_row_get(row, "돈흐름_후보군", _row_get(row, "돈흐름후보군", "")))
    flow_score = _first_number(row, "돈흐름_돈흐름점수", "돈흐름점수", "테마돈흐름점수")
    market_execution = _text(_row_get(row, "시장실행상태", ""))
    mtf_state = _text(_row_get(row, "상위시간대상태", ""))

    # Candidate quality and explanatory prose do not confirm an entry trigger.
    signal_text = _row_text(
        row,
        "최종읽기",
        "실행메모",
        "🔥기술적 타점",
        "패턴타점",
    )
    text = " ".join((signal_text, _text(_row_get(row, "판정코드", ""))))
    conditions = _row_text(row, "1차조건")
    flow_text = " ".join([flow_verdict, flow_group])

    reasons: list[str] = []
    evidence_ids: list[str] = []

    if code == "NEW_ETF_MIN_DATA_WATCH":
        return _gate(GATE_DATA_CHECK, "신규 ETF 가격 이력 부족: 최소 20봉 확인 필요", "data.history")
    if code in {"DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA"} or "데이터확인" in text or (
        _has_value(data_state) and data_state.upper() not in {"OK", "NORMAL", "정상"}
    ):
        reason = data_state if data_state.upper() not in {"", "OK", "NORMAL", "정상"} else "가격/지표 데이터 확인 필요"
        cause = "mtf" if mtf_state in {"자료부족", "상위 시간대 자료부족", "상위시간대 조회 실패"} else "data"
        return _gate(GATE_DATA_CHECK, reason, cause)

    if mtf_state in {"자료부족", "상위 시간대 자료부족", "상위시간대 조회 실패"}:
        return _gate(GATE_DATA_CHECK, "상위 시간대 검증 미완료", "mtf")

    if _RE_WEIGHT_BLOCK.search(text):
        return _gate(GATE_DEFENSE, "목표비중/비중초과 우선", "weight")

    if "시장방어" in market_execution:
        return _gate(GATE_DEFENSE, market_execution, "market")
    if mtf_state == "상위 시간대 경고":
        return _gate(GATE_DEFENSE, "상위 시간대 추세훼손", "mtf")

    defense_match = _RE_DEFENSE_BLOCK.search(text)
    if code == "CORE_DRAWDOWN_DCA":
        # This code names accumulation; explicit defensive prose still wins.
        defense_match = _RE_DEFENSE_BLOCK.search(signal_text) or re.search(
            r"하드차단|매수\s*금지|추매\s*금지|구조\s*훼손|추세\s*훼손|역배열|하락추세",
            signal_text,
        )
    if defense_match:
        cause = ("macro" if code in {"MACRO_STORM", "HARD_BLOCK_MACRO_STORM", "MACRO_STORM_HOLDING_CAUTION"} else "structure" if code in {
            "PRICE_DRAWDOWN", "SINGLE_DAY_BREAKDOWN", "STRUCTURE_DAMAGE", "DOWNTREND", "REVERSE_TREND"
        } or code.startswith(("PRICE_DRAWDOWN_", "SINGLE_DAY_BREAKDOWN_", "STRUCTURE_DAMAGE_",
                              "DRAWDOWN_20_", "DOWNTREND_", "REVERSE_TREND_")) else "gate.unresolved")
        return _gate(GATE_DEFENSE, "시장/가격/추세 방어 신호 우선", cause)

    # Only explicit overheat codes use the wait policy; prose cannot relax a block.
    if code.startswith("HARD_BLOCK") and code not in TODAY_QUEUE_OVERHEAT_HARD_BLOCK_CODES:
        return _gate(GATE_DEFENSE, "하드차단 우선", "quality" if code in {"HARD_BLOCK_FINANCIAL", "HARD_BLOCK_FINANCIAL_F"} else "gate.hard_block")

    if market_execution.startswith("시장정보 확인 필요"):
        return _gate(GATE_DATA_CHECK, market_execution, "market")

    missing = object()
    missing_indicators = [key for key in ("RSI", "MFI", "볼린저 %B")
                          if _row_get(row, key, missing) is not missing
                          and not math.isfinite(clean_float(_row_get(row, key), math.nan))]
    if missing_indicators:
        return _gate(GATE_DATA_CHECK, "핵심 지표 미확인: " + ", ".join(missing_indicators), "overheat")

    if math.isfinite(rr) and rr < 1.0:
        reasons.append(f"R/R {format_rr_ratio(rr)} < 1")
        evidence_ids.append("rr")

    if "투영상단" in rr_kind:
        reasons.append("R/R 목표가가 투영상단")
        evidence_ids.append("rr")

    if _RE_RESISTANCE_WAIT.search(text):
        reasons.append("하락/저항 패턴 확인 필요")
        evidence_ids.append("pattern")

    if code in TODAY_QUEUE_OVERHEAT_HARD_BLOCK_CODES or _RE_OVERHEAT_WAIT.search(text):
        reasons.append("과열/추격금지")
        evidence_ids.append("overheat")

    if code in TODAY_QUEUE_EXECUTION_WAIT_CODES or code == "QUALITY_RECOVERY_WATCH" or _RE_GENERAL_WAIT.search(text) or _RE_CONDITION_WAIT.search(conditions):
        reasons.append("조건 확인 대기")
        evidence_ids.append("entry")

    if _RE_FLOW_WAIT.search(flow_text):
        reasons.append(f"돈흐름 {flow_verdict or flow_group}")
        evidence_ids.append("flow")

    if math.isfinite(flow_score) and flow_score <= -10 and _RE_FLOW_WEAK.search(flow_text):
        reasons.append(f"돈흐름 약함 {flow_score:.1f}")
        evidence_ids.append("flow")

    if _RE_LEVERAGE_WAIT.search(text):
        reasons.append("레버리지 조건부 확인 대기")
        evidence_ids.append("leverage")

    if reasons:
        return _gate(GATE_WAIT, " · ".join(dict.fromkeys(reasons)), *evidence_ids)

    if group == "caution":
        return _gate(GATE_WAIT, "주의 판정은 실행 전 조건 확인", "entry")

    if group == "buyish" or _RE_PRECISION_CONFIRM.search(final_read):
        if not math.isfinite(rr) or rr <= 0:
            return _gate(GATE_DATA_CHECK, "현재가 R/R 확인 필요", "rr")
        return _gate(GATE_EXECUTABLE, "R/R·패턴·방어 게이트 통과")

    return _gate(GATE_WATCH_ONLY, "실행 신호 아님", "entry")


def apply_execution_gate_columns(
    df: pd.DataFrame,
    *,
    upside_value_map: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Return a copy with gate and quality columns attached."""
    if df is None or df.empty:
        return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

    out = df.copy()
    upside_value_map = upside_value_map or {}
    upper_upside_value_map = {str(key).upper(): value for key, value in upside_value_map.items()}
    gate_rows: list[dict[str, str]] = []
    upside_states: list[str] = []
    sector_states: list[str] = []
    candidate_notes: list[str] = []

    for _, row in out.iterrows():
        ticker = _text(row.get("티커", ""))
        upside = upside_value_map.get(ticker, math.nan)
        if not math.isfinite(clean_float(upside, math.nan)):
            upside = upper_upside_value_map.get(ticker.upper(), math.nan)
        if not math.isfinite(clean_float(upside, math.nan)):
            upside = clean_float(_text(row.get("애널목표Upside", "")).removesuffix("%"), math.nan)
        gate_rows.append(build_execution_gate(row))
        notes = []
        if "약함" in _text(row.get("섹터RS", "")):
            notes.append("섹터RS 약함")
        if math.isfinite(clean_float(upside, math.nan)) and upside <= 0:
            notes.append(f"애널목표Upside {upside:.1f}%")
        candidate_notes.append(" · ".join(notes))
        type_text = _text(row.get("유형", ""))
        is_etf = "ETF" in type_text or "펀드" in type_text
        display_upside = row.get("애널목표Upside", "")
        upside_state = classify_upside_state(display_upside, is_etf=is_etf)
        missing_states = {
            "etf_excluded": "ETF제외", "lookup_error": "조회실패", "invalid_snapshot": "조회실패",
            "no_target": "목표가 미제공", "no_price": "현재가 확인", "invalid_ticker": "티커 확인",
        }
        if upside_state == "결측/수동확인":
            upside_state = missing_states.get(_text(row.get("애널목표상태", "")), upside_state)
        upside_states.append(upside_state)
        flow_context = _row_text(row, "돈흐름_시장맥락", "돈흐름시장맥락", "돈흐름_기준업종", "돈흐름_테마")
        sector_states.append(classify_sector_rs_state(row.get("섹터RS", ""), flow_context=flow_context, is_etf=is_etf))

    gate_df = pd.DataFrame(gate_rows, index=out.index)
    for col in ["게이트상태", "게이트근거", "게이트근거ID"]:
        out[col] = gate_df[col] if col in gate_df.columns else ""
    if "최종읽기" in out:
        # Preserve diagnostics without allowing old action text to overrule a gate.
        if "원천최종읽기" not in out:
            out["원천최종읽기"] = out["최종읽기"]
        else:
            out["원천최종읽기"] = out["원천최종읽기"].fillna(out["최종읽기"])
        out["최종읽기"] = out["게이트상태"].map({
            GATE_EXECUTABLE: "실행가능: 정밀확인",
            GATE_WAIT: "대기/관찰: 실행조건 미충족",
            GATE_DEFENSE: "방어우선: 추가매수 보류",
            GATE_DATA_CHECK: "데이터확인: 판단 보류",
            GATE_WATCH_ONLY: "관망: 실행 신호 없음",
        })
    out["업사이드상태"] = upside_states
    out["섹터RS상태"] = sector_states
    out["후보검토사항"] = candidate_notes
    return out
