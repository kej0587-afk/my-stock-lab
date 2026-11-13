"""Period-exact, source-verified release metadata fallback; never fills values."""

import json
from datetime import datetime
from pathlib import Path

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
FACTS = Path(__file__).with_name("data") / "verified_release_metadata.json"


def apply_verified_release_metadata(row, now):
    if row.get("release_at") or row.get("source") != "BLS":
        return
    try:
        records = json.loads(FACTS.read_text(encoding="utf-8"))
        for fact in records:
            if (row.get("indicator") not in fact["indicators"] or row.get("period") != fact["period"]
                    or not fact["verified_at"] <= now.date().isoformat() < fact["expires_at"]):
                continue
            at = datetime.fromisoformat(fact["release_at"])
            if at.tzinfo is None or at > now:
                continue
            row.update(release_at=at.isoformat(), release_precision="datetime",
                       release_source="BLS release (verified metadata fallback)",
                       release_source_url=fact["source_url"], release_metadata_mode="verified_snapshot")
            row["missing_reason"] = ";".join(code for code in row.get("missing_reason", "").split(";")
                                              if code and code != "release_date_unavailable"
                                              and not code.startswith("release_schedule_"))
            return
    except (OSError, ValueError, KeyError, TypeError):
        return
