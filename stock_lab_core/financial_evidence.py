"""Offline audit of explicitly equivalent financial judgements.

This module does not select a trade grade or change the app's scoring. Its
normalization matches nominal score capacities, not historical distributions
or the calibration of existing grade thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import fsum, isfinite
from numbers import Real


# Only these quarterly criteria are equivalent in build_fin_judgements.
# Annual debt/capital, margins, profit quality and risk flags stay independent.
EXACT_EQUIVALENT_FAMILIES = (
    ("quarter_revenue_momentum", "quarter_revenue_increase"),
    ("quarter_profit_momentum", "quarter_profit_increase"),
    ("quarter_cashflow_quality", "quarter_ocf_positive", "quarter_cash_quality"),
    ("quarter_margin_good", "quarter_margin_quality"),
    ("quarter_debt_stability", "quarter_debt_ratio_quality"),
)
_FAMILY_BY_KEY = {key: family[0] for family in EXACT_EQUIVALENT_FAMILIES for key in family}
_DANGER = "\U0001f6a8"
_POSITIVE = ("\U0001f48e", "\u2705")
_NEGATIVE = ("\u26a0", "\u274c")
_NEUTRAL = "\u2796"


def _legacy_score(value: object) -> int:
    """Mirror app.getsymbol_score, including its icon precedence."""
    text = str(value)
    if _DANGER in text:
        return 0
    if any(icon in text for icon in _POSITIVE):
        return 1
    if "\u26a0\ufe0f" in text or "\u274c" in text:
        return -1
    return 0


def _evidence_score(value: object) -> tuple[int, str]:
    if value is None or isinstance(value, str) and not value.strip():
        return 0, "missing"
    if isinstance(value, Real) and not isinstance(value, bool):
        if not isfinite(value):
            return 0, "missing"
        if value == 0:
            return 0, "neutral"
    if not isinstance(value, str):
        return 0, "unknown"

    signals = []
    if _DANGER in value:
        signals.append((0, "danger"))
    if any(icon in value for icon in _POSITIVE):
        signals.append((1, "positive"))
    if any(icon in value for icon in _NEGATIVE):
        signals.append((-1, "negative"))
    if _NEUTRAL in value:
        signals.append((0, "neutral"))
    if not signals:
        return 0, "unknown"
    score = min(item[0] for item in signals)
    if len({item[0] for item in signals}) > 1:
        return score, "conflict"
    return signals[0]


def _audit_row(family: str, aliases: list[str], weights: dict, evidence: dict) -> dict:
    entries = [
        {"key": key, "weight": weights[key], "score": evidence[key][0],
         "status": evidence[key][1]}
        for key in aliases
    ]
    observed = [entry for entry in entries if entry["status"] != "missing"]
    weight = max(weights[key] for key in aliases)
    if not observed:
        selected_key, score, status = None, 0, "missing"
    else:
        selected = min(observed, key=lambda item: (item["score"], -item["weight"], item["key"]))
        selected_key, score = selected["key"], selected["score"]
        known_scores = {item["score"] for item in observed if item["status"] != "unknown"}
        if any(item["status"] == "conflict" for item in observed) or len(known_scores) > 1:
            status = "conflict"
        elif any(item["status"] == "unknown" for item in observed):
            status = "unknown"
        elif any(item["status"] == "danger" for item in observed):
            status = "danger"
        else:
            status = selected["status"]
    return {
        "family": family,
        "aliases": aliases,
        "selected_key": selected_key,
        "weight": weight,
        "score": score,
        "points": score * weight,
        "status": status,
        "alias_evidence": entries,
    }


def audit_financial_evidence(judgements: Mapping, tiers: Mapping) -> dict:
    """Return a deterministic, pure audit without importing app or Streamlit.

    ``tiers`` maps exact app keys to finite, nonnegative numeric weights. Only
    these keys contribute points/capacities; unscored keys are listed. Values
    in ``judgements`` are the app's icon-bearing strings. None, blanks and
    nonfinite numbers are missing; numeric zero is known neutral. Other
    unrecognized payloads are unknown and never earn positive audit points.
    Symbols identify outcomes; titles/bodies never identify alias families.

    A family's weight is the maximum CONFIGURED alias weight, even when its
    strongest alias is missing. Absent aliases contribute no observations;
    duplicating an observed outcome cannot change the family's unique net.
    A known neutral conflicting with a pass, or any unknown observation, caps
    the family at zero. An observed failure is retained at the family weight.
    Conflicts and unknowns remain explicit instead of selecting a passing alias.

    Finance's neutral quarter_debt_ratio_quality is excluded from equivalence
    when quarter_debt_stability is directional: the latter measures capital
    and profit in that branch. Both remain separate rows. No title parsing or
    inference that other finance criteria are equivalent is performed.

    Capacities are nominal sums over tiers, including missing/neutral rows;
    missing coverage never reduces a denominator. Normalization is
    unique_net * max_legacy_capacity / max_dedup_capacity (zero if capacity is
    zero). Changing the tier schema can change this scale despite an invariant
    unique_net. Neither normalization nor deduplication calibrates live grades.
    Danger flags retain their original keys/count, including unscored flags.
    """
    if not isinstance(judgements, Mapping) or not isinstance(tiers, Mapping):
        raise TypeError("judgements and tiers must be mappings")
    if any(not isinstance(key, str) for key in judgements) or any(
        not isinstance(key, str) for key in tiers
    ):
        raise TypeError("judgement and tier keys must be strings")

    weights = {}
    for key in sorted(tiers):
        weight = tiers[key]
        if isinstance(weight, bool) or not isinstance(weight, Real):
            raise TypeError(f"weight for {key} must be numeric")
        if not isfinite(weight) or weight < 0:
            raise ValueError(f"weight for {key} must be finite and nonnegative")
        weights[key] = float(weight)

    evidence = {key: _evidence_score(judgements.get(key)) for key in weights}
    # Finance rewrites debt stability but makes debt-ratio quality neutral.
    split_debt = (
        evidence.get("quarter_debt_ratio_quality", (0, "missing"))[1] == "neutral"
        and evidence.get("quarter_debt_stability", (0, "missing"))[1] in {"positive", "negative"}
    )
    groups = {}
    for key in weights:
        family = _FAMILY_BY_KEY.get(key, key)
        if split_debt and family == "quarter_debt_stability":
            family = key
        groups.setdefault(family, []).append(key)
    rows = [_audit_row(family, groups[family], weights, evidence) for family in sorted(groups)]

    raw_net = fsum(weights[key] * _legacy_score(judgements.get(key, "")) for key in weights)
    unique_net = fsum(row["points"] for row in rows)
    max_legacy = fsum(weights.values())
    max_dedup = fsum(row["weight"] for row in rows)
    scale = max_legacy / max_dedup if max_dedup else None
    danger_keys = sorted(key for key in judgements if _DANGER in str(judgements[key]))
    return {
        "raw_net": raw_net,
        "unique_net": unique_net,
        "max_legacy_capacity": max_legacy,
        "max_dedup_capacity": max_dedup,
        "normalized_legacy_equivalent_net": unique_net * scale if scale is not None else 0.0,
        "scale_factor": scale,
        "evidence_rows": rows,
        "danger_keys": danger_keys,
        "danger_count": len(danger_keys),
        "unscored_keys": sorted(set(judgements) - set(weights)),
        "calibrated": False,
        "calibration_note": (
            "Capacity rescaling only; missing/neutral evidence retains nominal capacity. "
            "Tier-schema changes can change the scale. Existing grade thresholds and "
            "historical outcome distributions require separate calibration. No grade is assigned."
        ),
    }
