"""Print-report tables and allocation summaries, without Streamlit state access."""

import numpy as np
import pandas as pd

from stock_lab_core.asset_classifier import resolve_effective_investment_bucket
from stock_lab_core.formatters import (
    clean_bool, is_kr_listed, normalize_bucket, sanitize_ticker_value,
    report_num as _num, format_report_money as _fmt_money,
    format_report_pct as _fmt_pct, format_report_ratio as _fmt_ratio,
)
from stock_lab_core.portfolio import append_cash_rows, calc_pnl_krw_from_row
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def make_report_asset_df(holdings_table, portfolio_summary, krw_cash, usd_cash, usdkrw):
    base_df = holdings_table.copy() if isinstance(holdings_table, pd.DataFrame) else pd.DataFrame()
    total_asset = _num(portfolio_summary.get("current_asset"), 0.0)
    report_df = append_cash_rows(base_df, krw_cash, usd_cash, usdkrw, total_asset)
    if report_df is None or report_df.empty:
        return pd.DataFrame()

    for col in ["원화환산", "현재비중", "목표비중", "리밸런싱목표비중", "비중차이", "평가손익", "수익률"]:
        if col in report_df.columns:
            report_df[col] = pd.to_numeric(report_df[col], errors="coerce").fillna(0.0)

    if "리밸런싱목표비중" not in report_df.columns and "목표비중" in report_df.columns:
        report_df["리밸런싱목표비중"] = report_df["목표비중"]
    if "비중차이" not in report_df.columns:
        target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in report_df.columns else "목표비중"
        if "현재비중" in report_df.columns and target_col in report_df.columns:
            report_df["비중차이"] = report_df["현재비중"] - report_df[target_col]

    if "평가손익_원화" not in report_df.columns:
        if "평가손익" in report_df.columns:
            report_df["평가손익_원화"] = report_df.apply(lambda row: calc_pnl_krw_from_row(row, usdkrw), axis=1)
        else:
            report_df["평가손익_원화"] = 0.0

    if "수익률_pct" not in report_df.columns:
        if "수익률" in report_df.columns:
            report_df["수익률_pct"] = report_df["수익률"] * 100
        else:
            report_df["수익률_pct"] = 0.0

    return report_df


def format_asset_table(df, max_rows=30):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy()
    target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in view.columns else "목표비중"
    rename_map = {
        "자산명": "자산명",
        "티커": "티커",
        "원화환산": "평가금액",
        "현재비중": "현재비중",
        target_col: "목표비중",
        "비중차이": "비중차이",
        "평가손익_원화": "평가손익",
        "수익률_pct": "수익률",
    }
    cols = [col for col in rename_map if col in view.columns]
    view = view[cols].rename(columns=rename_map)
    for col in ["평가금액", "평가손익"]:
        if col in view.columns:
            view[col] = view[col].apply(_fmt_money)
    for col in ["현재비중", "목표비중", "비중차이", "수익률"]:
        if col in view.columns:
            view[col] = view[col].apply(_fmt_pct)
    return view.head(max_rows)


def format_generic_table(df, max_rows=12):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy().head(max_rows)
    for col in view.columns:
        col_text = str(col)
        if any(key in col_text for key in ["금액", "평가자산", "투입원금", "손익", "원화환산", "현재가", "배당"]):
            view[col] = view[col].apply(_fmt_money)
        elif any(key in col_text for key in ["비중", "수익률", "변동성", "MDD", "VaR"]):
            view[col] = view[col].apply(_fmt_pct)
        elif any(key in col_text for key in ["상관", "샤프", "소르티노", "칼마"]):
            view[col] = view[col].apply(_fmt_ratio)
    return view


def active_plan_rows(holdings_table):
    if holdings_table is None or holdings_table.empty:
        return pd.DataFrame()
    df = holdings_table.copy()
    target_col = "리밸런싱목표비중" if "리밸런싱목표비중" in df.columns else "목표비중"
    if target_col not in df.columns:
        return pd.DataFrame()
    if "bucket" in df.columns:
        df = df[~df["bucket"].apply(lambda b: normalize_bucket(str(b)) in {"reserve", "cash"})].copy()
    if df.empty:
        return df
    if "운용대상" in df.columns:
        df = df[df["운용대상"].apply(clean_bool)].copy()
    df[target_col] = pd.to_numeric(df[target_col], errors="coerce").fillna(0.0)
    df = df[df[target_col] > 0].copy()
    df["_print_target_weight"] = df[target_col]
    return df


def build_monthly_plan_report(active_df, state, usdkrw, *, sanitize_asset_name, signal_multiplier):
    monthly = _num(state.get("rebcalc_monthly", 750000), 750000)
    carryover = _num(state.get("rebcalc_carryover", 0), 0.0)
    total_invest = max(monthly + carryover, 0.0)
    empty_metrics = {
        "monthly": monthly,
        "carryover": carryover,
        "total_invest": total_invest,
        "total_rec_krw": 0.0,
        "krw_buy": 0.0,
        "usd_buy_krw": 0.0,
        "usd_buy": 0.0,
        "underalloc_count": 0,
    }
    if active_df.empty or total_invest <= 0:
        return pd.DataFrame(), empty_metrics

    target_sum = float(active_df["_print_target_weight"].sum())
    if target_sum <= 0:
        return pd.DataFrame(), empty_metrics

    signal_cache = state.get("_ticker_signal_cache", {})
    accum_map = state.get("rebcalc_accum", {})
    rows = []
    for _, row in active_df.iterrows():
        ticker = sanitize_ticker_value(row.get("티커", ""))
        name = sanitize_asset_name(row.get("자산명", ""), ticker)
        bucket = resolve_effective_investment_bucket(name, ticker, row.get("bucket", "core"), row.get("asset_class", ""))
        target_w = _num(row.get("_print_target_weight"), 0.0)
        current_price = _num(row.get("현재가"), 0.0)
        avg_price = _num(row.get("매입가"), 0.0)
        is_usd = bool(ticker and not is_kr_listed(ticker) and ticker not in ("KRW_CASH", "USD_CASH"))
        unit_price_krw = current_price * _num(usdkrw, 1400.0) if is_usd else current_price
        base_alloc = total_invest * (target_w / target_sum)

        signal = str(signal_cache.get(ticker, "") or "").strip()
        dip_level = 0
        if bucket == "leverage" and avg_price > 0 and current_price > 0:
            pct_drop = (current_price - avg_price) / avg_price
            if pct_drop <= -0.15:
                dip_level = 3
            elif pct_drop <= -0.10:
                dip_level = 2
            elif pct_drop <= -0.05:
                dip_level = 1
        try:
            multiplier = signal_multiplier(signal or "-", bucket, dip_level=dip_level)
        except Exception:
            multiplier = 1.0 if bucket == "core" else 0.0

        alloc = base_alloc * multiplier
        rows.append({
            "name": name,
            "ticker": ticker,
            "bucket": bucket,
            "target_w": target_w,
            "signal": signal or "목표비중 기준",
            "multiplier": multiplier,
            "base_alloc": base_alloc,
            "alloc": alloc,
            "unit_price_krw": unit_price_krw,
            "is_usd": is_usd,
            "accum": _num(accum_map.get(ticker), 0.0),
        })

    blocked_total = sum(r["base_alloc"] for r in rows if r["multiplier"] <= 0)
    investable = [r for r in rows if r["multiplier"] > 0]
    inv_target_sum = sum(r["target_w"] for r in investable) or 1.0
    redistribute = bool(state.get("rebcalc_redistribute", True))
    for r in rows:
        if r["multiplier"] <= 0:
            r["final_alloc"] = 0.0
        else:
            bonus = blocked_total * (r["target_w"] / inv_target_sum) if redistribute else 0.0
            r["final_alloc"] = r["alloc"] + bonus

    total_final = sum(r["final_alloc"] for r in rows)
    if total_final > total_invest and total_final > 0:
        scale = total_invest / total_final
        for r in rows:
            r["final_alloc"] *= scale

    table_rows = []
    total_rec_krw = 0.0
    krw_buy = 0.0
    usd_buy_krw = 0.0
    underalloc_count = 0
    for r in rows:
        effective_alloc = r["final_alloc"] + r["accum"]
        shares = int(effective_alloc / r["unit_price_krw"]) if r["unit_price_krw"] > 0 and r["final_alloc"] > 0 else 0
        rec_krw = shares * r["unit_price_krw"]
        total_rec_krw += rec_krw
        if r["is_usd"]:
            usd_buy_krw += rec_krw
        else:
            krw_buy += rec_krw
        if r["final_alloc"] > 0 and shares == 0:
            underalloc_count += 1
        status = "매수 가능" if shares > 0 else ("1주 미달/누적" if r["final_alloc"] > 0 else "이번달 제외")
        table_rows.append({
            "자산명": r["name"],
            "티커": r["ticker"],
            "버킷": r["bucket"],
            "목표비중": r["target_w"],
            "판정기준": r["signal"],
            "이번달 배분": r["final_alloc"],
            "1주 가격": r["unit_price_krw"],
            "예상 주수": shares,
            "예상 매수금": rec_krw,
            "현재 누적금": r["accum"],
            "상태": status,
        })

    metrics = {
        "monthly": monthly,
        "carryover": carryover,
        "total_invest": total_invest,
        "total_rec_krw": total_rec_krw,
        "krw_buy": krw_buy,
        "usd_buy_krw": usd_buy_krw,
        "usd_buy": usd_buy_krw / _num(usdkrw, 1400.0) if _num(usdkrw, 0.0) > 0 else 0.0,
        "underalloc_count": underalloc_count,
    }
    return pd.DataFrame(table_rows), metrics


def build_total_needed_shares_report(active_df, state, usdkrw, portfolio_summary, *, sanitize_asset_name, signal_multiplier):
    if active_df.empty:
        return pd.DataFrame()
    total_asset = _num(portfolio_summary.get("current_asset"), 0.0)
    signal_cache = state.get("_ticker_signal_cache", {})
    rows = []
    for _, row in active_df.iterrows():
        ticker = sanitize_ticker_value(row.get("티커", ""))
        name = sanitize_asset_name(row.get("자산명", ""), ticker)
        current_price = _num(row.get("현재가"), 0.0)
        qty_now = _num(row.get("보유량"), 0.0)
        target_w = _num(row.get("_print_target_weight"), 0.0)
        bucket = resolve_effective_investment_bucket(name, ticker, row.get("bucket", "core"), row.get("asset_class", ""))
        is_usd = bool(ticker and not is_kr_listed(ticker) and ticker not in ("KRW_CASH", "USD_CASH"))
        unit_price_krw = current_price * _num(usdkrw, 1400.0) if is_usd else current_price
        target_value = total_asset * target_w / 100 if total_asset > 0 else 0.0
        target_shares = target_value / unit_price_krw if unit_price_krw > 0 else 0.0
        needed_shares = target_shares - qty_now
        needed_value = max(needed_shares, 0.0) * unit_price_krw
        signal = str(signal_cache.get(ticker, row.get("기술적타점", "")) or "").strip()
        dip_level = 0
        if bucket == "leverage" and _num(row.get("매입가"), 0.0) > 0 and current_price > 0:
            pct_drop = (current_price - _num(row.get("매입가"), 0.0)) / _num(row.get("매입가"), 0.0)
            if pct_drop <= -0.15:
                dip_level = 3
            elif pct_drop <= -0.10:
                dip_level = 2
            elif pct_drop <= -0.05:
                dip_level = 1
        try:
            timing_multiplier = signal_multiplier(signal or "-", bucket, dip_level=dip_level)
        except Exception:
            timing_multiplier = 1.0 if bucket == "core" else 0.0
        if needed_shares < -0.5:
            status = "비중 초과"
        elif needed_shares < 0.5:
            status = "거의 도달"
        elif timing_multiplier <= 0:
            status = "목표부족 · 타점대기"
        elif bucket == "leverage" and timing_multiplier < 1.0:
            status = "목표부족 · 소액정찰"
        else:
            status = "목표부족 · 매수검토"
        rows.append({
            "자산명": name,
            "티커": ticker,
            "버킷": bucket,
            "목표비중": target_w,
            "목표 주수": target_shares,
            "현재 주수": qty_now,
            "추가 필요 주수": needed_shares,
            "추가 필요 금액": needed_value,
            "상태": status,
        })
    return pd.DataFrame(rows)


def format_monthly_plan_table(df, max_rows=24):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy().sort_values(["상태", "이번달 배분"], ascending=[True, False]).head(max_rows)
    for col in ["이번달 배분", "1주 가격", "예상 매수금", "현재 누적금"]:
        if col in view.columns:
            view[col] = view[col].apply(_fmt_money)
    if "목표비중" in view.columns:
        view["목표비중"] = view["목표비중"].apply(_fmt_pct)
    return view


def format_needed_shares_table(df, max_rows=24):
    if df is None or df.empty:
        return pd.DataFrame()
    view = df.copy().sort_values("추가 필요 금액", ascending=False).head(max_rows)
    for col in ["목표 주수", "현재 주수", "추가 필요 주수"]:
        if col in view.columns:
            view[col] = view[col].apply(lambda v: "-" if not np.isfinite(_num(v, np.nan)) else f"{_num(v):,.2f}")
    if "목표비중" in view.columns:
        view["목표비중"] = view["목표비중"].apply(_fmt_pct)
    if "추가 필요 금액" in view.columns:
        view["추가 필요 금액"] = view["추가 필요 금액"].apply(_fmt_money)
    return view
