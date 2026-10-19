"""Time-bounded, source-checked release fallback; never claim a live API success."""

from copy import deepcopy
import json
from pathlib import Path

FACTS = Path(__file__).with_name("data") / "verified_kr_releases_20261019.json"


def apply_official_bulletins(rows, now):
    result = deepcopy(rows)
    try:
        facts = json.loads(FACTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if not facts["verified_at"] <= now.date().isoformat() < facts["expires_at"]:
        return result
    for row in result:
        for fact in facts["observations"]:
            if row.get("indicator") != fact["indicator"] or row.get("basis") != fact["basis"]:
                continue
            if row.get("period", "") >= fact["period"] and row.get("actual") is not None:
                continue
            # Do not carry a different month's consensus, revision or price reaction.
            configured = row.get("api_key_configured")
            failure = row.get("collection_error") or row.get("missing_reason") or "older_provider_period"
            row.clear()
            row.update(fact, status="verified_snapshot", collection_error=failure, api_key_configured=configured,
                       as_of=now.isoformat(), verified_at=facts["verified_at"], expires_at=facts["expires_at"], forecast=None, history=[],
                       release_precision="date", value_kind="verified_official_bulletin",
                       previous_unit=fact["unit"], previous_basis=fact["basis"], previous_source=fact["source"])
    return result
