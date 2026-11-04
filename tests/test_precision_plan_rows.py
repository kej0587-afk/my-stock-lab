"""Exact output comparison against the pre-extraction rendering block."""

import runpy
from pathlib import Path

import pytest

from stock_lab_core.formatters import format_currency
from stock_lab_core.precision_plan_rows import build_precision_exit_rows


@pytest.mark.parametrize("ticker", ["GOOGL", "379810.KS", "418660.KS", "SOXL", "RAM", "CIBR"])
@pytest.mark.parametrize("has_pos", [True, False])
@pytest.mark.parametrize("projection", [True, False])
def test_exit_rows_equal_pre_refactor(app_module, ticker, has_pos, projection):
    old = runpy.run_path(str(Path(__file__).parent / "fixtures/precision_exit_rows_before.py"))["legacy_exit_rows"]
    inputs = dict(ticker=ticker, has_pos=has_pos, cur=100, stop=90, target=120,
                  tp1=105, tp2=110, tp3=120, target_is_projection=projection,
                  format_currency=format_currency)
    condition = app_module.format_precision_take_profit_condition
    expected = old(**inputs, format_precision_take_profit_condition=condition)
    actual = build_precision_exit_rows(**inputs, take_profit_condition=condition)
    assert actual == expected
