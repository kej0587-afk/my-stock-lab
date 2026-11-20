import pandas as pd
import pytest

from stock_lab_core.macro_monitor import CATALOG, GROUPS, METRICS, observation, parse_fred_csv


def test_regular_korean_price_cites_its_actual_provider():
    item = CATALOG["005930.KS"]
    assert item.provider == "Npay"
    assert item.url.startswith("https://stock.naver.com/")
    row, _ = observation(item, pd.Series([100, 110], index=pd.to_datetime(["2026-11-18", "2026-11-19"])), pd.Timestamp("2026-11-20"))
    assert row["출처"] == item.url
    assert "+10.00%" in row["직전 관측 대비"]


def test_cboe_ratio_requires_explicit_observation_date_and_total_population():
    from stock_lab_core.macro_monitor import parse_cboe_ratio
    body = '<input placeholder="yyyy/mm/dd" value="18 November 2026"><table><tr><td>EQUITY PUT/CALL RATIO</td><td>0.72</td></tr><tr><td>TOTAL PUT/CALL RATIO</td><td>1.05</td></tr></table>'
    series = parse_cboe_ratio(body)
    assert series.index[0] == pd.Timestamp("2026-11-18")
    assert series.iloc[0] == 1.05
    assert parse_cboe_ratio(body.replace('TOTAL PUT/CALL RATIO', 'INDEX PUT/CALL RATIO')).empty
    assert parse_cboe_ratio(body.replace('placeholder="yyyy/mm/dd"', '')).empty


def test_public_price_reports_percentage_change_separately_from_level():
    series = pd.Series([100.0, 102.0], index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    row, _ = observation(CATALOG["^GSPC"], series, pd.Timestamp("2026-11-20"))
    assert row["직전 관측 대비"] == "+2.00 pt (+2.00%)"


def test_delayed_price_is_not_labelled_current_and_special_kr_close_is_respected():
    from stock_lab_core.macro_monitor import completed_price_history
    frame = pd.DataFrame({"Close": [100., 102.]}, index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    series = completed_price_history(frame, "KR", pd.Timestamp("2026-11-19T16:00+09:00"))
    assert series.index[-1] == pd.Timestamp("2026-11-18")
    late = completed_price_history(frame.iloc[:1], "KR", pd.Timestamp("2026-11-20T09:00+09:00"))
    row, _ = observation(CATALOG["^KS11"], late, pd.Timestamp("2026-11-20T09:00+09:00"))
    assert row["상태"] == "완료 일봉 지연 · 최근 완료일 2026-11-19"


def test_catalog_covers_reference_observations_without_changing_gates():
    required = {"^GSPC", "^IXIC", "^KS11", "^KQ11", "005930.KS", "GC=F", "BTC-USD", "KRW=X",
                "EWZ", "INDA", "VNM", "EWJ", "FNG", "VIXCLS", "BAMLH0A0HYM2", "STLFSI4", "T10Y2Y",
                "DGS10", "DX-Y.NYB", "JPY=X", "CL=F", "HG=F", "M2SL", "UNRATE", "ICSA", "WALCL", "WRESBAL", "RRPONTSYD", "WTREGEN",
                "^SKEW", "^VVIX", "^OVX", "PCR"}
    assert required == set(CATALOG)
    assert len(CATALOG) == len(METRICS)
    assert len(GROUPS) == 7


@pytest.mark.parametrize("symbol,raw,expected", [("WALCL",6758867,6758.867), ("WRESBAL",2960603,2960.603),
                                               ("WTREGEN",914370,914.370), ("ICSA",203000,203), ("M2SL",22000,22000)])
def test_units_are_converted_once(symbol, raw, expected):
    metric = CATALOG[symbol]
    series = parse_fred_csv(f"observation_date,{symbol}\n2026-11-11,{raw}\n2026-11-18,.\n", metric)
    assert series.iloc[0] == pytest.approx(expected)
    assert pd.isna(series.iloc[1])


def test_liquidity_change_has_same_unit_as_level():
    item = CATALOG["WALCL"]
    series = parse_fred_csv("DATE,WALCL\n2026-11-11,6758867\n2026-11-18,6741452\n", item)
    row, _ = observation(item, series, pd.Timestamp("2026-11-20T09:00+09:00"))
    assert row["값"] == "6,741.45 십억 USD"
    assert row["직전 관측 대비"].startswith("-17.4")
    assert row["직전 관측 대비"].endswith(" 십억 USD")


def test_missing_not_zero_and_future_excluded():
    item = CATALOG["DGS10"]
    row, _ = observation(item, pd.Series([5.1], index=pd.to_datetime(["2026-11-21"])), pd.Timestamp("2026-11-20"))
    assert row["값"] == "미연결"
    row, _ = observation(item, pd.Series([0.0], index=pd.to_datetime(["2026-11-19"])), pd.Timestamp("2026-11-20"))
    assert row["값"] == "0.00 %"


def test_rates_change_in_percentage_points_and_no_input_mutation():
    series = pd.Series([4.9, 5.1], index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    before = series.copy(deep=True)
    row, _ = observation(CATALOG["DGS10"], series, pd.Timestamp("2026-11-20"))
    assert row["직전 관측 대비"] == "+0.20 %p"
    pd.testing.assert_series_equal(before, series)


def test_observatory_ui_changes_view_without_mutating_gate_or_fetching():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
import pandas as pd
from stock_lab_core.macro_monitor import METRICS, render_macro_monitor
st.session_state.setdefault("gate", {"score": 9, "decision": "blocked"})
data = {m.symbol: (pd.Series([10.0, 11.0], index=pd.to_datetime(["2026-11-18", "2026-11-19"])), "fixture") for m in METRICS}
render_macro_monitor(st, data=data, now=pd.Timestamp("2026-11-20T10:00+09:00"))
''').run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 7
    app.radio(key="macro_monitor_group").set_value("연준·재무부").run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 4
    assert app.session_state["gate"] == {"score": 9, "decision": "blocked"}
