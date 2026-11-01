"""Pure evidence handling; callers group by market/sector and supply identity keys."""

import math

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


NUMERIC_FIELDS = ("score", "short", "r1d", "r5d", "mid", "long", "price_level")
_SOURCE_ORDER = {"ETF": 0, "테마": 1, "실행": 2}
_ACTION_RANK = {"정밀관측": 5, "눌림대기": 4, "추격금지": 3, "관심등록": 2, "관망/제외": 1}


def _text(value):
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"", "-", "nan", "none", "<na>"} else text


def _number(value):
    try:
        number = float(value) if not isinstance(value, bool) else math.nan
        return number if math.isfinite(number) else -math.inf
    except (TypeError, ValueError, OverflowError):
        return -math.inf


def _stable(item):
    return tuple(sorted((str(key), repr(value)) for key, value in item.items()))


def _execution_actions(item):
    actions = {_text(value) for value in item.get("execution_actions", ())}
    if item.get("source") == "실행":
        actions.add(_text(item.get("action")))
    return sorted(actions)


def _source_order(item):
    valid = sum(math.isfinite(_number(item.get(field))) for field in NUMERIC_FIELDS)
    return _SOURCE_ORDER.get(item.get("source"), 3), -valid, _stable(item)


def _representative_order(item):
    priority = min((_ACTION_RANK.get(action, 1) for action in _execution_actions(item)), default=0)
    return (-priority, -_number(item.get("short")),
            -_number(item.get("score")), _text(item.get("representative")).casefold(),
            _stable(item))


def deduplicate_evidence(items):
    """One row per key: ETF, then theme, then command supplies numerical evidence.

    Missing primary values stay missing. Commands attach representatives and all
    distinct finalized actions; raw observation actions remain separate. Missing
    identity keys are errors rather than silently merged anonymous observations.
    """
    grouped = {}
    for item in items:
        key = item.get("observation_key")
        if key is None or key == "":
            raise ValueError("Each evidence item needs an observation_key")
        grouped.setdefault(key, []).append(item)
    result = []
    for key in sorted(grouped, key=repr):
        group = grouped[key]
        merged = dict(min(group, key=_source_order))
        merged["execution_actions"] = sorted({
            action for item in group for action in _execution_actions(item)
        })
        observations = {action for item in group
                        for action in item.get("observation_actions", ())}
        observations.update(_text(item.get("action")) for item in group
                            if item.get("source") != "실행")
        merged["observation_actions"] = sorted(action for action in observations if action)
        representatives = [item for item in group if _text(item.get("representative"))]
        if representatives:
            representative = min(representatives, key=_representative_order)
            merged["representative"] = representative["representative"]
            merged["is_etf_representative"] = bool(
                representative.get("is_etf_representative", False)
            )
        result.append(merged)
    return result


def select_card_action(items, normalize, rank):
    """Resolve each observation conservatively, then select the best final action.

    A command with an empty/unknown action remains conservative. Without commands,
    raw ETF/theme actions are available separately for observation-only display.
    """
    fallback = normalize("관망/제외")
    order = lambda action: (rank(action), action)
    resolved = []
    for item in deduplicate_evidence(items):
        actions = {normalize(action) or fallback for action in _execution_actions(item)}
        if actions:
            resolved.append(min(actions, key=order))
    return max(resolved, key=order) if resolved else fallback


def sorted_representatives(items):
    """Return unique labels by resolved canonical final action, then short/score.

    Explicit ETF representatives are excluded. Sorting uses numerical evidence,
    never formatted percentage text, with lexical ties for reproducible results.
    """
    rows = [item for item in deduplicate_evidence(items)
            if _text(item.get("representative"))
            and not item.get("is_etf_representative", False)]
    labels = []
    for item in sorted(rows, key=_representative_order):
        label = _text(item["representative"])
        if label not in labels:
            labels.append(label)
    return labels


def source_quality(items, fields=NUMERIC_FIELDS):
    """Count unique observations and finite values without filling missing axes."""
    rows = deduplicate_evidence(items)
    return {
        "evidence_count": len(rows),
        "execution_count": sum(bool(_execution_actions(item)) for item in rows),
        "observation_count": sum(item.get("source") in {"ETF", "테마"} for item in rows),
        "valid_counts": {field: sum(math.isfinite(_number(item.get(field))) for item in rows)
                         for field in fields},
    }
