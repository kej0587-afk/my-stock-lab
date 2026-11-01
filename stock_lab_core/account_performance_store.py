"""Bounded private ledgers through an injected, server-only Supabase client.

Streamlit verifies the owner; it does not supply a Supabase user JWT. The
service client bypasses RLS, so construct one store per trusted app owner.
No credentials, database connections or schema are created here. Prepare the
dedicated table with docs/20261101_account_performance.sql before using it.
"""

from datetime import datetime, timezone
import json

from stock_lab_core.account_performance_io import decode_ledger, encode_ledger
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


TABLE_NAME = "account_performance_ledgers"
_COLUMNS = "owner_email,revision,payload,updated_at"
_MAX_REVISION = 2**63 - 1
_INVALID = (KeyError, TypeError, ValueError, OverflowError, RecursionError)


class AccountPerformanceStoreError(Exception):
    """Expose only a fixed code, never database messages or credentials."""

    def __init__(self, code="store_unavailable"):
        self.code = code
        super().__init__(code)


def _owner(value):
    return value.strip().lower() if isinstance(value, str) else ""


def _valid_revision(value):
    return type(value) is int and 0 < value <= _MAX_REVISION


def _portable(raw):
    ledger = decode_ledger(raw)
    return json.loads(encode_ledger(ledger)), ledger


def _database_error(exc):
    # PostgREST messages may contain SQL, request URLs or service credentials.
    code = getattr(exc, "code", None)
    if code in {"42P01", "42703", "3F000", "PGRST204", "PGRST205", "PGRST106"}:
        return AccountPerformanceStoreError("schema_unavailable")
    if code == "23505":
        return AccountPerformanceStoreError("conflict")
    return AccountPerformanceStoreError("store_unavailable")


class SupabaseAccountPerformanceStore:
    """Owner-bound portable drafts, saved by insert or compare-and-swap update.

    Pass only the verified app owner, never an owner from arbitrary UI input.
    Construction performs no database calls. No deletes or upserts are used.
    """

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner_scope = _owner(owner_scope)

    def _check_owner(self, owner_scope):
        if not self._owner_scope or _owner(owner_scope) != self._owner_scope:
            raise AccountPerformanceStoreError("owner_scope_mismatch")

    def _decode(self, row):
        if not isinstance(row, dict):
            raise AccountPerformanceStoreError("invalid_data")
        if row.get("owner_email") != self._owner_scope:
            raise AccountPerformanceStoreError("owner_scope_mismatch")
        try:
            if not _valid_revision(row["revision"]) or not isinstance(row["payload"], dict):
                raise ValueError
            updated_at = row["updated_at"]
            if (not isinstance(updated_at, str)
                    or datetime.fromisoformat(updated_at).utcoffset() is None):
                raise ValueError
            raw = json.dumps(row["payload"], ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
            payload, ledger = _portable(raw)
        except _INVALID:
            raise AccountPerformanceStoreError("invalid_data") from None
        return {"revision": row["revision"], "ledger": ledger, "updated_at": updated_at}, payload

    def load(self, *, owner_scope):
        self._check_owner(owner_scope)
        try:
            response = (self._client.table(TABLE_NAME).select(_COLUMNS)
                        .eq("owner_email", self._owner_scope).limit(2).execute())
        except Exception as exc:
            raise _database_error(exc) from None
        rows = getattr(response, "data", None)
        if not isinstance(rows, list) or len(rows) > 1:
            raise AccountPerformanceStoreError("invalid_data")
        return self._decode(rows[0])[0] if rows else None

    def save(self, ledger, *, expected_revision, owner_scope):
        self._check_owner(owner_scope)
        if expected_revision is not None and (
                not _valid_revision(expected_revision) or expected_revision == _MAX_REVISION):
            raise AccountPerformanceStoreError("invalid_data")
        try:
            payload, _ = _portable(encode_ledger(ledger))
        except _INVALID:
            raise AccountPerformanceStoreError("invalid_data") from None
        revision = 1 if expected_revision is None else expected_revision + 1
        # Keep an independent canonical candidate even if the client mutates its input.
        values = {"revision": revision, "payload": json.loads(json.dumps(payload))}
        try:
            if expected_revision is None:
                values["owner_email"] = self._owner_scope
                response = self._client.table(TABLE_NAME).insert(values).execute()
            else:
                values["updated_at"] = datetime.now(timezone.utc).isoformat()
                response = (self._client.table(TABLE_NAME).update(values)
                            .eq("owner_email", self._owner_scope)
                            .eq("revision", expected_revision).execute())
        except Exception as exc:
            raise _database_error(exc) from None
        rows = getattr(response, "data", None)
        if isinstance(rows, list) and not rows and expected_revision is not None:
            raise AccountPerformanceStoreError("conflict")
        if not isinstance(rows, list) or len(rows) != 1:
            raise AccountPerformanceStoreError("write_unconfirmed")
        saved, returned_payload = self._decode(rows[0])
        if saved["revision"] != revision or returned_payload != payload:
            raise AccountPerformanceStoreError("write_unconfirmed")
        return saved
