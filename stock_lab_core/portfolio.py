"""Portfolio summary and cash/reserve calculation helpers for Stock Lab."""

import re

import numpy as np
import pandas as pd

from stock_lab_core.formatters import (
    clean_bool,
    clean_float,
    is_kr_listed,
    normalize_bucket,
    normalize_ticker,
    sanitize_ticker_value,
)

try:
    from stock_lab_core.prices import load_price_df
except ImportError:
    def load_price_df(*args, **kwargs):
        return pd.DataFrame()


US_TECH_OR_GROWTH_TICKERS = {
    "MSFT", "AAPL", "NVDA", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "AMD", "AVGO", "MU", "MRVL", "ANET", "CIEN", "VRT", "TSM",
    "NBIS", "SNDK", "ADBE", "CRM", "ORCL", "NOW", "SNOW", "PLTR",
    "ASML", "LRCX", "KLAC", "AMAT", "INTC", "QCOM", "ARM", "SMCI",
    "LITE", "PANW", "HACK", "NFLX", "UBER", "ABNB",
}

try:
    from stock_lab_core.formatters import finite_num
except Exception:
    def finite_num(value) -> bool:
        try:
            return value is not None and not pd.isna(value) and np.isfinite(float(value))
        except Exception:
            return False


PORTFOLIO_ADD_ACTIONS = frozenset({
    "비중확대 후보",
    "계획적 적립",
    "조건부 소액",
    "별도 소액",
    "눌림 시 분할",
    "관찰 후 소액",
    "직접흐름 확인",
})
PORTFOLIO_SEPARATE_ACTIONS = frozenset({"별도관리"})
PORTFOLIO_TRIM_ACTIONS = frozenset({"축소/교체 후보"})
PORTFOLIO_STOP_ACTIONS = frozenset({
    "신규중단",
    "유지·추격금지",
    "유지·신규중단",
    "보유점검",
    "별도관리",
    "관망",
})
PORTFOLIO_CAUTION_ACTIONS = PORTFOLIO_STOP_ACTIONS | PORTFOLIO_TRIM_ACTIONS
PORTFOLIO_RECOMMEND_STOP_TOKENS = ("축소", "교체", "신규중단", "추격금지")
PORTFOLIO_RECOMMEND_GROUP_ORDER = {
    "보유 보강": 0,
    "조건부 보강": 1,
    "신규 정밀관측": 2,
    "신규 관찰": 3,
    "교체 재원": 4,
}
PORTFOLIO_NEWS_MISSING_LABELS = frozenset({"뉴스 미연결", "관련 뉴스 미포착"})
PORTFOLIO_MARKET_COMMAND_ACTIONS = frozenset({"정밀관측", "눌림대기", "관심등록"})
PORTFOLIO_MARKET_COMMAND_RANK = {
    "정밀관측": 3,
    "눌림대기": 2,
    "관심등록": 1,
}
PORTFOLIO_MARKET_COMMAND_BASE_PRIORITY = {
    "정밀관측": 76.0,
    "눌림대기": 66.0,
    "관심등록": 58.0,
}
PORTFOLIO_NEXT_CHECK_BASE_SCORE = {
    "비중확대 후보": 72,
    "계획적 적립": 68,
    "눌림 시 분할": 64,
    "직접흐름 확인": 58,
    "관찰 후 소액": 56,
    "조건부 소액": 55,
    "별도 소액": 50,
    "유지": 42,
    "보유점검": 40,
    "관망": 24,
    "축소/교체 후보": 74,
    "신규중단": 62,
    "유지·추격금지": 58,
    "유지·신규중단": 56,
    "별도관리": 16,
}
PORTFOLIO_NEXT_CHECK_GROUP_ORDER = {
    "줄이기/중단 점검": 0,
    "회복/DCA 대기": 1,
    "늘리기/적립 확인": 2,
    "보유/대기 점검": 3,
}
PORTFOLIO_NEXT_CHECK_PRIORITY_GROUPS = (
    "줄이기/중단 점검",
    "회복/DCA 대기",
    "늘리기/적립 확인",
)


def portfolio_flow_ticker_key(ticker):
    text = sanitize_ticker_value(ticker)
    if ":" in text:
        text = text.split(":")[-1]
    for suffix in (".US", ".KS", ".KQ"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _portfolio_alignment_names(df, limit=3):
    if not isinstance(df, pd.DataFrame) or df.empty:
        return "-"
    names = []
    for _, row in df.head(limit).iterrows():
        ticker = str(row.get("티커", "") or "").strip()
        asset = str(row.get("자산", "") or "").strip()
        label = ticker or asset
        if label and label not in names:
            names.append(label)
    return ", ".join(names) if names else "-"


def build_portfolio_market_alignment_brief(align_df):
    if not isinstance(align_df, pd.DataFrame) or align_df.empty:
        return {}
    work = align_df.copy()
    work["현재비중"] = work.get("현재비중", pd.Series(0.0, index=work.index)).apply(lambda v: clean_float(v, 0.0))
    add_df = work[work["포트판정"].astype(str).isin(PORTFOLIO_ADD_ACTIONS)].sort_values("현재비중", ascending=False)
    caution_df = work[work["포트판정"].astype(str).isin(PORTFOLIO_CAUTION_ACTIONS)].sort_values("현재비중", ascending=False)
    separate_df = work[work["포트판정"].astype(str).isin(PORTFOLIO_SEPARATE_ACTIONS)].sort_values("현재비중", ascending=False)
    direct_df = work[work["시장판정"].astype(str).str.contains("직접흐름", na=False)].sort_values("현재비중", ascending=False)

    add_weight = float(add_df["현재비중"].sum()) if not add_df.empty else 0.0
    caution_weight = float(caution_df["현재비중"].sum()) if not caution_df.empty else 0.0
    separate_weight = float(separate_df["현재비중"].sum()) if not separate_df.empty else 0.0
    direct_weight = float(direct_df["현재비중"].sum()) if not direct_df.empty else 0.0

    if add_weight > caution_weight:
        headline = "새 돈은 계획적 적립·직접흐름 확인 후보 중심으로 보고, 점검 자산은 추가매수를 멈추는 구도입니다."
    elif caution_weight > 0:
        headline = "현재 포트는 신규 확대보다 점검·대기가 더 큰 구도입니다. 새 돈은 기준축이나 확인된 흐름에만 제한합니다."
    else:
        headline = "포트 전체가 큰 충돌 없이 정리되어 있습니다. 목표비중과 정해진 적립률 위주로 관리합니다."

    return {
        "headline": headline,
        "add_names": _portfolio_alignment_names(add_df),
        "caution_names": _portfolio_alignment_names(caution_df),
        "separate_names": _portfolio_alignment_names(separate_df),
        "direct_names": _portfolio_alignment_names(direct_df),
        "add_weight": add_weight,
        "caution_weight": caution_weight,
        "separate_weight": separate_weight,
        "direct_weight": direct_weight,
    }


def _format_portfolio_weight_pair(current_weight, target_weight):
    current_weight = clean_float(current_weight, 0.0)
    target_weight = clean_float(target_weight, 0.0)
    return f"{current_weight:.1f}% / {target_weight:.1f}%"


def _portfolio_text_contains(text, patterns):
    text = str(text or "").lower()
    return any(str(pattern).lower() in text for pattern in patterns)


def _is_broad_core_asset(name, ticker):
    text = f"{name} {ticker}".lower()
    if any(key in text for key in ["s&p500", "s&p 500", "sp500", "voo", "spy", "379800"]):
        return True
    if any(key in text for key in ["나스닥", "nasdaq", "qqq", "379810"]) and not any(
        key in text for key in ["레버리지", "2x", "3x", "tqqq", "qld"]
    ):
        return True
    return False


def _is_semiconductor_tilt_asset(name, ticker):
    text = f"{name} {ticker}".lower()
    return any(key in text for key in ["반도체", "semiconductor", "soxl", "soxx", "smh", "dram", "ram", "0167a0"])


def _is_leverage_asset(row):
    name = str(row.get("자산명", "") or "")
    ticker = str(row.get("티커", "") or "")
    bucket = normalize_bucket(row.get("버킷", row.get("bucket", "")))
    text = f"{name} {ticker} {bucket}".lower()
    return bucket == "leverage" or any(
        key in text for key in ["레버리지", "leveraged", "2x", "3x", "tqqq", "qld", "soxl", "bitx", "ram"]
    )


def _portfolio_pnl_pct_from_row(row):
    pnl_pct = clean_float(row.get("수익률_pct"), np.nan)
    if np.isfinite(pnl_pct):
        return pnl_pct
    raw_return = clean_float(row.get("수익률"), np.nan)
    if not np.isfinite(raw_return):
        return np.nan
    return raw_return * 100


def _portfolio_pnl_krw_from_row(row, usdkrw=1400.0):
    pnl_krw = clean_float(row.get("평가손익_원화"), np.nan)
    if np.isfinite(pnl_krw):
        return pnl_krw
    raw_pnl = clean_float(row.get("평가손익"), np.nan)
    if not np.isfinite(raw_pnl):
        return np.nan
    return calc_pnl_krw_from_row(row, usdkrw)


def _format_portfolio_pnl(pnl_pct):
    pnl_pct = clean_float(pnl_pct, np.nan)
    if not np.isfinite(pnl_pct):
        return "-"
    return f"{pnl_pct:+.1f}%"


def _format_portfolio_krw_pnl(pnl_krw):
    pnl_krw = clean_float(pnl_krw, np.nan)
    if not np.isfinite(pnl_krw):
        return "-"
    return f"{pnl_krw:+,.0f}원"


def _join_reasons(reasons):
    reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    return " · ".join(reasons) if reasons else "특이 신호 없음"


def _portfolio_action_from_row(row, metrics):
    name = str(row.get("자산명", "") or row.get("티커", "") or "").strip()
    ticker = str(row.get("티커", "") or "").strip()
    bucket = normalize_bucket(row.get("버킷", row.get("bucket", "")))
    timing = str(row.get("기술적타점", "") or "").strip()
    trend = str(row.get("추세", "") or "").strip()
    rs = str(row.get("RS", "") or "").strip()
    macd = str(row.get("MACD", "") or "").strip()
    current_weight = clean_float(row.get("현재비중", row.get("전체비중")), 0.0)
    target_weight = clean_float(row.get("목표비중"), 0.0)
    gap = clean_float(row.get("비중차이"), target_weight - current_weight)
    pnl_pct = _portfolio_pnl_pct_from_row(row)
    pnl_krw = _portfolio_pnl_krw_from_row(row, clean_float(metrics.get("usdkrw"), 1400.0))
    risk_index = clean_float(metrics.get("risk_index"), 0.0)
    reserve_gap = clean_float(metrics.get("reserve_gap"), 0.0)

    is_high_risk_market = risk_index >= 60
    cash_short = reserve_gap > 0.5
    is_leverage = _is_leverage_asset(row)
    is_broad_core = _is_broad_core_asset(name, ticker)
    is_semiconductor_tilt = _is_semiconductor_tilt_asset(name, ticker)
    is_blocked = _portfolio_text_contains(timing, ["하드차단", "차단", "추세방어", "추세위험", "급락방어", "가격방어"])
    is_overweight = gap <= -0.3 or _portfolio_text_contains(timing, ["비중 초과", "비중충족", "비중 충족"])
    is_underweight = gap >= 0.3
    severe_loss = np.isfinite(pnl_pct) and pnl_pct <= -20
    moderate_loss = np.isfinite(pnl_pct) and pnl_pct <= -8
    trend_weak = _portfolio_text_contains(f"{timing} {trend} {macd}", ["역배열", "하락", "데드크로스", "추세위험", "추세방어"])
    strong_rs = _portfolio_text_contains(rs, ["강함", "strong"])

    reasons = []
    if np.isfinite(pnl_pct):
        reasons.append(f"손익 {_format_portfolio_pnl(pnl_pct)}")
    if target_weight > 0:
        reasons.append(f"비중 {_format_portfolio_weight_pair(current_weight, target_weight)}")
    if timing:
        reasons.append(timing)
    if trend_weak:
        reasons.append("추세 약함")
    elif strong_rs:
        reasons.append("RS 강함")

    decision = "보유 유지"
    action = "현재 비중 유지"
    condition = "다음 리밸런싱 때 목표비중만 확인"
    priority = 60

    if is_leverage:
        if is_overweight or is_blocked:
            decision = "축소/교체 검토"
            action = "추가매수 중단 · 반등 시 목표 이하로 축소"
            condition = "목표비중 이하 + 하드차단 해제 전까지 재매수 금지"
            priority = 10
        elif severe_loss and is_underweight:
            decision = "레버리지 DCA 대기"
            action = "추가매수 중단 · 가격/기초축 회복 조건 대기"
            condition = "DCA 가격조건 + 기초축 회복 + 시장 위험 완화"
            priority = 18
        elif severe_loss:
            decision = "레버리지 회복확인"
            action = "추가매수 중단 · 반등 강도 확인"
            condition = "손실 구간 회복 + 하락 패턴 해소"
            priority = 22
        elif is_underweight and _portfolio_text_contains(timing, ["DCA", "소액", "조건부"]):
            decision = "조건부 소액"
            action = "정해둔 회차와 금액만, 추격 금지"
            condition = "시장 위험 완화 + 손절선 확인"
            priority = 35
        else:
            decision = "레버리지 관찰"
            action = "신규매수 보류"
            condition = "시장 안전벨트가 경고 이하로 내려갈 때 재검토"
            priority = 40
    elif is_broad_core:
        if is_overweight:
            decision = "장기코어 유지·신규중단"
            action = "팔기보다 추가매수 중단, 신규 자금은 부족 코어/현금으로"
            condition = "목표비중 이하로 내려오면 적립 재개"
            priority = 20
        elif is_underweight:
            decision = "장기코어 유지·회복확인"
            if is_high_risk_market or cash_short or trend_weak:
                action = "오늘 추격보다 안정 확인 후 분할 적립"
                condition = "10Y/VIX 안정 + 종가/RS 회복 + 대기자금 목표 근접"
            else:
                action = "정해둔 적립금으로 분할 매수"
                condition = "월 적립 규칙 유지"
            priority = 25
        else:
            decision = "장기코어 유지"
            action = "교체보다 보유, 속도만 조절"
            condition = "목표비중 이탈 시 리밸런싱"
            priority = 30
    elif is_semiconductor_tilt and (severe_loss or is_overweight or is_blocked):
        decision = "위성/집중 축소 검토"
        action = "추가매수 중단 · 회복 시 코어보다 낮은 비중으로 정리"
        condition = "반도체 돈흐름 회복 + 목표비중 이하 + 추세 회복"
        priority = 15
    elif _portfolio_text_contains(timing, ["추세위험", "원인 점검", "스윙대기"]):
        decision = "대기/원인점검"
        action = "비중 확대 보류"
        condition = "추세 회복 또는 대체 후보가 더 명확할 때"
        priority = 45
    elif is_underweight and _portfolio_text_contains(timing, ["S급", "과매도", "분할"]):
        decision = "관심/분할대기"
        if is_high_risk_market or cash_short:
            action = "현금 목표와 시장 안정 확인 후 1차 소액"
            condition = "대기자금 15% 근접 + 가격 지지 확인"
        else:
            action = "목표비중 안에서 천천히 분할"
            condition = "손절선과 분할 횟수 고정"
        priority = 32
    elif is_underweight:
        decision = "조건부 적립"
        action = "목표비중 미달분을 한 번에 채우지 말고 분할"
        condition = "시장 위험 완화 + 개별 추세 확인"
        priority = 38
    elif is_overweight:
        decision = "비중초과 관리"
        action = "신규매수 중단, 자연 조정 또는 일부 트리밍"
        condition = "목표비중 이하"
        priority = 28
    elif moderate_loss and trend_weak:
        decision = "손실 원인점검"
        action = "추가매수보다 회복 조건 확인"
        condition = "추세 회복 실패 시 대체 후보 검토"
        priority = 42

    return {
        "우선": priority,
        "자산": name or ticker,
        "티커": ticker,
        "구분": bucket or "-",
        "손익": _format_portfolio_pnl(pnl_pct),
        "평가손익": _format_portfolio_krw_pnl(pnl_krw),
        "현재/목표": _format_portfolio_weight_pair(current_weight, target_weight),
        "판정": decision,
        "실행": action,
        "근거": _join_reasons(reasons),
        "재개/해제 조건": condition,
    }


def build_portfolio_action_decision_df_from_inputs(metrics, asset_df=None):
    source_df = metrics.get("strategy_df") if isinstance(metrics, dict) else None
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        source_df = asset_df if isinstance(asset_df, pd.DataFrame) else pd.DataFrame()
    if source_df.empty:
        return pd.DataFrame()

    rows = []
    for _, row in source_df.iterrows():
        name = str(row.get("자산명", "") or row.get("티커", "") or "").strip()
        if not name:
            continue
        if normalize_bucket(row.get("버킷", row.get("bucket", ""))) in {"cash", "reserve"}:
            continue
        rows.append(_portfolio_action_from_row(row, metrics if isinstance(metrics, dict) else {}))

    if not rows:
        return pd.DataFrame()

    decision_df = pd.DataFrame(rows)
    return decision_df.sort_values(["우선", "자산"]).reset_index(drop=True)


def portfolio_market_flow_score_from_row(row):
    for col in ["_점수", "점수", "테마점수", "하위점수", "돈흐름점수", "스윙점수"]:
        value = clean_float(row.get(col), np.nan) if isinstance(row, (pd.Series, dict)) else np.nan
        if finite_num(value):
            return float(value)
    return np.nan


def _first_portfolio_flow_text(*values, default=""):
    for value in values:
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        text = str(value or "").strip()
        if text and text.lower() not in ["nan", "none", "null"]:
            return text
    return default


def _portfolio_best_direct_flow(row, direct_df):
    if not isinstance(direct_df, pd.DataFrame) or direct_df.empty:
        return pd.Series(dtype=object)
    work = direct_df
    if "_ticker_key" not in work.columns and "Ticker" in work.columns:
        work = work.copy()
        work["_ticker_key"] = work["Ticker"].apply(portfolio_flow_ticker_key)
    key = portfolio_flow_ticker_key(row.get("티커", ""))
    if not key or "_ticker_key" not in work.columns:
        return pd.Series(dtype=object)
    matched = work[work["_ticker_key"].astype(str).eq(key)].copy()
    if matched.empty:
        return pd.Series(dtype=object)
    if "_flow_score" not in matched.columns:
        matched["_flow_score"] = matched.apply(portfolio_market_flow_score_from_row, axis=1)
    return matched.sort_values("_flow_score", ascending=False, na_position="last").iloc[0]


def _portfolio_market_action_from_rows(row, command_row, direct_row):
    action = str(command_row.get("행동", "") or "").strip()
    timing = str(row.get("기술적타점", "") or "")
    bucket = normalize_bucket(row.get("버킷", row.get("bucket", "")))
    gap = clean_float(row.get("비중차이"), 0.0)
    direct_score = portfolio_market_flow_score_from_row(direct_row)
    has_direct = finite_num(direct_score)
    blocked = _portfolio_text_contains(timing, ["하드차단", "추세위험", "추세방어", "추매중단", "시장방어"])

    if blocked:
        return "보유점검", "내 기술 신호가 방어라서 시장 흐름보다 회복 조건을 먼저 봅니다."
    if action == "기준축":
        if gap > 0.3:
            return "계획적 적립", "오늘 주도 후보가 아니라 장기 기준축이라 정해둔 적립률 안에서만 봅니다."
        if gap < -0.3:
            return "유지·신규중단", "기준축이지만 목표보다 많아 새 매수는 멈추고 비중만 관리합니다."
        return "유지", "기준축은 교체보다 장기 계획과 비중 유지가 우선입니다."
    if action == "별도관리":
        return "별도관리", "주식 주도맵과 별도 흐름이라 전용 기준과 목표비중으로 관리합니다."
    if action == "연결대기":
        if bucket == "leverage":
            return "보유점검", "분류 축은 있지만 오늘 실행 후보가 아니라 레버리지 추가는 정밀관측소 확인이 먼저입니다."
        return "관망", "분류 축은 있지만 오늘 실행 후보에는 직접 올라오지 않았습니다."
    if action == "정밀관측":
        if gap > 0.3:
            if bucket == "leverage":
                return "조건부 소액", "주도축은 맞지만 레버리지는 정해둔 회차와 금액만 봅니다."
            return "비중확대 후보", "주도축과 내 목표비중 미달이 같이 맞습니다."
        if gap < -0.3:
            return "유지·신규중단", "주도축은 맞지만 목표보다 많아 새 매수는 멈춥니다."
        return "유지", "주도축과 연결되어 있어 교체보다 보유 유지가 우선입니다."
    if action == "눌림대기":
        if gap > 0.3:
            return "눌림 시 분할", "흐름은 있으나 현재가 추격보다 눌림 확인이 우선입니다."
        return "유지·추격금지", "보유는 가능하나 신규 추격은 낮춥니다."
    if action == "추격금지":
        return "신규중단", "시장 주도축이 과열권이라 새 매수는 멈춥니다."
    if action == "관심등록":
        if gap > 0.3:
            return "관찰 후 소액", "주도축 초입 후보라 비중확대 전 지속 확인이 필요합니다."
        return "관찰", "흐름은 감지되지만 아직 주도 확정 전입니다."
    if action == "관망/제외":
        if gap < -0.3:
            return "축소/교체 후보", "현재 주도축과 맞지 않고 목표보다 많아 대체 후보와 비교합니다."
        return "관망", "시장 주도축과 아직 맞지 않습니다."
    if has_direct and direct_score > 0:
        return "직접흐름 확인", "개별 돈흐름은 잡혔지만 상위 주도축 확인이 더 필요합니다."
    if has_direct and direct_score <= 0:
        return "보유점검", "개별 돈흐름이 약세라 추가매수보다 회복 조건 확인이 먼저입니다."
    return "미연결", "오늘 주도맵과 직접 연결되지 않았습니다."


def _portfolio_market_action_label_from_rows(command_row, direct_row):
    action = str(command_row.get("행동", "") or "").strip()
    if action:
        return action
    direct_score = portfolio_market_flow_score_from_row(direct_row)
    if finite_num(direct_score):
        return "직접흐름" if direct_score > 0 else "직접흐름 약세"
    return "미연결"


def build_portfolio_market_alignment_df_from_inputs(
    metrics,
    asset_df,
    command_df=None,
    direct_df=None,
    best_command_flow_fn=None,
    fallback_row_fn=None,
):
    strategy_df = metrics.get("strategy_df") if isinstance(metrics, dict) else pd.DataFrame()
    source_df = strategy_df if isinstance(strategy_df, pd.DataFrame) and not strategy_df.empty else asset_df
    if not isinstance(source_df, pd.DataFrame) or source_df.empty:
        return pd.DataFrame()

    command_df = command_df if isinstance(command_df, pd.DataFrame) else pd.DataFrame()
    direct_df = direct_df if isinstance(direct_df, pd.DataFrame) else pd.DataFrame()

    rows = []
    for _, row in source_df.iterrows():
        if normalize_bucket(row.get("버킷", row.get("bucket", ""))) in {"cash", "reserve"}:
            continue
        direct_row = _portfolio_best_direct_flow(row, direct_df)
        command_row = (
            best_command_flow_fn(row, command_df)
            if callable(best_command_flow_fn)
            else pd.Series(dtype=object)
        )
        if not isinstance(command_row, pd.Series):
            command_row = pd.Series(dtype=object)
        if command_row.empty and direct_row.empty and callable(fallback_row_fn):
            command_row = fallback_row_fn(row)
            if not isinstance(command_row, pd.Series):
                command_row = pd.Series(dtype=object)
        port_action, reason = _portfolio_market_action_from_rows(row, command_row, direct_row)
        market_action = _portfolio_market_action_label_from_rows(command_row, direct_row)
        flow_score = portfolio_market_flow_score_from_row(command_row)
        if not finite_num(flow_score):
            flow_score = portfolio_market_flow_score_from_row(direct_row)
        current_w = clean_float(row.get("현재비중", row.get("전체비중")), 0.0)
        target_w = clean_float(row.get("목표비중"), 0.0)
        gap = clean_float(row.get("비중차이"), target_w - current_w)
        rows.append({
            "자산": _first_portfolio_flow_text(row.get("자산명", ""), row.get("티커", ""), default="-"),
            "티커": str(row.get("티커", "") or "").strip(),
            "구분": normalize_bucket(row.get("버킷", row.get("bucket", ""))),
            "현재비중": current_w,
            "목표비중": target_w,
            "비중차이": gap,
            "손익": _format_portfolio_pnl(_portfolio_pnl_pct_from_row(row)),
            "주도축": _first_portfolio_flow_text(
                command_row.get("후보군", ""),
                command_row.get("연결테마", ""),
                direct_row.get("흐름명", ""),
                default="미연결",
            ),
            "세부축": _first_portfolio_flow_text(
                command_row.get("내부세부축", ""),
                command_row.get("세부축", ""),
                direct_row.get("세부축", ""),
                default="-",
            ),
            "시장판정": market_action,
            "포트판정": port_action,
            "판단": _first_portfolio_flow_text(command_row.get("판단", ""), command_row.get("다음확인", ""), reason, default=reason),
            "근거": reason,
            "대표/ETF": _first_portfolio_flow_text(
                command_row.get("ETF/대표", ""),
                command_row.get("대표주", ""),
                direct_row.get("흐름명", ""),
                default="-",
            ),
            "점수": flow_score,
            "기술신호": str(row.get("기술적타점", "") or "").strip(),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["_판정순서"] = result["포트판정"].map({
        "비중확대 후보": 7,
        "조건부 소액": 6,
        "별도 소액": 5,
        "눌림 시 분할": 5,
        "계획적 적립": 5,
        "유지": 4,
        "유지·신규중단": 3,
        "직접흐름 확인": 3,
        "관찰 후 소액": 3,
        "유지·추격금지": 2,
        "신규중단": 2,
        "관망": 1,
        "보유점검": 1,
        "별도관리": 1,
        "축소/교체 후보": 1,
    }).fillna(0)
    result["_점수정렬"] = result["점수"].apply(lambda v: clean_float(v, -999.0))
    return result.sort_values(["_판정순서", "_점수정렬", "현재비중"], ascending=False).drop(
        columns=["_판정순서", "_점수정렬"]
    ).reset_index(drop=True)


def _portfolio_playbook_budget_multiplier(action, risk_index):
    action = str(action or "")
    base = {
        "비중확대 후보": 1.0,
        "계획적 적립": 0.50,
        "눌림 시 분할": 0.45,
        "조건부 소액": 0.25,
        "별도 소액": 0.12,
        "관찰 후 소액": 0.15,
        "직접흐름 확인": 0.10,
    }.get(action, 0.0)
    risk_index = clean_float(risk_index, 0.0)
    if risk_index >= 70:
        return min(base, 0.20)
    if risk_index >= 55:
        return min(base, 0.45)
    return base


def _portfolio_playbook_condition(row):
    action = str(row.get("포트판정", "") or "")
    market_action = str(row.get("시장판정", "") or "")
    tech = str(row.get("기술신호", "") or "")
    if action == "비중확대 후보":
        return "과열·R/R 확인 후 목표비중 안에서 분할"
    if action == "계획적 적립":
        return "장기 기준축은 시장 안정과 목표비중 안에서 정해진 금액만 적립"
    if action == "조건부 소액":
        return "레버리지 회차 규칙 고정, 손절·기초축 회복 확인"
    if action == "별도 소액":
        return "주식 주도맵과 분리해 전용 기준 충족 때만 소액"
    if action == "눌림 시 분할":
        return "눌림 지지·양봉 전환·거래량 회복 확인"
    if action in {"관찰 후 소액", "직접흐름 확인"}:
        return "2주·1개월 흐름 유지와 대표주 동행 확인"
    if action == "축소/교체 후보":
        return "같은 주도축 후보가 더 명확하면 목표초과분부터 교체 검토"
    if action in {"신규중단", "유지·추격금지", "유지·신규중단"}:
        return "보유는 유지하되 새 매수는 다음 확인까지 중단"
    if action == "별도관리":
        return "주식 주도맵과 분리해 전용 차트·목표비중으로 점검"
    if action == "보유점검" or "방어" in tech:
        return "기술 방어 신호 해소 전 추가매수 보류"
    if market_action == "미연결":
        return "오늘점검 주도축 재계산 후 재확인"
    return "다음 리밸런싱 때 목표비중만 확인"


def _portfolio_action_decision_lookup(action_df):
    if not isinstance(action_df, pd.DataFrame) or action_df.empty or "티커" not in action_df.columns:
        return {}
    lookup = {}
    for _, row in action_df.iterrows():
        key = portfolio_flow_ticker_key(row.get("티커", ""))
        if key:
            lookup[key] = row
    return lookup


def _enrich_portfolio_alignment_with_action_df(align_df, action_df):
    if not isinstance(align_df, pd.DataFrame) or align_df.empty:
        return align_df
    lookup = _portfolio_action_decision_lookup(action_df)
    if not lookup:
        return align_df
    work = align_df.copy()
    for col in ["자산현황판정", "자산현황실행", "재개/해제 조건"]:
        if col not in work.columns:
            work[col] = ""
    for idx, row in work.iterrows():
        decision_row = lookup.get(portfolio_flow_ticker_key(row.get("티커", "")))
        if decision_row is None:
            continue
        work.at[idx, "자산현황판정"] = str(decision_row.get("판정", "") or "")
        work.at[idx, "자산현황실행"] = str(decision_row.get("실행", "") or "")
        work.at[idx, "재개/해제 조건"] = str(decision_row.get("재개/해제 조건", "") or "")
        decision_text = " ".join([
            str(decision_row.get("판정", "") or ""),
            str(decision_row.get("실행", "") or ""),
        ])
        port_action = str(row.get("포트판정", "") or "")
        gap = clean_float(row.get("비중차이"), 0.0)
        if port_action == "별도관리" and gap > 0.3 and any(token in decision_text for token in ["조건부 소액", "조건부 적립"]):
            work.at[idx, "포트판정"] = "별도 소액"
            work.at[idx, "근거"] = "주식 주도맵과는 별도지만 자산현황 실행판에서 조건부 소액 후보로 잡혔습니다."
    return work


def build_portfolio_rebalance_playbook_df(align_df, metrics, monthly_budget=0.0, action_df=None):
    if not isinstance(align_df, pd.DataFrame) or align_df.empty:
        return pd.DataFrame()
    metrics = metrics if isinstance(metrics, dict) else {}
    total_asset = clean_float(metrics.get("total_asset"), 0.0)
    risk_index = clean_float(metrics.get("risk_index"), 0.0)
    reserve_summary = metrics.get("reserve_summary", {}) or {}
    reserve_deployable = max(clean_float(reserve_summary.get("deployable_value"), 0.0), 0.0)
    monthly_budget = max(clean_float(monthly_budget, 0.0), 0.0)
    reserve_budget = reserve_deployable if risk_index < 55 else (reserve_deployable * 0.5 if risk_index < 70 else 0.0)
    total_budget = monthly_budget + reserve_budget

    work = _enrich_portfolio_alignment_with_action_df(align_df, action_df).copy()
    for col in ["현재비중", "목표비중", "비중차이", "점수"]:
        if col in work.columns:
            work[col] = work[col].apply(lambda v: clean_float(v, 0.0))

    candidates = work[work["포트판정"].astype(str).isin(PORTFOLIO_ADD_ACTIONS)].copy()
    if not candidates.empty:
        candidates["_action_rank"] = candidates["포트판정"].map({
            "비중확대 후보": 5,
            "계획적 적립": 4,
            "눌림 시 분할": 4,
            "조건부 소액": 3,
            "별도 소액": 2,
            "관찰 후 소액": 2,
            "직접흐름 확인": 1,
        }).fillna(0)
        candidates = candidates.sort_values(["_action_rank", "점수", "비중차이"], ascending=False)

    rows = []
    remaining = total_budget
    for _, row in candidates.iterrows():
        gap_krw = max(total_asset * clean_float(row.get("비중차이"), 0.0) / 100.0, 0.0)
        multiplier = _portfolio_playbook_budget_multiplier(row.get("포트판정"), risk_index)
        cap = gap_krw * multiplier
        amount = min(max(cap, 0.0), max(remaining, 0.0))
        remaining -= amount
        rows.append({
            "우선": len(rows) + 1,
            "구분": "새 돈 후보",
            "자산": row.get("자산", row.get("티커", "")),
            "티커": row.get("티커", ""),
            "포트판정": row.get("포트판정", ""),
            "시장판정": row.get("시장판정", ""),
            "현재/목표": _format_portfolio_weight_pair(row.get("현재비중"), row.get("목표비중")),
            "목표미달액": gap_krw,
            "제안금액": amount,
            "조건": _portfolio_playbook_condition(row),
            "근거": row.get("근거", ""),
            "자산현황판정": row.get("자산현황판정", ""),
            "자산현황실행": row.get("자산현황실행", ""),
            "재개/해제 조건": row.get("재개/해제 조건", ""),
        })

    stop_df = work[work["포트판정"].astype(str).isin(PORTFOLIO_CAUTION_ACTIONS)].copy()
    if not stop_df.empty:
        stop_df["_stop_rank"] = stop_df["포트판정"].map({
            "축소/교체 후보": 5,
            "보유점검": 4,
            "신규중단": 3,
            "유지·추격금지": 2,
            "유지·신규중단": 1,
            "관망": 1,
            "별도관리": 1,
        }).fillna(0)
        stop_df = stop_df.sort_values(["_stop_rank", "현재비중"], ascending=False)
    for _, row in stop_df.head(10).iterrows():
        over_krw = max(total_asset * abs(min(clean_float(row.get("비중차이"), 0.0), 0.0)) / 100.0, 0.0)
        is_trim = str(row.get("포트판정", "")) in PORTFOLIO_TRIM_ACTIONS
        rows.append({
            "우선": len(rows) + 1,
            "구분": "축소/중단 후보" if is_trim else "신규중단/점검",
            "자산": row.get("자산", row.get("티커", "")),
            "티커": row.get("티커", ""),
            "포트판정": row.get("포트판정", ""),
            "시장판정": row.get("시장판정", ""),
            "현재/목표": _format_portfolio_weight_pair(row.get("현재비중"), row.get("목표비중")),
            "목표미달액": -over_krw if over_krw else 0.0,
            "제안금액": 0.0,
            "조건": _portfolio_playbook_condition(row),
            "근거": row.get("근거", ""),
            "자산현황판정": row.get("자산현황판정", ""),
            "자산현황실행": row.get("자산현황실행", ""),
            "재개/해제 조건": row.get("재개/해제 조건", ""),
        })

    result = pd.DataFrame(rows)
    if not result.empty:
        result.attrs["total_budget"] = total_budget
        result.attrs["monthly_budget"] = monthly_budget
        result.attrs["reserve_budget"] = reserve_budget
        result.attrs["remaining_budget"] = max(remaining, 0.0)
        result.attrs["risk_index"] = risk_index
    return result


def _portfolio_has_connected_news(news_text):
    return bool(news_text and news_text not in PORTFOLIO_NEWS_MISSING_LABELS)


def _portfolio_clamp_priority(value):
    return max(0.0, min(100.0, float(value)))


def _portfolio_recommendation_key(row):
    return "|".join([
        str(row.get("추천구분", "")),
        str(row.get("후보", "")),
        str(row.get("티커/대표", "")),
    ]).lower()


def _append_unique_portfolio_recommendation(rows, seen, row):
    key = _portfolio_recommendation_key(row)
    if key in seen:
        return False
    seen.add(key)
    rows.append(row)
    return True


def _portfolio_recommendation_strength(port_action, decision, bucket=""):
    joined = f"{port_action} {decision}"
    if any(token in joined for token in PORTFOLIO_RECOMMEND_STOP_TOKENS):
        return "재원 점검"
    if "DCA 대기" in joined or "회복확인" in joined:
        return "조건 대기"
    if "비중확대" in joined:
        return "보강 우선"
    if "계획적 적립" in joined or "장기코어" in joined:
        return "정해진 적립"
    if "조건부" in joined or str(bucket) == "leverage":
        return "소액 조건부"
    if "직접흐름" in joined or "눌림" in joined:
        return "정밀 확인"
    return "관찰"


def _portfolio_recommendation_market_action(action):
    action = str(action or "")
    if action == "정밀관측":
        return "가격/RR 확인"
    if action == "눌림대기":
        return "눌림 위치 대기"
    if action == "관심등록":
        return "관심 등록"
    return "확인"


def _portfolio_next_check_type(row):
    port_action = str(row.get("포트판정", "") or "")
    decision = str(row.get("자산현황판정", "") or "")
    joined = f"{port_action} {decision}"
    if any(token in joined for token in PORTFOLIO_RECOMMEND_STOP_TOKENS):
        return "축소/중단 점검"
    if "DCA 대기" in joined or "레버리지 회복확인" in joined:
        return "회복/DCA 대기"
    if port_action == "계획적 적립" or "장기코어" in decision:
        return "장기코어 적립 후보"
    if port_action == "비중확대 후보":
        return "비중 보강 후보"
    if port_action == "눌림 시 분할":
        return "눌림 분할 후보"
    if port_action == "별도 소액":
        return "별도 소액 후보"
    if port_action == "조건부 소액" or "조건부 소액" in decision:
        return "조건부 소액 후보"
    if "조건부 적립" in decision:
        return "조건부 적립 후보"
    if port_action in {"직접흐름 확인", "관찰 후 소액"}:
        return "직접흐름 확인 후보"
    if port_action == "보유점검":
        return "보유 사유 점검"
    return "관망/확인"


def _portfolio_next_check_group(check_type):
    check_type = str(check_type or "")
    if "축소/중단" in check_type:
        return "줄이기/중단 점검"
    if "회복/DCA" in check_type:
        return "회복/DCA 대기"
    if any(token in check_type for token in ["적립", "보강", "분할", "소액", "직접흐름"]):
        return "늘리기/적립 확인"
    return "보유/대기 점검"


def _portfolio_next_check_condition(row):
    port_action = str(row.get("포트판정", "") or "")
    decision = str(row.get("자산현황판정", "") or "")
    release = str(row.get("재개/해제 조건", "") or "").strip()
    base = str(row.get("판단", "") or row.get("근거", "") or "").strip()
    if release:
        return release
    if any(token in f"{port_action} {decision}" for token in PORTFOLIO_RECOMMEND_STOP_TOKENS):
        return "추가매수보다 보유 사유가 남아 있는지 먼저 확인"
    if "DCA 대기" in f"{port_action} {decision}" or "레버리지 회복확인" in f"{port_action} {decision}":
        return "가격 조건, 기초축 회복, 시장 위험 완화가 같이 맞는지 확인"
    if port_action == "계획적 적립":
        return "시장 위험 완화와 목표비중 안에서 정해진 적립만 진행"
    if port_action == "비중확대 후보":
        return "R/R, 과열, 눌림 위치가 동시에 맞는지 확인"
    if port_action in {"조건부 소액", "별도 소액"}:
        return "회차 금액 고정, 손절선과 기초축 회복을 먼저 확인"
    if port_action == "눌림 시 분할":
        return "지지 구간에서 하락 멈춤, 양봉 전환, 거래량 회복 확인"
    if port_action in {"직접흐름 확인", "관찰 후 소액"}:
        return "뉴스 재료, 대표주, ETF 흐름이 5D까지 같이 유지되는지 확인"
    return base or "다음 봉과 주도축 재계산 결과를 확인"


def _portfolio_next_check_weight_state(row):
    gap = clean_float(row.get("비중차이"), 0.0)
    if gap > 0.3:
        return f"목표 {gap:.1f}% 미달"
    if gap < -0.3:
        return f"목표 {abs(gap):.1f}% 초과"
    return "목표 근접"


def _portfolio_next_check_pct_value(value):
    text = str(value or "").replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return np.nan
    return clean_float(match.group(0), np.nan)


def _portfolio_next_check_score(row, news_text=""):
    port_action = str(row.get("포트판정", "") or "")
    market_action = str(row.get("시장판정", "") or "")
    decision = str(row.get("자산현황판정", "") or "")
    joined = f"{port_action} {decision}"
    is_stop_review = any(token in joined for token in PORTFOLIO_RECOMMEND_STOP_TOKENS)
    is_dca_wait = "DCA 대기" in joined or "레버리지 회복확인" in joined
    is_wait_review = any(token in joined for token in ["대기", "원인점검", "보유점검"])
    if is_stop_review:
        score = 74.0
    elif is_dca_wait:
        score = 70.0
    elif is_wait_review:
        score = 50.0
    else:
        score = PORTFOLIO_NEXT_CHECK_BASE_SCORE.get(port_action, 30)
    if "정밀관측" in market_action:
        score += 8
    elif "직접흐름" in market_action:
        score += 4
    elif "기준축" in market_action:
        score += 4
    elif "관심등록" in market_action:
        score += 3
    elif "관망/제외" in market_action:
        score += 4 if is_stop_review else -6

    gap = clean_float(row.get("비중차이"), 0.0)
    if is_stop_review:
        if gap < 0:
            score += min(abs(gap), 5.0) * 1.8
        elif gap > 0:
            score += min(gap, 3.0) * 0.3
    elif is_dca_wait:
        if gap > 0:
            score += min(gap, 5.0) * 1.0
    elif gap > 0:
        score += min(gap, 5.0) * 1.5
    elif gap < 0:
        score -= min(abs(gap), 5.0) * 1.2

    flow_score = clean_float(row.get("점수"), np.nan)
    if finite_num(flow_score):
        clipped_flow = max(min(flow_score, 10.0), -10.0)
        if is_stop_review and clipped_flow < 0:
            score += abs(clipped_flow) * 0.8
        else:
            score += clipped_flow * 0.8

    pnl_pct = _portfolio_next_check_pct_value(row.get("손익", ""))
    if (is_stop_review or is_dca_wait) and finite_num(pnl_pct) and pnl_pct < 0:
        score += min(abs(pnl_pct), 30.0) * 0.35

    if "조건부 적립" in decision or "조건부 소액" in decision:
        score += 6
    if "장기코어" in decision:
        score += 4
    if not is_stop_review and any(token in decision for token in ["축소", "교체", "신규중단", "원인점검"]):
        score -= 12
    if _portfolio_has_connected_news(news_text):
        score += 3
    return _portfolio_clamp_priority(score)


def _portfolio_text(value, default=""):
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value or "").strip()
    if text.lower() in ["", "nan", "none", "null"]:
        return default
    return text


def _first_portfolio_text(*values, default=""):
    for value in values:
        text = _portfolio_text(value)
        if text:
            return text
    return default


def _portfolio_default_news_text(*_args, **_kwargs):
    return "뉴스 미연결"


def _portfolio_default_flow_score(row):
    for col in ["돈흐름점수", "_flow_score", "주도점수", "점수"]:
        value = clean_float(row.get(col, np.nan), np.nan) if isinstance(row, (pd.Series, dict)) else np.nan
        if finite_num(value):
            return float(value)
    return np.nan


def build_portfolio_recommendation_df_from_inputs(
    align_df,
    command_df=None,
    action_df=None,
    owned_news_text_fn=None,
    command_news_text_fn=None,
    flow_score_fn=None,
    limit=8,
):
    if not isinstance(align_df, pd.DataFrame) or align_df.empty:
        return pd.DataFrame()
    news_for_owned = owned_news_text_fn or _portfolio_default_news_text
    news_for_command = command_news_text_fn or _portfolio_default_news_text
    score_command = flow_score_fn or _portfolio_default_flow_score
    work = _enrich_portfolio_alignment_with_action_df(align_df, action_df).copy()

    rows = []
    seen = set()

    for _, row in work.iterrows():
        port_action = str(row.get("포트판정", "") or "")
        decision = str(row.get("자산현황판정", "") or "")
        decision_text = f"{port_action} {decision}"
        bucket = str(row.get("구분", "") or "")
        candidate = _first_portfolio_text(row.get("자산", ""), row.get("티커", ""), default="-")
        ticker = str(row.get("티커", "") or "").strip()
        score = 0.0
        flow_score = clean_float(row.get("점수"), np.nan)
        if finite_num(flow_score):
            score += max(min(flow_score, 10.0), -10.0)
        gap = clean_float(row.get("비중차이"), 0.0)
        pnl_pct = _portfolio_next_check_pct_value(row.get("손익", ""))
        news_text = news_for_owned(row)

        if port_action in PORTFOLIO_ADD_ACTIONS:
            group = "보유 보강"
            base = 76.0
            if "조건부" in decision_text or bucket == "leverage":
                group = "조건부 보강"
                base = 66.0
            if port_action == "계획적 적립":
                base = 72.0
            priority = base + min(max(gap, 0.0), 6.0) * 1.8 + score * 0.7
            if _portfolio_has_connected_news(news_text):
                priority += 2.0
            _append_unique_portfolio_recommendation(rows, seen, {
                "추천구분": group,
                "후보": candidate,
                "티커/대표": ticker,
                "우선점수": _portfolio_clamp_priority(priority),
                "실행강도": _portfolio_recommendation_strength(port_action, decision, bucket),
                "근거": _first_portfolio_text(row.get("근거", ""), row.get("판단", ""), default="목표비중과 주도축이 같이 맞는지 확인합니다."),
                "다음 행동": _portfolio_next_check_condition(row),
                "주의/조건": _first_portfolio_text(row.get("재개/해제 조건", ""), default="가격위치와 R/R 확인"),
                "뉴스/재료": news_text,
            })
            continue

        if any(token in decision_text for token in PORTFOLIO_RECOMMEND_STOP_TOKENS):
            priority = 54.0 + min(abs(min(gap, 0.0)), 5.0) * 3.0
            if finite_num(pnl_pct) and pnl_pct < 0:
                priority += min(abs(pnl_pct), 30.0) * 0.4
            _append_unique_portfolio_recommendation(rows, seen, {
                "추천구분": "교체 재원",
                "후보": candidate,
                "티커/대표": ticker,
                "우선점수": _portfolio_clamp_priority(priority),
                "실행강도": _portfolio_recommendation_strength(port_action, decision, bucket),
                "근거": _first_portfolio_text(row.get("근거", ""), row.get("판단", ""), default="새 매수보다 비중 관리가 먼저입니다."),
                "다음 행동": _portfolio_next_check_condition(row),
                "주의/조건": _first_portfolio_text(row.get("재개/해제 조건", ""), default="회복 조건 전 신규매수 중단"),
                "뉴스/재료": news_text,
            })

    if isinstance(command_df, pd.DataFrame) and not command_df.empty and "행동" in command_df.columns:
        command_work = command_df[command_df["행동"].astype(str).isin(PORTFOLIO_MARKET_COMMAND_ACTIONS)].copy()
        if not command_work.empty:
            command_work["_portfolio_rec_rank"] = command_work["행동"].astype(str).map(PORTFOLIO_MARKET_COMMAND_RANK).fillna(0)
            command_work["_portfolio_rec_score"] = command_work.apply(score_command, axis=1)
            command_work = command_work.sort_values(["_portfolio_rec_rank", "_portfolio_rec_score"], ascending=False, na_position="last")
            for _, row in command_work.head(8).iterrows():
                action = str(row.get("행동", "") or "")
                candidate = _first_portfolio_text(row.get("후보군", ""), row.get("연결테마", ""), row.get("핵심하위테마", ""), row.get("세부축", ""), default="-")
                representative = _first_portfolio_text(row.get("ETF/대표", ""), row.get("대표주", ""), row.get("Ticker", ""), default="-")
                source = _first_portfolio_text(row.get("핵심하위테마", ""), row.get("세부축", ""), row.get("연결테마", ""), default="-")
                flow_score = score_command(row)
                priority = PORTFOLIO_MARKET_COMMAND_BASE_PRIORITY.get(action, 50.0)
                if finite_num(flow_score):
                    priority += max(min(flow_score, 10.0), -10.0) * 1.2
                news_text = news_for_command(candidate, source, representative)
                if _portfolio_has_connected_news(news_text):
                    priority += 2.0
                _append_unique_portfolio_recommendation(rows, seen, {
                    "추천구분": "신규 정밀관측" if action == "정밀관측" else "신규 관찰",
                    "후보": candidate,
                    "티커/대표": representative,
                    "우선점수": _portfolio_clamp_priority(priority),
                    "실행강도": _portfolio_recommendation_market_action(action),
                    "근거": _first_portfolio_text(row.get("판단", ""), row.get("다음확인", ""), default="오늘점검 실행 후보판에서 포착된 축입니다."),
                    "다음 행동": _first_portfolio_text(row.get("다음확인", ""), default="대표주 가격위치와 R/R 확인"),
                    "주의/조건": "보유 종목 교체 전 대표주 동행과 뉴스 재료 확인",
                    "뉴스/재료": news_text,
                })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["_group_order"] = result["추천구분"].map(PORTFOLIO_RECOMMEND_GROUP_ORDER).fillna(9)
    result = result.sort_values(["_group_order", "우선점수", "후보"], ascending=[True, False, True]).reset_index(drop=True)
    limit = max(int(limit), 1)
    if len(result) > limit:
        source_df = result[result["추천구분"].eq("교체 재원")]
        idea_df = result[~result["추천구분"].eq("교체 재원")]
        source_quota = min(2, len(source_df), limit)
        idea_quota = max(limit - source_quota, 0)
        result = pd.concat([idea_df.head(idea_quota), source_df.head(source_quota)], ignore_index=True)
        result = result.sort_values(["_group_order", "우선점수", "후보"], ascending=[True, False, True]).reset_index(drop=True)
    result = result.drop(columns=["_group_order"], errors="ignore")
    result.insert(0, "우선", range(1, len(result) + 1))
    return result


def build_portfolio_next_check_candidates_df_from_inputs(align_df, action_df=None, news_text_fn=None, limit=6):
    if not isinstance(align_df, pd.DataFrame) or align_df.empty:
        return pd.DataFrame()
    news_for_row = news_text_fn or _portfolio_default_news_text
    work = _enrich_portfolio_alignment_with_action_df(align_df, action_df).copy()
    rows = []
    for _, row in work.iterrows():
        news_text = news_for_row(row)
        priority_score = _portfolio_next_check_score(row, news_text=news_text)
        check_type = _portfolio_next_check_type(row)
        rows.append({
            "후보": row.get("자산", row.get("티커", "")),
            "티커": row.get("티커", ""),
            "점검그룹": _portfolio_next_check_group(check_type),
            "점검유형": check_type,
            "우선점수": priority_score,
            "비중상태": _portfolio_next_check_weight_state(row),
            "손익": row.get("손익", ""),
            "주도축": row.get("주도축", ""),
            "시장/추세": " · ".join([part for part in [
                str(row.get("시장판정", "") or ""),
                str(row.get("포트판정", "") or ""),
            ] if part]),
            "자산판정": row.get("자산현황판정", row.get("포트판정", "")),
            "뉴스/재료": news_text,
            "다음 확인": _portfolio_next_check_condition(row),
            "근거": row.get("근거", ""),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values(["우선점수", "티커"], ascending=[False, True]).reset_index(drop=True)
    limit = max(int(limit), 1)
    risk_df = result[result["점검그룹"].eq(PORTFOLIO_NEXT_CHECK_PRIORITY_GROUPS[0])]
    dca_df = result[result["점검그룹"].eq(PORTFOLIO_NEXT_CHECK_PRIORITY_GROUPS[1])]
    add_df = result[result["점검그룹"].eq(PORTFOLIO_NEXT_CHECK_PRIORITY_GROUPS[2])]
    wait_df = result[~result["점검그룹"].isin(PORTFOLIO_NEXT_CHECK_PRIORITY_GROUPS)]
    if len(result) > limit and (not risk_df.empty or not dca_df.empty) and not add_df.empty:
        remaining = limit
        max_risk_quota = 3 if len(risk_df) >= 3 else 2
        if dca_df.empty:
            max_risk_quota = max(max_risk_quota, 3)
        risk_quota = min(max_risk_quota, len(risk_df), remaining)
        remaining -= risk_quota
        dca_quota = min(1, len(dca_df), remaining)
        remaining -= dca_quota
        add_quota = min(len(add_df), remaining)
        remaining -= add_quota
        wait_quota = max(remaining, 0)
        result = pd.concat([
            risk_df.head(risk_quota),
            dca_df.head(dca_quota),
            add_df.head(add_quota),
            wait_df.head(wait_quota),
        ], ignore_index=True)
    else:
        result = result.head(limit).copy()
    result["_group_order"] = result["점검그룹"].map(PORTFOLIO_NEXT_CHECK_GROUP_ORDER).fillna(9)
    result = result.sort_values(["_group_order", "우선점수", "티커"], ascending=[True, False, True]).drop(columns=["_group_order"]).reset_index(drop=True)
    result.insert(0, "우선", range(1, len(result) + 1))
    return result


def build_portfolio_next_check_summary(candidates):
    if not isinstance(candidates, pd.DataFrame) or candidates.empty:
        return ""

    labels = [
        ("줄이기/중단 점검", "줄이기/중단"),
        ("회복/DCA 대기", "회복/DCA 대기"),
        ("늘리기/적립 확인", "늘리기/적립"),
        ("보유/대기 점검", "보유/대기"),
    ]
    parts = []
    for group, label in labels:
        group_df = candidates[candidates.get("점검그룹", "").eq(group)] if "점검그룹" in candidates.columns else pd.DataFrame()
        if group_df.empty:
            continue
        names = []
        for _, row in group_df.head(2).iterrows():
            name = _first_portfolio_text(row.get("후보", ""), row.get("티커", ""), default="")
            if name:
                names.append(name)
        suffix = f": {', '.join(names)}" if names else ""
        parts.append(f"{label} {len(group_df)}개{suffix}")

    if not parts:
        return ""
    return "오늘 점검 순서: " + " · ".join(parts) + ". 줄일 것부터 위험을 잠그고, DCA는 조건을 기다린 뒤, 남는 예산만 늘릴 후보로 봅니다."


def _normalize_bucket(value):
    raw = str(value or "").strip().lower()
    if raw in ["core", "swing", "reserve", "cash"]:
        return raw
    return "core"


def _is_reserve_or_cash_bucket(bucket):
    return _normalize_bucket(bucket) in {"reserve", "cash"}


def apply_holdings_weight_columns(df, krw_cash, usd_cash, usdkrw):
    if df.empty:
        return df

    df = df.copy()
    total_assets = df["원화환산"].sum() + krw_cash + (usd_cash * usdkrw)
    if total_assets > 0:
        df["현재비중"] = df["원화환산"] / total_assets * 100
    else:
        df["현재비중"] = 0.0

    df["운용대상"] = ~df["bucket"].apply(_is_reserve_or_cash_bucket)
    df["비중차이"] = df.apply(
        lambda r: 0.0 if _is_reserve_or_cash_bucket(r.get("bucket")) else float(r["목표비중"]) - float(r["현재비중"]),
        axis=1,
    )
    df["리밸런싱목표비중"] = df.apply(
        lambda r: float(r["현재비중"]) if _is_reserve_or_cash_bucket(r.get("bucket")) else float(r["목표비중"]),
        axis=1,
    )
    return df


def calc_portfolio_summary(holdings_table, seed_money, krw_cash, usd_cash, usdkrw, dividends_df):
    stock_value = holdings_table["원화환산"].sum() if not holdings_table.empty else 0.0
    cash_value = krw_cash + (usd_cash * usdkrw)
    current_asset = stock_value + cash_value

    total_dividend = 0.0
    if dividends_df is not None and not dividends_df.empty:
        for _, r in dividends_df.iterrows():
            amt = float(r.get("amount", 0) or 0)
            ccy = str(r.get("currency", "KRW")).upper()
            total_dividend += amt if ccy == "KRW" else amt * usdkrw

    cum_profit = current_asset + total_dividend - seed_money
    cum_return = (cum_profit / seed_money * 100) if seed_money > 0 else 0.0

    return {
        "current_asset": current_asset,
        "stock_value": stock_value,
        "cash_value": cash_value,
        "total_dividend": total_dividend,
        "cum_profit": cum_profit,
        "cum_return": cum_return,
    }


def make_cash_rows(krw_cash, usd_cash, usdkrw, total_asset):
    rows = []
    total_asset = float(total_asset or 0)

    if krw_cash > 0:
        cur_w = krw_cash / total_asset * 100 if total_asset > 0 else 0.0
        rows.append({
            "자산명": "원화예수금", "티커": "KRW_CASH", "보유량": krw_cash,
            "매입가": 1.0, "현재가": 1.0, "평가금액": krw_cash, "평가손익": 0.0,
            "수익률": 0.0, "원화환산": krw_cash, "현재비중": cur_w,
            "목표비중": 0.0, "비중차이": 0.0, "is_etf": True,
            "asset_class": "cash", "bucket": "cash", "운용대상": False,
            "리밸런싱목표비중": cur_w,
        })

    if usd_cash > 0:
        usd_cash_krw = usd_cash * usdkrw
        cur_w = usd_cash_krw / total_asset * 100 if total_asset > 0 else 0.0
        rows.append({
            "자산명": "달러예수금", "티커": "USD_CASH", "보유량": usd_cash,
            "매입가": usdkrw, "현재가": usdkrw, "평가금액": usd_cash, "평가손익": 0.0,
            "수익률": 0.0, "원화환산": usd_cash_krw, "현재비중": cur_w,
            "목표비중": 0.0, "비중차이": 0.0, "is_etf": True,
            "asset_class": "cash", "bucket": "cash", "운용대상": False,
            "리밸런싱목표비중": cur_w,
        })

    return rows


def append_cash_rows(df, krw_cash, usd_cash, usdkrw, total_asset):
    cash_rows = make_cash_rows(krw_cash, usd_cash, usdkrw, total_asset)
    if cash_rows:
        return pd.concat([df, pd.DataFrame(cash_rows)], ignore_index=True)
    return df


def calc_pnl_krw_from_row(row, usdkrw):
    ticker = str(row.get("티커", "")).upper()
    pnl = clean_float(row.get("평가손익"), 0.0)
    if is_kr_listed(ticker) or "CASH" in ticker:
        return pnl
    return pnl * clean_float(usdkrw, 1400.0)


def calc_reserve_summary(df, reserve_target_weight):
    total = float(df["원화환산"].sum()) if not df.empty else 0.0
    bucket = df["bucket"].apply(_normalize_bucket) if not df.empty else pd.Series(dtype=str)

    waiting_value = float(df.loc[bucket.isin(["reserve", "cash"]), "원화환산"].sum()) if total > 0 else 0.0
    reserve_value = float(df.loc[bucket == "reserve", "원화환산"].sum()) if total > 0 else 0.0
    cash_value = float(df.loc[bucket == "cash", "원화환산"].sum()) if total > 0 else 0.0
    invest_value = total - waiting_value

    waiting_pct = waiting_value / total * 100 if total > 0 else 0.0
    excess_pct = max(waiting_pct - float(reserve_target_weight), 0.0)

    return {
        "total": total,
        "invest_value": invest_value,
        "waiting_value": waiting_value,
        "reserve_value": reserve_value,
        "cash_value": cash_value,
        "waiting_pct": waiting_pct,
        "target_pct": float(reserve_target_weight),
        "excess_pct": excess_pct,
        "deployable_value": total * excess_pct / 100 if total > 0 else 0.0,
    }


def build_asset_overview_kpis(holdings_table, portfolio_summary, reserve_summary):
    df = holdings_table.copy() if holdings_table is not None else pd.DataFrame()
    current_asset = clean_float(portfolio_summary.get("current_asset"), 0.0)
    cum_return = clean_float(portfolio_summary.get("cum_return"), 0.0)
    waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_pct = clean_float(reserve_summary.get("target_pct"), 0.0)
    waiting_gap = waiting_pct - target_pct

    active_df = pd.DataFrame()
    if not df.empty and "운용대상" in df.columns:
        active_df = df[df["운용대상"].apply(clean_bool)].copy()
    elif not df.empty:
        active_df = df.copy()

    if not active_df.empty and "티커" in active_df.columns:
        active_df = active_df[~active_df["티커"].astype(str).str.upper().isin(["KRW_CASH", "USD_CASH"])]

    top_name = "-"
    top_weight = 0.0
    target_sum = 0.0
    rebalance_count = 0
    stale_price_count = 0
    etf_weight = 0.0

    if not active_df.empty:
        if "현재비중" in active_df.columns:
            weight_series = active_df["현재비중"].apply(clean_float)
            top_idx = weight_series.idxmax()
            top_weight = float(weight_series.loc[top_idx])
            top_name = str(active_df.loc[top_idx].get("자산명", active_df.loc[top_idx].get("티커", "-")) or "-")
            if "is_etf" in active_df.columns:
                etf_weight = float(active_df.loc[active_df["is_etf"].apply(clean_bool), "현재비중"].apply(clean_float).sum())

        if "리밸런싱목표비중" in active_df.columns:
            target_sum = float(active_df["리밸런싱목표비중"].apply(clean_float).sum())
        elif "목표비중" in active_df.columns:
            target_sum = float(active_df["목표비중"].apply(clean_float).sum())

        if "비중차이" in active_df.columns:
            rebalance_count = int((active_df["비중차이"].apply(clean_float).abs() >= 3.0).sum())

        if "현재가" in active_df.columns:
            stale_price_count = int((active_df["현재가"].apply(clean_float) <= 0).sum())

    if waiting_gap < -5:
        cash_status, cash_level = "부족", "주의"
    elif waiting_gap > 10:
        cash_status, cash_level = "여유", "양호"
    else:
        cash_status, cash_level = "정상", "양호"

    if top_weight >= 50:
        concentration_status, concentration_level = "집중위험", "위험"
    elif top_weight >= 35:
        concentration_status, concentration_level = "집중주의", "주의"
    else:
        concentration_status, concentration_level = "분산양호", "양호"

    if target_sum > 100.5:
        target_status, target_level = "초과", "위험"
    elif target_sum < 50 and len(active_df) > 0:
        target_status, target_level = "낮음", "참고"
    else:
        target_status, target_level = "정상", "양호"

    if stale_price_count > 0:
        data_status, data_level = "확인필요", "주의"
    else:
        data_status, data_level = "정상", "양호"

    if cum_return < -15:
        return_status, return_level = "손실확대", "주의"
    elif cum_return < 0:
        return_status, return_level = "손실권", "참고"
    else:
        return_status, return_level = "수익권", "양호"

    alerts = []
    if cash_level == "주의":
        alerts.append(f"대기자금이 목표보다 {abs(waiting_gap):.1f}%p 낮습니다.")
    elif waiting_gap > 10:
        alerts.append(f"대기자금이 목표보다 {waiting_gap:.1f}%p 높습니다. 투입 대기 자금인지 확인하세요.")
    if concentration_level in ["주의", "위험"]:
        alerts.append(f"최대 비중 자산은 {top_name} {top_weight:.1f}%입니다.")
    if target_level == "위험":
        alerts.append(f"운용대상 목표비중 합계가 {target_sum:.1f}%입니다.")
    if rebalance_count > 0:
        alerts.append(f"목표비중과 3%p 이상 차이나는 자산이 {rebalance_count}개 있습니다.")
    if stale_price_count > 0:
        alerts.append(f"현재가가 0이거나 누락된 운용자산이 {stale_price_count}개 있습니다.")

    kpis = [
        {"title": "운용 상태", "status": "점검" if alerts else "정상", "level": "주의" if alerts else "양호", "value": f"{len(alerts)}건", "detail": "확인 필요" if alerts else "큰 이상 없음"},
        {"title": "대기자금", "status": cash_status, "level": cash_level, "value": f"{waiting_pct:.1f}%", "detail": f"목표 {target_pct:.1f}% / {waiting_gap:+.1f}%p"},
        {"title": "집중도", "status": concentration_status, "level": concentration_level, "value": f"{top_weight:.1f}%", "detail": top_name},
        {"title": "목표비중", "status": target_status, "level": target_level, "value": f"{target_sum:.1f}%", "detail": f"리밸런싱 {rebalance_count}개"},
        {"title": "성과 상태", "status": return_status, "level": return_level, "value": f"{cum_return:.2f}%", "detail": f"총자산 {current_asset:,.0f}원"},
        {"title": "ETF 비중", "status": "참고", "level": "참고", "value": f"{etf_weight:.1f}%", "detail": "운용자산 내 ETF"},
        {"title": "데이터", "status": data_status, "level": data_level, "value": f"{stale_price_count}개", "detail": "현재가 누락"},
    ]

    return kpis, alerts


def build_asset_overview_dashboard_state(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    portfolio_summary = portfolio_summary or {}
    holdings = holdings_table.copy() if holdings_table is not None else pd.DataFrame()
    current_asset = clean_float(portfolio_summary.get("current_asset"), 0.0)
    full_df = append_cash_rows(holdings, krw_cash, usd_cash, usdkrw, current_asset)
    reserve_summary = calc_reserve_summary(full_df, reserve_target_weight)

    stock_value = clean_float(portfolio_summary.get("stock_value"), 0.0)
    cash_value = clean_float(portfolio_summary.get("cash_value"), 0.0)
    total_dividend = clean_float(portfolio_summary.get("total_dividend"), 0.0)
    cum_profit = clean_float(portfolio_summary.get("cum_profit"), 0.0)
    cum_return = clean_float(portfolio_summary.get("cum_return"), 0.0)
    invest_value = clean_float(reserve_summary.get("invest_value"), 0.0)
    waiting_value = clean_float(reserve_summary.get("waiting_value"), 0.0)
    waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_pct = clean_float(reserve_summary.get("target_pct"), 0.0)
    excess_pct = clean_float(reserve_summary.get("excess_pct"), 0.0)
    deployable_value = clean_float(reserve_summary.get("deployable_value"), 0.0)
    waiting_gap = waiting_pct - target_pct
    invest_pct = (invest_value / current_asset * 100) if current_asset > 0 else 0.0

    kpis, alerts = build_asset_overview_kpis(holdings_table, portfolio_summary, reserve_summary)

    return {
        "full_df": full_df,
        "reserve_summary": reserve_summary,
        "kpis": kpis,
        "alerts": alerts,
        "metrics": {
            "current_asset": current_asset,
            "stock_value": stock_value,
            "cash_value": cash_value,
            "total_dividend": total_dividend,
            "cum_profit": cum_profit,
            "cum_return": cum_return,
            "invest_value": invest_value,
            "waiting_value": waiting_value,
            "waiting_pct": waiting_pct,
            "target_pct": target_pct,
            "excess_pct": excess_pct,
            "deployable_value": deployable_value,
            "profit_label": "수익" if cum_profit >= 0 else "손실",
            "profit_delta": f"{cum_return:.2f}%",
            "waiting_gap": waiting_gap,
            "waiting_delta": f"{waiting_gap:+.2f}%p vs 목표",
            "invest_pct": invest_pct,
        },
    }


def build_scenario_context(holdings_table, krw_cash, usd_cash, usdkrw, reserve_target_weight):
    total_asset = (
        float(holdings_table["원화환산"].sum()) if holdings_table is not None and not holdings_table.empty and "원화환산" in holdings_table.columns else 0.0
    ) + clean_float(krw_cash) + clean_float(usd_cash) * clean_float(usdkrw, 1400.0)
    full_df = append_cash_rows(
        holdings_table.copy() if holdings_table is not None else pd.DataFrame(),
        krw_cash,
        usd_cash,
        usdkrw,
        total_asset,
    )
    active_df = get_active_portfolio_rows(full_df)
    reserve_summary = calc_reserve_summary(full_df, reserve_target_weight)
    label_map = build_asset_label_map(active_df)

    return {
        "total_asset": total_asset,
        "full_df": full_df,
        "active_df": active_df,
        "reserve_summary": reserve_summary,
        "label_map": label_map,
    }


def calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier=True):
    if active_df is None or active_df.empty:
        return pd.DataFrame(columns=["자산", "티커", "현재금액", "현재비중", "적용충격", "예상손익", "충격후금액", "충격배수"])

    label_map = build_asset_label_map(active_df)
    rows = []
    for _, row in active_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        value = clean_float(row.get("원화환산"), 0.0)
        multiplier = infer_scenario_shock_multiplier(row) if use_multiplier else 1.0
        applied_shock = clean_float(shock_pct, 0.0) * multiplier
        pnl = value * applied_shock / 100
        rows.append({
            "자산": label_map.get(ticker, str(row.get("자산명", "")).strip() or ticker),
            "티커": ticker,
            "현재금액": value,
            "현재비중": value / total_asset * 100 if total_asset > 0 else 0.0,
            "적용충격": applied_shock,
            "예상손익": pnl,
            "충격후금액": max(value + pnl, 0.0),
            "충격배수": multiplier,
        })

    return pd.DataFrame(rows).sort_values("예상손익").reset_index(drop=True)


def build_market_scenario_summary(active_df, total_asset, shock_values, use_multiplier=True):
    rows = []
    for shock_pct in shock_values:
        detail_df = calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier)
        total_pnl = float(detail_df["예상손익"].sum()) if not detail_df.empty else 0.0
        after_asset = total_asset + total_pnl
        rows.append({
            "시나리오": f"운용자산 {shock_pct:+.0f}%",
            "기본충격": shock_pct,
            "예상손익": total_pnl,
            "충격후자산": after_asset,
            "총자산변화율": total_pnl / total_asset * 100 if total_asset > 0 else 0.0,
        })

    return pd.DataFrame(rows)


def build_cash_buffer_scenario(active_df, total_asset, reserve_summary, target_waiting_pct, shock_pct, use_multiplier=True):
    active_value = float(active_df["원화환산"].sum()) if active_df is not None and not active_df.empty else 0.0
    current_waiting_pct = clean_float(reserve_summary.get("waiting_pct"), 0.0)
    target_waiting_pct = clean_float(target_waiting_pct, current_waiting_pct)
    additional_waiting = max(total_asset * (target_waiting_pct - current_waiting_pct) / 100, 0.0)

    current_detail = calc_asset_shock_table(active_df, total_asset, shock_pct, use_multiplier)
    current_loss = float(current_detail["예상손익"].sum()) if not current_detail.empty else 0.0

    if active_value <= 0:
        rebalanced_loss = current_loss
    else:
        exposure_ratio = max((active_value - additional_waiting) / active_value, 0.0)
        rebalanced_loss = current_loss * exposure_ratio

    return {
        "current_waiting_pct": current_waiting_pct,
        "target_waiting_pct": target_waiting_pct,
        "additional_waiting": additional_waiting,
        "current_loss": current_loss,
        "rebalanced_loss": rebalanced_loss,
        "loss_reduction": rebalanced_loss - current_loss,
        "current_after_asset": total_asset + current_loss,
        "rebalanced_after_asset": total_asset + rebalanced_loss,
    }


def _portfolio_ticker_key(ticker):
    raw = sanitize_ticker_value(ticker)
    if not raw:
        return ""
    raw = re.sub(r"^(NYSE|NASDAQ|AMEX|ARCA|BATS):", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\.(KS|KQ|US|NYSE|NASDAQ|AMEX|ARCA|NMS|NYQ|O|PK)$", "", raw, flags=re.IGNORECASE)
    return normalize_ticker(raw)


def get_holding_row_by_ticker(holdings_table, ticker):
    if holdings_table.empty:
        return None
    t = _portfolio_ticker_key(ticker)
    if not t or "티커" not in holdings_table.columns:
        return None
    matched = holdings_table[holdings_table["티커"].apply(_portfolio_ticker_key) == t]
    if not matched.empty:
        return matched.iloc[0]
    return None


def parse_month_end_date(value):
    raw = str(value or "").strip()
    if not raw:
        return pd.NaT

    if len(raw) == 7 and raw[4] == "-":
        dt = pd.to_datetime(f"{raw}-01", errors="coerce")
    else:
        dt = pd.to_datetime(raw, errors="coerce")

    if pd.isna(dt):
        return pd.NaT

    return dt + pd.offsets.MonthEnd(0)


def prepare_monthly_performance_df(monthly_df):
    required = ["month", "total_invested", "evaluated_value", "dividend"]
    if monthly_df is None or monthly_df.empty:
        return pd.DataFrame(columns=required)

    df = monthly_df.copy()
    for col in required:
        if col not in df.columns:
            df[col] = 0 if col != "month" else ""

    df["month_end"] = df["month"].apply(parse_month_end_date)
    df = df.dropna(subset=["month_end"]).sort_values("month_end")

    if df.empty:
        return df

    df["month_label"] = df["month_end"].dt.strftime("%y-%m")
    for col in ["total_invested", "evaluated_value", "dividend"]:
        df[col] = df[col].apply(clean_float)

    df["cum_dividend"] = df["dividend"].cumsum()
    df["cum_profit"] = df["evaluated_value"] + df["cum_dividend"] - df["total_invested"]
    df["cum_return_pct"] = np.where(
        df["total_invested"] > 0,
        df["cum_profit"] / df["total_invested"] * 100,
        0.0,
    )

    first_return = float(df["cum_return_pct"].iloc[0]) if not df.empty else 0.0
    df["relative_return_pct"] = df["cum_return_pct"] - first_return
    return df


def build_monthly_record_status(monthly_logs_df, portfolio_summary, today=None):
    perf_df = prepare_monthly_performance_df(monthly_logs_df)
    today_ts = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
    current_month = today_ts.strftime("%Y-%m")
    previous_month = (today_ts.replace(day=1) - pd.Timedelta(days=1)).strftime("%Y-%m")

    empty_status = {
        "is_empty": True,
        "status": "기록 없음",
        "latest_month": "-",
        "record_count": 0,
        "latest_asset": 0.0,
        "latest_return": 0.0,
        "current_asset": clean_float((portfolio_summary or {}).get("current_asset"), 0.0),
        "asset_gap": 0.0,
    }
    if perf_df is None or perf_df.empty:
        return empty_status

    latest = perf_df.iloc[-1]
    latest_month = pd.Timestamp(latest["month_end"]).strftime("%Y-%m")
    latest_asset = clean_float(latest.get("evaluated_value"), 0.0)
    latest_return = clean_float(latest.get("cum_return_pct"), 0.0)
    current_asset = clean_float((portfolio_summary or {}).get("current_asset"), 0.0)
    asset_gap = current_asset - latest_asset

    if latest_month == current_month:
        status = "이번 달 기록 있음"
    elif latest_month == previous_month:
        status = "최근 월 기록 완료"
    else:
        status = "업데이트 필요"

    return {
        "is_empty": False,
        "status": status,
        "latest_month": latest_month,
        "record_count": int(len(perf_df)),
        "latest_asset": latest_asset,
        "latest_return": latest_return,
        "current_asset": current_asset,
        "asset_gap": asset_gap,
    }


def _month_end_price_points(close, month_ends):
    close = pd.Series(close).dropna().copy()
    if close.empty:
        return []

    close.index = pd.to_datetime(close.index).tz_localize(None)
    prices = []
    for month_end in month_ends:
        target_dt = pd.Timestamp(month_end).tz_localize(None)
        eligible = close[close.index <= target_dt]
        prices.append(float(eligible.iloc[-1]) if not eligible.empty else np.nan)
    return prices


def _add_single_benchmark_rows(rows, perf_df, label, ticker):
    try:
        px = load_price_df(ticker, "5y")
        if px.empty or "Close" not in px.columns:
            return

        prices = _month_end_price_points(px["Close"], perf_df["month_end"])
        valid_prices = [p for p in prices if finite_num(p) and p > 0]
        if not valid_prices:
            return

        base = valid_prices[0]
        for month_label, price in zip(perf_df["month_label"], prices):
            if finite_num(price) and price > 0:
                ret = (float(price) / base - 1) * 100
                rows.append({"month_label": month_label, "구분": label, "수익률_pct": ret})
    except Exception:
        return


def _add_blended_benchmark_rows(rows, perf_df, benchmark_spec):
    if not benchmark_spec:
        return

    components = benchmark_spec.get("components", []) if isinstance(benchmark_spec, dict) else []
    if not components:
        return

    weighted_returns = []
    weight_sum = 0.0
    for comp in components:
        try:
            ticker = str(comp.get("ticker", "")).strip()
            weight = clean_float(comp.get("weight"), 0.0)
            multiplier = clean_float(comp.get("multiplier"), 1.0)
            if not ticker or weight <= 0:
                continue

            px = load_price_df(ticker, "5y")
            if px.empty or "Close" not in px.columns:
                continue

            prices = _month_end_price_points(px["Close"], perf_df["month_end"])
            valid_prices = [p for p in prices if finite_num(p) and p > 0]
            if not valid_prices:
                continue

            base = valid_prices[0]
            comp_returns = []
            for price in prices:
                if finite_num(price) and price > 0:
                    comp_returns.append((float(price) / base - 1) * 100 * multiplier)
                else:
                    comp_returns.append(np.nan)
            weighted_returns.append((weight, comp_returns))
            weight_sum += weight
        except Exception:
            continue

    if not weighted_returns or weight_sum <= 0:
        return

    label = str(benchmark_spec.get("label") or "내 목표비중 벤치")
    for idx, month_label in enumerate(perf_df["month_label"]):
        numerator = 0.0
        usable_weight = 0.0
        for weight, comp_returns in weighted_returns:
            if idx >= len(comp_returns):
                continue
            value = comp_returns[idx]
            if finite_num(value):
                numerator += weight * value
                usable_weight += weight
        if usable_weight > 0:
            rows.append({
                "month_label": month_label,
                "구분": label,
                "수익률_pct": numerator / usable_weight,
            })


def build_benchmark_return_df(perf_df, benchmark_spec=None):
    if perf_df is None or perf_df.empty or "month_end" not in perf_df.columns:
        return pd.DataFrame(columns=["month_label", "구분", "수익률_pct"])

    rows = []
    for _, row in perf_df.iterrows():
        rows.append({
            "month_label": row["month_label"],
            "구분": "내 기간수익률",
            "수익률_pct": float(row.get("relative_return_pct", 0.0)),
        })

    benchmarks = {
        "S&P500": "379800.KS",
        "나스닥100": "379810.KS",
        "코스피": "069500.KS",
    }

    _add_blended_benchmark_rows(rows, perf_df, benchmark_spec)

    for label, ticker in benchmarks.items():
        _add_single_benchmark_rows(rows, perf_df, label, ticker)

    return pd.DataFrame(rows)


def infer_benchmark_leverage_multiplier(ticker, asset_name=""):
    text = f"{str(ticker or '').upper()} {str(asset_name or '').upper()}".replace(" ", "")

    inverse = any(k in text for k in ["INVERSE", "BEAR", "인버스", "곱버스", "SQQQ", "SOXS", "SPXU", "SDOW"])
    if any(k in text for k in ["3X", "3배", "TQQQ", "SQQQ", "SOXL", "SOXS", "UPRO", "SPXL", "SPXU", "SDOW", "TECL", "FNGU"]):
        return -3.0 if inverse else 3.0
    if any(k in text for k in ["2X", "2배", "BITX", "BITU", "QLD", "SSO", "레버리지", "LEVERAGE", "ULTRA"]):
        return -2.0 if inverse else 2.0
    if inverse:
        return -1.0
    return 1.0


def infer_blended_benchmark_proxy(ticker, asset_name="", asset_class="", bucket=""):
    symbol = normalize_ticker(ticker)
    text = f"{symbol} {asset_name or ''} {asset_class or ''} {bucket or ''}".upper()
    compact = text.replace(" ", "").replace("-", "")

    if not symbol or "CASH" in symbol or normalize_bucket(bucket) in {"cash", "reserve"}:
        return None

    if any(k in compact for k in ["NASDAQ100", "NASDAQ", "나스닥100", "나스닥", "QQQ", "QQQM", "QLD", "TQQQ", "SOXX", "SOXL", "SMH", "DRAM", "RAM", "TECL", "FNGU", "379810"]):
        return {"label": "나스닥100", "ticker": "379810.KS"}
    if any(k in compact for k in ["S&P500", "SP500", "SNP500", "에스앤피", "SPY", "VOO", "IVV", "SPLG", "379800"]):
        return {"label": "S&P500", "ticker": "379800.KS"}
    if any(k in compact for k in ["KOSPI", "코스피", "KODEX200", "KODEX 200", "069500", "KODEX200"]):
        return {"label": "코스피", "ticker": "069500.KS"}

    clean_symbol_only = symbol.split(".")[0].upper()
    if is_kr_listed(symbol):
        return {"label": "코스피", "ticker": "069500.KS"}
    if clean_symbol_only in US_TECH_OR_GROWTH_TICKERS:
        return {"label": "나스닥100", "ticker": "379810.KS"}
    return {"label": "S&P500", "ticker": "379800.KS"}


def build_portfolio_blended_benchmark_spec(holdings_df):
    if holdings_df is None or getattr(holdings_df, "empty", True):
        return {}

    df = holdings_df.copy()
    if "티커" not in df.columns:
        return {}

    for col in ["목표비중", "현재비중", "전체비중", "원화환산"]:
        if col not in df.columns:
            df[col] = 0.0

    if "bucket" not in df.columns:
        df["bucket"] = "core"
    if "자산명" not in df.columns:
        df["자산명"] = df["티커"]

    df["티커"] = df["티커"].astype(str).str.strip()
    df = df[df["티커"].ne("")]
    df = df[~df["티커"].astype(str).str.upper().isin(["KRW_CASH", "USD_CASH"])]
    df = df[~df["bucket"].apply(lambda value: normalize_bucket(value) in {"cash", "reserve"})]
    if "운용대상" in df.columns:
        df = df[df["운용대상"].apply(clean_bool)]

    if df.empty:
        return {}

    target_sum = float(df["목표비중"].apply(clean_float).clip(lower=0).sum())
    current_sum = float(df["현재비중"].apply(clean_float).clip(lower=0).sum())
    total_value = float(df["원화환산"].apply(clean_float).clip(lower=0).sum())

    if target_sum > 0:
        weight_col = "목표비중"
        basis = "목표비중"
    elif current_sum > 0:
        weight_col = "현재비중"
        basis = "현재비중"
    elif total_value > 0:
        weight_col = "원화환산"
        basis = "현재금액"
    else:
        return {}

    merged = {}
    order = []
    for _, row in df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        name = str(row.get("자산명", "") or ticker).strip()
        bucket = str(row.get("bucket", "core") or "core").strip()
        asset_class = str(row.get("asset_class", "") or row.get("자산군", "") or "").strip()

        raw_weight = clean_float(row.get(weight_col), 0.0)
        if weight_col == "원화환산" and total_value > 0:
            weight = raw_weight / total_value * 100
        else:
            weight = raw_weight
        if weight <= 0:
            continue

        proxy = infer_blended_benchmark_proxy(ticker, name, asset_class, bucket)
        if not proxy:
            continue
        multiplier = infer_benchmark_leverage_multiplier(ticker, name)
        key = (proxy["label"], proxy["ticker"], float(multiplier))
        if key not in merged:
            merged[key] = {
                "label": proxy["label"],
                "ticker": proxy["ticker"],
                "weight": 0.0,
                "multiplier": float(multiplier),
            }
            order.append(key)
        merged[key]["weight"] += float(weight)

    components = [merged[key] for key in order if merged[key]["weight"] > 0]
    total_weight = sum(comp["weight"] for comp in components)
    if not components or total_weight <= 0:
        return {}

    parts = []
    for comp in components:
        multiplier = clean_float(comp.get("multiplier"), 1.0)
        mult_txt = f"x{multiplier:g}" if abs(multiplier) != 1 else ""
        parts.append(f"{comp['label']}{mult_txt} {comp['weight']:.1f}%")

    return {
        "label": "내 목표비중 벤치",
        "basis": basis,
        "components": components,
        "description": f"{basis} 기준: " + " + ".join(parts),
    }


def calc_series_mdd(series):
    series = pd.Series(series).dropna()
    if series.empty:
        return 0.0

    running_max = series.cummax()
    drawdown = series / running_max - 1
    return float(drawdown.min()) if not drawdown.empty else 0.0


def calc_drawdown_details(portfolio_curve):
    """Return underwater series and drawdown period details."""
    if portfolio_curve is None or len(portfolio_curve) < 2:
        return {}

    series = pd.Series(portfolio_curve).dropna()
    if series.empty:
        return {}

    running_max = series.cummax()
    drawdown = series / running_max - 1
    underwater = drawdown * 100

    in_dd = drawdown[drawdown < -0.001]
    avg_drawdown = float(in_dd.mean() * 100) if not in_dd.empty else 0.0

    dd_bool = drawdown < -0.001
    max_dur = cur_dur = 0
    for value in dd_bool:
        cur_dur = cur_dur + 1 if value else 0
        max_dur = max(max_dur, cur_dur)

    mdd_idx = int(drawdown.argmin())
    peak_val = float(running_max.iloc[mdd_idx])
    recovery_days = np.nan
    if mdd_idx < len(series) - 1:
        post = series.iloc[mdd_idx:]
        recovered = post[post >= peak_val]
        if not recovered.empty:
            recovery_days = (recovered.index[0] - series.index[mdd_idx]).days

    n_periods = 0
    in_period = False
    for value in dd_bool:
        if value and not in_period:
            n_periods += 1
            in_period = True
        elif not value:
            in_period = False

    return {
        "underwater": underwater,
        "avg_drawdown": avg_drawdown,
        "mdd_duration_days": max_dur,
        "mdd_recovery_days": recovery_days,
        "n_drawdown_periods": n_periods,
    }


def normalize_datetime_index_no_tz(index):
    idx = pd.to_datetime(index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    return idx


def annualize_period_return(period_return_decimal, observation_count):
    if not finite_num(period_return_decimal) or observation_count <= 0:
        return np.nan
    growth = 1 + float(period_return_decimal)
    if growth <= 0:
        return -1.0
    return float(growth ** (252 / observation_count) - 1)


def calc_downside_volatility(returns, target=0.0):
    returns = pd.Series(returns).dropna()
    if returns.empty:
        return np.nan
    downside = returns[returns < target] - target
    if downside.empty:
        return 0.0
    return float(downside.std() * np.sqrt(252))


def calc_var_cvar(returns, confidence=0.95):
    returns = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 20:
        return np.nan, np.nan

    tail_cut = float(returns.quantile(1 - confidence))
    tail = returns[returns <= tail_cut]
    cvar = float(tail.mean()) if not tail.empty else tail_cut
    return tail_cut * 100, cvar * 100


def ratio_or_nan(numer, denom):
    if not finite_num(numer) or not finite_num(denom) or float(denom) == 0:
        return np.nan
    return float(numer) / float(denom)


def calc_benchmark_metrics_from_returns(portfolio_returns, benchmark_returns, label="", benchmark_ticker="", rf_rate=0.035):
    if portfolio_returns is None or portfolio_returns.empty or benchmark_returns is None or benchmark_returns.empty:
        return {}

    try:
        br_all = pd.Series(benchmark_returns).replace([np.inf, -np.inf], np.nan).dropna()
        br_all.index = normalize_datetime_index_no_tz(br_all.index)
        common = portfolio_returns.index.intersection(br_all.index)
        if len(common) < 20:
            return {}

        pr = pd.Series(portfolio_returns.loc[common]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        br = pd.Series(br_all.loc[common]).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        bm_var = float(br.var())
        if bm_var <= 0:
            return {}

        beta = float(np.cov(pr.values, br.values)[0, 1] / bm_var)
        bm_period_ret = float((1 + br).prod() - 1)
        bm_annual = annualize_period_return(bm_period_ret, len(br)) if np.isfinite(bm_period_ret) else np.nan
        port_annual = annualize_period_return(float((1 + pr).prod() - 1), len(pr))

        alpha = np.nan
        if np.isfinite(bm_annual) and np.isfinite(port_annual):
            alpha = (port_annual - (rf_rate + beta * (bm_annual - rf_rate))) * 100

        active_ret = pr - br
        tracking_error = float(active_ret.std() * np.sqrt(252) * 100)
        info_ratio = ratio_or_nan(float(active_ret.mean() * 252 * 100), tracking_error)

        return {
            "beta": round(beta, 2),
            "alpha": round(alpha, 2) if np.isfinite(alpha) else np.nan,
            "tracking_error": round(tracking_error, 1),
            "info_ratio": round(info_ratio, 2) if np.isfinite(info_ratio) else np.nan,
            "bm_annual_return": round(bm_annual * 100, 1) if np.isfinite(bm_annual) else np.nan,
            "bm_period_return": round(bm_period_ret * 100, 1) if np.isfinite(bm_period_ret) else np.nan,
            "benchmark_ticker": benchmark_ticker,
            "benchmark_label": label,
            "n_common_days": len(common),
        }
    except Exception:
        return {}


def build_blended_benchmark_returns(benchmark_spec, period, analysis_start_date=None):
    if not benchmark_spec:
        return pd.Series(dtype=float)

    components = benchmark_spec.get("components", []) if isinstance(benchmark_spec, dict) else []
    if not components:
        return pd.Series(dtype=float)

    series_list = []
    weight_map = {}
    for idx, comp in enumerate(components):
        try:
            ticker = str(comp.get("ticker", "")).strip()
            weight = clean_float(comp.get("weight"), 0.0)
            multiplier = clean_float(comp.get("multiplier"), 1.0)
            if not ticker or weight <= 0:
                continue

            px_df = load_price_df(ticker, period)
            if px_df is None or px_df.empty or "Close" not in px_df.columns:
                continue
            close = pd.Series(px_df["Close"]).dropna()
            close.index = normalize_datetime_index_no_tz(close.index)
            if analysis_start_date is not None:
                close = close[close.index >= analysis_start_date]
            if len(close) < 20:
                continue

            key = f"bench_{idx}"
            ret = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna() * multiplier
            if ret.empty:
                continue
            series_list.append(ret.rename(key))
            weight_map[key] = weight
        except Exception:
            continue

    if not series_list or not weight_map:
        return pd.Series(dtype=float)

    returns_df = pd.concat(series_list, axis=1).sort_index().ffill(limit=3).dropna(how="all").fillna(0.0)
    weights = pd.Series(weight_map, dtype=float)
    usable = [col for col in returns_df.columns if col in weights.index]
    if not usable:
        return pd.Series(dtype=float)

    weights = weights[usable]
    weight_sum = float(weights.sum())
    if weight_sum <= 0:
        return pd.Series(dtype=float)

    return returns_df[usable].mul(weights / weight_sum, axis=1).sum(axis=1).dropna()


def calc_blended_benchmark_comparison(portfolio_returns, benchmark_spec, period, rf_rate=0.035, analysis_start_date=None):
    benchmark_returns = build_blended_benchmark_returns(benchmark_spec, period, analysis_start_date=analysis_start_date)
    result = calc_benchmark_metrics_from_returns(
        portfolio_returns,
        benchmark_returns,
        label=benchmark_spec.get("label", "내 목표비중 벤치") if benchmark_spec else "",
        benchmark_ticker="BLENDED",
        rf_rate=rf_rate,
    )
    if result and benchmark_spec:
        result["benchmark_description"] = benchmark_spec.get("description", "")
    return result


def calc_benchmark_comparison(portfolio_returns, benchmark_ticker, period, rf_rate=0.035, analysis_start_date=None):
    """Return beta, alpha, tracking error, and information ratio."""
    if portfolio_returns is None or portfolio_returns.empty:
        return {}
    try:
        bm_df = load_price_df(benchmark_ticker, period)
        if bm_df is None or bm_df.empty or "Close" not in bm_df.columns:
            return {}
        bm_close = pd.Series(bm_df["Close"]).dropna()
        bm_close.index = normalize_datetime_index_no_tz(bm_close.index)
        if analysis_start_date is not None:
            bm_close = bm_close[bm_close.index >= analysis_start_date]
        bm_returns = bm_close.pct_change().dropna()
        return calc_benchmark_metrics_from_returns(
            portfolio_returns,
            bm_returns,
            label=benchmark_ticker,
            benchmark_ticker=benchmark_ticker,
            rf_rate=rf_rate,
        )
    except Exception:
        return {}


def calc_rolling_metrics(portfolio_returns, window=63, rf_rate=0.035):
    """Return rolling annualized volatility and Sharpe series."""
    if portfolio_returns is None or len(portfolio_returns) < window + 5:
        return pd.DataFrame()
    rolling_vol = portfolio_returns.rolling(window).std() * np.sqrt(252) * 100
    rolling_ret = portfolio_returns.rolling(window).mean() * 252
    rolling_sharpe = ((rolling_ret - rf_rate) / (rolling_vol / 100)).replace([np.inf, -np.inf], np.nan)
    df = pd.DataFrame({"rolling_vol": rolling_vol, "rolling_sharpe": rolling_sharpe}, index=portfolio_returns.index)
    return df.dropna(how="all")


def get_active_portfolio_rows(holdings_table):
    if holdings_table is None or holdings_table.empty:
        return pd.DataFrame()

    df = holdings_table.copy()
    if "원화환산" not in df.columns or "티커" not in df.columns:
        return pd.DataFrame()

    df["원화환산"] = df["원화환산"].apply(clean_float)
    df = df[df["원화환산"] > 0].copy()

    if "bucket" in df.columns:
        df = df[~df["bucket"].apply(lambda value: _normalize_bucket(value) in ["reserve", "cash"])]
    if "운용대상" in df.columns:
        df = df[df["운용대상"].apply(clean_bool)]

    df = df[~df["티커"].astype(str).str.upper().isin(["KRW_CASH", "USD_CASH"])]
    return df.reset_index(drop=True)


PORTFOLIO_SIGNAL_COLUMNS = [
    "기술적타점",
    "ADJ점수",
    "후보등급",
    "추세",
    "RS",
    "RSI",
    "MFI",
    "MACD",
    "SQZ",
    "판정코드",
    "실행메모",
    "핵심근거",
]


def _portfolio_signal_key(ticker):
    text = sanitize_ticker_value(ticker)
    if ":" in text:
        text = text.split(":")[-1]
    for suffix in (".US", ".KS", ".KQ"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def merge_portfolio_signal_details(holdings_table, signal_df):
    """Attach cached today-check/precision signal columns to portfolio holdings."""
    holdings = holdings_table.copy() if isinstance(holdings_table, pd.DataFrame) else pd.DataFrame()
    if holdings.empty or "티커" not in holdings.columns:
        return holdings
    if not isinstance(signal_df, pd.DataFrame) or signal_df.empty or "티커" not in signal_df.columns:
        return holdings

    usable_cols = [col for col in PORTFOLIO_SIGNAL_COLUMNS if col in signal_df.columns]
    if not usable_cols:
        return holdings

    left = holdings.copy()
    right = signal_df[["티커", *usable_cols]].copy()
    left["_signal_key"] = left["티커"].apply(_portfolio_signal_key)
    right["_signal_key"] = right["티커"].apply(_portfolio_signal_key)
    right = right[right["_signal_key"].astype(str).str.len() > 0].drop_duplicates("_signal_key", keep="last")

    for col in usable_cols:
        if col in left.columns:
            left = left.drop(columns=[col])

    merged = left.merge(right.drop(columns=["티커"]), on="_signal_key", how="left")
    return merged.drop(columns=["_signal_key"])


def add_portfolio_risk_note(notes, level, area, detail, suggestion):
    notes.append({
        "등급": level,
        "영역": area,
        "내용": detail,
        "확인/조치": suggestion,
    })


def classify_portfolio_risk(risk_index):
    if risk_index >= 70:
        return "공격/위험", "#dc2626"
    if risk_index >= 50:
        return "주의", "#f59e0b"
    if risk_index >= 30:
        return "균형", "#10b981"
    return "방어", "#3b82f6"


def classify_corr_value(value):
    if value >= 0.8:
        return "매우 높음", "거의 같은 방향으로 움직입니다. 분산 효과가 낮습니다."
    if value >= 0.5:
        return "높음", "비슷한 방향으로 움직이는 편입니다."
    if value > 0.3:
        return "보통", "어느 정도 같은 방향성이 있습니다."
    if value >= -0.3:
        return "낮음", "서로 크게 묶여 움직이지 않습니다."
    return "반대", "반대로 움직이는 경향이 있어 변동성 완충에 도움이 될 수 있습니다."


def build_risk_contribution_df(asset_df, aligned_returns, weights):
    columns = ["자산명", "티커", "운용비중", "연환산변동성", "리스크기여도", "비중대비리스크"]
    if asset_df is None or asset_df.empty or aligned_returns is None or aligned_returns.empty or weights is None or weights.empty:
        return pd.DataFrame(columns=columns)

    cols = [col for col in weights.index if col in aligned_returns.columns]
    if len(cols) < 2:
        return pd.DataFrame(columns=columns)

    returns = aligned_returns[cols].replace([np.inf, -np.inf], np.nan).dropna(how="all").fillna(0.0)
    weights = weights[cols].astype(float)
    weight_sum = float(weights.sum())
    if weight_sum <= 0 or returns.empty:
        return pd.DataFrame(columns=columns)
    weights = weights / weight_sum

    cov = returns.cov() * 252
    portfolio_var = float(weights.T @ cov @ weights)
    if not np.isfinite(portfolio_var) or portfolio_var <= 0:
        return pd.DataFrame(columns=columns)

    marginal = cov.dot(weights)
    contribution = (weights * marginal / portfolio_var) * 100
    vol = returns.std() * np.sqrt(252) * 100

    name_map = {
        str(row.get("티커", "")): str(row.get("자산명", "") or row.get("티커", ""))
        for _, row in asset_df.iterrows()
    }

    rows = []
    for ticker in cols:
        weight_pct = float(weights.get(ticker, 0.0) * 100)
        contrib_pct = float(contribution.get(ticker, np.nan))
        rows.append({
            "자산명": name_map.get(ticker, ticker),
            "티커": ticker,
            "운용비중": weight_pct,
            "연환산변동성": float(vol.get(ticker, np.nan)),
            "리스크기여도": contrib_pct,
            "비중대비리스크": ratio_or_nan(contrib_pct, weight_pct),
        })

    return pd.DataFrame(rows, columns=columns).sort_values("리스크기여도", ascending=False).reset_index(drop=True)


def build_asset_label_map(asset_df):
    if asset_df is None or asset_df.empty or "티커" not in asset_df.columns:
        return {}

    base_by_ticker = {}
    label_counts = {}
    for _, row in asset_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        if not ticker:
            continue
        name = str(row.get("자산명", "")).strip()
        base_label = name if name else ticker
        base_by_ticker[ticker] = base_label
        label_counts[base_label] = label_counts.get(base_label, 0) + 1

    label_map = {}
    used_labels = set()
    for ticker, base_label in base_by_ticker.items():
        label = f"{base_label} ({ticker})" if label_counts.get(base_label, 0) > 1 else base_label
        if label in used_labels:
            label = f"{base_label} ({ticker})"
        label_map[ticker] = label
        used_labels.add(label)

    return label_map


def build_correlation_pair_summary(corr_df):
    if corr_df is None or corr_df.empty or len(corr_df.columns) < 2:
        return pd.DataFrame(columns=["자산 A", "자산 B", "상관계수", "구분", "해석"])

    rows = []
    cols = list(corr_df.columns)
    for i, left in enumerate(cols):
        for j in range(i + 1, len(cols)):
            right = cols[j]
            if str(left).strip() == str(right).strip():
                continue
            value = clean_float(corr_df.iloc[i, j], np.nan)
            if not np.isfinite(value):
                continue
            label, meaning = classify_corr_value(value)
            rows.append({
                "자산 A": left,
                "자산 B": right,
                "상관계수": value,
                "구분": label,
                "해석": meaning,
            })

    if not rows:
        return pd.DataFrame(columns=["자산 A", "자산 B", "상관계수", "구분", "해석"])

    df = pd.DataFrame(rows)
    df["_abs"] = df["상관계수"].abs()
    return df.sort_values(["상관계수", "_abs"], ascending=[False, False]).drop(columns="_abs").reset_index(drop=True)


def infer_scenario_shock_multiplier(row):
    ticker = str(row.get("티커", row.get("ticker", ""))).strip().upper()
    name = str(row.get("자산명", row.get("name", ""))).strip().upper()
    asset_class = str(row.get("asset_class", "")).strip().upper()
    text = f"{ticker} {name} {asset_class}"

    inverse = any(keyword in text for keyword in [
        "INVERSE", "인버스", "곱버스", "BEAR", "SHORT", "SQQQ", "SOXS", "SPXU", "SDS", "PSQ", "SH",
    ])

    multiplier = 1.0
    if any(keyword in text for keyword in ["3X", "3배", "TQQQ", "SOXL", "SQQQ", "SOXS", "SPXL", "SPXU", "UPRO", "TECL", "FNGU", "BULZ"]):
        multiplier = 3.0
    elif any(keyword in text for keyword in ["2X", "2배", "BITX", "BITU", "QLD", "SSO", "ROM", "USD", "UWM", "SDS", "QID"]):
        multiplier = 2.0
    elif any(keyword in text for keyword in ["레버리지", "LEVERAGE", "LEVERAGED"]):
        multiplier = 2.0

    return -multiplier if inverse else multiplier


def calc_portfolio_leverage_summary(asset_df):
    columns = ["자산명", "티커", "전체비중", "운용비중", "충격배수", "레버리지환산노출", "추가노출"]
    summary = {
        "leveraged_principal_pct": 0.0,
        "effective_exposure_pct": 0.0,
        "extra_exposure_pct": 0.0,
        "active_effective_exposure_pct": 0.0,
        "max_multiplier": 1.0,
    }

    if asset_df is None or asset_df.empty:
        return summary, pd.DataFrame(columns=columns)

    rows = []
    for _, row in asset_df.iterrows():
        ticker = str(row.get("티커", "")).strip()
        name = str(row.get("자산명", "")).strip()
        multiplier = abs(clean_float(infer_scenario_shock_multiplier({
            "티커": ticker,
            "자산명": name,
        }), 1.0))

        if multiplier <= 1.05:
            continue

        total_weight = clean_float(row.get("전체비중"), 0.0)
        active_weight = clean_float(row.get("운용비중"), 0.0)
        effective_exposure = total_weight * multiplier
        active_effective_exposure = active_weight * multiplier
        extra_exposure = max(effective_exposure - total_weight, 0.0)

        rows.append({
            "자산명": name if name else ticker,
            "티커": ticker,
            "전체비중": total_weight,
            "운용비중": active_weight,
            "충격배수": multiplier,
            "레버리지환산노출": effective_exposure,
            "추가노출": extra_exposure,
            "_active_effective_exposure": active_effective_exposure,
        })

    if not rows:
        return summary, pd.DataFrame(columns=columns)

    leverage_df = pd.DataFrame(rows)
    summary["leveraged_principal_pct"] = float(leverage_df["전체비중"].sum())
    summary["effective_exposure_pct"] = float(leverage_df["레버리지환산노출"].sum())
    summary["extra_exposure_pct"] = float(leverage_df["추가노출"].sum())
    summary["active_effective_exposure_pct"] = float(leverage_df["_active_effective_exposure"].sum())
    summary["max_multiplier"] = float(leverage_df["충격배수"].max())

    return summary, leverage_df.drop(columns=["_active_effective_exposure"], errors="ignore")[columns]


def get_portfolio_analysis_start_date(monthly_logs_df):
    perf_df = prepare_monthly_performance_df(monthly_logs_df)
    if perf_df is None or perf_df.empty or "month_end" not in perf_df.columns:
        return None

    month_end = pd.to_datetime(perf_df["month_end"], errors="coerce").dropna()
    if month_end.empty:
        return None

    first_month = pd.Timestamp(month_end.min())
    if getattr(first_month, "tzinfo", None) is not None:
        first_month = first_month.tz_convert(None)
    return first_month.replace(day=1).normalize()
