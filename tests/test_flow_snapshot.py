import pandas as pd
import pytest

from stock_lab_core.flow_snapshot import can_reuse_theme_snapshot, flow_source_date_rows, source_sessions


def frame(*rows):
    return pd.DataFrame(rows, columns=["Ticker", "기준일"])


@pytest.mark.parametrize("theme_day,allowed", [("2026-10-30", True), ("2026-10-29", False),
    ("2026-11-02", False), ("", False), (None, False)])
def test_new_etf_session_never_relabels_old_or_future_theme_as_fresh(theme_day, allowed):
    snapshot = {"theme_flow_df": frame(("NVDA", theme_day))}
    assert can_reuse_theme_snapshot(snapshot, frame(("SOXX", "2026-10-30"))) is allowed


def test_korean_and_us_dates_are_not_compared_to_each_other_or_crypto():
    flow = frame(("SOXX", "2026-10-29"), ("396500.KS", "2026-10-30"), ("BTC-USD", "2026-11-01"))
    snapshot = {"theme_flow_df": frame(("NVDA", "2026-10-29"), ("005930.KS", "2026-10-30"))}
    assert can_reuse_theme_snapshot(snapshot, flow)
    assert source_sessions(flow) == {"미국": "2026-10-29", "한국": "2026-10-30"}
    assert len(flow_source_date_rows({**snapshot, "flow_df": flow})) == 4


def test_no_dates_or_exchange_mapping_is_not_reuse_confirmation():
    assert not can_reuse_theme_snapshot({}, frame(("SOXX", "2026-10-30")))
    assert not can_reuse_theme_snapshot({"theme_flow_df": frame(("7203.T", "2026-10-30"))}, frame(("SOXX", "2026-10-30")))


def test_one_new_row_does_not_hide_old_scored_rows_or_missing_dates():
    flow = frame(("SOXX", "2026-10-30"))
    theme = frame(("NVDA", "2026-10-30"), ("MRNA", "2026-10-29"))
    assert not can_reuse_theme_snapshot({"theme_flow_df": theme}, flow)
    report = flow_source_date_rows({"theme_flow_df": theme})[0]
    assert report["이전일 자료"] == 1
    assert report["가격 기준일"] == "2026-10-29 ~ 2026-10-30"
    theme.loc[1, "기준일"] = None
    assert not can_reuse_theme_snapshot({"theme_flow_df": theme}, flow)
    theme["돈흐름점수"] = [20, None]
    assert can_reuse_theme_snapshot({"theme_flow_df": theme}, flow)  # Unscored failure is not a signal.
    assert flow_source_date_rows({"theme_flow_df": theme})[0]["기준일 미확인"] == 1
