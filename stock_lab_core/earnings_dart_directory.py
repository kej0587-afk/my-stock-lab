"""DART identity preparation; no financial values or investment decisions."""

from datetime import datetime
import re
import time

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.performance import count_event, measure
from stock_lab_core.earnings_discovery_performance import dart_status_event

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

    with measure("external_data", "earnings_collection.dart_directory.store_lookup"):
        data = fresh_corporate_codes(now=now)
    count_event("earnings_collection.dart_directory.persisted_cache." + ("hit" if data is not None else "miss"))
    attempts = 0
    if data is None:
        with measure("external_data", "earnings_collection.dart_directory.fetch_decode"):
            data = fetch_corporate_codes(api_key, get=get, timeout=5)
        if data.diagnostic.get("api_status") is not None:
            dart_status_event(data.diagnostic["api_status"])
        attempts = 1
        # One transient retry shares the existing collection deadline.
        if (not data and data.diagnostic.get("cause") in
                {"connect_timeout", "read_timeout", "timeout", "transport_error"}
                and deadline - time.monotonic() >= 6):
            count_event("earnings_collection.dart_directory.retry")
            with measure("external_data", "earnings_collection.dart_directory.fetch_decode"):
                data = fetch_corporate_codes(api_key, get=get, timeout=5)
            if data.diagnostic.get("api_status") is not None:
                dart_status_event(data.diagnostic["api_status"])
            attempts += 1
        # This existing call may validate/read a fallback OR persist live data.
        # Its internals live outside task1; do not label the whole span a DB write.
        with measure("external_data", "earnings_collection.dart_directory.snapshot_store"):
            data = use_corporate_snapshot(data, now=now)
        status = data.diagnostic.get("persist_status")
        if status is not None:
            allowed = {"saved", "unchanged_recent", "rejected_shrunk", "rejected_invalid", "not_configured", "not_live_success"}
            count_event("earnings_collection.dart_directory.store." + (status if status in allowed else "unavailable"))
    count_event("earnings_collection.dart_directory.output_codes", len(data))
    if not data:
        cause = data.diagnostic.get("cause", "unavailable")
        status = str(data.diagnostic.get("api_status", ""))
        suffix = "_" + status if re.fullmatch(r"\d{3}", status) else ""
        raise ValueError("dart_corporate_mapping_" + cause + suffix)
    return dict(data), {"mapping_attempts": attempts, **{key: data.diagnostic[key] for key in
        ("mapping_source", "snapshot_origin", "snapshot_asof", "snapshot_valid_until")
        if key in data.diagnostic}}
