"""Original Today input scope for bounded, read-only restoration. No state or IO."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math

import numpy as np
import pandas as pd

INPUTS_KEY = "today_restore_inputs"
SCHEMA_VERSION = 1
# Existing Today two-hour warning boundary, applied only to this new restore route.
RESTORE_WINDOW = timedelta(hours=2)
SAVED_ATTR_KEYS = (INPUTS_KEY, "today_observation_inputs", "today_saved_display",
                   "today_observation_cache", "today_saved_market_guard")


def encode_snapshot_value(value, _depth=0):
    """Closed JSON codec: no pickle, imports by payload, or stringified unknown objects."""
    if _depth > 48:
        raise ValueError("Snapshot nesting too deep")
    enc = lambda item: encode_snapshot_value(item, _depth + 1)
    if value is pd.NA:
        return {"kind": "NA"}
    if value is pd.NaT:
        return {"kind": "NaT"}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, pd.Timestamp):
        return {"kind": "timestamp", "value": value.isoformat(), "tz": str(value.tz) if value.tz else None}
    if isinstance(value, datetime):
        return {"kind": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"kind": "date", "value": value.isoformat()}
    if isinstance(value, pd.Timedelta):
        return {"kind": "timedelta", "value": value.value}
    if isinstance(value, np.datetime64):
        return enc(pd.Timestamp(value))
    if isinstance(value, np.generic):
        return {"kind": "numpy", "dtype": str(value.dtype), "value": enc(value.item())}
    if isinstance(value, float):
        return value if math.isfinite(value) else {"kind": "float", "value": str(value)}
    if isinstance(value, pd.MultiIndex):
        return {"kind": "multiindex", "values": enc(value.tolist()), "names": enc(value.names)}
    if isinstance(value, pd.RangeIndex):
        return {"kind": "rangeindex", "start": value.start, "stop": value.stop,
                "step": value.step, "name": enc(value.name)}
    if isinstance(value, pd.Index):
        return {"kind": "index", "values": enc(value.tolist()), "dtype": str(value.dtype),
                "name": enc(value.name), "freq": getattr(value, "freqstr", None)}
    if isinstance(value, pd.DataFrame):
        dtypes = []
        for dtype in value.dtypes:
            spec = {"dtype": str(dtype)}
            if isinstance(dtype, pd.CategoricalDtype):
                spec.update(categories=enc(dtype.categories.tolist()), ordered=dtype.ordered)
            dtypes.append(spec)
        return {"kind": "frame", "columns": enc(value.columns), "index": enc(value.index),
                "data": enc(value.to_numpy(dtype=object).tolist()), "dtypes": dtypes, "attrs": enc(value.attrs)}
    if isinstance(value, dict):
        return {"kind": "dict", "items": [[enc(key), enc(item)] for key, item in value.items()]}
    if isinstance(value, tuple):
        return {"kind": "tuple", "items": [enc(item) for item in value]}
    if isinstance(value, list):
        return [enc(item) for item in value]
    raise TypeError("Unsupported snapshot value")


def decode_snapshot_value(value, _depth=0):
    """Decode only the fixed codec types; malformed data raises, never silently coerces."""
    if _depth > 48:
        raise ValueError("Snapshot nesting too deep")
    dec = lambda item: decode_snapshot_value(item, _depth + 1)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-JSON number")
        return value
    if isinstance(value, list):
        return [dec(item) for item in value]
    if not isinstance(value, dict):
        raise ValueError("Invalid snapshot value")
    kind = value.get("kind")
    if kind in ("NA", "NaT"):
        return pd.NA if kind == "NA" else pd.NaT
    if kind == "float" and value.get("value") in ("nan", "inf", "-inf"):
        return float(value["value"])
    if kind == "timestamp":
        result = pd.Timestamp(value["value"])
        return result.tz_convert(value["tz"]) if value.get("tz") else result
    if kind == "datetime":
        return datetime.fromisoformat(value["value"])
    if kind == "date":
        return date.fromisoformat(value["value"])
    if kind == "timedelta":
        return pd.Timedelta(value["value"], unit="ns")
    if kind == "numpy":
        dtype = np.dtype(value["dtype"])
        if dtype.kind not in "biuf":
            raise ValueError("Unsupported numpy scalar")
        return dtype.type(dec(value["value"]))
    if kind == "tuple":
        return tuple(dec(item) for item in value["items"])
    if kind == "dict":
        result = {}
        for pair in value["items"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Invalid dictionary item")
            key = dec(pair[0])
            if key in result:
                raise ValueError("Duplicate dictionary key")
            result[key] = dec(pair[1])
        return result
    if kind == "rangeindex":
        return pd.RangeIndex(value["start"], value["stop"], value["step"], name=dec(value["name"]))
    if kind == "multiindex":
        return pd.MultiIndex.from_tuples(dec(value["values"]), names=dec(value["names"]))
    if kind == "index":
        index = pd.Index(dec(value["values"]), dtype=value["dtype"], name=dec(value["name"]))
        if isinstance(index, pd.DatetimeIndex) and value.get("freq"):
            index.freq = value["freq"]
        return index
    if kind == "frame":
        columns, index, data = dec(value["columns"]), dec(value["index"]), dec(value["data"])
        dtypes = value["dtypes"]
        if (not isinstance(columns, pd.Index) or not isinstance(index, pd.Index)
                or not isinstance(data, list) or len(data) != len(index)
                or not isinstance(dtypes, list) or len(dtypes) != len(columns)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in data)):
            raise ValueError("Invalid stored frame dimensions")
        frame = pd.DataFrame(data, columns=columns, index=index)
        for i, spec in enumerate(dtypes):
            dtype = spec["dtype"]
            if dtype == "category":
                dtype = pd.CategoricalDtype(dec(spec["categories"]), ordered=spec["ordered"])
            frame.isetitem(i, frame.iloc[:, i].astype(dtype))
        attrs = dec(value["attrs"])
        if not isinstance(attrs, dict):
            raise ValueError("Invalid frame attributes")
        frame.attrs = attrs
        return frame
    raise ValueError("Unknown snapshot type")


def _signature(items, mode, logic_version):
    # Lazy import avoids today_queue -> today_snapshot -> this module cycle.
    from stock_lab_core.today_queue import build_today_queue_signature
    return build_today_queue_signature(items, mode, logic_version=logic_version)


def _items(items):
    if not isinstance(items, (tuple, list)):
        raise ValueError("Invalid item sequence")
    from stock_lab_core.formatters import sanitize_ticker_value
    keys = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("ticker"), str):
            raise ValueError("Invalid item")
        key = sanitize_ticker_value(item["ticker"])
        if not key or key in keys:
            raise ValueError("Missing or duplicate item")
        keys.append(key)
    return keys


def _timestamp(value):
    if not isinstance(value, (str, datetime, pd.Timestamp)):
        raise ValueError("Missing calculation time")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("Missing calculation time")
    # App's legacy displayed calculation times are KST without an offset.
    return stamp.tz_localize("Asia/Seoul") if stamp.tz is None else stamp


def _digest(value):
    return hashlib.sha256(json.dumps(encode_snapshot_value(value), ensure_ascii=False,
                                    sort_keys=True, allow_nan=False).encode()).hexdigest()


def flow_input_identity(snapshot):
    """Content identity excluding top-level caches and known derived display cards.

    Mapping insertion order is immaterial; frame values/dates/attrs, row order,
    Other public keys and nested underscore keys remain evidence. Empty return means
    unsupported/missing input, and must not be treated as a proven matching flow.
    """
    if not isinstance(snapshot, dict):
        return ""

    def canonical(value):
        if isinstance(value, list):
            return [canonical(item) for item in value]
        if isinstance(value, dict):
            result = {key: canonical(item) for key, item in value.items()}
            if result.get("kind") == "dict":
                result["items"].sort(key=lambda pair: json.dumps(pair[0], sort_keys=True, ensure_ascii=False))
            return result
        return value

    try:
        source = {key: value for key, value in snapshot.items()
                  if not (isinstance(key, str) and key.startswith("_"))
                  and key not in {"sector_ability_cards", "sector_cards_view_version"}}
        payload = canonical(encode_snapshot_value(source))
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return ""


def capture_restore_inputs(*, raw_watch_items, base_items, watch_items, flow_auto_items,
                           mode, logic_version, account_context, flow_snapshot, calculated_at,
                           refresh_flow_candidates, account_inputs=None):
    """Capture original inputs only. Caller attaches the returned copy to raw attrs."""
    try:
        envelope = deepcopy(dict(
            raw_watch_items=tuple(raw_watch_items), base_items=tuple(base_items), watch_items=tuple(watch_items),
            flow_auto_items=tuple(flow_auto_items), mode=mode, logic_version=logic_version,
            account_context=account_context, flow_snapshot=flow_snapshot, calculated_at=calculated_at,
            refresh_flow_candidates=refresh_flow_candidates, account_inputs=account_inputs,
        ))
        envelope.update(version=SCHEMA_VERSION,
                        raw_signature=_signature(envelope["raw_watch_items"], mode, logic_version),
                        base_signature=_signature(envelope["base_items"], mode, logic_version),
                        signature=_signature(envelope["watch_items"], mode, logic_version))
        envelope["integrity"] = _digest(envelope)
        reason = validate_restore_inputs(envelope, raw_watch_items=raw_watch_items, base_items=base_items,
                                         mode=mode, logic_version=logic_version, account_context=account_context,
                                         now=calculated_at)
        return {} if reason else envelope
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return {}


def restore_expiry_reason(envelope, now=None):
    """Same two-hour rule on hydration and later renders; legacy has no new TTL."""
    if not isinstance(envelope, dict) or envelope.get("version") != SCHEMA_VERSION:
        return ""
    try:
        age = _timestamp(now if now is not None else datetime.now(timezone.utc)) - _timestamp(envelope["calculated_at"])
        if age < timedelta(0) or age > RESTORE_WINDOW:
            return "원계산 2시간 경과 또는 시각 불일치 · 재계산 필요"
        return ""
    except (ValueError, TypeError, KeyError, OverflowError):
        return "원계산 시각 미확인 · 재계산 필요"


def validate_restore_inputs(envelope, *, raw_watch_items, base_items, mode, logic_version,
                            account_context, now=None):
    """Empty reason means eligible scope, not fresh prices or permission to execute.

    Caller must additionally match the raw frame's original account/time/signature,
    and reject a newer current flow snapshot before installing saved inputs.
    No account, calculation timestamp, signal, amount or state is rewritten here.
    """
    try:
        if not isinstance(envelope, dict) or envelope.get("version") != SCHEMA_VERSION:
            return "복원 원입력 미저장 또는 형식 불일치 · 재계산 필요"
        original = {key: value for key, value in envelope.items() if key != "integrity"}
        if envelope.get("integrity") != _digest(original):
            return "복원 원입력 무결성 불일치 · 재계산 필요"
        if not isinstance(account_context, str) or not account_context or envelope["account_context"] != account_context:
            return "계좌·입력맥락 불일치 · 재계산 필요"
        if not mode or not logic_version or envelope["mode"] != mode or envelope["logic_version"] != logic_version:
            return "계산 모드·버전 불일치 · 재계산 필요"
        for key in ("raw_watch_items", "base_items", "watch_items", "flow_auto_items"):
            _items(envelope[key])
        _items(raw_watch_items)
        _items(base_items)
        for key, sig_key in (("raw_watch_items", "raw_signature"), ("base_items", "base_signature"), ("watch_items", "signature")):
            if envelope[sig_key] != _signature(envelope[key], mode, logic_version):
                return "저장 입력서명 불일치 · 재계산 필요"
        if (envelope["raw_signature"] != _signature(raw_watch_items, mode, logic_version)
                or envelope["base_signature"] != _signature(base_items, mode, logic_version)):
            return "관심·보유 기본입력 변경 · 재계산 필요"
        base_keys, auto_keys, all_keys = (_items(envelope[key]) for key in ("base_items", "flow_auto_items", "watch_items"))
        if set(base_keys) & set(auto_keys) or set(base_keys) | set(auto_keys) != set(all_keys):
            return "저장 계산대상 범위 불일치 · 재계산 필요"
        calculated = dict(zip(all_keys, envelope["watch_items"]))
        for keys, items in ((base_keys, envelope["base_items"]), (auto_keys, envelope["flow_auto_items"])):
            if _signature([calculated[key] for key in keys], mode, logic_version) != _signature(items, mode, logic_version):
                return "저장 계산대상 입력 불일치 · 재계산 필요"
        if (type(envelope["refresh_flow_candidates"]) is not bool
                or (auto_keys and (not envelope["refresh_flow_candidates"] or not envelope["flow_snapshot"]))
                or (envelope["flow_snapshot"] is not None and not isinstance(envelope["flow_snapshot"], dict))):
            return "돈흐름 원입력 미확인 · 재계산 필요"
        return restore_expiry_reason(envelope, now=now)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return "복원 원입력 형식 미확인 · 재계산 필요"


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
