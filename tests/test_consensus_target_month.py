from datetime import datetime, timezone

from stock_lab_core.economic_consensus import _event
from stock_lab_core.report_evidence import consensus_connection_line


def test_live_event_carries_its_target_month():
    event = _event(("US_PPI", "YoY", "%"), "2026-10", "2026-11-13", 6.6, "PPI YoY", None, "https://x")
    assert event["forecast_period"] == "2026-10"


def test_connection_line_names_each_rows_target_month_not_old_survey_month():
    status = {"attached_count": 1, "verified_survey_count": 0, "verified_survey_used": 0,
              "verified_survey_coverage": "2026-09 발표 당시 설문 · 사후 기사 검증(10/21)",
              "attached_rows": [{"indicator": "US_PPI", "period": "2026-10", "basis": "YoY",
                                 "forecast_period": "2026-10", "release_at": "2026-11-13T13:30:00Z",
                                 "forecast_source": "Trading Economics"}]}
    line = consensus_connection_line(status)
    assert "US_PPI 2026-10 YoY ← Trading Economics(대상월 2026-10 · 발표 2026-11-13)" in line
    assert "쓰지 않음" in line and line.index("2026-10") < line.index("2026-09")


def test_attach_never_moves_a_forecast_to_another_month():
    from stock_lab_core import report_consensus
    row = {"indicator": "US_PPI", "period": "2026-10", "basis": "YoY", "unit": "%", "actual": 6.5,
           "release_at": "2026-11-13T13:30:00Z", "release_precision": "date"}
    other = dict(row, period="2026-09", forecast=6.1, forecast_period="2026-09")
    orig = report_consensus.load_economic_consensus
    report_consensus.load_economic_consensus = lambda rows, **_: {"events": [other], "diagnostics": {}}
    try:
        rows, diag = report_consensus.attach_economic_consensus([row], datetime(2026, 11, 24, tzinfo=timezone.utc))
    finally:
        report_consensus.load_economic_consensus = orig
    assert rows[0].get("forecast") is None and diag["attached_count"] == 0
