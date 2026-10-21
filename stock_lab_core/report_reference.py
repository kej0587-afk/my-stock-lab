"""Report-only NY 16:00 references, not exchange settlements or trading inputs.

Only an exact completed Yahoo 5m bar may seed an immutable local snapshot.
Local files survive reruns/restarts on the same disk, not necessarily redeploys.
An unavailable/corrupt store fails closed instead of returning a moving value.
"""

from datetime import date
import json
import math
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

REFERENCE_SYMBOLS = {"CL=F": "wti", "USDKRW=X": "usdkrw"}
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "report_reference_v1"
MAX_SNAPSHOTS = 128
MAX_RECORD_BYTES = 8192
NY = ZoneInfo("America/New_York")
BAR = pd.Timedelta(minutes=5)


def _anchor(day):
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError("invalid reference date")
    return pd.Timestamp(day + " 16:00", tz=NY)


def _source(symbol, anchor):
    return (f"Yahoo Finance {symbol} 5m close ending {anchor.isoformat()} "
            "(16:00 America/New_York reference; not official settlement; delay possible)")


def _read(location, symbol, anchor, now):
    try:
        with location.open("rb") as handle:
            payload = handle.read(MAX_RECORD_BYTES + 1)
        if len(payload) > MAX_RECORD_BYTES:
            return {}
        row = json.loads(payload)
        if not isinstance(row, dict):
            return {}
        value = row.get("val")
        captured = pd.Timestamp(row["captured_at"])
        if (row.get("version") != 1 or row.get("symbol") != symbol
                or row.get("as_of") != anchor.date().isoformat()
                or row.get("as_of_at") != anchor.isoformat()
                or row.get("bar_start") != (anchor - BAR).isoformat()
                or row.get("source") != _source(symbol, anchor)
                or row.get("interval") != "5m"
                or row.get("kind") != "fixed_asof_reference"
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0
                or pd.isna(captured) or captured.tzinfo is None or not anchor <= captured <= now):
            return {}
        return row
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return {}


def _closed_value(frame, anchor):
    if (not isinstance(frame, pd.DataFrame) or frame.empty
            or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
            or not isinstance(frame.get("Close"), pd.Series)):
        return None
    interval = frame.attrs.get("interval")
    if interval not in (None, "5m"):
        return None
    start = anchor - BAR
    selected = frame.loc[frame.index == start, "Close"]
    if len(selected) != 1:
        return None
    if interval is None:
        # The shared live loader has no interval attr. Verify local 5m spacing;
        # isolated/daily/1m rows cannot masquerade as a completed 5m candle.
        nearby = frame.index[(frame.index >= start - BAR) & (frame.index <= start + BAR)]
        offsets = abs(nearby - start)
        if not (offsets == BAR).any() or ((offsets > pd.Timedelta(0)) & (offsets < BAR)).any():
            return None
    close = pd.to_numeric(selected, errors="coerce")
    value = close.iloc[0]
    if pd.api.types.is_bool_dtype(close.dtype) or pd.isna(value) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _prune(directory):
    locations = []
    for suffix in REFERENCE_SYMBOLS.values():
        for location in directory.glob(f"????-??-??-{suffix}.json"):
            try:
                _anchor(location.name[:10])
            except ValueError:
                continue
            locations.append(location)
    for location in sorted(locations, key=lambda path: path.name)[:-MAX_SNAPSHOTS]:
        location.unlink(missing_ok=True)


def snapshot_at_us_close(frame, symbol, reference_date, now, *, cache_dir=None):
    """Reuse a date/symbol/policy snapshot; never cache missing or partial bars.

    Inputs are timezone-aware Yahoo bar-start 5m frames. ``captured_at`` is the
    report observation time, not a claimed provider retrieval/publication time.
    Pass a dedicated ``cache_dir`` for isolated tests. Records contain only
    public prices and fixed provenance, never frame attrs or account details.
    """
    if symbol not in REFERENCE_SYMBOLS:
        return {}
    try:
        anchor, observed = _anchor(reference_date), pd.Timestamp(now)
        if pd.isna(observed) or observed.tzinfo is None or observed < anchor:
            return {}
    except (ValueError, TypeError, OverflowError):
        return {}
    directory = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
    location = directory / f"{reference_date}-{REFERENCE_SYMBOLS[symbol]}.json"
    temporary = None
    try:
        if location.exists():
            return _read(location, symbol, anchor, observed)
        value = _closed_value(frame, anchor)
        if value is None:
            return {}
        row = {"version": 1, "symbol": symbol, "val": value, "as_of": reference_date,
               "as_of_at": anchor.isoformat(), "bar_start": (anchor - BAR).isoformat(),
               "captured_at": observed.isoformat(), "interval": "5m",
               "kind": "fixed_asof_reference", "source": _source(symbol, anchor)}
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".reference-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(row, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Atomic no-replace publication: simultaneous writers read the winner.
            # Unsupported/read-only filesystems fail closed, with no live fallback.
            os.link(temporary, location)
        except FileExistsError:
            pass
        saved = _read(location, symbol, anchor, observed)
        _prune(directory)
        return saved
    except (OSError, ValueError, TypeError, OverflowError):
        return {}
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def macro_reference(frame, symbol, reference_date, now, *, previous_date="", base_date="", cache_dir=None):
    """Compare only matching anchors on explicitly supplied US session dates.

    Price provenance is separate from comparison provenance/coverage. A caller
    must not present a complete stress score when ``stress_incomplete`` is true;
    no change, baseline, or risk-relief points are fabricated here.
    """
    current = snapshot_at_us_close(frame, symbol, reference_date, now, cache_dir=cache_dir)
    if not current:
        return {}
    result = dict(current, chg=None, base_date="", base_as_of_at="", day_ret=None,
                  previous_date="", previous_as_of_at="", day_change_bp=None,
                  chg_source="", day_ret_source="", comparison_missing={})
    for day, value_key, date_key, time_key, scale in (
        (previous_date, "day_ret", "previous_date", "previous_as_of_at", 1),
        (base_date, "chg", "base_date", "base_as_of_at", 100),
    ):
        label = "Month (21 US sessions)" if value_key == "chg" else "Previous US session"
        result["comparison_missing"][value_key] = f"{label} comparison unavailable: baseline session date unverified"
        try:
            if not day or _anchor(day) >= _anchor(reference_date):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        result["comparison_missing"][value_key] = (
            f"{label} comparison unavailable: required baseline snapshot missing at {_anchor(day).isoformat()}"
        )
        base = snapshot_at_us_close(frame, symbol, day, now, cache_dir=cache_dir)
        if base:
            result.update({value_key: (current["val"] / base["val"] - 1) * scale,
                           date_key: day, time_key: base["as_of_at"],
                           value_key + "_source": (
                               f"Yahoo Finance {symbol} completed 5m references: "
                               f"{base['as_of_at']} -> {current['as_of_at']}; "
                               "matching 16:00 America/New_York anchors; not official settlement"
                           )})
            del result["comparison_missing"][value_key]
    result["stress_incomplete"] = "chg" in result["comparison_missing"]
    return result
