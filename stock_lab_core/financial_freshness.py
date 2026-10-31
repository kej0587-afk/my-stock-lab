"""Financial input identity and observation dates, independent from trade scores."""

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json

import pandas as pd


def financial_input_signature(frame):
    """Invalidate derived views when saved evidence changes, even at equal scores."""
    columns = ["ticker", "auto_score", "manual_score", "final_score", "source", "notes_json"]
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        rows = []
    else:
        selected = frame.reindex(columns=columns).copy()
        selected["ticker"] = selected["ticker"].fillna("").astype(str).str.strip().str.upper()
        rows = selected.astype(object).where(pd.notna(selected), None).to_dict("records")
        rows.sort(key=lambda row: (row["ticker"], json.dumps(row, sort_keys=True, default=str)))
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def financial_basis(fin_meta, *, is_etf=False, now=None):
    """Expose stored periods; never infer the last announcement from price data."""
    if is_etf:
        return {"재무자료상태": "기업재무 해당없음", "재무자료기간": "-", "재무계산시각": "-"}
    meta = fin_meta if isinstance(fin_meta, Mapping) else {}
    notes = meta.get("notes") if isinstance(meta.get("notes"), Mapping) else {}
    metrics = meta.get("metrics") if isinstance(meta.get("metrics"), Mapping) else notes.get("metrics", {})
    metrics = metrics if isinstance(metrics, Mapping) else {}
    periods = []
    def period_label(row):
        text = str(row.get("date") or "")
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            year = str(row.get("fiscal_year") or "")
            quarter = row.get("fiscal_quarter")
            if year.isdigit() and len(year) == 4:
                return f"FY{year}" + (f" Q{quarter}" if quarter in (1, 2, 3, 4) and row.get("period") != "annual" else "")
            return "보고기간 미확인"
    for label, latest_key, records_key in (("연간", "annual_latest", "annual_records"),
                                           ("분기", "quarter_latest", "quarter_records")):
        record = metrics.get(latest_key)
        if not isinstance(record, Mapping) or not record:
            records = metrics.get(records_key)
            dates = [period_label(row) for row in records or [] if isinstance(row, Mapping)]
            day = max(dates, default="")
        else:
            day = period_label(record)
        if day:
            periods.append(f"{label} {day}")
    computed = str(notes.get("computed_at") or meta.get("computed_at") or "")
    status = "저장 자료 · 최신 발표 반영 여부 미확인"
    if meta.get("source") == "not_calculated" or meta.get("auto_score") is None:
        status = "자동 미계산 · 수동/임시 점수" if meta.get("manual_score") is not None else "자동 미계산 · 임시 점수"
    elif notes.get("ok") is False:
        status = "조회 실패/간이 자료 · 정식 재무와 구분"
    if computed:
        try:
            stamp = datetime.fromisoformat(computed.replace("Z", "+00:00"))
            current = now or datetime.now(timezone.utc)
            if stamp.tzinfo is None or current.tzinfo is None:
                raise ValueError("Timezone required")
            age = (current - stamp).total_seconds()
            if age >= 21600:
                status += " · 계산 후 6시간 경과"
            elif age < 0:
                status += " · 계산 시각 확인 필요"
        except (TypeError, ValueError, OverflowError):
            computed = ""
    return {"재무자료상태": status, "재무자료기간": " / ".join(periods) or "보고기간 미저장",
            "재무계산시각": computed or "계산 시각 미저장"}
