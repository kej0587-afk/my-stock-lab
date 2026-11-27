"""Saved quick-chart settings (moving-average periods, which lines are on, daily overlay, interval).

Stored per verified login in Supabase ``chart_preferences`` (docs/20261127_chart_preferences.sql).
Until that table exists, settings stay for the current browser session only and the screen says so.
Display preferences only; never read by decisions.
"""

from __future__ import annotations

from stock_lab_core.intraday_chart import DEFAULT_MA_PERIODS, INTERVALS, MAX_MA, MIN_MA
from stock_lab_core.report_history_store import ReportHistoryStoreError, _database_error, _owner

TABLE_NAME = "chart_preferences"
STATE_KEY = "_quick_chart_preferences"
STATUS_KEY = "_quick_chart_preferences_status"
LOADED_KEY = "_quick_chart_preferences_loaded"

DEFAULTS = {"periods": list(DEFAULT_MA_PERIODS), "enabled": [5, 20, 120], "daily_overlay": False,
            "interval": "일봉"}


def normalize(prefs) -> dict:
    prefs = prefs if isinstance(prefs, dict) else {}
    periods = []
    for value in prefs.get("periods", DEFAULTS["periods"]) or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if MIN_MA <= number <= MAX_MA and number not in periods:
            periods.append(number)
    periods = sorted(periods)[:12] or list(DEFAULTS["periods"])
    enabled = []
    for value in prefs.get("enabled", DEFAULTS["enabled"]) or []:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number in periods and number not in enabled:
            enabled.append(number)
    interval = prefs.get("interval") if prefs.get("interval") in INTERVALS else DEFAULTS["interval"]
    return {"periods": periods, "enabled": sorted(enabled), "daily_overlay": bool(prefs.get("daily_overlay", False)),
            "interval": interval}


class SupabaseChartPreferenceStore:
    """One row per verified owner. Construct per owner (server-only service-role client)."""

    def __init__(self, client, *, owner_scope):
        self._client = client
        self._owner_scope = _owner(owner_scope)

    def load(self):
        if not self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        try:
            response = (self._client.table(TABLE_NAME).select("owner_email,prefs")
                        .eq("owner_email", self._owner_scope).limit(1).execute())
        except Exception as exc:
            raise _database_error(exc) from None
        rows = getattr(response, "data", None)
        if not isinstance(rows, list):
            raise ReportHistoryStoreError("invalid_data")
        if not rows:
            return None
        if rows[0].get("owner_email") != self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        return normalize(rows[0].get("prefs"))

    def save(self, prefs):
        if not self._owner_scope:
            raise ReportHistoryStoreError("owner_scope_mismatch")
        row = {"owner_email": self._owner_scope, "prefs": normalize(prefs)}
        try:
            response = self._client.table(TABLE_NAME).upsert(row, on_conflict="owner_email").execute()
        except Exception as exc:
            raise _database_error(exc) from None
        data = getattr(response, "data", None)
        if not isinstance(data, list) or len(data) != 1 or data[0].get("owner_email") != self._owner_scope:
            raise ReportHistoryStoreError("write_unconfirmed")


def load_into_state(state, store) -> dict:
    """Load once per session; fall back to defaults with an explicit status."""
    if state.get(LOADED_KEY):
        return state.get(STATE_KEY) or dict(DEFAULTS)
    state[LOADED_KEY] = True
    prefs, status = None, "session"
    if store is not None:
        try:
            prefs = store.load()
            status = "saved" if prefs else "default"
        except ReportHistoryStoreError as exc:
            status = "table_missing" if str(exc) == "schema_unavailable" else "store_error"
    state[STATE_KEY] = normalize(prefs) if prefs else dict(DEFAULTS)
    state[STATUS_KEY] = status
    return state[STATE_KEY]


def save_from_state(state, prefs, store) -> str:
    prefs = normalize(prefs)
    state[STATE_KEY] = prefs
    if store is None:
        state[STATUS_KEY] = "session"
        return "session"
    try:
        store.save(prefs)
        state[STATUS_KEY] = "saved"
    except ReportHistoryStoreError as exc:
        state[STATUS_KEY] = "table_missing" if str(exc) == "schema_unavailable" else "store_error"
    return state[STATUS_KEY]


STATUS_TEXT = {
    "saved": "설정 저장됨 (로그인 계정 기준)",
    "default": "기본 설정 (아직 저장한 설정 없음)",
    "session": "이번 접속 동안만 유지 (저장소 미연결)",
    "table_missing": "이번 접속 동안만 유지 (차트 설정 테이블 미생성)",
    "store_error": "이번 접속 동안만 유지 (저장소 응답 실패)",
}
