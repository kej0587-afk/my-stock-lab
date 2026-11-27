"""Dated public corporate identities, separate from filing/financial freshness.

Two dated sources may stand in for a failed live download: the latest validated
live download kept in a persistent store (survives app restarts), and the list
bundled with the code. Both use the same validation and the same 7-day limit.
This is an identity list only; it says nothing about filing or financial freshness.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from stock_lab_core.dart_corporate_codes import CorporateCodeMap


SNAPSHOT_PATH = Path(__file__).parent / "data" / "dart_corporate_codes.json"
SOURCE = "https://opendart.fss.or.kr/api/corpCode.xml"
MAX_AGE = timedelta(days=7)
FRESH_AGE = timedelta(days=1)
TRANSIENT = frozenset({"connect_timeout", "read_timeout", "timeout", "transport_error"})
# A live list much shorter than the last good one is more likely a truncated
# response than mass delisting; keep the stored list rather than overwrite it.
MIN_RETAINED_RATIO = 0.9
# Rewriting an identical list more often than this adds writes, not information.
UNCHANGED_REWRITE_AFTER = timedelta(hours=12)
ORIGIN_LABELS = {"persistent_last_success": "마지막 정상 조회 목록(보관소)",
                 "bundled_file": "앱 동봉 목록"}

_STORE = None


def configure_corporate_store(store):
    """Install (or clear with None) the persistent last-success store."""
    global _STORE
    _STORE = store


def _validated(payload, current):
    """Return (codes, stamp, age) or raise ValueError; same rules for every origin."""
    if not isinstance(payload, dict):
        raise ValueError("invalid snapshot")
    stamp = datetime.fromisoformat(str(payload["retrieved_at"]))
    if stamp.tzinfo is None or current.tzinfo is None:
        raise ValueError("timezone required")
    age = current - stamp
    codes = payload["codes"]
    if (payload.get("version") != 1 or payload.get("source") != SOURCE
            or age < timedelta(0) or not isinstance(codes, dict) or not codes):
        raise ValueError("invalid snapshot")
    if any(not re.fullmatch(r"[0-9A-Z]{6}", str(stock)) or not isinstance(corp, str)
           or not re.fullmatch(r"\d{8}", corp) for stock, corp in codes.items()):
        raise ValueError("invalid corporate identifiers")
    return codes, stamp, age


def _candidate(origin, loader, current):
    """(status, payload) without raising; status distinguishes absent/expired/invalid."""
    try:
        payload = loader()
    except (OSError, ValueError, TypeError, KeyError):
        return "unavailable", None
    if payload is None:
        return "absent", None
    try:
        _, _, age = _validated(payload, current)
    except (ValueError, TypeError, KeyError):
        return "invalid", None
    return ("expired", None) if age > MAX_AGE else ("valid", payload)


def _store_load(store):
    def load():
        return store.load(SOURCE)
    return load


def fresh_corporate_codes(*, now, store=None):
    """Reuse a validated last-success list for its original one-day lifetime.

    Never renew the timestamp on read or use a bundled list as a fresh cache.
    Missing issuers remain explicitly unlinked, as in the existing one-day cache.
    Filing requests still authenticate with the caller's own DART key.
    """
    store = _STORE if store is None else store
    if store is None or now.tzinfo is None:
        return None
    _, payload = _candidate("persistent_last_success", _store_load(store), now)
    if payload is None:
        return None
    codes, stamp, age = _validated(payload, now)
    if age >= FRESH_AGE:
        return None
    return CorporateCodeMap(dict(codes), diagnostic={
        "mapping_source": "official_cache", "snapshot_origin": "persistent_last_success",
        "snapshot_asof": stamp.isoformat(), "snapshot_valid_until": (stamp + FRESH_AGE).isoformat(),
        "mapped_count": len(codes), "cause": "cache_hit",
    })


def remember_corporate_codes(live, *, store=None, now=None):
    """After a successful live download, validate and persist it; never raises.

    Returns the persist status and records it in the live diagnostic.
    """
    store = _STORE if store is None else store
    if store is None or not live or live.diagnostic.get("cause") != "ok":
        return "not_configured" if store is None else "not_live_success"
    current = now or datetime.now(timezone.utc)
    payload = {"version": 1, "source": SOURCE, "retrieved_at": current.isoformat(), "codes": dict(live)}
    try:
        _validated(payload, current)
    except (ValueError, TypeError, KeyError):
        status = "rejected_invalid"
    else:
        try:
            previous = store.load(SOURCE)
        except ValueError:
            previous = None
        status = None
        if isinstance(previous, dict) and isinstance(previous.get("codes"), dict):
            old = previous["codes"]
            if len(payload["codes"]) < MIN_RETAINED_RATIO * len(old):
                status = "rejected_shrunk"
            elif old == payload["codes"]:
                try:
                    age = current - datetime.fromisoformat(str(previous.get("retrieved_at")))
                except (TypeError, ValueError):
                    age = None
                if age is not None and timedelta(0) <= age < UNCHANGED_REWRITE_AFTER:
                    status = "unchanged_recent"
        if status is None:
            try:
                store.save(payload)
                status = "saved"
            except ValueError as error:
                status = str(error) if re.fullmatch(r"[a-z_]{1,40}", str(error)) else "store_unavailable"
    live.diagnostic["persist_status"] = status
    return status


def use_corporate_snapshot(live, *, path=SNAPSHOT_PATH, now=None, store=None):
    """Never replace successful live data or conceal authentication/IP errors."""
    store = _STORE if store is None else store
    if live:
        remember_corporate_codes(live, store=store, now=now)
        return live
    diagnostic = dict(getattr(live, "diagnostic", {}))
    cause = diagnostic.get("cause")
    if cause not in TRANSIENT:
        return live
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        diagnostic["snapshot_status"] = "unavailable_or_expired"
        return CorporateCodeMap(diagnostic=diagnostic)

    def load_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))

    loaders = [("bundled_file", load_file)]
    if store is not None:
        loaders.insert(0, ("persistent_last_success", _store_load(store)))
    statuses, chosen = {}, None
    for origin, loader in loaders:
        status, payload = _candidate(origin, loader, current)
        statuses[origin] = status
        if payload is not None:
            stamp = datetime.fromisoformat(str(payload["retrieved_at"]))
            if chosen is None or stamp > chosen[1]:
                chosen = (origin, stamp, payload)
    diagnostic["snapshot_candidates"] = statuses
    if chosen is None:
        diagnostic["snapshot_status"] = "unavailable_or_expired"
        return CorporateCodeMap(diagnostic=diagnostic)
    origin, stamp, payload = chosen
    codes = payload["codes"]
    age = current - stamp
    diagnostic.update(mapping_source="official_snapshot", snapshot_origin=origin,
                      snapshot_asof=stamp.isoformat(), snapshot_age_days=age.days,
                      snapshot_valid_until=(stamp + MAX_AGE).isoformat(),
                      snapshot_status="valid", mapped_count=len(codes))
    return CorporateCodeMap(codes, diagnostic=diagnostic)


def snapshot_notice(diagnostic):
    """One Korean line for screens/reports; empty when the live list was used."""
    if isinstance(diagnostic, dict) and diagnostic.get("mapping_source") == "official_cache":
        return ("DART 기업코드 1일 캐시 사용 · 저장 " + str(diagnostic.get("snapshot_asof", "미확인"))
                + " · 만료 " + str(diagnostic.get("snapshot_valid_until", "미확인"))
                + ". 기업 식별용 목록이며 공시·실적의 기준일과 수집 주기는 변경하지 않았습니다. "
                "저장 이후 신규 상장 기업은 미등록일 수 있습니다.")
    if not isinstance(diagnostic, dict) or diagnostic.get("mapping_source") != "official_snapshot":
        if isinstance(diagnostic, dict) and diagnostic.get("snapshot_status") == "unavailable_or_expired":
            states = diagnostic.get("snapshot_candidates") or {}
            detail = ", ".join(f"{ORIGIN_LABELS.get(k, k)} {v}" for k, v in states.items())
            return ("DART 실시간 기업코드 조회 실패 · 사용 가능한 7일 이내 보관 목록 없음"
                    + (f" ({detail})" if detail else ""))
        return ""
    label = ORIGIN_LABELS.get(diagnostic.get("snapshot_origin"), "보관 목록")
    asof = str(diagnostic.get("snapshot_asof", ""))[:16].replace("T", " ")
    until = str(diagnostic.get("snapshot_valid_until", ""))[:10]
    return (f"DART 실시간 기업코드 조회 실패 · {label} 사용 (저장 {asof} UTC, "
            f"{diagnostic.get('snapshot_age_days', '?')}일 경과, 유효 {until}까지). "
            "기업 식별용 목록이며 재무제표·공시의 최신성과는 별개입니다. "
            "저장 이후 신규 상장 기업은 식별되지 않을 수 있습니다.")
