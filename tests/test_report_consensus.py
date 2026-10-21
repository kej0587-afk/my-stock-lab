from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

import pytest

from stock_lab_core.report_consensus import attach_economic_consensus

NOW = datetime.fromisoformat("2026-10-21T20:00:00+09:00")


def release(indicator="US_CPI", **kwargs):
    return dict(indicator=indicator, period="2026-09", basis="MoM", unit="%", actual=.6, forecast=None,
                release_at="2026-10-14T08:30:00-04:00", release_precision="datetime",
                missing_reason="forecast_not_supplied", **kwargs)


def test_verified_september_survey_links_exact_period_release_units_and_provenance():
    rows = [release(), dict(release(), basis="YoY", actual=3.7),
            dict(release("US_PPI"), release_at="2026-10-15", actual=1.3),
            dict(release("US_RETAIL_SALES"), release_at=None, actual=.8, missing_reason="release_date_unavailable;forecast_not_supplied")]
    before = deepcopy(rows)
    result, status = attach_economic_consensus(rows, NOW)
    assert [r["forecast"] for r in result] == [.6, 3.6, .5, .3]
    assert [r["actual_minus_forecast"] for r in result] == [0, .1, .8, .5]
    assert all(r["forecast_verified_at"] == "2026-10-21" and "Reuters" in r["forecast_source"] for r in result)
    assert result[-1]["release_at"] == "2026-10-15" and result[-1]["release_precision"] == "date"
    assert not result[-1]["missing_reason"]
    assert status["verified_survey_count"] == 4 and status["attached_count"] == 4
    assert rows == before


@pytest.mark.parametrize("changes", [dict(period="2026-10"), dict(basis="YoY", actual=.6),
                                     dict(unit="index"), dict(release_at="2026-10-15"),
                                     dict(actual=.7), dict(release_time_confirmed=False)])
def test_forecast_cannot_bleed_between_months_definitions_dates_or_revised_actuals(changes):
    result, _ = attach_economic_consensus([dict(release(), **changes)], NOW)
    assert result[0]["forecast"] is None


def test_existing_user_forecast_is_preserved_and_future_verification_not_backdated():
    rows = [dict(release(), forecast=.55, forecast_source="User supplied survey")]
    result, _ = attach_economic_consensus(rows, NOW)
    assert result[0]["forecast"] == .55 and result[0]["forecast_source"] == "User supplied survey"
    result, _ = attach_economic_consensus([release()], datetime.fromisoformat("2026-10-20T20:00:00+09:00"))
    assert result[0]["forecast"] is None


def test_exact_api_event_is_preferred_to_snapshot_without_modifying_official_actual():
    item = dict(release(), forecast=.58, forecast_unit="%", forecast_basis="MoM", forecast_source="Provider survey", forecast_source_url="https://example.com/source")
    with patch("stock_lab_core.report_consensus.load_economic_consensus", return_value={"events": [item], "diagnostics": {}}):
        result, _ = attach_economic_consensus([release()], NOW, api_key="test-placeholder")
    assert result[0]["forecast"] == .58 and result[0]["actual"] == .6
