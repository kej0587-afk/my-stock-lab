"""Pure, change-first Today wording over saved observations; no I/O or policy.

Integration contract
--------------------
* Pass payloads returned by an owner-bound report-history loader, and its verified
  owner as ``history_owner_scope``. Never stamp legacy history with today's account.
* ``account_key`` is report_latest.account_key(selected_accounts). Existing report
  history has no account key: those records cannot prove portfolio comparability.
* ``make_today_change_session`` creates a report-history-compatible payload. The
  caller may persist its account_key/brief_inputs alongside existing rows. This
  module does not change storage, gate calculations, scores, or cache lifetimes.
* comparison_context is a nonempty mapping describing the same observation
  universe, count/membership definitions and display-policy version. Keep changing
  timestamps/values out of it. Unknown or different contexts cannot say unchanged.
* Sector leaders and recovery membership must be observed/stored inputs. Missing
  fields mean unknown, not zero. Never rebuild old headlines with today's inputs.
* ``previous_sessions`` is an optional VERIFIED previous trading-date pair from
  the caller's market calendar. Without it, wording says previous SAVED basis.
  Today snapshot's last_run/previous.date are run dates, not source trading dates.
* Escape ``headline`` at the HTML boundary; render ``static_policy`` separately.
  ``audit`` contains the selected <=20 saved pairs and exact inputs/timestamps for
  private inspection. It is not an assertion of 20 consecutive trading days.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json


FIELDS = ("sector_leaders", "recovery_watch", "execution_count", "held_actions")
LABELS = dict(zip(FIELDS, ("섹터 선두", "회복 관찰", "실행후보", "보유행동")))


def _text(value):
    value = " ".join(str(value if value is not None else "").split())
    return "" if value.lower() in {"nan", "none", "<na>", "nat"} else value


def _dates(value):
    if not isinstance(value, Mapping):
        return None
    try:
        result = {market: value[market] for market in ("US", "KR")}
        return result if all(isinstance(day, str) and date.fromisoformat(day).isoformat() == day
                             for day in result.values()) else None
    except (KeyError, TypeError, ValueError):
        return None


def _stamp(value):
    # An ambiguous local run time is not sufficient for point-in-time comparison.
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _key(dates):
    return dates["US"], dates["KR"]


def _clean_map(value):
    if not isinstance(value, Mapping):
        return None
    if any(not _text(k) or not _text(v) for k, v in value.items()):
        return None
    return dict(sorted((_text(k), _text(v)) for k, v in value.items()))


def _clean_members(value):
    if not isinstance(value, (list, tuple, set)) or any(not _text(v) for v in value):
        return None
    return sorted({_text(v) for v in value})


def _inputs(session):
    """Read actual stored fields; only legacy gate/held labels can be recovered."""
    supplied = session.get("brief_inputs")
    supplied = supplied if isinstance(supplied, Mapping) else {}
    result = {}
    for field in ("sector_leaders", "held_actions"):
        if (value := _clean_map(supplied.get(field))) is not None:
            result[field] = value
    if (value := _clean_members(supplied.get("recovery_watch"))) is not None:
        result["recovery_watch"] = value
    value = supplied.get("execution_count")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        result["execution_count"] = value
    rows = session.get("rows")
    if not isinstance(rows, list) or not rows or not all(isinstance(r, Mapping) for r in rows):
        return result, None
    tickers = [_text(r.get("티커", r.get("ticker"))) for r in rows]
    if not all(tickers) or len(set(tickers)) != len(tickers):
        return result, None
    universe = sorted((ticker, _text(r.get("입력출처"))) for ticker, r in zip(tickers, rows))
    gates = [_text(r.get("게이트상태", r.get("gate_state"))) for r in rows]
    if "execution_count" not in supplied and all(gates):
        result["execution_count"] = sum(g in {"실행가능", "EXECUTABLE"} for g in gates)
    # report_history.normalized_decisions stores actual booleans. Unknown holding
    # status must not silently turn into an empty portfolio.
    if "held_actions" not in supplied and all(isinstance(r.get("보유여부"), bool) for r in rows):
        held = {ticker: _text(r.get("최종읽기")) for ticker, r in zip(tickers, rows) if r["보유여부"]}
        if all(held.values()):
            result["held_actions"] = dict(sorted(held.items()))
    return result, universe


def make_today_change_session(rows, *, dates, generated_at, account_key, comparison_context,
                              sector_leaders=None, recovery_watch=None,
                              execution_count=None, held_actions=None):
    """Package already computed facts; None is unknown and []/{} is observed empty.

    ``rows`` are report_history.normalized_decisions(...) or equivalent records.
    ``sector_leaders`` maps market -> observed leader, ``recovery_watch`` is the
    observed ticker list, ``held_actions`` maps held ticker -> existing action.
    execution_count is the existing UI count, never recomputed by new thresholds.
    """
    facts = {"sector_leaders": sector_leaders, "recovery_watch": recovery_watch,
             "execution_count": execution_count, "held_actions": held_actions}
    session = {"dates": deepcopy(dates), "generated_at": generated_at,
               "account_key": account_key, "comparison_context": deepcopy(comparison_context),
               "rows": deepcopy(list(rows)),
               "brief_inputs": deepcopy({k: v for k, v in facts.items() if v is not None})}
    if (not _dates(dates) or not _stamp(generated_at) or not _text(account_key)
            or not isinstance(comparison_context, Mapping) or not comparison_context):
        raise ValueError("dates, timezone-aware generated_at, account_key and comparison_context required")
    return session


def _comparable_fields(current, previous, current_universe, previous_universe):
    fields = []
    for field in FIELDS:
        if field not in current or field not in previous:
            continue
        if field == "sector_leaders" and (not current[field] or current[field].keys() != previous[field].keys()):
            continue
        if field in {"recovery_watch", "execution_count"} and (
                current_universe is None or current_universe != previous_universe):
            continue
        # Membership changes are not purchases/sales or an action change.
        if field == "held_actions" and current[field].keys() != previous[field].keys():
            continue
        fields.append(field)
    return fields


def _current_fact(facts):
    if facts.get("sector_leaders"):
        market, leader = next(iter(facts["sector_leaders"].items()))
        return f"현재 {market} 섹터 선두 {leader}"
    if "recovery_watch" in facts:
        return f"현재 회복 관찰 {len(facts['recovery_watch'])}개"
    if "execution_count" in facts:
        return f"현재 실행후보 {facts['execution_count']}개"
    if "held_actions" in facts:
        return f"현재 보유행동 점검 {len(facts['held_actions'])}개"
    return "현재 요약 입력 미확보"


def _change(field, before, after):
    if field == "sector_leaders":
        market = next(k for k in after if before[k] != after[k])
        return f"{market} 섹터 선두 {before[market]} → {after[market]}"
    if field == "recovery_watch":
        added, removed = sorted(set(after) - set(before)), sorted(set(before) - set(after))
        parts = []
        if added:
            parts.append(f"{added[0]}" + (f" 외 {len(added) - 1}개" if len(added) > 1 else "") + " 편입")
        if removed:
            parts.append(f"{removed[0]}" + (f" 외 {len(removed) - 1}개" if len(removed) > 1 else "") + " 제외")
        return "회복 관찰 " + " / ".join(parts)
    if field == "execution_count":
        return f"실행후보 {before}개 → {after}개"
    tickers = [k for k in after if before[k] != after[k]]
    ticker = tickers[0]
    return (f"보유 {ticker} 행동 {before[ticker]} → {after[ticker]}"
            + (f" (외 {len(tickers) - 1}개 변경)" if len(tickers) > 1 else ""))


def build_today_change_brief(current_session, saved_sessions=(), *, owner_scope="",
                            history_owner_scope="", account_key="", today_action="",
                            previous_sessions=None, static_policy=()):
    """Return one change + today's action, separate policy, and private audit data.

    Select actual earlier saved source-date pairs (both dates <= current; at least
    one <), excluding same-session reruns and future generations. Deduplicate pairs
    by latest generation, then use existing history's US-first date order. Priority
    is sector leader, recovery membership, execution count, held action. This is
    wording priority only; no investment recommendation or severity is inferred.

    ``saved_sessions`` accepts the dict from load_sessions or an iterable of payloads.
    Every selected record needs a stored matching account_key. A loader must verify
    history_owner_scope; supplying a matching string is not an authentication check.
    """
    current = current_session if isinstance(current_session, Mapping) else {}
    facts, universe = _inputs(current)
    dates, generated = _dates(current.get("dates")), _stamp(current.get("generated_at"))
    owner = _text(owner_scope).lower()
    scoped = bool(owner and owner == _text(history_owner_scope).lower()
                  and _text(account_key) and current.get("account_key") == account_key)
    context = current.get("comparison_context")
    skipped = {}
    selected = {}
    available_pairs = set()
    entries = saved_sessions.values() if isinstance(saved_sessions, Mapping) else (saved_sessions or ())
    for entry in entries:
        source_dates = _dates(entry.get("dates")) if isinstance(entry, Mapping) else None
        if (scoped and dates and source_dates and source_dates != dates
                and all(source_dates[m] <= dates[m] for m in dates)):
            available_pairs.add(_key(source_dates))
        reason = ""
        if not scoped:
            reason = "unverified_scope"
        elif not isinstance(entry, Mapping) or entry.get("account_key") != account_key:
            reason = "account_scope_unknown_or_different"
        elif entry.get("owner_scope") is not None and _text(entry["owner_scope"]).lower() != owner:
            reason = "owner_scope_different"
        elif not isinstance(context, Mapping) or not context or entry.get("comparison_context") != context:
            reason = "observation_context_unknown_or_different"
        else:
            old_dates, old_at = _dates(entry.get("dates")), _stamp(entry.get("generated_at"))
            if not dates or not generated or not old_dates or not old_at:
                reason = "dates_or_timestamp_unknown"
            elif old_at > generated:
                reason = "future_generation"
            elif old_dates == dates:
                reason = "same_source_dates"
            elif any(old_dates[m] > dates[m] for m in dates):
                reason = "future_source_date"
            else:
                key = _key(old_dates)
                if key not in selected or old_at > _stamp(selected[key].get("generated_at")):
                    selected[key] = entry
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1

    # Deduplicate before comparing fields: never fall back to an overwritten older
    # version of a pair just because the latest saved input is incomplete.
    audits = []
    for key in sorted(selected, reverse=True):
        entry = selected[key]
        old_facts, old_universe = _inputs(entry)
        fields = _comparable_fields(facts, old_facts, universe, old_universe)
        if not fields:
            skipped["no_comparable_inputs"] = skipped.get("no_comparable_inputs", 0) + 1
            continue
        audits.append({"dates": deepcopy(entry["dates"]), "generated_at": entry["generated_at"],
                       "observed_at": entry.get("brief_observed_at", entry["generated_at"]),
                       "inputs": deepcopy(old_facts), "compared_fields": fields})
        if len(audits) == 20:
            break

    prior = audits[0] if audits else None
    field = ""
    status = "current_only"
    headline = _current_fact(facts)
    if prior:
        reference = ("전 거래일" if _dates(previous_sessions) == prior["dates"] else "직전 저장 기준일")
        field = next((f for f in prior["compared_fields"] if facts[f] != prior["inputs"][f]), "")
        if field:
            headline = f"{reference} 대비 " + _change(field, prior["inputs"][field], facts[field])
            status = "changed"
        else:
            labels = "·".join(LABELS[f] for f in prior["compared_fields"])
            headline = f"{reference}과 동일({labels})"
            status = "unchanged"
    action = _text(today_action) or "입력 확인 후 행동 점검"
    return {"headline": headline + " · 오늘은 " + action, "status": status,
            "change_kind": field, "today_action": action,
            "static_policy": [_text(v) for v in static_policy if _text(v)],
            "comparison_dates": deepcopy(prior["dates"]) if prior else None,
            "comparison_generated_at": prior["generated_at"] if prior else None,
            "audit": {"requested": 20, "available": len(audits),
                      "available_saved_prior_pairs": len(available_pairs),
                      "eligible_comparison_pairs": len(audits), "unit": "saved_source_date_pairs",
                      "consecutive_trading_days_verified": False,
                      "coverage_note": (f"확보한 이전 저장 기준일 쌍 {len(available_pairs)}개 중 비교 가능 {len(audits)}/20개; 연속 20거래일 검증 아님"),
                      "current_dates": deepcopy(dates), "current_generated_at": current.get("generated_at"),
                      "current_inputs": deepcopy(facts), "sessions": audits, "excluded": skipped}}


def merge_today_briefs(*sessions):
    """Merge per-account observations, retaining the newest stored input per account."""
    merged = {}
    for session in sessions:
        entries = session.get("today_briefs", {}) if isinstance(session, Mapping) else {}
        if not isinstance(entries, Mapping):
            continue
        for account, observation in entries.items():
            # Unknown legacy metadata is not comparable, but still belongs to
            # that account: leave it intact instead of deleting it on our write.
            if account not in merged:
                merged[account] = deepcopy(observation)
            if not isinstance(observation, Mapping) or observation.get("account_key") != account:
                continue
            at = _stamp(observation.get("generated_at"))
            previous_entry = merged.get(account)
            previous = _stamp(previous_entry.get("generated_at")) if isinstance(previous_entry, Mapping) else None
            if at is not None and (previous is None or at >= previous):
                merged[account] = deepcopy(observation)
    return merged


def refresh_today_change_brief(state, current_session, *, owner_scope, accounts=(),
                               store=None, today_action="", previous_sessions=None,
                               static_policy=(), path=None):
    """Render adapter: once per calculation fingerprint, read and save real history.

    ``state`` is st.session_state or an ordinary mutable dict. ``store`` is an
    already owner-bound SupabaseReportHistoryStore (never a global shared client).
    ``path`` optionally overrides report_history.DEFAULT_PATH for tests. Local
    fallback uses the existing hashed owner file and atomic JSON writer. A failed
    remote read never triggers a blind upsert. The caller renders the returned
    headline and persistence/audit captions; no UI, remote pricing or scoring here.

    Current observations live at payload.today_briefs[account_key]. Old owner-only
    rows remain unscoped/uncomparable; report_history preserves this map on its own
    writes. Existing store uses read-modify-upsert, not a transactional JSON merge:
    simultaneous writes in different browser processes remain a storage limitation.
    """
    from stock_lab_core.report_latest import account_key as make_account_key
    from stock_lab_core.report_history import DEFAULT_PATH, _load_local, _save_local
    from stock_lab_core.today_snapshot import _snapshot_location

    owner, account = _text(owner_scope).lower(), make_account_key(accounts)
    valid = (isinstance(current_session, Mapping) and owner
             and current_session.get("account_key") == account
             and _dates(current_session.get("dates")) and _stamp(current_session.get("generated_at"))
             and isinstance(current_session.get("comparison_context"), Mapping)
             and bool(current_session["comparison_context"]))
    if not valid:
        result = build_today_change_brief(current_session, today_action=today_action, static_policy=static_policy)
        result["persistence"] = {"backend": "none", "read_status": "invalid_context", "saved": False}
        return result

    fingerprint = hashlib.sha256(json.dumps(
        [owner, account, current_session], ensure_ascii=False, sort_keys=True, default=str,
    ).encode("utf-8")).hexdigest()
    cache_key = "_today_change_brief_calculation_cache"
    cached = state.get(cache_key)
    cache_hit = isinstance(cached, Mapping) and cached.get("fingerprint") == fingerprint
    if not cache_hit:
        location, owner_hash = _snapshot_location(path or DEFAULT_PATH, owner)
        try:
            saved = _load_local(location, owner_hash)
            local_ok = True
        except (OSError, ValueError, TypeError, KeyError):
            saved, local_ok = {}, False
        remote_loaded = False
        persistence = {"backend": "local", "read_status": "local", "saved": False}
        if store is not None:
            try:
                remote = store.load_sessions(current_session["dates"], owner_scope=owner)
                from stock_lab_core.report_history_store import validate_session
                if not isinstance(remote, dict) or any(validate_session(v) != k for k, v in remote.items()):
                    raise ValueError("invalid history")
                for key, value in remote.items():
                    briefs = merge_today_briefs(saved.get(key, {}), value)
                    saved[key] = deepcopy(value)
                    if briefs:
                        saved[key]["today_briefs"] = briefs
                remote_loaded = True
                persistence.update(backend="supabase", read_status="loaded")
            except Exception:
                persistence.update(read_status="remote_unavailable_local_fallback")

        # Extract only this account's stored observations. Legacy payloads remain
        # in the audit as excluded records; never stamp them with current context.
        observations = []
        for session in saved.values():
            briefs = session.get("today_briefs", {})
            observation = briefs.get(account) if isinstance(briefs, Mapping) else None
            if (isinstance(observation, Mapping) and observation.get("account_key") == account
                    and observation.get("dates") == session.get("dates")):
                observations.append(deepcopy(observation))
            else:
                observations.append({"dates": deepcopy(session.get("dates")),
                                     "generated_at": session.get("generated_at"), "rows": []})

        pair = "/".join(_key(current_session["dates"]))
        existing = deepcopy(saved.get(pair, {"dates": current_session["dates"],
                                            "generated_at": current_session["generated_at"],
                                            "rows": current_session.get("rows", [])}))
        existing["today_briefs"] = merge_today_briefs(existing, {"today_briefs": {account: current_session}})
        if remote_loaded:
            try:
                store.upsert_session(existing, owner_scope=owner)
                persistence["saved"] = True
            except Exception:
                persistence.update(backend="local", write_status="remote_unavailable")
        saved[pair] = existing
        if local_ok:
            try:
                _save_local(location, owner_hash, saved)
                persistence["local_saved"] = True
                if persistence["backend"] == "local":
                    persistence["saved"] = True
            except (OSError, ValueError, TypeError):
                persistence["local_saved"] = False
        cached = {"fingerprint": fingerprint, "observations": observations, "persistence": persistence}
        state[cache_key] = cached

    result = build_today_change_brief(
        current_session, cached["observations"], owner_scope=owner, history_owner_scope=owner,
        account_key=account, today_action=today_action, previous_sessions=previous_sessions,
        static_policy=static_policy,
    )
    result["persistence"] = dict(cached["persistence"], cache_hit=cache_hit)
    result["audit"]["read_status"] = cached["persistence"]["read_status"]
    if cached["persistence"]["read_status"] == "remote_unavailable_local_fallback":
        result["audit"]["coverage_note"] += " · 원격 가용 일수 미확인(로컬 확보분만 집계)"
    return result
