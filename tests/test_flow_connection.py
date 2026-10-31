"""Ticker-level fallback reuses source data across all decision views."""

from copy import deepcopy
import json
import zipfile
from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import flow_connection as module
from stock_lab_core.data_freshness import input_freshness_fields
from stock_lab_core.decision_workflow import build_decision_workflow
from stock_lab_core.execution_gate import apply_execution_gate_columns


@pytest.fixture
def history():
    close = np.linspace(100, 125, 251)
    return pd.DataFrame({"Close": close, "High": close + 2, "Low": close - 2,
                         "Volume": np.arange(251) + 1000.0},
                        index=pd.bdate_range(end="2026-10-30", periods=251))


def _context(day="2026-10-30", **values):
    return {"돈흐름_Ticker": "GOOGL", "돈흐름_기준일": day, "돈흐름_거래량기준일": day,
            "돈흐름_판정": "관찰", "돈흐름_연결경로": module.SOURCE_PATH, **values}


def test_source_metrics_are_radar_formula_without_network(history, monkeypatch):
    from stock_lab_core import money_flow

    def unexpected(*args, **kwargs):
        pytest.fail("The ticker connection must not load another price/radar universe")

    monkeypatch.setattr(money_flow, "get_money_flow_ohlc", unexpected)
    monkeypatch.setattr(money_flow, "download_money_flow_prices", unexpected)
    monkeypatch.setattr(money_flow, "calculate_money_flow_df", unexpected)
    before = history.copy(deep=True)
    actual = module.build_price_flow_row(history, "GOOGL", "Alphabet")
    expected = money_flow._compute_ticker_metrics(history)
    for key, value in expected.items():
        assert actual[key] == value
    assert actual["연결경로"] == module.SOURCE_PATH
    assert actual["자료봉수"] == 251 and actual["연결상태"] == "연결"
    assert "테마내순위" not in actual and "점수_랭킹보조" not in actual
    pd.testing.assert_frame_equal(history, before)


@pytest.mark.parametrize("frame,reason", [
    (pd.DataFrame(), "가격 이력 없음"),
    (pd.DataFrame({"Close": [1]}), "일봉 형식"),
    (pd.DataFrame({"Close": [1]}, index=pd.date_range("2026-10-30", periods=1)), "원자료 부족"),
])
def test_no_invented_metrics_when_source_is_unusable(frame, reason):
    row = module.build_price_flow_row(frame, "GOOGL")
    assert row["연결상태"] == "자료부족" and reason in row["연결사유"]
    assert "돈흐름점수" not in row and "기준일" not in row


def test_short_history_is_partial_not_a_full_history_claim(history):
    row = module.build_price_flow_row(history.tail(30), "NEW")
    assert row["연결상태"] == "부분연결" and "3M" in row["연결사유"]
    assert np.isnan(row["3개월수익률"]) and row["기준일"] == "2026-10-30"
    insufficient = module.build_price_flow_row(history.tail(19), "NEW")
    fields = {"돈흐름_" + k: v for k, v in insufficient.items()}
    state = input_freshness_fields({"가격자료기준일": "2026-10-30", **fields}, reference={})
    assert state["돈흐름신선도"] == "not_connected"
    assert "19개" in state["돈흐름신선도근거"]


def test_no_forward_fill_and_volume_date_is_not_quote_date(history):
    history.loc[history.index[-1], "Volume"] = np.nan
    history.loc[pd.Timestamp("2026-10-31"), :] = np.nan
    row = module.build_price_flow_row(history, "GOOGL")
    assert row["기준일"] == "2026-10-30" and row["거래량기준일"] == "2026-10-29"
    fields = {"돈흐름_" + k: v for k, v in row.items()}
    assert input_freshness_fields({"가격자료기준일": "2026-10-30", **fields}, reference={})["돈흐름신선도"] == "volume_lag"


def test_crypto_year_window_not_252_stock_sessions():
    dates = pd.date_range(end="2026-10-30", periods=500)
    history = pd.DataFrame({"Close": range(1, 501), "High": range(2, 502),
                            "Low": np.arange(500) + .5, "Volume": 100}, index=dates)
    row = module.build_price_flow_row(history, "BTC-USD")
    assert row["자료봉수"] == 365
    assert row["52주 최저가"] == 135.5


@pytest.mark.parametrize("day,volume,alias", [
    ("2026-10-29", "2026-10-29", None),
    ("2026-10-31", "2026-10-31", None),
    ("2026-10-30", "2026-10-29", None),
    ("2026-10-30", "", None),
    ("2026-10-30", "2026-10-30", "2026-10-29"),
])
def test_invalid_radar_cannot_erase_current_ticker_evidence(day, volume, alias):
    row = {"가격자료기준일": "2026-10-30", **_context()}
    radar = _context(day, 돈흐름_거래량기준일=volume, 돈흐름_판정="눌림대기", 돈흐름_연결경로=module.RADAR_PATH)
    if alias:
        radar["돈흐름_source_asof"] = alias
    before = deepcopy((row, radar))
    result = module.select_flow_fields(row, radar)
    assert result["돈흐름_연결경로"] == module.SOURCE_PATH
    assert result["돈흐름_기준일"] == "2026-10-30"
    assert result["돈흐름_레이더판정"] == "눌림대기"
    assert (row, radar) == before


def test_same_session_radar_keeps_original_veto_and_ranking():
    row = {"가격자료기준일": "2026-10-30", **_context()}
    radar = _context(돈흐름_판정="내부확인", 돈흐름_돈흐름점수=32, 돈흐름_연결경로=module.RADAR_PATH)
    assert module.select_flow_fields(row, radar) == radar


def test_invalid_veto_remains_if_no_valid_replacement_exists():
    radar = _context("2026-10-29", 돈흐름_판정="눌림대기")
    result = module.select_flow_fields({"가격자료기준일": "2026-10-30"}, radar)
    assert result["돈흐름_판정"] == "눌림대기"
    assert result["돈흐름_기준일"] == "2026-10-29"


def test_invalid_neutral_radar_cannot_clear_an_existing_invalid_veto():
    row = {"티커": "GOOGL", "가격자료기준일": "2026-10-30", "판정분류": "buyish", "RR값": 2,
           **_context(돈흐름_판정="눌림대기", 돈흐름_거래량기준일="2026-10-29")}
    incoming = _context("2026-10-29", 돈흐름_판정="관찰")
    selected = module.select_flow_fields(row, incoming)
    assert selected["돈흐름_판정"] == "눌림대기"
    assert "기존 대기 근거 유지" in selected["돈흐름_연결보완사유"]
    actual = apply_execution_gate_columns(pd.DataFrame([{**row, **selected}])).iloc[0]
    assert actual["게이트상태"] == "데이터확인"


@pytest.mark.parametrize("missing_column", [False, True])
def test_loader_zeros_cannot_certify_volume_that_was_missing(history, missing_column):
    from stock_lab_core.prices import _clean_ohlcv_frame, _normalize_pykrx_ohlcv

    history.loc[history.index[-1], "Volume"] = np.nan
    raw = history.drop(columns="Volume") if missing_column else history
    for normalize in (_clean_ohlcv_frame, _normalize_pykrx_ohlcv):
        normalized = normalize(raw)
        assert normalized.iloc[-1]["Volume"] == 0
        assert "2026-10-30" in normalized.attrs["volume_missing_sessions"]
        cleaned_twice = _clean_ohlcv_frame(normalized)
        result = module.build_price_flow_row(cleaned_twice, "GOOGL")
        assert result["거래량기준일"] == ("" if missing_column else "2026-10-29")
        fields = {"돈흐름_" + key: value for key, value in result.items()}
        assert input_freshness_fields({"가격자료기준일": "2026-10-30", **fields}, reference={})["돈흐름신선도"] == "volume_lag"


def test_genuine_zero_volume_is_not_mistaken_for_missing(history):
    from stock_lab_core.prices import _clean_ohlcv_frame

    history.loc[history.index[-1], "Volume"] = 0
    result = module.build_price_flow_row(_clean_ohlcv_frame(history), "GOOGL")
    assert result["거래량기준일"] == "2026-10-30"


def test_merge_preserves_unmatched_rows_duplicate_index_and_attrs():
    summary = pd.DataFrame([
        {"티커": "GOOGL", "_검토키": "googl", "가격자료기준일": "2026-10-30", **_context()},
        {"티커": "MSFT", "_검토키": "msft", "가격자료기준일": "2026-10-30", **_context(돈흐름_Ticker="MSFT")},
    ], index=[8, 8])
    summary.attrs["measurement_id"] = "same-computation"
    flow = pd.DataFrame([{**_context(돈흐름_판정="내부확인"), "_검토키": "googl"}])
    before = summary.copy(deep=True)
    actual = module.merge_flow_context(summary, flow)
    assert actual.index.tolist() == [8, 8] and actual["티커"].tolist() == ["GOOGL", "MSFT"]
    assert actual["돈흐름_판정"].tolist() == ["내부확인", "관찰"]
    assert actual.attrs == summary.attrs
    pd.testing.assert_frame_equal(summary, before)


def test_precision_dashboard_and_today_reuse_same_ticker_fields(app_module, monkeypatch, history):
    app = app_module
    monkeypatch.setattr(app, "get_auto_benchmark_info", lambda *a: {
        "sector_bench": "XLK", "sector_rs_label": "강함"})
    monkeypatch.setattr(app, "get_benchmark_display_name", lambda t: t)
    monkeypatch.setattr(app, "get_cached_today_market_flow_snapshot", lambda: None)
    monkeypatch.setattr(app, "build_today_flow_shortlist_df", lambda value: pd.DataFrame())
    monkeypatch.setattr(app, "build_today_market_guard", lambda *a: {})
    monkeypatch.setattr(app, "attach_today_analyst_context", lambda frame, **kw: frame)
    monkeypatch.setattr(app, "build_today_analyst_upside_map", lambda frame: {})
    decision = {"grade": "A", "t_score": 8, "dec": "정밀확인", "decision_group": "buyish",
                "rr_ratio": 2, "input_basis": {"가격자료기준일": "2026-10-30"}}
    original = deepcopy(decision)
    precision = app.build_precision_execution_workflow("Alphabet", "GOOGL", decision, False, "us_stock", False, price_df=history)
    flow = app.build_source_flow_context(history, "GOOGL", "Alphabet")
    raw = build_decision_workflow("Alphabet", "GOOGL", {**decision, "flow_context": flow})
    today = app.attach_today_flow_context(pd.DataFrame([raw]), pd.DataFrame(), snapshot={})
    dashboard = apply_execution_gate_columns(today)
    for row in (raw, today.iloc[0], dashboard.iloc[0]):
        for key in (*flow, "돈흐름기준일", "돈흐름신선도", "게이트상태"):
            assert row[key] == precision[key], key
    assert precision["돈흐름신선도"] == "aligned"
    assert decision == original


def test_market_defense_is_never_relaxed_by_connected_flow():
    row = {"티커": "GOOGL", "가격자료기준일": "2026-10-30", "시장실행상태": "시장방어: 신규매수 중단",
           "판정분류": "buyish", "RR값": 2, **_context(돈흐름_돈흐름점수=90)}
    actual = apply_execution_gate_columns(pd.DataFrame([row])).iloc[0]
    assert actual["게이트상태"] == "방어우선"


def test_export_contains_displayed_connection_rows_without_duplicate_decision_fields(history):
    from stock_lab_core.precision_review_export import build_precision_review_export_zip

    raw = module.build_price_flow_row(history, "GOOGL")
    workflow = {"돈흐름_" + key: value for key, value in raw.items()}
    rows = module.flow_connection_rows(workflow)
    data = build_precision_review_export_zip(selected_ticker="GOOGL", result_ticker="GOOGL",
                                      decision={"execution_workflow": workflow, "flow_connection": rows,
                                                "flow_context": workflow})
    with zipfile.ZipFile(BytesIO(data)) as archive:
        snapshot = json.loads(archive.read("snapshot.json"))
    assert snapshot["sections"]["flow_connection"] == rows
    assert not {"flow_context", "flow_connection"} & set(snapshot["sections"]["main_decision"])
