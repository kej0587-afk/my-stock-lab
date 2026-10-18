"""Account-scoped, atomic storage for the last manual Today Queue calculation."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


TODAY_QUEUE_LOGIC_VERSION = "20261014_market_stop_basis_v8"
TODAY_QUEUE_SUMMARY_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "cache" / "today_queue_summary_snapshot.json"
_LOG = logging.getLogger(__name__)


def _snapshot_location(path, owner_scope):
    scope = str(owner_scope or "").strip().lower()
    # Unauthenticated sessions must not read or replace a shared personal snapshot.
    if not scope and path is None:
        return None, ""
    base = Path(path) if path is not None else TODAY_QUEUE_SUMMARY_SNAPSHOT_PATH
    owner_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest() if scope else ""
    if owner_hash:
        base = base.with_name(f"{base.stem}_{owner_hash}{base.suffix}")
    return base, owner_hash


def save_today_queue_summary_snapshot(
    summary_df: pd.DataFrame, signature: str = "", last_run: str = "", *,
    path: Path | str | None = None, owner_scope: str = "",
) -> None:
    if not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        return
    snapshot_path, owner_hash = _snapshot_location(path, owner_scope)
    if snapshot_path is None:
        return
    temporary_path = None
    try:
        previous = {}
        try:
            old = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if old.get("owner_hash") == owner_hash and old.get("version") == TODAY_QUEUE_LOGIC_VERSION:
                old_date = str(old.get("last_run", ""))[:10]
                new_date = str(last_run or "")[:10]
                if old_date and new_date and old_date < new_date:
                    previous = {"data": old.get("data"), "date": old_date}
                else:
                    previous = old.get("previous", {})
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        payload = {
            "version": TODAY_QUEUE_LOGIC_VERSION,
            "owner_hash": owner_hash,
            "signature": str(signature or ""),
            "last_run": str(last_run or ""),
            "saved_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "data": summary_df.to_json(orient="split", force_ascii=False, date_format="iso"),
            "previous": previous,
        }
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        # A failed or concurrent write must leave readers a complete previous/new file.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=snapshot_path.parent,
            prefix=f".{snapshot_path.stem}_", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, snapshot_path)
    except (OSError, ValueError, TypeError) as exc:
        _LOG.warning("Today Queue snapshot save failed (%s)", type(exc).__name__)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as exc:
                _LOG.warning("Today Queue temporary cleanup failed (%s)", type(exc).__name__)


def load_today_queue_summary_snapshot(
    path: Path | str | None = None, *, owner_scope: str = "",
    expected_signature: str | None = None,
):
    empty = (pd.DataFrame(), "", "")
    snapshot_path, owner_hash = _snapshot_location(path, owner_scope)
    if snapshot_path is None:
        return empty
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != TODAY_QUEUE_LOGIC_VERSION:
            return empty
        if payload.get("owner_hash") != owner_hash:
            return empty
        signature = str(payload.get("signature", ""))
        if expected_signature is not None and signature != expected_signature:
            return empty
        raw_data = payload.get("data")
        if not isinstance(raw_data, str) or not raw_data:
            return empty
        split = json.loads(raw_data)
        if not isinstance(split, dict) or not all(
            isinstance(split.get(key), list) for key in ("columns", "index", "data")
        ):
            raise ValueError("Invalid snapshot frame structure")
        # Reject truncated rows instead of letting pandas fabricate missing cells.
        if len(split["data"]) != len(split["index"]) or any(
            not isinstance(row, list) or len(row) != len(split["columns"])
            for row in split["data"]
        ):
            raise ValueError("Invalid snapshot frame dimensions")
        # Preserve leading-zero domestic ticker strings across JSON restoration.
        frame = pd.read_json(io.StringIO(raw_data), orient="split", dtype=False)
        if frame.empty:
            return empty
        return frame, signature, str(payload.get("last_run", ""))
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _LOG.warning("Today Queue snapshot load failed (%s)", type(exc).__name__)
        return empty


def load_previous_today_summary(*, owner_scope="", path=None):
    """Last earlier-date snapshot for this account, never another user's data."""
    snapshot_path, owner_hash = _snapshot_location(path, owner_scope)
    if snapshot_path is None:
        return pd.DataFrame(), ""
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if payload.get("owner_hash") != owner_hash or payload.get("version") != TODAY_QUEUE_LOGIC_VERSION:
            return pd.DataFrame(), ""
        previous = payload.get("previous", {})
        if not previous.get("data") or not previous.get("date"):
            return pd.DataFrame(), ""
        return pd.read_json(io.StringIO(previous["data"]), orient="split", dtype=False), str(previous["date"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return pd.DataFrame(), ""


def clear_today_queue_summary_snapshot(path: Path | str | None = None, *, owner_scope: str = "") -> None:
    snapshot_path, _ = _snapshot_location(path, owner_scope)
    if snapshot_path is None:
        return
    try:
        snapshot_path.unlink(missing_ok=True)
    except OSError as exc:
        _LOG.warning("Today Queue snapshot delete failed (%s)", type(exc).__name__)
