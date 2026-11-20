"""Audit scalar quote overlays without inventing provider times or changing scores."""

from collections.abc import Mapping
import hashlib
import json
import math

import pandas as pd

from stock_lab_core.report_build import register_loaded_source


PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def _number(value):
    if pd.api.types.is_bool(value):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def source_price_rows(frame):
    """Undo a captured same-date overlay for range calculations, not indicators.

    Old exports without a captured source row retain quote-only exclusion. Source
    rows are not certified completed sessions here; their session check is separate.
    """
    if not isinstance(frame, pd.DataFrame) or "LiveQuoteOnly" not in frame:
        return frame
    out = frame.copy(deep=True)
    marked = out.LiveQuoteOnly.fillna(False).astype(bool)
    metadata = out.attrs.get("live_quote") or {}
    original = metadata.get("source_last_bar") if isinstance(metadata, Mapping) else None
    if isinstance(original, Mapping) and isinstance(out.index, pd.DatetimeIndex) and out.index.is_unique:
        try:
            at = pd.Timestamp(original.get("at"))
            values = {k: _number(original.get(k)) for k in PRICE_COLUMNS}
            valid = (all(values[k] is not None and values[k] > 0 for k in PRICE_COLUMNS[:4])
                     and values["Low"] <= min(values["Open"], values["Close"])
                     and values["High"] >= max(values["Open"], values["Close"]))
            if valid and at in out.index and marked.loc[at]:
                for column, value in values.items():
                    if column in out:
                        out.loc[at, column] = value if value is not None else float("nan")
                marked.loc[at] = False
        except (TypeError, ValueError, KeyError):
            pass
    out["LiveQuoteOnly"] = marked
    return out.loc[~marked].copy()


def capture_source_last_bar(frame):
    source = source_price_rows(frame)
    if (not isinstance(source, pd.DataFrame) or source.empty
            or not isinstance(source.index, pd.DatetimeIndex) or pd.isna(source.index[-1])):
        return None
    last = source.iloc[-1]
    return {"at": source.index[-1].isoformat(), **{key: _number(last.get(key)) for key in PRICE_COLUMNS}}


def price_input_identity(source, chart, *, ticker="", input_price=None):
    """Same price inputs have the same ID even when views render at different times."""
    digest = hashlib.sha256()
    digest.update(json.dumps(["price-input-v1", str(ticker).strip().upper(), _number(input_price)],
                             allow_nan=False).encode())
    for frame in (source, chart):
        if not isinstance(frame, pd.DataFrame):
            digest.update(b"missing")
            continue
        values = frame.reindex(columns=PRICE_COLUMNS).apply(pd.to_numeric, errors="coerce").astype(float)
        # Include provisional status; equal prices do not imply equal observations.
        values["LiveQuoteOnly"] = frame.get("LiveQuoteOnly", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
        digest.update(pd.util.hash_pandas_object(values, index=True).values.tobytes())
    return digest.hexdigest()[:16]


register_loaded_source(__name__, __file__)
