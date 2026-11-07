"""Dated public corporate identities, only for transient DART transport outages."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from stock_lab_core.dart_corporate_codes import CorporateCodeMap


SNAPSHOT_PATH = Path(__file__).parent / "data" / "dart_corporate_codes.json"
SOURCE = "https://opendart.fss.or.kr/api/corpCode.xml"
MAX_AGE = timedelta(days=7)


def use_corporate_snapshot(live, *, path=SNAPSHOT_PATH, now=None):
    """Never replace successful live data or conceal authentication/IP errors."""
    if live:
        return live
    diagnostic = dict(getattr(live, "diagnostic", {}))
    cause = diagnostic.get("cause")
    transient = cause in {"connect_timeout", "read_timeout", "timeout", "transport_error"}
    if not transient:
        return live
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(payload["retrieved_at"])
        current = now or datetime.now(timezone.utc)
        if stamp.tzinfo is None or current.tzinfo is None:
            raise ValueError("timezone required")
        age = current - stamp
        codes = payload["codes"]
        if (payload.get("version") != 1 or payload.get("source") != SOURCE
                or age < timedelta(0) or age > MAX_AGE or not isinstance(codes, dict) or not codes):
            raise ValueError("invalid snapshot")
        if any(not re.fullmatch(r"[0-9A-Z]{6}", str(stock)) or not isinstance(corp, str)
               or not re.fullmatch(r"\d{8}", corp) for stock, corp in codes.items()):
            raise ValueError("invalid corporate identifiers")
    except (OSError, ValueError, TypeError, KeyError):
        diagnostic["snapshot_status"] = "unavailable_or_expired"
        return CorporateCodeMap(diagnostic=diagnostic)
    diagnostic.update(mapping_source="official_snapshot", snapshot_asof=stamp.isoformat(),
                      snapshot_age_days=age.days, snapshot_valid_until=(stamp + MAX_AGE).isoformat(),
                      mapped_count=len(codes))
    return CorporateCodeMap(codes, diagnostic=diagnostic)
