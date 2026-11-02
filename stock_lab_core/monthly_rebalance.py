"""Monthly allocation arithmetic, separate from widgets and persistence.

This preserves the calculator's own policy; the print summary has different
normalization and signal-fallback rules and is deliberately not substituted.
"""

import math

from stock_lab_core.asset_classifier import is_known_etf_ticker, resolve_effective_investment_bucket
from stock_lab_core.formatters import clean_bool, clean_float, is_kr_listed, normalize_bucket
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


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


def build_base_allocations(eligible, target_w_sum, total_invest, _signal_cache, always_invest_set, signal_multiplier):
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
        multiplier = signal_multiplier(tap_raw, bucket, dip_level=dip_level)
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
                         always_invest_set, redistribute_mode, accumulated, signal_multiplier):
    """Build new rows; never modify the caller's holdings or accumulated-money map."""
    calc_rows = build_base_allocations(
        eligible, target_w_sum, total_invest, signal_cache, always_invest_set, signal_multiplier,
    )
    redistribute_allocations(calc_rows, total_invest, redistribute_mode)
    apply_share_counts(calc_rows, usdkrw, accumulated)
    return calc_rows
