"""A-5/A-6 (2026-11-25): macro data completeness, kept separate from any risk score.

Missing macro data is neither risk nor normal. If any core input is missing, the macro
risk is unknown (NaN). The decision is computed without macro effect and the execution
gate shows DATA_CHECK. The missing inputs are kept for the screen and the diagnostics.
No last good value is reused and no fallback number is created.
"""

from __future__ import annotations

import math

CORE_MACRO_KEYS = ("10Y 금리", "VIX", "환율", "유가")
DISPLAY_NAMES = {"10Y 금리": "미국 10년물 금리", "VIX": "VIX", "환율": "USD/KRW", "유가": "유가", "MOVE": "MOVE"}
COMPLETE, PARTIAL, FAILED = "complete", "core_missing", "collection_failed"


def _valid(info) -> bool:
    if not isinstance(info, dict):
        return False
    try:
        value = float(info.get("val"))
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0


def macro_data_status(results) -> dict:
    """Return macro_data_status, macro_missing_components (core) and move_status for one snapshot."""
    data = results if isinstance(results, dict) else {}
    missing = tuple(key for key in CORE_MACRO_KEYS if not _valid(data.get(key)))
    if not data:
        status = FAILED
    elif missing:
        status = PARTIAL
    else:
        status = COMPLETE
    return {
        "macro_data_status": status,
        "macro_missing_components": tuple(DISPLAY_NAMES[key] for key in missing),
        "move_status": "ok" if _valid(data.get("MOVE")) else "MOVE 미확인",
        "as_of": {key: str(info.get("as_of") or "미확인") for key, info in data.items() if isinstance(info, dict)},
    }


def macro_unknown_reason(missing_components=()) -> str:
    names = [str(name) for name in (missing_components or ()) if str(name).strip()]
    if not names:
        return "매크로 미확인"
    return "매크로 미확인 · " + ", ".join(names) + " 데이터 누락"


def macro_caption_text(final_macro_risk, status: dict | None) -> str:
    """Header text: never prints a number for a missing macro risk."""
    status = status if isinstance(status, dict) else {}
    try:
        risk = float(final_macro_risk)
    except (TypeError, ValueError):
        risk = math.nan
    if not math.isfinite(risk):
        if status.get("macro_data_status") == FAILED:
            return "매크로 미확인 · 수집 실패"
        return macro_unknown_reason(status.get("macro_missing_components"))
    text = f"{risk:.1f}pt"
    if status.get("move_status") and status.get("move_status") != "ok":
        text += " · MOVE 미확인"
    return text


from stock_lab_core.report_build import register_loaded_source  # noqa: E402

register_loaded_source(__name__, __file__)
