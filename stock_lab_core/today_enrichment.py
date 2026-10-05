"""Analyst context for Today Queue, independent of grades and execution gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import math
import re
from typing import Any

import pandas as pd

from stock_lab_core.asset_classifier import is_fin_score_exempt_asset
from stock_lab_core.formatters import (
    clean_bool,
    ensure_kr_suffix_if_code,
    format_currency,
    is_kr_code_like,
    normalize_ticker,
    sanitize_ticker_value,
)


_NUMERIC_COLUMNS = (
    "애널목표가", "애널목표Upside값", "애널참여수", "애널가격기준", "애널가격괴리pct",
)
_TEXT_COLUMNS = (
    "애널목표가표시", "애널목표Upside", "애널목표상태", "애널목표사유",
    "애널목표출처", "애널목표출처URL", "애널목표기준일", "애널목표조회시각", "애널목표종류",
    "애널가격출처", "애널가격상태", "애널조회티커",
)
_EMPTY_TEXT = {"", "-", "—", "nan", "none", "null", "<na>", "nat"}


def _text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in _EMPTY_TEXT else text


def _number(value: Any) -> float:
    if isinstance(value, Mapping):
        value = value.get("raw")
    if isinstance(value, bool):
        return math.nan
    text = _text(value).replace(",", "")
    text = re.sub(r"^(?:USD|KRW|[$₩])\s*", "", text, flags=re.I)
    text = re.sub(r"\s*(?:원|달러)$", "", text)
    try:
        number = float(text)
        return number if math.isfinite(number) else math.nan
    except (TypeError, ValueError, OverflowError):
        return math.nan


def _positive(value: Any) -> float:
    number = _number(value)
    return number if number > 0 else math.nan


def _symbol(value: Any) -> str:
    symbol = sanitize_ticker_value(_text(value))
    if symbol.lower() in _EMPTY_TEXT or not re.fullmatch(r"[A-Z0-9][A-Z0-9.^=-]*", symbol):
        return ""
    if re.fullmatch(r"\d+(?:\.0+)?", symbol):
        code = symbol.split(".")[0]
        symbol = code.zfill(6) if len(code) <= 6 and int(code) > 0 else ""
    return symbol


def _excluded(row: Mapping, ticker: str) -> bool:
    type_text = _text(row.get("유형")).upper()
    if any(word in type_text for word in ("ETF", "ETN", "FUND", "펀드")):
        return True
    return is_fin_score_exempt_asset(
        ticker,
        is_etf=clean_bool(row.get("is_etf", False)),
        asset_class=_text(row.get("asset_class")),
        name=_text(row.get("종목명", row.get("name"))),
    )


def _metadata(snapshot: Mapping, data: Mapping, *keys: str) -> str:
    for container in (snapshot, data):
        for key in keys:
            value = _text(container.get(key))
            if value:
                return value
    return ""


def _default_snapshot(ticker: str) -> Mapping:
    from stock_lab_core.news import get_analyst_snapshot

    return get_analyst_snapshot(ticker)


def _default_price(ticker: str) -> Any:
    from stock_lab_core.prices import load_latest_price

    return load_latest_price(ticker)


def attach_today_analyst_context(
    summary_df: pd.DataFrame,
    *,
    get_analyst_snapshot: Callable[[str], Mapping] | None = None,
    load_latest_price: Callable[[str], Any] | None = None,
    ticker_col: str = "티커",
    price_col: str = "현재가",
    price_mismatch_tolerance_pct: float = 1.0,
) -> pd.DataFrame:
    """Return a copy enriched with real consensus targets and numeric upside.

    Prices prefer the displayed row, then the same analyst snapshot, then the
    price loader. Snapshot and price loaders are called at most once per lookup
    ticker per invocation, including failed fetches. Bare KR codes use an
    explicit suffix from another row when available, otherwise .KS; an existing
    .KQ is retained. Only mean/median consensus is used, never high/low or chart
    projections. ``애널목표종류`` identifies a median fallback.

    Status codes: available, etf_excluded, invalid_ticker, lookup_error,
    invalid_snapshot, no_target, no_price. Missing values are NaN / '-'.
    ``애널목표기준일`` is the provider's date, never the enrichment time.
    Original API fields are retained in attrs['today_analyst_snapshots']; when
    the existing news loader omits source/date, source is the loader name and
    asof stays blank. Grade, timing, wording, index and row order are preserved.
    """
    if not isinstance(summary_df, pd.DataFrame):
        raise TypeError("summary_df must be a pandas DataFrame")
    tolerance = _number(price_mismatch_tolerance_pct)
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("price_mismatch_tolerance_pct must be finite and nonnegative")

    out = summary_df.copy()
    rows = out.to_dict("records")
    symbols = [_symbol(row.get(ticker_col)) for row in rows]
    explicit_kr: dict[str, set[str]] = {}
    for symbol in symbols:
        if symbol.endswith((".KS", ".KQ")):
            explicit_kr.setdefault(normalize_ticker(symbol), set()).add(symbol)

    def lookup_symbol(symbol: str) -> str:
        if symbol and is_kr_code_like(symbol) and not symbol.endswith((".KS", ".KQ")):
            explicit = explicit_kr.get(normalize_ticker(symbol), set())
            if len(explicit) == 1:
                return next(iter(explicit))
        return ensure_kr_suffix_if_code(symbol)

    snapshot_loader = get_analyst_snapshot or _default_snapshot
    price_loader = load_latest_price or _default_price
    snapshot_cache: dict[str, tuple[Mapping, str, str, str]] = {}
    price_cache: dict[str, tuple[float, str]] = {}
    records = []

    for row, symbol in zip(rows, symbols):
        record = {col: math.nan for col in _NUMERIC_COLUMNS}
        record.update({col: "" for col in _TEXT_COLUMNS})
        record.update({"애널목표가표시": "-", "애널목표Upside": "-"})
        records.append(record)
        if _excluded(row, symbol):
            record["애널목표상태"] = "etf_excluded"
            continue
        if not symbol:
            record["애널목표상태"] = "invalid_ticker"
            continue

        ticker = lookup_symbol(symbol)
        record["애널조회티커"] = ticker
        if ticker not in snapshot_cache:
            fetched_at = datetime.now(timezone.utc).isoformat()
            try:
                snapshot = snapshot_loader(ticker)
                if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("data"), Mapping):
                    snapshot_cache[ticker] = (dict(snapshot) if isinstance(snapshot, Mapping) else {}, "invalid_snapshot", "Expected snapshot.data mapping", fetched_at)
                else:
                    snapshot_cache[ticker] = (dict(snapshot), "", "", fetched_at)
            except Exception as exc:
                snapshot_cache[ticker] = ({}, "lookup_error", f"{type(exc).__name__}: {exc}"[:300], fetched_at)

        snapshot, error_status, error_reason, fetched_at = snapshot_cache[ticker]
        data = snapshot.get("data", {})
        if not isinstance(data, Mapping):
            data = {}
        record["애널목표조회시각"] = _text(snapshot.get("fetched_at")) or fetched_at
        record["애널목표출처"] = _metadata(snapshot, data, "source", "provider") or "get_analyst_snapshot"
        record["애널목표출처URL"] = _metadata(snapshot, data, "source_url")
        record["애널목표기준일"] = _metadata(snapshot, data, "target_asof", "asof", "as_of")
        if error_status:
            record.update({"애널목표상태": error_status, "애널목표사유": error_reason})
            continue
        if _text(data.get("quoteType", snapshot.get("quoteType"))).upper() in {"ETF", "ETN", "MUTUALFUND"}:
            record["애널목표상태"] = "etf_excluded"
            continue

        count = _number(data.get("numberOfAnalystOpinions", snapshot.get("analyst_count")))
        if math.isfinite(count) and count >= 0 and count.is_integer():
            record["애널참여수"] = count
        target = math.nan
        # A failed snapshot may contain partial prices; it is not a valid target.
        if snapshot.get("ok") is not False:
            for key in ("targetMeanPrice", "targetMedianPrice"):
                target = _positive(data.get(key))
                if math.isfinite(target):
                    record["애널목표종류"] = key
                    break
        if not math.isfinite(target):
            record.update({"애널목표상태": "no_target", "애널목표사유": _text(snapshot.get("reason")) or "No positive mean/median consensus target"})
            continue
        record["애널목표가"] = target
        record["애널목표가표시"] = format_currency(target, ticker)
        field_sources = snapshot.get("field_sources", {})
        target_source = field_sources.get(record["애널목표종류"]) if isinstance(field_sources, Mapping) else None
        if isinstance(target_source, Mapping):
            record["애널목표출처"] = _text(target_source.get("source")) or "get_analyst_snapshot"
            record["애널목표출처URL"] = _text(target_source.get("source_url"))
            record["애널목표기준일"] = _metadata(target_source, {}, "target_asof", "asof", "as_of")

        snapshot_price = _positive(data.get("currentPrice"))
        snapshot_price_key = "currentPrice"
        if not math.isfinite(snapshot_price):
            snapshot_price = _positive(data.get("regularMarketPrice"))
            snapshot_price_key = "regularMarketPrice"
        current = _positive(row.get(price_col))
        if math.isfinite(current):
            record.update({"애널가격출처": price_col, "애널가격상태": "row_price"})
            if math.isfinite(snapshot_price):
                drift = (current / snapshot_price - 1.0) * 100.0
                record["애널가격괴리pct"] = drift
                if abs(drift) > tolerance:
                    record["애널가격상태"] = "row_snapshot_mismatch"
        elif math.isfinite(snapshot_price):
            current = snapshot_price
            record.update({"애널가격출처": snapshot_price_key, "애널가격상태": "snapshot_fallback"})
        else:
            if ticker not in price_cache:
                try:
                    price_cache[ticker] = (_positive(price_loader(ticker)), "")
                except Exception as exc:
                    price_cache[ticker] = (math.nan, f"{type(exc).__name__}: {exc}"[:300])
            current, price_error = price_cache[ticker]
            record.update({"애널가격출처": "load_latest_price", "애널가격상태": "latest_price_fallback", "애널목표사유": price_error})
        if not math.isfinite(current):
            record.update({"애널목표상태": "no_price", "애널가격상태": "missing"})
            continue
        upside = (target / current - 1.0) * 100.0
        if not math.isfinite(upside):
            record.update({"애널목표상태": "no_price", "애널목표사유": "Nonfinite target/price ratio"})
            continue
        record.update({
            "애널가격기준": current,
            "애널목표Upside값": upside,
            "애널목표Upside": f"{upside:+.1f}%",
            "애널목표상태": "available",
        })

    for column in _NUMERIC_COLUMNS + _TEXT_COLUMNS:
        out[column] = pd.Series([record[column] for record in records], index=out.index, dtype="float64" if column in _NUMERIC_COLUMNS else "object")
    out.attrs["today_analyst_snapshots"] = {ticker: dict(entry[0]) for ticker, entry in snapshot_cache.items()}
    return out


def build_today_analyst_upside_map(
    summary_df: pd.DataFrame, *, ticker_col: str = "티커"
) -> dict[str, float]:
    """Map raw/sanitized/normalized tickers to available, unrounded upside.

    Ambiguous aliases (duplicate rows with different prices or exchange codes)
    are omitted. Such callers should use each row's numeric upside directly.
    """
    values: dict[str, set[float]] = {}
    for row in summary_df.to_dict("records"):
        if row.get("애널목표상태") != "available":
            continue
        upside = _number(row.get("애널목표Upside값"))
        raw = _text(row.get(ticker_col))
        if not raw or not math.isfinite(upside):
            continue
        symbol = _symbol(raw)
        keys = {raw, symbol, normalize_ticker(symbol), _text(row.get("애널조회티커"))}
        for key in keys - {""}:
            values.setdefault(key, set()).add(upside)
    return {key: next(iter(upsides)) for key, upsides in values.items() if len(upsides) == 1}
