"""DART identity preparation; no financial values or investment decisions."""

from datetime import datetime
import re
import time

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def directory_cache_valid(pair, now):
    """A process-cache read cannot extend the persisted list's original expiry."""
    mapping = pair[1]
    if mapping.get("mapping_source") != "official_cache":
        return True
    try:
        return (datetime.fromisoformat(mapping["snapshot_asof"]) <= now
                < datetime.fromisoformat(mapping["snapshot_valid_until"]))
    except (KeyError, TypeError, ValueError):
        return False


def prepare_directory(api_key, now, deadline, get):
    from stock_lab_core.dart_corporate_codes import fetch_corporate_codes
    from stock_lab_core.dart_corporate_snapshot import fresh_corporate_codes, use_corporate_snapshot

    data = fresh_corporate_codes(now=now)
    attempts = 0
    if data is None:
        data = fetch_corporate_codes(api_key, get=get, timeout=5)
        attempts = 1
        # One transient retry shares the existing collection deadline.
        if (not data and data.diagnostic.get("cause") in
                {"connect_timeout", "read_timeout", "timeout", "transport_error"}
                and deadline - time.monotonic() >= 6):
            data = fetch_corporate_codes(api_key, get=get, timeout=5)
            attempts += 1
        data = use_corporate_snapshot(data, now=now)
    if not data:
        cause = data.diagnostic.get("cause", "unavailable")
        status = str(data.diagnostic.get("api_status", ""))
        suffix = "_" + status if re.fullmatch(r"\d{3}", status) else ""
        raise ValueError("dart_corporate_mapping_" + cause + suffix)
    return dict(data), {"mapping_attempts": attempts, **{key: data.diagnostic[key] for key in
        ("mapping_source", "snapshot_origin", "snapshot_asof", "snapshot_valid_until")
        if key in data.diagnostic}}
