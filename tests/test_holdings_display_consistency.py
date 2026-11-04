"""Display fixes must not change holdings valuation or investment decisions."""

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.formatters import clean_float, is_kr_listed
from stock_lab_core.portfolio import apply_holdings_weight_columns
from stock_lab_core.holdings_display import breakeven_recovery_pct


@pytest.mark.parametrize("current,breakeven,expected", [(50, 100, 100), (80, 100, 25),
    (100, 100, 0), (125, 100, 0), (50, 100.15, 100.30), (50, 100.1, 100.20)])
def test_required_recovery(current, breakeven, expected):
    assert breakeven_recovery_pct(current, breakeven) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, np.nan, np.inf, -np.inf, 0, -1, "missing"])
def test_missing_prices_do_not_show_zero_recovery(value):
    assert np.isnan(breakeven_recovery_pct(value, 100))
    assert np.isnan(breakeven_recovery_pct(100, value))


def test_real_holdings_builder_changes_only_recovery_column():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8-sig")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "build_holdings_table")
    holdings = pd.DataFrame([dict(ticker=t, name=t, qty=q, avg_price=100., target_weight=20.,
                                  is_etf=False, asset_class="kr_stock" if t.endswith(".KS") else "us_stock", bucket="core")
                            for t, q in [("TEST", 10), ("TEST", 2), ("005930.KS", 3)]])
    namespace = dict(pd=pd, np=np, IS_PUBLIC_DEMO=True, st=SimpleNamespace(session_state={}),
                     clean_float=clean_float, is_kr_listed=is_kr_listed,
                     normalize_price_lookup_key=lambda t: t, infer_bucket=lambda t,b: b,
                     is_fin_score_exempt_asset=lambda *a: False,
                     get_public_demo_latest_price_map=lambda ts: {t: 50. for t in ts},
                     apply_holdings_weight_columns=apply_holdings_weight_columns)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<holdings>", "exec"), namespace)
    namespace["breakeven_recovery_pct"] = lambda current, breakeven: round((current / breakeven - 1) * 100, 2)
    before = namespace[node.name](holdings.copy(), 1000., 10., 1300.)
    namespace["breakeven_recovery_pct"] = breakeven_recovery_pct
    after = namespace[node.name](holdings.copy(), 1000., 10., 1300.)
    # All cash, valuation, P/L, weight and other returned values remain identical.
    pd.testing.assert_frame_equal(before.drop(columns="본전까지%"), after.drop(columns="본전까지%"))
    assert (before["본전까지%"] < 0).all()
    assert after.set_index("티커").loc["TEST", "본전까지%"] == pytest.approx(100.2)

