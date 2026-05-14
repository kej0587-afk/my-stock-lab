"""Financial-score helper functions for Stock Lab.

This module keeps fallback scoring logic small and testable.  The main app
still owns data fetching and persistence, but score estimation and source
labelling should not depend on Streamlit state.
"""

from __future__ import annotations

import math
from typing import Any


def optional_float(value: Any) -> float | None:
    """Return a finite float, or None when a field is missing/unusable."""
    try:
        if value is None:
            return None
        text = str(value).strip()
        if text in {"", "-", "None", "nan", "NaN"}:
            return None
        number = float(text.replace(",", "").replace("%", ""))
        if not math.isfinite(number):
            return None
        return number
    except Exception:
        return None


def unwrap_snapshot_data(snapshot: dict | None) -> dict:
    """Accept either a raw data dict or a wrapper with a `data` key."""
    if not isinstance(snapshot, dict):
        return {}
    data = snapshot.get("data")
    if isinstance(data, dict):
        return data
    return snapshot


def estimate_kr_fin_score_from_naver_snapshot(
    snapshot: dict | None,
    default_score: int = 3,
) -> tuple[int, str]:
    """Estimate a capped KR stock score from Naver/KRX-style summary fields.

    This is intentionally capped at 3 because it is a fallback, not a full
    financial-statement score.  When no usable fields exist, keep the app's
    neutral default rather than fabricating a low or high score.
    """
    data = unwrap_snapshot_data(snapshot)

    per = optional_float(data.get("trailingPE"))
    roe = optional_float(data.get("returnOnEquity"))
    op_margin = optional_float(data.get("operatingMargins"))
    debt_ratio = optional_float(data.get("debtToEquity"))

    hints: list[str] = []
    score = 1

    if per is not None:
        if 0 < per <= 15:
            score += 1
            hints.append(f"PER {per:.1f} low")
        elif 0 < per <= 25:
            hints.append(f"PER {per:.1f} normal")
        elif per > 40:
            hints.append(f"PER {per:.1f} high")

    if roe is not None:
        roe_pct = roe * 100 if abs(roe) <= 1 else roe
        if roe_pct >= 15:
            score += 1
            hints.append(f"ROE {roe_pct:.1f}% strong")
        elif roe_pct >= 8:
            hints.append(f"ROE {roe_pct:.1f}% ok")
        elif roe_pct < 0:
            score -= 1
            hints.append(f"ROE {roe_pct:.1f}% negative")

    if op_margin is not None:
        op_margin_pct = op_margin * 100 if abs(op_margin) <= 1 else op_margin
        if op_margin_pct >= 10:
            score += 1
            hints.append(f"operating margin {op_margin_pct:.1f}%")
        elif op_margin_pct < 0:
            score -= 1
            hints.append("operating margin negative")

    if debt_ratio is not None and debt_ratio > 200:
        score -= 1
        hints.append(f"debt/equity {debt_ratio:.0f}% high")

    if not hints:
        return int(default_score), "Naver fallback: no usable summary indicators; kept neutral default"

    score = max(1, min(3, score))
    return int(score), "Naver fallback: " + ", ".join(hints)


def resolve_fin_score_source(fin_auto: dict | None, fin_notes: dict | None) -> str:
    """Prefer the actual scoring source stored in notes over fetch metadata."""
    if isinstance(fin_notes, dict):
        source = str(fin_notes.get("source") or "").strip()
        if source:
            return source
    if isinstance(fin_auto, dict):
        return str(fin_auto.get("source") or "unknown")
    return "unknown"
