"""C-13 macro missing tracking (2026-11-26): record changes only, month outages, summary text."""
from datetime import datetime

from stock_lab_core import macro_status_log as m


def test_observed_status_and_needs_record():
    assert m.observed_status({"macro_data_status": "complete"}) == m.COMPLETE
    assert m.observed_status({"macro_data_status": "core_missing"}) == m.MISSING
    assert m.observed_status({"macro_data_status": "collection_failed"}) == m.MISSING
    assert m.observed_status({}) is None
    assert m.needs_record(None, m.MISSING) and not m.needs_record(None, m.COMPLETE)
    assert m.needs_record(m.MISSING, m.COMPLETE) and m.needs_record(m.COMPLETE, m.MISSING)
    assert not m.needs_record(m.MISSING, m.MISSING) and not m.needs_record(m.COMPLETE, m.COMPLETE)


def test_month_outages_start_end_components():
    rows = [
        {"status": "missing", "observed_at": "2026-11-03T00:00:00+00:00", "missing_components": "USD/KRW"},
        {"status": "missing", "observed_at": "2026-11-03T01:00:00+00:00", "missing_components": "VIX"},
        {"status": "complete", "observed_at": "2026-11-03T05:00:00+00:00", "missing_components": ""},
        {"status": "missing", "observed_at": "2026-11-20T00:00:00+00:00", "missing_components": "유가"},
    ]
    now = datetime(2026, 11, 21, 9, 0, tzinfo=m.KST)
    out = m.month_outages(rows, "2026-11", now=now)
    assert len(out) == 2
    assert out[0]["components"] == ["USD/KRW", "VIX"] and round(out[0]["hours"]) == 5
    assert out[1]["end"] is None
    assert m.month_outages(rows, "2026-10", now=now) == []


def test_summary_text_with_core_execution():
    now = datetime(2026, 11, 21, 9, 0, tzinfo=m.KST)
    rows = [{"status": "missing", "observed_at": "2026-11-20T00:00:00+00:00", "missing_components": "유가"}]
    text = m.outage_summary_text(m.month_outages(rows, "2026-11", now=now), {"QQQ": 0.0, "SPY": 100.0, "XLK": None})
    assert "결측 1회" in text and "진행 중" in text and "유가" in text
    assert "QQQ 집행 없음" in text and "SPY 집행 있음" in text and "XLK 미확인" in text
    assert m.outage_summary_text([], {}) == "이번 달 기록된 매크로 결측 없음"


class _Fail:
    def table(self, name):
        raise RuntimeError(f'relation "{name}" does not exist')


def test_table_missing_is_reported_not_raised():
    assert m.load_latest(_Fail(), owner_email="o") == (None, "table_missing")
    assert m.record(_Fail(), owner_email="o", status="missing", missing_components=("VIX",)) == "table_missing"
