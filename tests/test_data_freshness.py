"""Session/source dates, independent of cache warmth, processing time and scores."""

from copy import deepcopy
from datetime import date
import io
import json
import zipfile

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import data_freshness as module, money_flow
from stock_lab_core.execution_gate import (
    GATE_DATA_CHECK, GATE_DEFENSE, GATE_EXECUTABLE, GATE_WAIT, apply_execution_gate_columns,
)
from stock_lab_core.financial_freshness import financial_basis
from stock_lab_core.precision_review_export import build_precision_review_export_zip


NOW = pd.Timestamp("2026-10-31T11:00:00Z")
REF = {"completed": "2026-10-30", "active": "", "source": "fixture"}


def _row(**changes):
    return {"티커": "MSFT", "가격자료기준일": "2026-10-30", "지표마지막봉": "2026-10-30",
            "판정분류": "buyish", "R/R": 2.0, **changes}


@pytest.mark.parametrize("value,expected", [
    (None, ""), (pd.NaT, ""), (np.nan, ""), (1793318400, ""),
    ("2026-02-30", ""), ("20261030", ""), ("2026-10-30", "2026-10-30"),
    ("2026-10-30T00:00:00-04:00", "2026-10-30"), (date(2026, 10, 30), "2026-10-30"),
])
def test_session_labels_are_not_processing_timestamps(value, expected):
    assert module.session_date(value) == expected


@pytest.mark.parametrize("source,state", [
    ("2026-10-30", "current"), ("2026-10-29", "stale"), ("2026-10-31", "future"), (None, "unknown"),
])
def test_price_compares_to_completed_session_not_calendar_age(source, state):
    row = _row(가격자료기준일=source, 계산시각="2026-10-31 20:00:00 KST")
    before = deepcopy(row)
    assert module.input_freshness_fields(row, reference=REF)["가격신선도"] == state
    assert row == before


def test_active_candle_and_quote_only_overlay_keep_different_meanings():
    ref = {"completed": "2026-10-29", "active": "2026-10-30"}
    actual = module.input_freshness_fields(_row(), reference=ref)
    assert actual["가격신선도"] == "in_progress"
    quote_only = _row(가격자료기준일="2026-10-29", 가격반영="조회 현재가 보정 · 미확정",
                      돈흐름_기준일="2026-10-29", 돈흐름_판정="눌림대기")
    result = module.input_freshness_fields(quote_only, reference=REF)
    assert result["가격신선도"] == "stale"  # Today's quote does not refresh yesterday's indicators.
    assert result["돈흐름기준일"] == "2026-10-29"


@pytest.mark.parametrize("flow,expected", [
    ("2026-10-30", "aligned"), ("2026-10-29", "older"), ("2026-10-31", "newer"), (None, "unknown"),
])
def test_flow_dates_are_actual_prices_not_snapshot_generation_dates(flow, expected):
    row = _row(돈흐름_판정="눌림대기", 돈흐름_기준일=flow, 계산시각="2099-01-01")
    assert module.input_freshness_fields(row, reference=REF)["돈흐름신선도"] == expected


def test_conflicting_flow_dates_are_not_resolved_by_picking_the_newest():
    row = _row(돈흐름_기준일="2026-10-29", 돈흐름_source_asof="2026-10-30")
    assert module.input_freshness_fields(row, reference=REF)["돈흐름신선도"] == "conflict"


@pytest.mark.parametrize("changes,gate", [
    ({}, GATE_EXECUTABLE),
    ({"가격자료기준일": "2026-10-29"}, GATE_DATA_CHECK),
    ({"가격자료기준일": None}, GATE_DATA_CHECK),
    ({"가격자료기준일": "2026-11-01"}, GATE_DATA_CHECK),
    ({"돈흐름_판정": "눌림대기", "돈흐름_기준일": "2026-10-30"}, GATE_WAIT),
    ({"돈흐름_판정": "눌림대기", "돈흐름_기준일": "2026-10-29"}, GATE_DATA_CHECK),
    ({"돈흐름_판정": "눌림대기"}, GATE_DATA_CHECK),
    ({"돈흐름_판정": "관망", "돈흐름_돈흐름점수": -20, "돈흐름_기준일": "2026-10-29"}, GATE_DATA_CHECK),
    # Optional positive context does not grant permission and is not a mandatory source.
    ({"돈흐름_판정": "관심후보", "돈흐름_기준일": "2026-10-29"}, GATE_EXECUTABLE),
    ({"시장실행상태": "시장방어: 신규매수 중단", "가격자료기준일": "2026-10-29"}, GATE_DEFENSE),
])
def test_gate_does_not_apply_stale_flow_as_a_current_veto_or_relax_known_defense(monkeypatch, changes, gate):
    monkeypatch.setattr(module, "session_reference", lambda *args: REF)
    frame = pd.DataFrame([_row(**changes)], index=[5])
    frame.attrs["measurement_id"] = "same-calculation"
    before = frame.copy(deep=True)
    result = apply_execution_gate_columns(frame, freshness_now=NOW)
    assert result.loc[5, "게이트상태"] == gate
    if changes.get("돈흐름_판정") == "관심후보":
        assert result.loc[5, "돈흐름사용범위"] == "참고 전용 · 실행근거 제외"
        assert "실행근거 제외" in result.loc[5, "후보검토사항"]
    assert result.attrs == frame.attrs
    pd.testing.assert_frame_equal(frame, before)
    pd.testing.assert_frame_equal(result, apply_execution_gate_columns(result, freshness_now=NOW))


def test_legacy_rows_without_date_schema_stay_explicitly_unverified(monkeypatch):
    monkeypatch.setattr(module, "session_reference", lambda *args: pytest.fail("No date was supplied"))
    row = _row()
    row.pop("가격자료기준일")
    result = apply_execution_gate_columns(pd.DataFrame([row]))
    assert result.iloc[0]["가격신선도"] == "unknown"
    assert not result.iloc[0]["가격신선도검증대상"]


def test_latest_source_replaces_old_derived_stale_state(monkeypatch):
    monkeypatch.setattr(module, "session_reference", lambda *args: REF)
    row = _row(가격신선도="stale", 돈흐름_판정="눌림대기", 돈흐름_기준일="2026-10-30")
    result = apply_execution_gate_columns(pd.DataFrame([row]), freshness_now=NOW)
    assert result.iloc[0]["가격신선도"] == "current"
    assert result.iloc[0]["게이트상태"] == GATE_WAIT


def test_raw_workflow_checks_source_dates_before_cache_or_display(monkeypatch):
    from stock_lab_core.decision_workflow import build_decision_workflow
    from tests.test_decision_governance import _decision
    monkeypatch.setattr(module, "session_reference", lambda *args: REF)
    decision = _decision(input_basis={"가격자료기준일": "2026-10-29", "계산시각": "2026-10-31 20:00:00 KST"})
    before = deepcopy(decision)
    workflow = build_decision_workflow("Test", "MSFT", decision)
    assert workflow["게이트상태"] == GATE_DATA_CHECK
    assert workflow["게이트근거ID"] == "data.price"
    assert workflow["후보품질"] == before["grade"] and workflow["후보점수"] == before["t_score"]
    assert decision == before


@pytest.mark.parametrize("ticker,clock,completed,active", [
    ("MSFT", "2026-10-31T11:00:00Z", "2026-10-30", ""),  # Saturday KST
    ("MSFT", "2026-11-02T14:00:00Z", "2026-10-30", ""),  # EST, before open
    ("MSFT", "2026-11-02T15:00:00Z", "2026-10-30", "2026-11-02"),
    ("MSFT", "2026-11-02T21:00:00Z", "2026-11-02", ""),
    ("005930.KS", "2026-10-30T05:00:00Z", "2026-10-29", "2026-10-30"),
    ("005930.KS", "2026-10-30T06:30:00Z", "2026-10-30", ""),
    ("^KS11", "2026-10-30T07:00:00Z", "2026-10-30", ""),
    ("^KQ11", "2026-10-30T07:00:00Z", "2026-10-30", ""),
    ("MSFT", "2026-11-26T17:00:00Z", "2026-11-25", ""),  # Thanksgiving
    ("MSFT", "2026-11-27T18:00:00Z", "2026-11-27", ""),  # Early close
    ("BTC-USD", "2026-10-31T11:00:00Z", "2026-10-30", "2026-10-31"),
])
def test_exchange_calendar_handles_sessions_holidays_dst_and_crypto(ticker, clock, completed, active):
    result = module.session_reference(ticker, pd.Timestamp(clock))
    assert (result["completed"], result["active"]) == (completed, active)


def test_unconnected_and_failed_calendars_are_distinct(monkeypatch):
    assert module.session_reference("7203.T", NOW)["unsupported"]
    assert module.session_reference("^N225", NOW)["unsupported"]
    assert module.session_reference("^HSI", NOW)["unsupported"]
    import stock_lab_core.report_eventstudy as calendars
    monkeypatch.setattr(calendars, "_exchange_schedule", lambda *args: (_ for _ in ()).throw(ValueError("bad calendar")))
    ref = module.session_reference("MSFT", NOW)
    assert module.input_freshness_fields(_row(), reference=ref)["가격신선도"] == "unknown"
    with pytest.raises(ValueError, match="timezone"):
        module.session_reference("MSFT", pd.Timestamp("2026-10-31"))


@pytest.mark.parametrize("group_by", ["ticker", "field"])
def test_union_calendar_does_not_fabricate_weekend_sessions_or_missing_volume(group_by):
    days = pd.bdate_range(end="2026-10-30", periods=80)
    px = pd.DataFrame({"Close": np.arange(80.) + 100, "High": np.arange(80.) + 101,
                       "Low": np.arange(80.) + 99, "Volume": np.arange(80.) + 1000}, index=days)
    # Another venue/crypto contributed Saturday's index and an incomplete Monday row.
    union = px.reindex(days.union(pd.to_datetime(["2026-10-31", "2026-11-02"])))
    union.loc["2026-10-30", "Volume"] = np.nan
    union.loc["2026-11-02", "Close"] = 180
    data = pd.concat({"MSFT": union}, axis=1)
    if group_by == "field":
        data = data.swaplevel(axis=1)
    before = data.copy(deep=True)
    extracted = money_flow._extract_ohlc_from_yf(data, "MSFT")
    assert extracted.index[-1] == days[-1] and len(extracted) == 80
    assert pd.isna(extracted.Volume.iloc[-1])
    metrics = money_flow._compute_ticker_metrics(extracted)
    assert metrics["기준일"] == "2026-10-30"
    assert metrics["거래량기준일"] == days[-2].strftime("%Y-%m-%d")
    assert metrics["1일수익률"] == pytest.approx(179/178 - 1)
    pd.testing.assert_frame_equal(data, before)


def test_aligned_prices_do_not_mask_old_flow_volume(monkeypatch):
    monkeypatch.setattr(module, "session_reference", lambda *args: REF)
    row = _row(돈흐름_판정="눌림대기", 돈흐름_기준일="2026-10-30", 돈흐름_거래량기준일="2026-10-29")
    result = apply_execution_gate_columns(pd.DataFrame([row]), freshness_now=NOW).iloc[0]
    assert result["돈흐름신선도"] == "volume_lag"
    assert result["게이트상태"] == GATE_DATA_CHECK
    assert "거래량 2026-10-29" in result["게이트근거"]


def test_recent_financial_calculation_is_not_proof_of_latest_report_and_export_has_same_rows():
    meta = {"auto_score": 4, "notes": {"computed_at": "2026-10-31T10:00:00Z"},
            "metrics": {"quarter_latest": {"date": "2026-03-31"}}}
    before = deepcopy(meta)
    basis = financial_basis(meta, now=NOW)
    workflow = dict(_row(), **basis, **module.input_freshness_fields(_row(), reference=REF))
    rows = module.input_freshness_rows(workflow)
    assert "2026-03-31" in rows[2]["기준일/기간"]
    assert "최신 발표 반영 여부 미확인" in rows[2]["상태"]
    payload = build_precision_review_export_zip(selected_ticker="MSFT", result_ticker="MSFT",
        decision={"execution_workflow": workflow, "input_basis": basis, "input_freshness": rows, "grade": "A"})
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        sections = json.loads(archive.read("snapshot.json"))["sections"]
    assert sections["input_freshness"] == rows
    assert "input_basis" not in sections["main_decision"]
    assert meta == before
