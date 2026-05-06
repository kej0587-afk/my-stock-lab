"""Portfolio summary and cash/reserve calculation helpers for Stock Lab."""

import numpy as np
import pandas as pd

from stock_lab_core.formatters import clean_float, normalize_ticker
from stock_lab_core.prices import load_price_df


def finite_num(x):
    return x is not None and not pd.isna(x) and np.isfinite(float(x))


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


def get_holding_row_by_ticker(holdings_table, ticker):
    if holdings_table.empty:
        return None
    t = normalize_ticker(ticker)
    matched = holdings_table[holdings_table["티커"].apply(normalize_ticker) == t]
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


def build_benchmark_return_df(perf_df):
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

    for label, ticker in benchmarks.items():
        try:
            px = load_price_df(ticker, "5y")
            if px.empty:
                continue

            close = px["Close"].copy()
            close.index = pd.to_datetime(close.index).tz_localize(None)

            prices = []
            for month_end in perf_df["month_end"]:
                target_dt = pd.Timestamp(month_end).tz_localize(None)
                eligible = close[close.index <= target_dt]
                prices.append(float(eligible.iloc[-1]) if not eligible.empty else np.nan)

            valid_prices = [p for p in prices if finite_num(p) and p > 0]
            if not valid_prices:
                continue

            base = valid_prices[0]
            for month_label, price in zip(perf_df["month_label"], prices):
                if finite_num(price) and price > 0:
                    ret = (float(price) / base - 1) * 100
                    rows.append({"month_label": month_label, "구분": label, "수익률_pct": ret})
        except Exception:
            continue

    return pd.DataFrame(rows)
