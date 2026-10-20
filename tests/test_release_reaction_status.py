from datetime import datetime, timezone

from stock_lab_core.report_prices import release_day_reaction


def test_published_value_with_unknown_release_date_is_not_pending():
    text = release_day_reaction({"indicator": "KR_CPI", "actual": 2.9, "status": "released"}, {}, datetime.now(timezone.utc))
    assert "발표치는 수집됨" in text and "발표일 미확인" in text
    assert "미발표" not in text and "발표 대기" not in text


def test_http_failure_does_not_mean_economic_release_has_not_occurred():
    text = release_day_reaction({"indicator": "US_CPI", "actual": None, "status": "unavailable",
                                "missing_reason": "http_403"}, {}, datetime.now(timezone.utc))
    assert "수집 실패" in text and "발표 여부 미확인" in text
    assert "미발표" not in text


def test_explicit_future_release_is_pending():
    text = release_day_reaction({"actual": None, "status": "pending", "release_at": "2026-11-10"}, {}, datetime.now(timezone.utc))
    assert text.startswith("발표 대기") and "수집 실패" not in text
