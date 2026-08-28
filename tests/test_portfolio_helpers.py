import pandas as pd

from stock_lab_core.portfolio import get_holding_row_by_ticker


def test_holding_lookup_matches_us_suffix_variants():
    holdings = pd.DataFrame([
        {"티커": "FCX.US", "자산명": "프리포트 맥모란", "보유량": 2, "매입가": 78.5},
    ])

    row = get_holding_row_by_ticker(holdings, "FCX")

    assert row is not None
    assert row["매입가"] == 78.5


def test_holding_lookup_matches_prefixed_us_ticker():
    holdings = pd.DataFrame([
        {"티커": "NYSE:FCX", "자산명": "프리포트 맥모란", "보유량": 2, "매입가": 78.5},
    ])

    row = get_holding_row_by_ticker(holdings, "FCX")

    assert row is not None
    assert row["자산명"] == "프리포트 맥모란"
