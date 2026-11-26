"""Shared decision record (C-6/C-11 step 1, 2026-11-26, user decision).

One record per ticker, account scope and input time. Each screen reads the part it needs; the record
keeps the raw engine decision and the post-processed (MTF, leveraged override, pattern) decision side by
side, so screens may show different codes on purpose.

Step 1 is structure only: building a record never changes a decision, gate, sizing or multiplier.
The monthly multiplier is read from the raw engine code only (never a post-processing code or the
replay's hypothetical t_mult). The tech review stays display only.
"""

import hashlib
import json

from stock_lab_core.decision_behavior_groups import behavior_group_label

RECORD_VERSION = "decision_record_v1_2026-11-26"
SOURCE_ENGINE = "engine"            # 자산관리 · 월적립: calc_scores_and_decision only
SOURCE_TODAY = "today"              # Today · 자동시황: MTF guard, leveraged overrides, pattern, market guard, gate
SOURCE_PRECISION = "precision"      # 정밀관측소: same chain with the daily MTF snapshot
SOURCE_PRECISION_MANUAL = "precision_manual"  # 정밀관측소 수동 가격: never mixed into normal records

ENGINE_FIELDS = ("decision_code", "dec", "decision_group", "core_dca_label", "core_dca_rate", "core_dca_amt",
                 "buy_amt", "grade", "safety_state", "macro_state", "current_w", "target_w", "bucket")
POST_FIELDS = ("decision_code", "dec", "decision_group", "mtf_bias_label", "sizing_hint", "buy_amt")
CANDIDATE_FIELDS = ("grade", "adj", "fin_score", "rs_label", "trend")
MARKET_FIELDS = ("macro_state", "macro_missing_components", "data_state")


def _pick(src, fields):
    src = src if isinstance(src, dict) else {}
    out = {}
    for key in fields:
        value = src.get(key)
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value
    return out


def policy_versions(extra=None):
    """Versions of every policy layer a record depends on (strings only)."""
    versions = {"record": RECORD_VERSION}
    try:
        from stock_lab_core.today_snapshot import TODAY_QUEUE_LOGIC_VERSION
        versions["today_logic"] = TODAY_QUEUE_LOGIC_VERSION
    except Exception:
        versions["today_logic"] = "미확인"
    try:
        from stock_lab_core.tech_review import TECH_REVIEW_POLICY_VERSION
        versions["tech_review"] = TECH_REVIEW_POLICY_VERSION
    except Exception:
        versions["tech_review"] = "미확인"
    try:
        from stock_lab_core.leverage_l3_policy import POLICY_VERSION as L3_VERSION
        versions["leverage_l3"] = L3_VERSION
    except Exception:
        versions["leverage_l3"] = "미확인"
    versions["monthly_multiplier"] = "B-3 code table (rebalance_multiplier_table)"
    versions.update({str(k): str(v) for k, v in (extra or {}).items()})
    return versions


def record_cache_key(*, ticker, account_scope, has_pos, price_asof, macro_asof, versions, source):
    """Cache key: a record is reused only for the same ticker, account scope, holding state, price and macro
    as-of, policy versions and source. Missing parts stay in the key as 미확인 (never guessed)."""
    payload = {
        "ticker": str(ticker or "").upper(),
        "account_scope": str(account_scope or "미확인"),
        "has_pos": bool(has_pos),
        "price_asof": str(price_asof or "미확인"),
        "macro_asof": macro_asof if isinstance(macro_asof, (dict, list, str)) else "미확인",
        "versions": versions or {},
        "source": str(source or ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def engine_monthly_multiplier(engine_decision, bucket, dip_level=0, signal_multiplier=None):
    """Monthly multiplier from the raw engine decision (B-3 path), unchanged in step 1."""
    if signal_multiplier is None:
        from stock_lab_core.rebalance_multiplier import decision_signal_multiplier
        if not isinstance(engine_decision, dict):
            return None
        return decision_signal_multiplier(engine_decision, bucket, dip_level=dip_level)
    tap = str((engine_decision or {}).get("dec", "-"))
    return signal_multiplier(tap, bucket, dip_level=dip_level, decision=engine_decision)


def build_decision_record(*, ticker, source, engine, post=None, workflow=None, account_scope=None, has_pos=False,
                          price_asof=None, macro_status=None, sizing=None, monthly=None, leverage_l3=None,
                          tech_review=None, manual_price=False, extra_versions=None):
    """Assemble the shared record. Pure: reads its inputs and never mutates them."""
    if manual_price and source == SOURCE_PRECISION:
        source = SOURCE_PRECISION_MANUAL
    macro_status = macro_status if isinstance(macro_status, dict) else {}
    versions = policy_versions(extra_versions)
    engine_part = _pick(engine, ENGINE_FIELDS)
    engine_part["behavior_group"] = behavior_group_label(engine_part.get("decision_code"))
    post_part = _pick(post, POST_FIELDS) if isinstance(post, dict) else None
    if post_part is not None:
        post_part["behavior_group"] = behavior_group_label(post_part.get("decision_code"))
    wf = workflow if isinstance(workflow, dict) else {}
    gate = {
        "state": wf.get("게이트상태"),
        "reason": wf.get("게이트근거"),
        "evidence": wf.get("게이트근거ID") or wf.get("게이트증거"),
        "final_read": wf.get("최종읽기"),
        "group": wf.get("판정분류"),
        "market": wf.get("시장실행상태"),
    } if wf else None
    macro_asof = macro_status.get("as_of") or "미확인"
    record = {
        "version": RECORD_VERSION,
        "source": source,
        "ticker": str(ticker or "").upper(),
        "as_of": {
            "account_scope": account_scope or "미확인",
            "has_pos": bool(has_pos),
            "price_asof": price_asof or "미확인",
            "macro_status": macro_status.get("macro_data_status") or "미확인",
            "macro_asof": macro_asof,
            "manual_price": bool(manual_price),
        },
        "policy_versions": versions,
        "candidate": _pick(engine, CANDIDATE_FIELDS),
        "engine": engine_part,
        "post": post_part,
        "market": _pick(post if isinstance(post, dict) else engine, MARKET_FIELDS),
        "gate": gate,
        "sizing": sizing if sizing is not None else (post or {}).get("sizing_hint") if isinstance(post, dict) else None,
        "monthly": monthly,
        "leverage_l3": leverage_l3,
        "tech_review": tech_review,  # display only (C-5); never read by a decision
    }
    record["cache_key"] = record_cache_key(
        ticker=ticker, account_scope=account_scope, has_pos=has_pos, price_asof=price_asof,
        macro_asof=macro_asof, versions=versions, source=source,
    )
    return record


def store_record(state, record, *, key="_decision_records"):
    """Keep the latest record per (ticker, source). Manual-price records live under their own source."""
    if not isinstance(record, dict):
        return
    try:
        store = dict(state.get(key) or {})
    except Exception:
        return
    store[(record.get("ticker"), record.get("source"))] = record
    state[key] = store


def read_record(state, ticker, source, *, account_scope=None, key="_decision_records"):
    """Return the stored record only when its account scope matches (None when absent or out of scope)."""
    try:
        record = (state.get(key) or {}).get((str(ticker or "").upper(), source))
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    if account_scope is not None and record.get("as_of", {}).get("account_scope") != account_scope:
        return None
    return record


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
