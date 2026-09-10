"""Pure helpers for Today Queue display decisions.

The Streamlit page builds full stock decisions, then this module compresses
them into the few execution fields that belong in the queue table.
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

import pandas as pd

from stock_lab_core.formatters import (
    clean_float,
    format_currency,
    is_kr_listed,
    sanitize_ticker_value,
)
try:
    from stock_lab_core.formatters import finite_num as _finite_num
except Exception:
    def _finite_num(value) -> bool:
        try:
            return math.isfinite(float(value))
        except Exception:
            return False


TODAY_QUEUE_DEFENSE_CODES = {
    "PANIC_FINAL_DEPLOY",
    "PANIC_CASH_DEPLOY",
    "CRISIS_CORE_FOCUS",
    "CRISIS_PANIC_SELL_OFF",
    "DRAWDOWN_20_HOLDING_STOP_CHECK",
    "DRAWDOWN_20_HOLDING_CAUSE_CHECK",
    "DRAWDOWN_20_NO_ENTRY",
    "DOWNTREND_NO_ENTRY",
    "REVERSE_TREND_NO_ENTRY",
    "STRONG_REVERSE_NO_ENTRY",
    "COST_MINUS_15_TREND_RISK",
    "COST_MINUS_15_CAUSE_CHECK",
    "TREND_RISK_CAUSE_CHECK",
    "MACRO_STORM_HOLDING_CAUTION",
    "HARD_BLOCK_MACRO_STORM",
    "LEVERAGED_DAILY_DROP_NO_ADD",
    "LEVERAGED_RECOVERY_DCA_BLOCK",
    "MTF_DAMAGE_NO_ADD",
}

TODAY_QUEUE_DEFENSE_PREFIXES = (
    "STRUCTURE_DAMAGE",
    "PRICE_DRAWDOWN",
    "SINGLE_DAY_BREAKDOWN",
)

TODAY_QUEUE_DEFENSE_TEXT_RE = re.compile(
    r"패닉|위기|고점대비\s*-?20|하락추세|역배열|추세위험|구조훼손|추세훼손|"
    r"신규진입\s*보류|진입\s*보류|진입보류|추매금지|손절기준|원인점검|"
    r"코어\s*집중|현금\s*투입|최종투입|투매\s*포착|시장위험|추매중단|보유점검",
    flags=re.IGNORECASE,
)

TODAY_QUEUE_EXECUTION_BLOCK_CODES = {
    "REVERSE_TREND_NO_ENTRY", "STRONG_REVERSE_NO_ENTRY", "DOWNTREND_NO_ENTRY",
    "SHORT_OVERHEAT_NO_ENTRY", "NEAR_UPPER_WAIT", "COST_MINUS_15_TREND_RISK",
    "COST_MINUS_15_CAUSE_CHECK", "TREND_RISK_CAUSE_CHECK",
    "MACRO_STORM_HOLDING_CAUTION",
    "PRICE_DRAWDOWN_HOLDING_CHECK", "PRICE_DRAWDOWN_NO_ENTRY",
    "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK", "SINGLE_DAY_BREAKDOWN_NO_ENTRY",
    "STRUCTURE_DAMAGE_HOLDING_CHECK", "STRUCTURE_DAMAGE_NO_ENTRY", "MTF_DAMAGE_NO_ADD",
    "TARGET_ZERO_NO_ADD", "LEVERAGED_DAILY_DROP_NO_ADD", "LEVERAGED_RECOVERY_DCA_BLOCK",
    "HARD_BLOCK_FINANCIAL_F", "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED",
    "HARD_BLOCK_MACRO_STORM",
}

TODAY_QUEUE_EXECUTION_WAIT_CODES = {
    "S_UPTREND_WAIT_PULLBACK", "A_UPTREND_SEARCH_ENTRY", "UPTREND_PULLBACK_CONFIRM",
    "OVERHEAT_EXTENSION_WAIT_MA5", "LEADER_MA5_PULLBACK_ENTRY",
    "LEADER_MA5_FAST_PULLBACK_ENTRY", "S_GRADE_OVERHEAT_WAIT",
    "PREMARKET_REBOUND_WAIT", "PREMARKET_REBOUND_HOLDING_WAIT",
    "MTF_OVERHEAT_SCOUT_ONLY", "LEVERAGED_DCA_WAIT_PULLBACK", "LEVERAGED_DCA_OVERHEAT_PASS",
    "LEVERAGED_DCA_CONDITIONAL", "LEVERAGED_RECOVERY_DCA_CONDITIONAL",
    "HOLDING_DCA_CONDITION_MISS", "FUND_OVERSOLD_REBALANCE_REVIEW",
}


def is_today_queue_defense_signal(decision: dict | None, extra_text: str = "") -> bool:
    """Return True when a decision belongs in the defensive queue buckets."""
    code = str((decision or {}).get("decision_code", "") or "")
    label = str((decision or {}).get("dec", "") or "")
    text = " ".join([label, code, str(extra_text or "")])
    if code in TODAY_QUEUE_DEFENSE_CODES:
        return True
    if any(code.startswith(prefix) for prefix in TODAY_QUEUE_DEFENSE_PREFIXES):
        return True
    return bool(TODAY_QUEUE_DEFENSE_TEXT_RE.search(text))


def today_queue_reason_bucket(row: Any) -> str:
    """Classify a Today Queue row into the display bucket used by the tabs."""
    ticker = str(row.get("티커", "") or "").upper()
    type_label = str(row.get("유형", "") or "")
    label = str(row.get("🔥기술적 타점", "") or "")
    code = str(row.get("판정코드", "") or "")
    data_state = str(row.get("데이터상태", "") or "")
    macro_state = str(row.get("매크로상태", "") or "")
    pattern_timing = str(row.get("패턴타점", "") or "")
    pattern_reason = str(row.get("패턴근거", "") or "")
    final_read = str(row.get("최종읽기", "") or "")
    grade_label = str(row.get("📌후보등급", "") or "")
    core_reason = str(row.get("핵심근거", "") or "")
    text = " ".join([ticker, type_label, label, code, data_state, macro_state, pattern_timing, pattern_reason, final_read, grade_label, core_reason])
    primary_text = " ".join([label, code, pattern_timing, final_read, grade_label])
    leveraged_text = re.search(
        r"레버리지|인버스|2X|3X|ULTRA|DAILY\s+TARGET|QLD|TQQQ|SOXL|BITX|BITU|UPRO|SSO|TECL|FNGU",
        text,
        flags=re.IGNORECASE,
    )
    if macro_state.upper() == "STORM" and leveraged_text:
        return "시장방어"
    if re.search(r"LEVERAGED_(?:RECOVERY_)?DCA_CONDITIONAL|DCA조건부|레버리지\s*DCA\s*조건부|레버리지.*조건부\s*DCA", text, flags=re.IGNORECASE):
        return "관심/눌림대기"
    if re.search(r"회복관찰|회복초입|회복 후보|QUALITY_RECOVERY", primary_text, flags=re.IGNORECASE):
        return "관심/눌림대기"
    if re.search(r"비중\s*(?:초과|충족)|OVERWEIGHT|TARGET_FILLED", text, flags=re.IGNORECASE):
        return "비중초과 방어"
    if re.search(r"MACRO_STORM|퍼펙트스톰|시장위험|추매중단|보유점검", text, flags=re.IGNORECASE):
        return "시장방어"
    if re.search(r"SINGLE_DAY_BREAKDOWN|단기급락|급락방어|단일 봉 급락", text, flags=re.IGNORECASE):
        return "급락방어"
    if re.search(r"DRAWDOWN_20|PRICE_DRAWDOWN|가격위험|가격방어|고점대비\s*-?20", text, flags=re.IGNORECASE):
        return "가격방어"
    if re.search(
        r"PANIC|CRISIS|DOWNTREND|REVERSE_TREND|COST_MINUS_15|구조훼손|추세훼손|추세방어|"
        r"패닉|위기|하락추세|역배열|추세위험|신규진입 보류|진입보류|진입 보류|STRUCTURE",
        text,
        flags=re.IGNORECASE,
    ):
        return "추세방어"
    if re.search(r"회복관찰|회복초입|회복 후보|QUALITY_RECOVERY", text, flags=re.IGNORECASE):
        return "관심/눌림대기"
    if re.search(r"R/R\s*<\s*1|손익비\s*1\s*미만|목표가.*부족", text, flags=re.IGNORECASE):
        return "관심/눌림대기"
    if re.search(r"패턴관찰|패턴성공|패턴유효|돌파대기|첫 눌림", text, flags=re.IGNORECASE):
        return "관심/눌림대기"
    if re.search(r"과열|볼린|MFI|추격금지|상단", text, flags=re.IGNORECASE):
        return "과열/타점대기"
    if data_state and data_state.upper() not in {"OK", "NORMAL", "-", "정상"}:
        return "데이터확인"
    if "하드차단" in label or "HARD_BLOCK" in code:
        return "기타 하드차단"
    return "일반"


def today_queue_wait_mask(
    summary_df: pd.DataFrame,
    buyish_mask: pd.Series,
    upside_value_map: dict[str, float] | None = None,
) -> pd.Series:
    """Return the rows that should move from execution to watch/wait."""
    if summary_df is None or summary_df.empty:
        return pd.Series(dtype=bool)
    label = summary_df.get("🔥기술적 타점", pd.Series("", index=summary_df.index)).astype(str)
    pattern = summary_df.get("패턴타점", pd.Series("", index=summary_df.index)).astype(str)
    ticker = summary_df.get("티커", pd.Series("", index=summary_df.index)).astype(str)
    code = summary_df.get("판정코드", pd.Series("", index=summary_df.index)).astype(str)
    final_read = summary_df.get("최종읽기", pd.Series("", index=summary_df.index)).astype(str)
    grade_label = summary_df.get("📌후보등급", pd.Series("", index=summary_df.index)).astype(str)
    core_reason = summary_df.get("핵심근거", pd.Series("", index=summary_df.index)).astype(str)
    bucket_series = summary_df.apply(lambda row: today_queue_reason_bucket(row), axis=1)
    wait_text = label + " " + pattern + " " + final_read + " " + grade_label + " " + core_reason
    leveraged_dca_watch = (
        code.str.contains(r"LEVERAGED_(?:RECOVERY_)?DCA_CONDITIONAL", regex=True, na=False)
        | final_read.str.contains("DCA조건부", regex=False, na=False)
        | grade_label.str.contains("레버리지DCA조건부", regex=False, na=False)
        | label.str.contains(r"레버리지.*DCA.*조건부|레버리지.*조건부.*DCA", regex=True, na=False)
    )
    forced_wait = wait_text.str.contains(
        r"R/R\s*[<＜]\s*1|손익비\s*1\s*미만|목표가.*부족|풀진입\s*보류|현재가\s*보류|"
        r"눌림대기|눌림\s*대기|돌파대기|패턴관찰|패턴성공|패턴유효|DCA조건부",
        regex=True,
        na=False,
    )
    wait_mask = (
        label.str.contains(r"R/R\s*[<＜]\s*1|상위과열|과열확장|추격금지|대기|회복관찰|회복초입|회복 후보", regex=True, na=False)
        | pattern.str.contains(r"패턴관찰|패턴성공|패턴유효", regex=True, na=False)
        | bucket_series.eq("관심/눌림대기")
        | leveraged_dca_watch
        | forced_wait
    )
    if upside_value_map:
        neg_upside = ticker.map(lambda t: _finite_num(upside_value_map.get(str(t), math.nan)) and float(upside_value_map.get(str(t))) <= 0)
        wait_mask = wait_mask | neg_upside.fillna(False)
    pattern_interest = pattern.str.contains(r"패턴관찰|패턴성공|패턴유효", regex=True, na=False) & bucket_series.eq("관심/눌림대기")
    overheat_timing_watch = (
        bucket_series.eq("과열/타점대기")
        | wait_text.str.contains(r"추격금지|과열|밴드상단|볼린저.*상단|MFI.*과열|상단부근", regex=True, na=False)
    )
    defense_bucket = bucket_series.isin(["비중초과 방어", "시장방어", "급락방어", "가격방어", "추세방어", "기타 하드차단"])
    overheat_hard_watch = (
        code.str.contains(r"HARD_BLOCK_BOLLINGER_UPPER|HARD_BLOCK_MFI_OVERHEAT|EXTREME_OVERHEAT_NO_CHASE|OVERHEAT", regex=True, na=False)
        | wait_text.str.contains(r"볼린상단|볼린저.*상단|MFI.*과열|극단과열|추격금지", regex=True, na=False)
    )
    hard_block = code.str.contains("HARD_BLOCK", regex=False, na=False) & ~overheat_hard_watch
    return (
        buyish_mask.reindex(summary_df.index, fill_value=False)
        | pattern_interest
        | leveraged_dca_watch
        | overheat_timing_watch
    ) & wait_mask & ~defense_bucket & ~hard_block


def is_dashboard_block_or_wait_label(label: str) -> bool:
    """Return True when a label already says no-action or wait."""
    return any(word in str(label or "") for word in ("금지", "차단", "보류", "대기", "관망", "정리대상", "시장위험", "추매중단", "보유점검"))


def is_dashboard_low_rr_caution(decision: dict) -> bool:
    """Return True when an actionable label has poor current R/R."""
    label = str((decision or {}).get("dec", "") or "")
    rr = clean_float((decision or {}).get("rr_ratio"), math.nan)
    if not _finite_num(rr) or rr >= 1.0:
        return False
    if is_dashboard_block_or_wait_label(label):
        return False
    return any(word in label for word in ("매수", "진입", "추매", "탑승", "분할"))


def is_dashboard_actionable_signal(decision: dict) -> bool:
    """Return True when the decision label reads like an executable action."""
    label = str((decision or {}).get("dec", "") or "")
    if is_dashboard_block_or_wait_label(label):
        return False
    return any(word in label for word in ("매수", "진입", "추매", "탑승", "분할", "눌림", "정찰", "적립"))


def apply_leveraged_dca_dashboard_override(decision: dict) -> dict:
    """Convert broad ETF DCA wording into leveraged-product wording."""
    if not isinstance(decision, dict):
        return decision
    if not bool(decision.get("is_leveraged_or_inverse")):
        return decision
    code = str(decision.get("decision_code", "") or "")
    panic_codes = {"PANIC_FINAL_DEPLOY", "PANIC_CASH_DEPLOY", "CRISIS_CORE_FOCUS"}
    if code in panic_codes:
        out = dict(decision)
        dd = clean_float(out.get("dd"), math.nan)
        out.update({
            "dec": "⚡레버리지 패닉권: DCA 보류" if _finite_num(dd) and dd <= -0.5 else "⚡레버리지 급락권: 회복조건 확인",
            "col": "#d97706",
            "decision_code": "LEVERAGED_RECOVERY_DCA_BLOCK",
            "decision_group": "caution",
            "decision_reasons": (
                f"고점대비 {dd * 100:.1f}% 하락" if _finite_num(dd) else "고점대비 급락 구간",
                "레버리지 ETF는 일반 코어 ETF의 현금투입/최종투입 규칙을 쓰지 않고 MA20·MA50·기초축·회차별 DCA 조건을 먼저 확인합니다.",
            ),
        })
        return out
    if code not in {"ETF_DCA_OK", "ETF_LARGE_GAP_DCA_OK"}:
        return decision

    out = dict(decision)
    dd = clean_float(out.get("dd"), math.nan)
    pct_b = clean_float(out.get("pct_b"), math.nan)
    day_ret = clean_float(out.get("day_ret"), math.nan)
    target_w = clean_float(out.get("target_w"), 0.0)
    current_w = clean_float(out.get("current_w"), 0.0)
    weight_gap = clean_float(out.get("weight_gap"), target_w - current_w)

    high_or_chasing = (
        (_finite_num(dd) and dd > -0.10)
        or (_finite_num(pct_b) and pct_b >= 0.85)
        or (_finite_num(day_ret) and day_ret >= 0.08)
    )
    if high_or_chasing:
        out.update({
            "dec": "⚡레버리지 과열패스: DCA 대기",
            "col": "#d97706",
            "decision_code": "LEVERAGED_DCA_OVERHEAT_PASS",
            "decision_group": "caution",
            "decision_reasons": (
                f"목표비중 {target_w:.1f}% 대비 {max(weight_gap, 0.0):.1f}%p 부족",
                f"고점대비 {dd * 100:.1f}% / %B {pct_b:.2f} / 전일등락 {day_ret * 100:.1f}%",
                "레버리지 ETF는 목표비중 미달이어도 고점권·과열권에서는 월 적립 DCA를 패스하고 눌림 가격을 기다립니다.",
            ),
        })
    else:
        out.update({
            "dec": "⚡레버리지 DCA 조건부: 단계별 소액",
            "col": "#8b5cf6",
            "decision_code": "LEVERAGED_DCA_CONDITIONAL",
            "decision_group": "caution",
            "decision_reasons": (
                f"목표비중 {target_w:.1f}% 대비 {max(weight_gap, 0.0):.1f}%p 부족",
                f"고점대비 {dd * 100:.1f}% / %B {pct_b:.2f} / 전일등락 {day_ret * 100:.1f}%",
                "레버리지 DCA 조건부 구간입니다. 자산 현황의 레버리지 배율과 회차별 금액 안에서만 소액 접근합니다.",
            ),
        })
    return out


def format_dashboard_timing_label(decision: dict) -> str:
    """Format the Today Queue timing label with R/R and MTF guard notes."""
    decision = apply_leveraged_dca_dashboard_override(decision)
    label = str((decision or {}).get("dec", "") or "")
    if not label:
        return label
    if is_dashboard_low_rr_caution(decision) and "신규진입: 대장주 포착" in label:
        label = "🔍대장주 포착: R/R 대기"
    notes = []
    if is_dashboard_low_rr_caution(decision):
        notes.append("R/R<1 정찰")
    if is_dashboard_actionable_signal(decision) and str((decision or {}).get("mtf_bias_label", "")) == "정찰만 적합":
        if "상위과열" not in label and "정찰만" not in label:
            notes.append("상위과열 정찰")
    for note in notes:
        if note not in label:
            label = f"{label} / {note}"
    return label


def format_dashboard_candidate_grade(decision: dict) -> str:
    """Format the Today Queue candidate-grade cell without changing the source decision."""
    decision = apply_leveraged_dca_dashboard_override(decision)
    grade = str((decision or {}).get("grade", "") or "")
    label = str((decision or {}).get("dec", "") or "")
    code = str((decision or {}).get("decision_code", "") or "")
    curr_w = clean_float((decision or {}).get("current_w"), 0.0)
    target_w = clean_float((decision or {}).get("target_w"), 0.0)
    hard_codes = {
        "TARGET_ZERO_NO_ADD",
        "HARD_BLOCK_FINANCIAL_F",
        "LEVERAGED_DAILY_DROP_NO_ADD",
        "PRICE_DRAWDOWN_HOLDING_CHECK",
        "PRICE_DRAWDOWN_NO_ENTRY",
        "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK",
        "SINGLE_DAY_BREAKDOWN_NO_ENTRY",
        "HARD_BLOCK_OVERWEIGHT",
        "HARD_BLOCK_TARGET_FILLED",
        "HARD_BLOCK_MACRO_STORM",
        "STRUCTURE_DAMAGE_HOLDING_CHECK",
        "STRUCTURE_DAMAGE_NO_ENTRY",
        "MTF_DAMAGE_NO_ADD",
    }
    if code == "TARGET_ZERO_NO_ADD" or (curr_w > 0 and target_w <= 0):
        return "🛑후보제외(목표0%)"
    if code == "HARD_BLOCK_FINANCIAL_F":
        return "🛑재무위험(매수금지)"
    if code == "HARD_BLOCK_OVERWEIGHT":
        return "🛡️비중방어(추매금지)"
    if code == "HARD_BLOCK_TARGET_FILLED":
        return "⏸️비중충족(관망)"
    if code == "HARD_BLOCK_MACRO_STORM":
        return "🛡️시장방어(매수금지)"
    if code == "MACRO_STORM_HOLDING_CAUTION":
        return "🛡️시장방어(추매중단)"
    if code == "LEVERAGED_DAILY_DROP_NO_ADD":
        return "🛑레버리지급락(추매금지)"
    if code == "LEVERAGED_RECOVERY_DCA_BLOCK":
        return "🛡️레버리지DCA보류"
    if code == "LEVERAGED_RECOVERY_DCA_CONDITIONAL":
        return "⚡레버리지DCA조건부"
    if code == "PRICE_DRAWDOWN_HOLDING_CHECK":
        return "🛡️가격방어(추매주의)"
    if code == "PRICE_DRAWDOWN_NO_ENTRY":
        return "🛡️가격방어(신규금지)"
    if code == "SINGLE_DAY_BREAKDOWN_HOLDING_CHECK":
        return "🛡️급락방어(종가확인)"
    if code == "SINGLE_DAY_BREAKDOWN_NO_ENTRY":
        return "🛡️급락방어(신규금지)"
    if code == "STRUCTURE_DAMAGE_HOLDING_CHECK":
        return "🛡️추세방어(추매금지)"
    if code == "STRUCTURE_DAMAGE_NO_ENTRY":
        return "🛡️추세방어(신규금지)"
    if code == "MTF_DAMAGE_NO_ADD":
        return "🛡️상위추세방어(추매금지)"
    if code in {"PANIC_FINAL_DEPLOY", "PANIC_CASH_DEPLOY", "CRISIS_CORE_FOCUS", "CRISIS_PANIC_SELL_OFF"}:
        return "🛡️위기/패닉(방어우선)"
    if code == "DRAWDOWN_20_HOLDING_STOP_CHECK":
        return "🛡️가격방어(손절점검)"
    if code == "DRAWDOWN_20_HOLDING_CAUSE_CHECK":
        return "🛡️가격방어(원인점검)"
    if code == "DRAWDOWN_20_NO_ENTRY":
        return "🛡️가격방어(신규금지)"
    if code in {"DOWNTREND_NO_ENTRY", "REVERSE_TREND_NO_ENTRY", "STRONG_REVERSE_NO_ENTRY"}:
        return "🛡️추세방어(신규금지)"
    if code == "TREND_RISK_CAUSE_CHECK":
        return "🛡️추세방어(추매보류)"
    if code == "COST_MINUS_15_TREND_RISK":
        return "🛡️평단/추세방어"
    if code == "COST_MINUS_15_CAUSE_CHECK":
        return "🛡️평단방어(원인점검)"
    if code == "FUND_OVERSOLD_REBALANCE_REVIEW":
        return "⏳펀드리밸런싱"
    if code == "QUALITY_RECOVERY_WATCH":
        return "🔎우량주 회복관찰"
    if code == "QUALITY_RECOVERY_SCOUT":
        return "🟢우량주 회복초입"
    if code == "QUALITY_RECOVERY_CANDIDATE":
        return "✅우량주 회복후보"
    if "시장위험" in label or "퍼펙트스톰" in label or "추매중단" in label or "보유점검" in label:
        return "🛡️시장방어(추매중단)" if "추매" in label or "보유" in label else "🛡️시장방어(매수금지)"
    if "가격위험" in label or "가격방어" in label:
        return "🛡️가격방어(추매주의)" if "추매" in label else "🛡️가격방어(신규금지)"
    if "단기급락" in label or "급락방어" in label:
        return "🛡️급락방어(종가확인)"
    if TODAY_QUEUE_DEFENSE_TEXT_RE.search(label) or "추세훼손" in label or "추세방어" in label:
        return "🛡️추세방어(추매금지)" if "추매" in label else "🛡️추세방어(신규금지)"
    if code in {"HARD_BLOCK_BOLLINGER_UPPER", "HARD_BLOCK_MFI_OVERHEAT"} or "볼린상단 이탈" in label:
        return "🚫상단과열(추격금지)"
    if code in hard_codes or any(word in label for word in ("추매금지", "하드차단", "구조훼손", "추세훼손", "가격위험", "레버리지 급락")):
        return "🛑매수금지"
    badges = []
    if is_dashboard_low_rr_caution(decision):
        badges.append("⚠️R/R<1")
    if is_dashboard_actionable_signal(decision) and str((decision or {}).get("mtf_bias_label", "")) == "정찰만 적합":
        badges.append("🟡정찰")
    if badges:
        return f"{grade} / {' · '.join(badges)}" if grade else " · ".join(badges)
    return grade


def format_dashboard_reason(decision: dict) -> str:
    """Return the compact reason string used in Today Queue rows."""
    decision = apply_leveraged_dca_dashboard_override(decision)
    reasons = tuple((decision or {}).get("decision_reasons") or ())
    base = str(reasons[0]) if reasons else ""
    code = str((decision or {}).get("decision_code", "") or "")
    if (code.startswith("STRUCTURE_DAMAGE") or code.startswith("SINGLE_DAY_BREAKDOWN")) and len(reasons) > 1:
        base = " / ".join(str(x) for x in reasons[:3] if str(x).strip())
    if is_dashboard_actionable_signal(decision) and str((decision or {}).get("mtf_bias_label", "")) == "정찰만 적합":
        mtf_note = "상위 시간대 과열: 풀비중보다 정찰/대기"
        base = f"{base} / {mtf_note}" if base else mtf_note
    if is_dashboard_low_rr_caution(decision):
        rr = clean_float((decision or {}).get("rr_ratio"), math.nan)
        rr_note = f"R/R {rr:.2f}: 현재가 풀진입 보류"
        return f"{base} / {rr_note}" if base else rr_note
    return base


def build_dashboard_final_read(
    decision: dict,
    dashboard_timing: str = "",
    dashboard_grade: str = "",
    pattern_timing: str = "",
    pattern_bucket: str = "",
) -> str:
    """Build the final Today Queue read label from timing, grade, and pattern context."""
    decision = apply_leveraged_dca_dashboard_override(decision)
    code = str((decision or {}).get("decision_code", "") or "")
    group = str((decision or {}).get("decision_group", "") or "")
    text = " ".join([
        str(dashboard_timing or ""),
        str(dashboard_grade or ""),
        str(pattern_timing or ""),
        code,
    ])

    if code in {"DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA"} or "데이터" in text:
        return "⚪데이터확인"

    if "하락패턴 유효" in pattern_timing:
        if code.startswith("QUALITY_RECOVERY"):
            return "👀회복관찰"
        return "🛡️방어우선"

    if code == "QUALITY_RECOVERY_WATCH":
        return "👀회복관찰"
    if code in {"QUALITY_RECOVERY_SCOUT", "QUALITY_RECOVERY_CANDIDATE"}:
        return "✅정밀확인"
    if code == "LEVERAGED_RECOVERY_DCA_BLOCK":
        return "🛡️방어우선"
    if code == "LEVERAGED_RECOVERY_DCA_CONDITIONAL":
        return "⏳DCA조건부"
    if code == "TREND_RISK_CAUSE_CHECK":
        return "🛡️추세방어(추매보류)"
    if code == "COST_MINUS_15_TREND_RISK":
        return "🛡️평단/추세방어"
    if code == "COST_MINUS_15_CAUSE_CHECK":
        return "🛡️평단방어(원인점검)"
    if code == "HOLDING_DCA_CONDITION_MISS":
        return "⏳추매대기"
    if code == "FUND_OVERSOLD_REBALANCE_REVIEW":
        return "⏳리밸런싱대기"
    if code == "MACRO_STORM_HOLDING_CAUTION":
        return "🛡️시장방어(추매중단)"
    if code == "HARD_BLOCK_MACRO_STORM":
        return "🛡️시장방어(매수금지)"
    if is_today_queue_defense_signal(decision, text):
        return "🛡️방어우선"
    if code.startswith("STRUCTURE_DAMAGE") or code.startswith("PRICE_DRAWDOWN") or code.startswith("SINGLE_DAY_BREAKDOWN"):
        return "🛡️방어우선"
    if code in {"TARGET_ZERO_NO_ADD", "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED"}:
        return "🛡️방어우선"
    if code.startswith("HARD_BLOCK") and not re.search(r"볼린|MFI|과열|상단", text):
        return "🛡️방어우선"

    if re.search(r"극단과열|하드차단: 볼린|볼린상단|MFI.*과열|추격금지", text):
        return "🚫추격금지"
    if "패턴관찰" in pattern_timing:
        return "👀돌파대기"
    if "패턴성공" in pattern_timing:
        return "⏳눌림대기"
    if "패턴유효" in pattern_timing:
        if re.search(r"상단|과열|대기|R/R\s*<\s*1", text):
            return "⏳눌림대기"
        return "✅정밀확인"

    if re.search(r"상단|과열|대기|R/R\s*<\s*1|정찰", text):
        return "⏳눌림대기"
    if group == "buyish" or is_dashboard_actionable_signal(decision):
        return "✅정밀확인"
    return "🔍관망"


def _amount_text(amount_krw: Any, ticker: str, usdkrw_value: Any = 1400.0) -> str:
    amount = clean_float(amount_krw, 0.0)
    if amount <= 0:
        return "-"
    if not is_kr_listed(ticker):
        fx = clean_float(usdkrw_value, 1400.0) or 1400.0
        return f"${amount / fx:,.0f} (≈{amount:,.0f}원)"
    return f"{amount:,.0f}원"


def _is_leveraged_from_callback(
    name: str,
    ticker: str,
    asset_class: str,
    callback: Callable[[str, str, str], bool] | None,
) -> bool:
    if callback is None:
        return False
    try:
        return bool(callback(name, ticker, asset_class))
    except Exception:
        return False


def _compact_action(decision_code: str, decision_label: str, *, is_weight_block: bool,
                    is_hard_blocked: bool, is_wait: bool, is_poor_rr: bool,
                    rr: float, target_is_projection: bool) -> str:
    if decision_code in {"LEVERAGED_DCA_CONDITIONAL", "LEVERAGED_RECOVERY_DCA_CONDITIONAL"}:
        return "조건부 소액 DCA"
    if decision_code in {"LEVERAGED_DCA_OVERHEAT_PASS", "LEVERAGED_RECOVERY_DCA_BLOCK"}:
        return "DCA 대기"
    if is_weight_block:
        return "추가매수 제외"
    if is_hard_blocked:
        return "방어/원인점검"
    if decision_code == "FUND_OVERSOLD_REBALANCE_REVIEW":
        return "소액 리밸런싱"
    if is_poor_rr:
        return "R/R 회복 대기"
    if is_wait:
        return "눌림/종가 확인"
    if _finite_num(rr) and rr < 1.5:
        return "소액 1차만"
    if target_is_projection:
        return "분할/추적"
    if "익절" in decision_label:
        return "익절/추적"
    return "분할 가능"


def _dedup_supports(candidates: list[tuple[str, float]], current_price: float) -> list[tuple[str, float]]:
    candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    unique_candidates: list[tuple[str, float]] = []
    min_gap = max(current_price * 0.003, 1.0)
    for label, value in candidates:
        if all(abs(value - used_value) > min_gap for _, used_value in unique_candidates):
            unique_candidates.append((label, value))
    return unique_candidates


def _support_candidates(c: dict, current_price: float, stop: float, atr: float) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for label, value in [
        ("MA5", clean_float(c.get("ma5"), 0.0)),
        ("MA20", clean_float(c.get("ma20"), 0.0)),
        ("FVG 상단", clean_float(c.get("fvg_top"), 0.0)),
        ("FVG 하단", clean_float(c.get("fvg_bottom"), 0.0)),
        ("0.5ATR", current_price - atr * 0.5 if atr > 0 else 0.0),
        ("1ATR", current_price - atr if atr > 0 else 0.0),
    ]:
        if _finite_num(value) and stop < float(value) < current_price:
            candidates.append((label, float(value)))
    return _dedup_supports(candidates, current_price)


def build_today_queue_execution_snapshot(
    name: str,
    ticker: str,
    decision: dict | None,
    *,
    has_pos: bool = False,
    usdkrw_value: Any = 1400.0,
    is_leveraged_product_fn: Callable[[str, str, str], bool] | None = None,
) -> dict:
    """Return compact queue-table fields from an existing precision decision."""
    c = decision or {}
    tkr = sanitize_ticker_value(ticker)
    cur = clean_float(c.get("cur_p"), 0.0)
    atr = clean_float(c.get("atr"), 0.0)
    stop = clean_float(c.get("rr_stop"), 0.0)
    target = clean_float(c.get("rr_target"), 0.0)
    rr = clean_float(c.get("rr_ratio"), math.nan)
    if cur > 0 and stop > 0 and target > cur and stop < cur:
        rr = round((target - cur) / (cur - stop), 2)

    target_is_projection = bool(c.get("rr_target_is_projection", False))
    target_text = "-"
    if target > 0:
        target_prefix = "상단 " if target_is_projection else ""
        target_text = f"{target_prefix}{format_currency(target, tkr)}"
    stop_text = format_currency(stop, tkr) if stop > 0 else "-"
    rr_text = f"{rr:.2f}" if _finite_num(rr) and rr > 0 else "-"

    target_w = clean_float(c.get("target_w"), 0.0)
    current_w = clean_float(c.get("current_w"), 0.0)
    weight_gap = max(clean_float(c.get("weight_gap"), target_w - current_w), 0.0)
    buy_amt_krw = clean_float(c.get("buy_amt"), 0.0)
    effective_total_asset = clean_float(c.get("effective_total_asset"), 0.0)
    if buy_amt_krw <= 0 and effective_total_asset > 0 and weight_gap > 0:
        buy_amt_krw = round(effective_total_asset * weight_gap / 100.0, 0)
    amount_text = _amount_text(buy_amt_krw, tkr, usdkrw_value)

    decision_code = str(c.get("decision_code", "") or "")
    decision_label = str(c.get("dec", "") or "")
    pct_b = clean_float(c.get("pct_b"), math.nan)
    pd_zone = str(c.get("pd_zone", "") or "")
    asset_class = str(c.get("asset_class", "") or "")
    is_leveraged_product = bool(c.get("is_leveraged_or_inverse")) or _is_leveraged_from_callback(
        name, tkr, asset_class, is_leveraged_product_fn
    )
    leveraged_label_block = is_leveraged_product and any(
        word in decision_label
        for word in ["추매금지", "추매중단", "매수금지", "매수 금지", "DCA 보류", "회복 전", "원인점검", "원인 점검", "추격금지"]
    )
    is_weight_block = decision_code in {"TARGET_ZERO_NO_ADD", "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED"}
    is_hard_blocked = (
        decision_code in TODAY_QUEUE_EXECUTION_BLOCK_CODES
        or decision_code.startswith("HARD_BLOCK")
        or leveraged_label_block
        or any(word in decision_label for word in ["하드차단", "진입보류", "진입 보류", "추매금지", "추매중단", "시장위험", "보유점검", "매수금지", "원인점검", "손절기준"])
    )
    is_wait = (
        decision_code in TODAY_QUEUE_EXECUTION_WAIT_CODES
        or (_finite_num(pct_b) and pct_b >= 0.78 and "Premium" in pd_zone)
        or any(word in decision_label for word in ["대기", "관망", "추격금지"])
    )
    is_poor_rr = _finite_num(rr) and rr < 1.0
    action = _compact_action(
        decision_code,
        decision_label,
        is_weight_block=is_weight_block,
        is_hard_blocked=is_hard_blocked,
        is_wait=is_wait,
        is_poor_rr=is_poor_rr,
        rr=rr,
        target_is_projection=target_is_projection,
    )

    if is_weight_block or is_hard_blocked:
        if is_weight_block:
            entry_text = "추가매수 제외"
            entry_cond = "목표비중 기준 추가 필요 없음"
        else:
            entry_text = "회복 후 재계산"
            entry_cond = "차단 사유 해소 후 정밀관측소 확인"
        return {
            "R/R": rr_text,
            "차트목표": target_text,
            "손절가": stop_text,
            "1차기준": entry_text,
            "1차조건": entry_cond,
            "부족액": amount_text,
            "실행메모": action,
            "RR값": rr if _finite_num(rr) else math.nan,
        }

    if cur <= 0 or stop <= 0 or target <= 0 or stop >= cur:
        return {
            "R/R": rr_text,
            "차트목표": target_text,
            "손절가": stop_text,
            "1차기준": "데이터확인",
            "1차조건": "가격/ATR 재조회 필요",
            "부족액": amount_text,
            "실행메모": "데이터확인",
            "RR값": math.nan,
        }

    supports = _support_candidates(c, cur, stop, atr)
    if (is_wait or is_poor_rr) and supports:
        entry_label, entry_price = supports[0]
        entry_text = format_currency(entry_price, tkr)
        entry_cond = f"{entry_label} 눌림 후 R/R 재계산" if is_poor_rr else f"{entry_label} 눌림 확인 후 1차"
    else:
        entry_text = format_currency(cur, tkr)
        entry_cond = "현재 보유분 유지, 추가 1차는 소액만" if has_pos else "현재가 부근 1차 정찰"

    return {
        "R/R": rr_text,
        "차트목표": target_text,
        "손절가": stop_text,
        "1차기준": entry_text,
        "1차조건": entry_cond,
        "부족액": amount_text,
        "실행메모": action,
        "RR값": rr if _finite_num(rr) else math.nan,
    }
