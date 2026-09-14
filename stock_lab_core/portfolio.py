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
