"""Portfolio summary and cash/reserve calculation helpers for Stock Lab."""

import re

import numpy as np
import pandas as pd

from stock_lab_core.formatters import clean_bool, clean_float, normalize_ticker, sanitize_ticker_value

try:
    from stock_lab_core.prices import load_price_df
except ImportError:
    def load_price_df(*args, **kwargs):
        return pd.DataFrame()

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
