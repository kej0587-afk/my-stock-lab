"""Immutable, owner-bound evidence storage using an injected server client.

No client/credentials/schema creation; no UI, app or score imports. The caller
must supply a verified app identity and a currently usable official corporate map.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import re

from stock_lab_core.dart_evidence import canonical_bytes, stamp, validate_bundle, validate_scope
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


TABLE_NAME = "financial_evidence_bundles"
COLUMNS = "owner_email,ticker,corp_code,bundle_sha256,scope_sha256,schema_version,source,collected_at,imported_at,payload"


class EvidenceStoreError(ValueError):
    """Fixed codes only: database exception messages can expose private data."""


def _check(condition, code):
    if not condition:
        raise EvidenceStoreError(code)


def _owner(value):
    return value.strip().lower() if isinstance(value, str) else ""


def _scope_hash(scope, now):
    keys = sorted(validate_scope(scope, now=now))
    return hashlib.sha256(canonical_bytes(keys)).hexdigest()


def _database_error(error):
    return EvidenceStoreError("schema_unavailable" if getattr(error, "code", None) in
                              {"42P01", "PGRST204", "PGRST205"} else "store_unavailable")


class SupabaseDartEvidenceStore:
    """Construct per verified owner; do not globally cache across app users.

    Every public operation checks that owner again. Service credentials bypass
    RLS, so both query filters and returned identities are checked here.
    """

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner = _owner(owner_scope)
        _check(bool(self._owner) and len(self._owner) <= 320, "invalid_owner")

    def _context(self, owner_scope, ticker, corporate_codes, now):
        _check(_owner(owner_scope) == self._owner, "owner_scope_mismatch")
        _check(isinstance(ticker, str) and re.fullmatch(r"[0-9A-Z]{6}\.(KS|KQ)", ticker), "invalid_ticker")
        _check(isinstance(corporate_codes, dict) and bool(corporate_codes), "identity_map_required")
        _check(isinstance(corporate_codes.get(ticker.split(".")[0]), str), "identity_map_required")
        current = now or datetime.now(timezone.utc)
        _check(isinstance(current, datetime) and current.tzinfo is not None, "timezone_required")
        return current.astimezone(timezone.utc)

    def _query(self, ticker):
        return (self._client.table(TABLE_NAME).select(COLUMNS)
                .eq("owner_email", self._owner).eq("ticker", ticker))

    def _decode(self, row, ticker, codes, now, *, digest=None, scope_hash=None):
        _check(isinstance(row, dict) and row.get("owner_email") == self._owner, "owner_scope_mismatch")
        _check(row.get("ticker") == ticker, "ticker_mismatch")
        payload = deepcopy(row.get("payload"))
        try:
            summary = validate_bundle(payload, corporate_codes=codes, now=now)
            scope = _scope_hash(payload["requested_reports"], now)
            _check(summary["eligible"], "evidence_not_eligible")
            _check(all(row.get(k) == payload[k] for k in ("ticker", "corp_code", "source", "schema_version")), "invalid_data")
            _check(stamp(row.get("collected_at")) == stamp(payload["collected_at"]), "invalid_data")
            imported = stamp(row.get("imported_at"))
            _check(imported <= now + timedelta(minutes=5), "invalid_data")
            _check(row.get("bundle_sha256") == summary["sha256"] and row.get("scope_sha256") == scope, "invalid_data")
            _check(digest is None or digest == summary["sha256"], "invalid_data")
            _check(scope_hash is None or scope_hash == scope, "scope_mismatch")
        except EvidenceStoreError:
            raise
        except (ValueError, TypeError, KeyError):
            raise EvidenceStoreError("invalid_data") from None
        return {"payload": payload, "summary": summary, "imported_at": imported.isoformat()}

    def insert_bundle(self, payload, *, ticker, owner_scope, corporate_codes, now=None):
        current = self._context(owner_scope, ticker, corporate_codes, now)
        candidate = deepcopy(payload)
        summary = validate_bundle(candidate, corporate_codes=corporate_codes, now=current)
        _check(candidate["ticker"] == ticker, "ticker_mismatch")
        _check(summary["eligible"], "evidence_not_eligible")
        scope = _scope_hash(candidate["requested_reports"], current)
        digest = summary["sha256"]
        row = {"owner_email": self._owner, "bundle_sha256": digest, "scope_sha256": scope,
               **{k: candidate[k] for k in ("ticker", "corp_code", "source", "schema_version", "collected_at")},
               "payload": candidate}  # imported_at comes from the database, never the upload.
        inserted = True
        try:
            response = self._client.table(TABLE_NAME).insert(row).execute()
        except Exception as error:
            if getattr(error, "code", None) != "23505":
                raise _database_error(error) from None
            # Race-safe duplicate handling: verify the precise existing row, never UPDATE.
            inserted = False
            try:
                response = self._query(ticker).eq("bundle_sha256", digest).limit(1).execute()
            except Exception as read_error:
                raise _database_error(read_error) from None
        data = getattr(response, "data", None)
        _check(isinstance(data, list) and len(data) == 1, "write_unconfirmed")
        result = self._decode(data[0], ticker, corporate_codes, current, digest=digest, scope_hash=scope)
        return {"inserted": inserted, **result}

    def load_latest(self, ticker, *, requested_reports, owner_scope, corporate_codes, now=None):
        current = self._context(owner_scope, ticker, corporate_codes, now)
        scope = _scope_hash(requested_reports, current)
        try:
            response = (self._query(ticker).eq("scope_sha256", scope)
                        .gte("collected_at", (current - timedelta(days=7)).isoformat())
                        .lte("collected_at", (current + timedelta(minutes=5)).isoformat())
                        .order("collected_at", desc=True).order("imported_at", desc=True)
                        .order("bundle_sha256", desc=True).limit(1).execute())
        except Exception as error:
            raise _database_error(error) from None
        data = getattr(response, "data", None)
        _check(isinstance(data, list) and len(data) <= 1, "invalid_data")
        if not data:
            return None
        return self._decode(data[0], ticker, corporate_codes, current, scope_hash=scope)

    def load_recent(self, ticker, *, owner_scope, corporate_codes, now=None):
        """Latest collected bundle, any stored scope; NOT latest released filing.

        Company review has no uploaded scope to select. Return one validated
        bundle with its original requested_reports; never merge reporting bases.
        The precision panel's exact-scope load_latest contract stays unchanged.
        """
        current = self._context(owner_scope, ticker, corporate_codes, now)
        try:
            response = (self._query(ticker)
                        .gte("collected_at", (current - timedelta(days=7)).isoformat())
                        .lte("collected_at", (current + timedelta(minutes=5)).isoformat())
                        .order("collected_at", desc=True).order("imported_at", desc=True)
                        .order("bundle_sha256", desc=True).limit(1).execute())
        except Exception as error:
            raise _database_error(error) from None
        data = getattr(response, "data", None)
        _check(isinstance(data, list) and len(data) <= 1, "invalid_data")
        if not data:
            return None
        return self._decode(data[0], ticker, corporate_codes, current)
