"""Persistent last-success DART corporate identity list, via an injected client.

Public identifiers only (stock code -> DART corp code). This is an identity
list, not financial statements or filings; those keep their own freshness.
No client/credential/schema creation here. Database exception text is never
retained because it can contain connection details.
"""

import hashlib
import json

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


TABLE_NAME = "dart_corporate_code_snapshots"
COLUMNS = "source,version,retrieved_at,mapped_count,codes_sha256,codes"


class CorporateStoreError(ValueError):
    """Fixed codes only."""


def codes_digest(codes):
    canonical = json.dumps(codes, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _database_error(error):
    return CorporateStoreError("schema_unavailable" if getattr(error, "code", None) in
                               {"42P01", "PGRST204", "PGRST205"} else "store_unavailable")


class SupabaseCorporateCodeStore:
    """One row per official source URL: the latest validated live download."""

    def __init__(self, client):
        if client is None:
            raise CorporateStoreError("client_required")
        self._client = client

    def load(self, source):
        try:
            response = (self._client.table(TABLE_NAME).select(COLUMNS)
                        .eq("source", source).limit(1).execute())
        except Exception as error:
            raise _database_error(error) from None
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) > 1:
            raise CorporateStoreError("invalid_data")
        if not data:
            return None
        row = data[0]
        codes = row.get("codes") if isinstance(row, dict) else None
        if (not isinstance(codes, dict) or row.get("source") != source
                or row.get("mapped_count") != len(codes) or row.get("codes_sha256") != codes_digest(codes)):
            raise CorporateStoreError("invalid_data")
        return {"version": row.get("version"), "source": row["source"],
                "retrieved_at": row.get("retrieved_at"), "codes": codes}

    def save(self, payload):
        codes = payload["codes"]
        row = {"source": payload["source"], "version": payload["version"],
               "retrieved_at": payload["retrieved_at"], "mapped_count": len(codes),
               "codes_sha256": codes_digest(codes), "codes": codes}
        try:
            response = self._client.table(TABLE_NAME).upsert(row, on_conflict="source").execute()
        except Exception as error:
            raise _database_error(error) from None
        data = getattr(response, "data", None)
        if not (isinstance(data, list) and len(data) == 1
                and data[0].get("codes_sha256") == row["codes_sha256"]):
            raise CorporateStoreError("write_unconfirmed")
        return row["codes_sha256"]
