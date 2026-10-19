"""Private report history accessed through the app's injected server client.

Streamlit authenticates the owner; it does not forward a Supabase user JWT.
The service client bypasses RLS, so every operation is bound to an owner here.
No credentials, clients, tables, or policies are created by this module.
"""

from copy import deepcopy
from datetime import date
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


TABLE_NAME = "report_history"
_COLUMNS = "owner_email,us_session,kr_session,payload"


class ReportHistoryStoreError(Exception):
    """Expose only a fixed error code, never database messages or credentials."""

    def __init__(self, code="store_unavailable"):
        self.code = code
        super().__init__(code)


def _owner(value):
    return str(value or "").strip().lower()


def validate_session(session):
    """Validate both legacy local entries and JSONB entries without changing them."""
    if not isinstance(session, dict) or not isinstance(session.get("dates"), dict):
        raise ValueError("invalid history session")
    for market in ("US", "KR"):
        value = session["dates"].get(market)
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError("invalid history date")
    if not isinstance(session.get("rows"), list) or not all(isinstance(row, dict) for row in session["rows"]):
        raise ValueError("invalid history rows")
    if "macro_data" in session and not isinstance(session["macro_data"], dict):
        raise ValueError("invalid macro history")
    if "generated_at" in session and not isinstance(session["generated_at"], str):
        raise ValueError("invalid history timestamp")
    return session["dates"]["US"] + "/" + session["dates"]["KR"]


def _database_error(exc):
    # PostgREST exceptions can include request URLs, SQL, or tokens in their text.
    code = getattr(exc, "code", None)
    return ReportHistoryStoreError(
        "schema_unavailable" if code in {"42P01", "PGRST205", "PGRST204"}
        else "store_unavailable"
    )


class SupabaseReportHistoryStore:
    """Bind an existing server-only Supabase client to a verified app owner.

    Construct per owner (do not globally cache this object across users), then
    pass it as ``store=`` to ``update_report_history``. Durable storage requires
    docs/20261020_report_history.sql; absence is handled by local fallback.
    """

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner_scope = _owner(owner_scope)

    def _check_owner(self, owner_scope):
        if not self._owner_scope or _owner(owner_scope) != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")

    def _decode(self, row):
        if not isinstance(row, dict) or row.get("owner_email") != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        payload = row.get("payload")
        try:
            key = validate_session(payload)
            if payload["dates"] != {"US": row.get("us_session"), "KR": row.get("kr_session")}:
                raise ValueError("history key mismatch")
        except (ValueError, TypeError):
            raise ReportHistoryStoreError("invalid_data") from None
        return key, deepcopy(payload)

    def load_sessions(self, dates, *, owner_scope):
        self._check_owner(owner_scope)
        validate_session({"dates": dates, "rows": []})
        try:
            response = (self._client.table(TABLE_NAME).select(_COLUMNS)
                        .eq("owner_email", self._owner_scope)
                        .lte("us_session", dates["US"]).lte("kr_session", dates["KR"])
                        .order("us_session", desc=True).order("kr_session", desc=True)
                        .limit(40).execute())
        except Exception as exc:
            raise _database_error(exc) from None
        if not isinstance(getattr(response, "data", None), list):
            raise ReportHistoryStoreError("invalid_data")
        saved = {}
        for row in response.data:
            key, payload = self._decode(row)
            if any(payload["dates"][market] > dates[market] for market in ("US", "KR")):
                raise ReportHistoryStoreError("invalid_data")
            saved[key] = payload
        return saved

    def upsert_session(self, session, *, owner_scope):
        self._check_owner(owner_scope)
        key = validate_session(session)
        row = {"owner_email": self._owner_scope, "us_session": session["dates"]["US"],
               "kr_session": session["dates"]["KR"], "payload": deepcopy(session)}
        try:
            response = self._client.table(TABLE_NAME).upsert(
                row, on_conflict="owner_email,us_session,kr_session",
            ).execute()
        except Exception as exc:
            raise _database_error(exc) from None
        if not isinstance(getattr(response, "data", None), list) or len(response.data) != 1:
            raise ReportHistoryStoreError("write_unconfirmed")
        returned_key, _ = self._decode(response.data[0])
        if returned_key != key:
            raise ReportHistoryStoreError("write_unconfirmed")
