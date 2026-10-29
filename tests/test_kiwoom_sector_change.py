"""Only sector display percentages may use a corroborated scale."""

from copy import deepcopy

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.kiwoom_market import normalize_market_rows


def normalize(**fields):
    item = dict(inds_cd="001", inds_nm="KOSPI", frgnr_netprps="-301",
                orgn_netprps="+20.5", ind_netprps="0", **fields)
    original = deepcopy(item)
    result = normalize_market_rows({"inds_netprps": [item]}, "sector_kospi")
    assert item == original and result["ok"]
    row = result["rows"][0]
    assert row["외국인 순매수(억원)"] == -301
    assert row["기관 순매수(억원)"] == 20.5
    assert row["개인 순매수(억원)"] == 0
    return row


@pytest.mark.parametrize("fields,expected", [
    ({"cur_prc": "+265381", "pred_pre": "+9030", "pre_smbol": "2", "flu_rt": "352"}, 3.52),
    ({"cur_prc": "+265381", "pred_pre": "+9030", "flu_rt": "3.52"}, 3.52),
    ({"cur_prc": "-9699", "pred_pre": "-301", "pre_smbol": "5", "flu_rt": "-301"}, -3.01),
    ({"cur_prc": "9699", "pred_pre": "-301", "flu_rt": "-3.01"}, -3.01),
    ({"cur_prc": "10300", "pred_pre": "+300", "flu_rt": "3"}, 3),
    ({"cur_prc": "10000", "pred_pre": "0", "pre_smbol": "3", "flu_rt": "0"}, 0),
    ({"flu_rt": "+3.52"}, 3.52),
    ({"flu_rt": "-3.01"}, -3.01),
    ({"flu_rt": "0.00"}, 0),
])
def test_decimal_or_unique_corroborated_rate_preserves_flow_amounts(fields, expected):
    row = normalize(**fields)
    assert row["등락률(%)"] == expected
    assert "등락률 확인" in row["구분"] and fields["flu_rt"] in row["구분"]


@pytest.mark.parametrize("fields", [
    {"flu_rt": "-301"},
    {"flu_rt": "352", "cur_prc": "265381"},
    {"flu_rt": "352", "cur_prc": "265381", "pred_pre": "9030"},
    {"flu_rt": "352", "cur_prc": "265381", "pred_pre": "+9030", "pre_smbol": "5"},
    {"flu_rt": "-352", "cur_prc": "265381", "pred_pre": "+9030"},
    {"flu_rt": "352", "cur_prc": "10200", "pred_pre": "+200"},
    {"flu_rt": "3.52", "cur_prc": "10200", "pred_pre": "+200"},
    {"flu_rt": "352", "cur_prc": "0", "pred_pre": "+9030"},
    {"flu_rt": "352", "cur_prc": "100", "pred_pre": "+100"},
    {"flu_rt": "0.01", "cur_prc": "100005", "pred_pre": "+5"},
    {"flu_rt": "3.51", "cur_prc": "265381", "pred_pre": "+9030"},
    {"flu_rt": "-301.00"}, {"flu_rt": "NaN"}, {"flu_rt": "Inf"},
    {"flu_rt": "3e2"}, {"flu_rt": None},
])
def test_missing_inconsistent_ambiguous_or_unsigned_basis_is_not_guessed(fields):
    row = normalize(**fields)
    assert row["등락률(%)"] is None
    assert "등락률 확인" in row["구분"] and "원값" in row["구분"]


def test_non_sector_rate_is_not_scaled_or_reinterpreted():
    result = normalize_market_rows({"trde_prica_upper": [
        {"stk_cd": "005930", "stk_nm": "Samsung", "flu_rt": "352"}]}, "turnover")
    assert result["rows"][0]["등락률(%)"] == 352


def test_mock_panel_shows_missing_rate_and_readable_original_reason():
    app = AppTest.from_string('''
import streamlit as st
from stock_lab_core.kiwoom_market import normalize_market_rows
from stock_lab_core.market_evidence_panel import render_snapshot
snapshot = normalize_market_rows({"inds_netprps": [
    {"inds_cd": "001", "inds_nm": "KOSPI", "flu_rt": "-301", "frgnr_netprps": "-301"},
    {"inds_cd": "002", "inds_nm": "Large", "flu_rt": "352", "cur_prc": "+265381", "pred_pre": "+9030"}
]}, "sector_kospi")
render_snapshot(st, dict(snapshot, is_mock=True))
''').run(timeout=10)
    assert not app.exception
    frame = app.dataframe[0].value
    assert pd.isna(frame.iloc[0]["등락률(%)"])
    assert "등락률 확인" in frame.iloc[0]["구분"] and "-301" in frame.iloc[0]["구분"]
    assert frame.iloc[0]["외국인 순매수(억원)"] == -301
    assert frame.iloc[1]["등락률(%)"] == 3.52
    assert any("모의환경" in caption.value for caption in app.caption)
