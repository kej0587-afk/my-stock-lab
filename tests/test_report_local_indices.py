from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from stock_lab_core.report_dashboard import local_index_observations, local_index_table_lines

KST = ZoneInfo("Asia/Seoul")


def frame(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(pd.to_datetime(dates)))


def test_today_bar_waits_for_local_close_plus_30_minutes():
    frames = {"^N225": frame(["2026-11-20", "2026-11-24"], [56436.65, 58716.83])}
    before = local_index_observations(frames, datetime(2026, 11, 24, 15, 50, tzinfo=KST))["^N225"]
    after = local_index_observations(frames, datetime(2026, 11, 24, 16, 5, tzinfo=KST))["^N225"]
    assert before["date"] == "2026-11-20" and before["previous_price"] is None
    assert after["date"] == "2026-11-24" and after["previous_date"] == "2026-11-20"
    assert round(after["return"], 6) == round(58716.83 / 56436.65 - 1, 6)


def test_missing_and_vietnam_stay_unconnected_and_rows_keep_local_currency():
    frames = {"^BVSP": frame(["2026-11-19", "2026-11-23"], [166376.0, 164796.0])}
    context = {"local_indices": local_index_observations(frames, datetime(2026, 11, 24, 16, tzinfo=KST))}
    assert context["local_indices"]["^N225"] == {} and context["local_indices"]["^NSEI"] == {}
    table = "\n".join(local_index_table_lines(context))
    assert "보베스파(^BVSP) · EWZ 비교 | 164,796.00 BRL" in table
    assert "2026-11-19 → 2026-11-23" in table
    assert "닛케이225(^N225) · EWJ 비교 | 미연결" in table
    assert "베트남 VN-Index · 미연결" in table
