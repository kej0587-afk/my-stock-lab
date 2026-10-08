import math

import pandas as pd
import pytest

from stock_lab_core.money_flow import get_return_by_days, get_return_by_days_offset


def test_return_by_days_uses_full_interval_not_one_day_short():
    close = pd.Series([100, 101, 102, 103, 104, 110])

    assert get_return_by_days(close, 5) == pytest.approx(0.10)


def test_return_by_days_requires_enough_history():
    close = pd.Series([100, 110, 120])

    assert math.isnan(get_return_by_days(close, 5))


def test_return_by_days_offset_uses_exact_prior_window():
    close = pd.Series([100, 105, 110, 115, 120, 126])

    assert get_return_by_days_offset(close, 2, offset=2) == pytest.approx((115 / 105) - 1)
    assert math.isnan(get_return_by_days_offset(close, 3, offset=3))
