"""Monthly allocation arithmetic, separate from widgets and persistence.

This preserves the calculator's own policy; the print summary has different
normalization and signal-fallback rules and is deliberately not substituted.
"""

import math

from stock_lab_core.asset_classifier import is_known_etf_ticker, resolve_effective_investment_bucket
from stock_lab_core.formatters import clean_bool, clean_float, is_kr_listed, normalize_bucket
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

# C-6/C-11 step 2 (2026-11-26, user decisions 3 and 4). Applied after the unchanged base allocation.
UNKNOWN_SIGNAL_LABEL = "신호 미확인 · 데이터확인"
UNKNOWN_SIGNAL_STATUS = "❔ 신호 미확인"
# Always-invest no longer overrides these: hard block, target 0, target overweight/filled, data check.
ALWAYS_INVEST_SAFETY_CODES = frozenset({
    "HARD_BLOCK_FINANCIAL_F", "HARD_BLOCK_MACRO_STORM",
    "TARGET_ZERO_NO_ADD", "LEVERAGED_TARGET_ZERO_DCA_EXCLUDED",
    "HARD_BLOCK_OVERWEIGHT", "HARD_BLOCK_TARGET_FILLED", "TARGET_FILLED_HOLD", "TARGET_FILLED_S_GRADE_WAIT",
    "BELOW_COST_TARGET_FILLED", "NEW_ETF_TARGET_FILLED", "LEVERAGED_TARGET_FILLED_DCA_EXCLUDED",
    "DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA",
})
_EMPTY_SIGNALS = ("-", "", "nan", "None", "none")


def signal_is_missing(tap_raw):
    """No valid signal: no label, or the engine run failed (계산 실패). Never estimated (decision 3)."""
    tap = str(tap_raw).strip()
    return tap in _EMPTY_SIGNALS or tap.startswith("계산 실패")


def always_invest_blocked(decision):
    code = str(decision.get("decision_code") or "") if isinstance(decision, dict) else ""
    return code in ALWAYS_INVEST_SAFETY_CODES


def apply_monthly_signal_safety(calc_rows, always_invest_set, signal_multiplier, signal_decisions=None):
    """Decision 3: a missing signal gets no estimate (multiplier 0, plan 미확인, flagged signal_unknown).
    Decision 4: always-invest keeps the engine multiplier when the engine code is a safety block.
    Rows are changed in place before redistribution; every other row is left exactly as built."""
    decisions = signal_decisions or {}
    for r in calc_rows:
        r["signal_unknown"] = signal_is_missing(r["tap_raw"])
        if r["signal_unknown"]:
            r["multiplier"], r["eff_alloc"] = 0.0, 0.0
            r["tap_disp"] = UNKNOWN_SIGNAL_LABEL + (" → 항상투자 보류" if r["ticker"] in always_invest_set else "")
            continue
        decision = decisions.get(r["ticker"])
        if r["ticker"] in always_invest_set and r["bucket"] != "leverage" and always_invest_blocked(decision):
            r["multiplier"] = signal_multiplier(r["tap_raw"], r["bucket"], dip_level=r["dip_level"], decision=decision)
            r["eff_alloc"] = r["base_alloc"] * r["multiplier"]
            r["tap_disp"] = f"{r['tap_raw']} → 항상투자 보류(안전 차단)"
    return calc_rows


def prepare_rebalance_holdings(holdings_table):
    df = holdings_table.copy()
    excl_buckets = {"reserve", "cash"}
    eligible = df[~df["bucket"].apply(lambda b: normalize_bucket(str(b)) in excl_buckets)].copy()
    # Normalize on a private frame once; both the denominator and row allocation reuse it.
    eligible["목표비중"] = eligible["목표비중"].apply(lambda v: clean_float(v, 0.0))
    eligible = eligible[eligible["목표비중"] > 0]
    if "운용대상" in eligible.columns:
        eligible = eligible[eligible["운용대상"].apply(clean_bool)]
    return eligible


def build_base_allocations(eligible, target_w_sum, total_invest, _signal_cache, always_invest_set, signal_multiplier,
                           signal_decisions=None):
    calc_rows = []
    for _, row in eligible.iterrows():
        ticker   = str(row.get("티커", ""))
        name     = str(row.get("자산명", ""))
        target_w = row.get("목표비중")
        bucket   = resolve_effective_investment_bucket(name, ticker, row.get("bucket", "core"), row.get("asset_class", ""))
        cur_p    = clean_float(row.get("현재가"), 0.0)
        avg_p    = clean_float(row.get("매입가"), 0.0)
        qty      = clean_float(row.get("보유량"), 0.0)
        is_usd   = not is_kr_listed(ticker) and ticker not in ("KRW_CASH", "USD_CASH")
        asset_is_etf = (
            clean_bool(row.get("is_etf", False))
            or is_known_etf_ticker(ticker)
        )

        # 신호: 캐시에서 먼저 조회 (= 대시보드 분석과 동일 값), 없으면 holdings_table 값
        tap_raw = str(_signal_cache.get(ticker, row.get("기술적타점", "-"))).strip()

        # 표시용 레이블: 빈 신호일 때 ETF/레버리지/일반 구분
        if tap_raw in ("-", "", "nan", "None", "none"):
            if bucket == "leverage":
                tap_disp = "레버리지 (신호없음)"
            elif asset_is_etf:
                tap_disp = "ETF (신호없음)"
            else:
                tap_disp = "신호없음"
        else:
            tap_disp = tap_raw

        # 레버리지 하락 감지: 평단 대비 하락 깊이를 3단계로 분류
        # 일상 변동(-2%~-5%)은 노이즈 → -5% 이상부터 의미있는 하락으로 처리
        if bucket == "leverage" and avg_p > 0:
            pct_drop = (cur_p - avg_p) / avg_p   # 음수 = 하락
            if pct_drop <= -0.15:
                dip_level = 3   # 강하락 -15%↓
            elif pct_drop <= -0.10:
                dip_level = 2   # 중하락 -10%~-15%
            elif pct_drop <= -0.05:
                dip_level = 1   # 약하락 -5%~-10%
            else:
                dip_level = 0   # 정상 (평단 -5% 이내)
        else:
            dip_level = 0
        is_dip = dip_level > 0   # 표시용 플래그 유지

        base_alloc = total_invest * (target_w / target_w_sum)
        # B-3: pass the engine decision so the multiplier is read from its code (same values).
        decision = (signal_decisions or {}).get(ticker)
        multiplier = (signal_multiplier(tap_raw, bucket, dip_level=dip_level, decision=decision) if isinstance(decision, dict)
                      else signal_multiplier(tap_raw, bucket, dip_level=dip_level))
        if ticker in always_invest_set and bucket != "leverage":
            multiplier = 1.0
            tap_disp = f"📌 항상투자" if tap_disp in ("-", "신호없음", "ETF (신호없음)") else f"{tap_disp} → 📌무시"
        elif ticker in always_invest_set and bucket == "leverage":
            tap_disp = f"{tap_disp} → 항상투자 제외(레버리지)"
        eff_alloc  = base_alloc * multiplier

        calc_rows.append({
            "ticker": ticker, "name": name, "bucket": bucket,
            "target_w": target_w, "tap_raw": tap_raw, "tap_disp": tap_disp,
            "is_etf": asset_is_etf, "is_dip": is_dip, "dip_level": dip_level,
            "avg_p": avg_p,
            "base_alloc": base_alloc, "multiplier": multiplier,
            "eff_alloc": eff_alloc,
            "cur_p": cur_p, "is_usd": is_usd, "qty": qty,
        })
    return calc_rows


def redistribute_allocations(calc_rows, total_invest, redistribute_mode):
    blocked_total = sum(r["base_alloc"] for r in calc_rows if r["multiplier"] == 0)
    investable    = [r for r in calc_rows if r["multiplier"] > 0]
    inv_w_sum     = sum(r["target_w"] for r in investable) or 1

    for r in calc_rows:
        if r["multiplier"] == 0:
            r["final_alloc"] = 0.0
        elif redistribute_mode:
            bonus = blocked_total * (r["target_w"] / inv_w_sum)
            r["final_alloc"] = r["eff_alloc"] + bonus
        else:
            r["final_alloc"] = r["eff_alloc"]

    # 레버리지 1.5x/2.0x 등으로 합계가 total_invest 초과 시 비례 정규화
    total_final = sum(r["final_alloc"] for r in calc_rows)
    if total_final > total_invest * 1.005:   # 0.5% 허용 오차
        _scale = total_invest / total_final
        for r in calc_rows:
            r["final_alloc"] *= _scale


def apply_share_counts(calc_rows, usdkrw, accumulated):
    _accum = dict(accumulated)   # 종목별 누적금 읽기
    for r in calc_rows:
        alloc  = r["final_alloc"]
        cur_p  = r["cur_p"]
        is_usd = r["is_usd"]
        ticker = r["ticker"]

        # 기존 적립 누적금 포함한 실질 배분 가능금
        accumulated_krw = _accum.get(ticker, 0.0)
        effective_alloc = alloc + accumulated_krw   # 누적금 포함

        if is_usd:
            alloc_usd       = alloc / usdkrw if usdkrw > 0 else 0
            eff_alloc_usd   = effective_alloc / usdkrw if usdkrw > 0 else 0
            rec_shares      = int(eff_alloc_usd / cur_p) if cur_p > 0 else 0
            rec_krw         = rec_shares * cur_p * usdkrw
            unit_price_krw  = cur_p * usdkrw           # 1주 원화 환산가
            r["alloc_disp"] = f"${alloc_usd:,.2f}" + (f" (+누적${accumulated_krw/usdkrw:,.2f})" if accumulated_krw > 0 else "")
        else:
            rec_shares      = int(effective_alloc / cur_p) if cur_p > 0 else 0
            rec_krw         = rec_shares * cur_p
            unit_price_krw  = cur_p
            r["alloc_disp"] = f"{alloc:,.0f}원" + (f" (+누적{accumulated_krw:,.0f}원)" if accumulated_krw > 0 else "")
        r["rec_shares"]        = rec_shares
        r["rec_krw"]           = rec_krw
        r["accumulated_krw"]   = accumulated_krw
        r["effective_alloc"]   = effective_alloc
        r["unit_price_krw"]    = unit_price_krw

        # 1주 미달 판정: 투자 신호가 있는데 누적 포함해도 1주를 못 살 때
        r["is_underalloc"] = (r["multiplier"] > 0 and cur_p > 0 and rec_shares == 0)

        # 상태 레이블
        tap   = r["tap_raw"]
        mult  = r["multiplier"]
        bkt   = r["bucket"]

        if mult == 0:
            if any(k in tap for k in ["하드", "차단", "구조", "추세훼손", "가격위험", "단기급락", "가격방어", "급락방어", "추세방어", "🔴", "⛔"]):
                r["status"] = "⛔ 가격/급락/추세방어" if bkt == "leverage" else "⛔ 차단"
            elif bkt == "leverage" and any(k in tap for k in ["과열", "주의", "⚠"]):
                r["status"] = "🌡️ 과열패스"   # 레버리지 과열은 완전 중단
            elif any(k in tap for k in ["평단", "하락", "대기", "⏸"]):
                r["status"] = "⏸ 대기"
            elif bkt == "swing":
                r["status"] = "⏸ 스윙대기"
            else:
                r["status"] = "⏸ 제외"
        elif r["is_underalloc"]:
            alloc_for_months = r["final_alloc"]
            months_at_eff = (
                math.ceil((unit_price_krw - accumulated_krw) / alloc_for_months)
                if alloc_for_months > 0 else 99
            )
            r["months_to_buy"] = months_at_eff
            r["status"] = f"🟡 적립중 (~{months_at_eff}달 후)"
        elif bkt == "leverage":
            if mult >= 2.0:
                r["status"] = "📉📉📉🚀 강하락+집중매수"
            elif mult >= 1.75:
                r["status"] = "📉📉🚀 중하락+집중매수"
            elif mult >= 1.5:
                r["status"] = "🚀 레버리지 진입"
            elif mult >= 1.25:
                r["status"] = "📉📉 강하락 DCA"
            elif mult >= 1.0:
                r["status"] = "📉 중하락 DCA"
            elif mult >= 0.75:
                r["status"] = "〰️ 약하락 DCA"
            else:
                r["status"] = "〰️ 레버리지 DCA"
        elif bkt == "core" and mult > 1.0:
            r["status"] = f"🧱 코어 집중 {int(mult * 100)}%"
        elif mult < 1.0:
            r["status"] = f"⚠️ {int(mult*100)}%"
        else:
            r["status"] = "🟢 투자"


def build_rebalance_plan(eligible, target_w_sum, total_invest, usdkrw, signal_cache,
                         always_invest_set, redistribute_mode, accumulated, signal_multiplier, signal_decisions=None,
                         signal_scope_valid=True):
    """Build new rows; never modify the caller's holdings or accumulated-money map."""
    if not signal_scope_valid:
        # Signals computed for another account scope are invalid, never reused (decision 3).
        signal_cache, signal_decisions = {}, {}
    calc_rows = build_base_allocations(
        eligible, target_w_sum, total_invest, signal_cache, always_invest_set, signal_multiplier,
        signal_decisions=signal_decisions,
    )
    apply_monthly_signal_safety(calc_rows, always_invest_set, signal_multiplier, signal_decisions)
    # Unknown-signal amounts are never moved to other tickers: redistribute among known rows only.
    known = [r for r in calc_rows if not r["signal_unknown"]]
    redistribute_allocations(known, total_invest, redistribute_mode)
    for r in calc_rows:
        if r["signal_unknown"]:
            r["final_alloc"] = 0.0
    apply_share_counts(calc_rows, usdkrw, accumulated)
    for r in calc_rows:
        if r["signal_unknown"]:
            r["status"] = UNKNOWN_SIGNAL_STATUS
    return calc_rows


def compute_monthly_plan(holdings_table, *, total_invest, usdkrw, signal_cache, signal_decisions,
                         always_invest_set, redistribute_mode, accumulated, signal_multiplier, month,
                         signal_scope_valid=True, account_scope=None):
    """C-6/C-11 step 1: the calculator's plan as one shared, widget-free call (same results as before).

    Returns None when there is nothing to plan (no holdings, no eligible rows, zero target sum), with the
    reason, so callers keep their own messages. ``alloc`` is the per-ticker final allocation (KRW) that the
    leveraged L3 read uses for this month.
    """
    if holdings_table is None or getattr(holdings_table, "empty", True) or total_invest <= 0:
        return {"status": "no_input", "rows": [], "alloc": {}, "month": month}
    eligible = prepare_rebalance_holdings(holdings_table)
    if eligible.empty:
        return {"status": "no_eligible", "rows": [], "alloc": {}, "month": month, "eligible": eligible}
    target_w_sum = float(eligible["목표비중"].sum())
    if target_w_sum <= 0:
        return {"status": "zero_target", "rows": [], "alloc": {}, "month": month, "eligible": eligible}
    rows = build_rebalance_plan(
        eligible, target_w_sum, total_invest, usdkrw, signal_cache, always_invest_set, redistribute_mode,
        accumulated, signal_multiplier, signal_decisions=signal_decisions, signal_scope_valid=signal_scope_valid,
    )
    # Unknown-signal tickers carry NaN (미확인) so the L3 read never takes them as a 0 plan.
    alloc = {str(r.get("ticker", "")).upper(): (float("nan") if r.get("signal_unknown") else float(r.get("final_alloc") or 0.0))
             for r in rows}
    return {"status": "ok", "rows": rows, "alloc": alloc, "month": month, "eligible": eligible,
            "target_w_sum": target_w_sum, "account_scope": account_scope,
            "unknown": sorted(str(r.get("ticker", "")).upper() for r in rows if r.get("signal_unknown"))}
