"""Pure reference prices shared by queue summaries and precision plans.

No quote requests, allocation rules or execution gates belong in this module.
"""

import math

from stock_lab_core.formatters import clean_float
from stock_lab_core.report_build import register_loaded_source


def build_entry_price_plan(decision, *, wait_for_pullback=False):
    c = decision or {}
    cur, stop, target = (clean_float(c.get(key), 0.0)
                         for key in ("cur_p", "rr_stop", "rr_target"))
    if not (all(math.isfinite(value) for value in (cur, stop, target)) and 0 < stop < cur < target):
        return {"valid": False, "rr": math.nan, "supports": []}

    atr = clean_float(c.get("atr"), 0.0)
    risk = cur - stop
    rr = (target - cur) / risk
    candidates = [(label, clean_float(c.get(key), 0.0)) for label, key in (
        ("MA5", "ma5"), ("MA20", "ma20"), ("FVG 상단", "fvg_top"), ("FVG 하단", "fvg_bottom"))]
    if atr > 0 and math.isfinite(atr):
        candidates += [("0.5ATR", cur - atr * 0.5), ("1ATR", cur - atr)]
    candidates = sorted(((label, value) for label, value in candidates
                         if math.isfinite(value) and stop < value < cur), key=lambda item: item[1], reverse=True)
    supports = []
    min_gap = max(cur * 0.003, 1.0)
    for label, value in candidates:
        if all(abs(value - used) > min_gap for _, used in supports):
            supports.append((label, value))

    entry1 = supports[0] if wait_for_pullback and supports else ("현재가", cur)
    entry2 = (supports[1] if len(supports) >= 2 else supports[0] if supports
              else ("0.5ATR", max(stop + risk * 0.45, cur - risk * 0.25)))
    if len(supports) >= 3:
        entry3 = supports[2]
    else:
        last = stop + risk * 0.25
        if abs(last - entry2[1]) <= min_gap:
            last = max(stop + risk * 0.15, entry2[1] - risk * 0.25)
        entry3 = ("손절 전 마지막 방어선", last)

    if c.get("rr_target_is_projection") and atr > 0:
        exits = []
        for key, fallback in (("rr_tp1", cur + atr), ("rr_tp2", cur + atr * 2), ("rr_tp3", target)):
            value = clean_float(c.get(key), 0.0)
            exits.append(value if value > cur else fallback)
    else:
        exits = [min(target, entry1[1] + (entry1[1] - stop)), target, target]
    return {"valid": True, "rr": rr, "supports": supports,
            "entries": (entry1, entry2, entry3), "exits": tuple(exits)}


register_loaded_source(__name__, __file__)
