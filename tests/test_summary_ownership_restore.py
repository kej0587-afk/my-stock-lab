"""Ownership and read-only snapshot regressions, with no provider/account IO."""

from functools import partial
from datetime import datetime
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import today_queue_session as session
from stock_lab_core import today_snapshot as snapshots
from stock_lab_core.decision_workflow import attach_market_execution_context, partition_today_queue
from stock_lab_core.execution_context import prepare_execution_context
from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_EXECUTABLE, apply_execution_gate_columns
from stock_lab_core.report_evidence import is_held
from stock_lab_core.today_queue_display import prepare_today_queue_display
from tests.test_fresh_quote_summary import replay, summary_ast


@pytest.mark.parametrize("kind", ["DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA"])
@pytest.mark.parametrize("qty", [7, 0, .0001])
def test_status_rows_keep_ownership_without_inventing_price_or_weight(replay, kind, qty):
    item = {"ticker": "RAM", "name": "RAM", "is_etf": True, "qty": qty}
    replay.env["load_display_live_price"] = lambda ticker: 0
    if kind == "LIVE_ONLY_DATA":
        build = lambda value: replay.env["_build_live_only_summary_item"](value, 25, "missing history")["row"]
    else:
        build = lambda value: replay.env["build_summary_status_item"](value, "fixture", code=kind)["row"]
    row = build(item)
    without_qty = build({k: v for k, v in item.items() if k != "qty"})
    assert row["qty"] == qty
    assert row["has_pos"] == is_held(row) == (qty > 0)
    pd.testing.assert_series_equal(pd.Series(row).drop(["qty", "has_pos"]),
                                   pd.Series(without_qty).drop(["qty", "has_pos"]))
    assert np.isnan(row["현재비중"])
    assert row["판정코드"] == kind
    assert row["현재가"] == ("$25.00" if kind == "LIVE_ONLY_DATA" else "-")


def test_normal_ram_and_uncaught_worker_error_retain_ownership(replay):
    item = {"ticker": "RAM", "name": "RAM", "is_etf": True, "qty": 7}
    replay.quotes["RAM"] = 120.
    close = np.linspace(70., 100., 260)
    frame = pd.DataFrame({"Open": close, "High": close + 2, "Low": close - 2,
                          "Close": close, "Volume": 1_000_000},
                         index=pd.bdate_range(end="2026-10-29", periods=260))
    replay.env["prefetch_price_data_parallel"] = lambda tickers, period: {"RAM": frame.copy()}
    baseline, _ = replay.run(items=[{k: v for k, v in item.items() if k != "qty"}])
    normal, _ = replay.run(items=[item])
    assert normal.iloc[0]["qty"] == 7 and is_held(normal.iloc[0])
    pd.testing.assert_frame_equal(normal.drop(columns=["qty", "has_pos"]),
                                  baseline.drop(columns=["qty", "has_pos"]))
    replay.env["_compute_summary_item"] = Mock(side_effect=RuntimeError("worker failure"))
    replay.env["load_display_live_price"] = lambda ticker: 0
    failed, _ = replay.run(items=[item])
    row = failed.iloc[0]
    assert row["qty"] == 7 and is_held(row)
    assert row["판정코드"] == "DATA_ERROR" and row["현재가"] == "-"
    assert np.isnan(row["현재비중"])


def test_report_lists_error_ram_as_held_with_unknown_weight(replay):
    from stock_lab_core.market_memo import build_auto_market_memo
    from stock_lab_core.report_evidence import KST

    replay.env["load_display_live_price"] = lambda ticker: 0
    row = replay.env["build_summary_status_item"](
        {"ticker": "RAM", "name": "RAM", "is_etf": True, "qty": 7},
        "fixture price error", code="DATA_ERROR")["row"]
    report = build_auto_market_memo(
        summary_rows=[row], now=datetime(2026, 10, 18, 18, tzinfo=KST),
        report_context={"sessions": {"KR": "2026-10-16", "US": "2026-10-16"}, "prices": {}})
    holdings = report.split("## 내 보유 종목 영향", 1)[1].split("\n## ", 1)[0]
    assert "RAM(RAM) |" in holdings
    assert "데이터부족" in holdings and "현재비중·일간 기여 미연결" in holdings
    assert "보유목록 미연결" not in holdings
    assert "현재비중 0.00%" not in holdings
    assert row["qty"] == 7 and pd.isna(row["현재비중"])


def snapshot_frame():
    frame = pd.DataFrame([{"티커": "RAM", "종목명": "RAM", "유형": "ETF", "qty": 7,
                           "has_pos": True, "현재가": "-", "현재비중": np.nan,
                           "판정코드": "NEW_ENTRY_LEADER", "판정분류": "buyish",
                           "최종읽기": "정밀확인", "RR값": 2., "데이터상태": "OK",
                           "게이트상태": GATE_EXECUTABLE, "게이트근거": "original reason",
                           "게이트근거ID": "original.id"}])
    frame.attrs = {"portfolio_signal_context": "original-context", "portfolio_signal_at": "original-time"}
    return frame


def disk_fixture(tmp_path, *, signature="stored", owner="owner", version=None, last_run="2026-11-05 10:00"):
    path = tmp_path / "snapshot.json"
    frame = snapshot_frame()
    snapshots.save_today_queue_summary_snapshot(frame, signature, last_run, path=path, owner_scope=owner)
    location, _ = snapshots._snapshot_location(path, owner)
    if version is not None:
        data = json.loads(location.read_text(encoding="utf8"))
        data["version"] = version
        location.write_text(json.dumps(data), encoding="utf8")
    return frame, Mock(wraps=partial(snapshots.load_today_queue_summary_snapshot, path=path))


def test_mismatched_restore_is_read_only_through_real_display_pipeline(tmp_path):
    original, load = disk_fixture(tmp_path)
    state = {"portfolio_today_signal_df": original.copy()}
    restored = session.restore_cached_summary(state, "owner", "current", load_today_queue_summary_snapshot=load)
    assert state[session.SIGNATURE_KEY] == "stored"
    assert state[session.LAST_RUN_KEY] == "2026-11-05 10:00"
    assert state[session.STALE_KEY] == restored.attrs[session.STALE_KEY]
    assert "portfolio_today_signal_df" not in state
    assert "portfolio_signal_context" not in restored.attrs
    for key in ("게이트상태", "게이트근거", "게이트근거ID", "데이터상태"):
        assert restored.iloc[0]["저장당시" + key] == original.iloc[0][key]
    pd.testing.assert_frame_equal(restored[original.columns].drop(columns=["게이트상태", "게이트근거", "게이트근거ID", "데이터상태"]),
                                  original.drop(columns=["게이트상태", "게이트근거", "게이트근거ID", "데이터상태"]), check_dtype=False)
    guard = {"mode": "정상", "kr_stats": {"mode": "정상"}, "us_stats": {"mode": "정상"}}
    displayed, reasons, _ = prepare_today_queue_display(restored, guard, restored["판정분류"])
    displayed = prepare_execution_context(
        displayed, snapshot={}, flow_shortlist=pd.DataFrame(), market_guard=guard,
        attach_flow=lambda value, *a, **kw: value, attach_market=attach_market_execution_context,
        apply_gate=apply_execution_gate_columns)
    assert displayed.iloc[0]["게이트상태"] == GATE_DATA_CHECK
    assert not partition_today_queue(displayed, reasons)["execution"].any()
    assert displayed.attrs[session.STALE_KEY]
    assert is_held(displayed.iloc[0])
    save = Mock()
    for clicked in (False, True):
        result = session.finalize_summary(state, restored, "current", clicked, "owner",
            dedupe_dashboard_summary_df=lambda value: value.copy(), save_today_queue_summary_snapshot=save)
        assert result.attrs[session.STALE_KEY]
    save.assert_not_called()
    # A subsequent signature match cannot silently re-promote a guarded frame.
    again = session.restore_cached_summary(state, "owner", "stored", load_today_queue_summary_snapshot=load)
    assert again.iloc[0]["게이트상태"] == GATE_DATA_CHECK
    assert again.iloc[0]["저장당시게이트상태"] == GATE_EXECUTABLE
    assert load.call_count == 1
    session.remember_calculated_summary(state, original.copy(), "current", "fresh-time")
    assert session.STALE_KEY not in state
    assert session.STALE_KEY not in state[session.SUMMARY_KEY].attrs
    session.finalize_summary(state, state[session.SUMMARY_KEY], "current", True, "owner",
        dedupe_dashboard_summary_df=lambda value: value.copy(), save_today_queue_summary_snapshot=save)
    save.assert_called_once()


@pytest.mark.parametrize("last_run", ["2000-01-01 00:00", "", "invalid"])
@pytest.mark.parametrize("warm", [True, False])
def test_matching_signature_does_not_add_time_policy(tmp_path, last_run, warm):
    original, load = disk_fixture(tmp_path, signature="current", last_run=last_run)
    state = {session.SUMMARY_KEY: original.copy(), session.SIGNATURE_KEY: "current",
             session.LAST_RUN_KEY: last_run} if warm else {}
    result = session.restore_cached_summary(state, "owner", "current", load_today_queue_summary_snapshot=load)
    pd.testing.assert_frame_equal(result, original, check_dtype=False)
    assert result.attrs == original.attrs and session.STALE_KEY not in state
    assert load.call_count == (0 if warm else 1)


@pytest.mark.parametrize("kind", ["owner", "version", "corrupt"])
def test_fallback_never_bypasses_snapshot_validation(tmp_path, kind):
    _, load = disk_fixture(tmp_path, version="incompatible" if kind == "version" else None)
    if kind == "corrupt":
        location, _ = snapshots._snapshot_location(tmp_path / "snapshot.json", "owner")
        location.write_text("{broken", encoding="utf8")
    result = session.restore_cached_summary({}, "other" if kind == "owner" else "owner", "current",
                                             load_today_queue_summary_snapshot=load)
    assert result.empty


def test_explicit_clear_blocks_failed_disk_delete_across_reruns_and_owner_switch(tmp_path):
    original, load = disk_fixture(tmp_path)
    state = {}
    session.restore_cached_summary(state, "owner", "current", load_today_queue_summary_snapshot=load)
    session.clear_cached_summary(state)
    load.reset_mock()  # Leave disk intact, simulating a failed unlink.
    for owner in ("owner", "other", "owner"):
        result = session.restore_cached_summary(state, owner, "current", load_today_queue_summary_snapshot=load)
        assert result.empty
    assert [call.kwargs["owner_scope"] for call in load.call_args_list] == ["other"]
    session.remember_calculated_summary(state, pd.DataFrame(), "current", "failed-time")
    assert "owner" in state[session.CLEARED_OWNERS_KEY]
    session.remember_calculated_summary(state, original.copy(), "current", "fresh-time")
    assert session.CLEARED_OWNERS_KEY not in state


@pytest.mark.parametrize("signature", ["current", "old"])
def test_legacy_ram_ownership_repaired_only_with_current_inputs(signature):
    original = snapshot_frame().drop(columns=["qty", "has_pos"])
    original.loc[1] = {"티커": "UNMATCHED", "종목명": "RAM"}
    holdings = pd.DataFrame([{"티커": "RAM", "보유량": 7, "현재비중": 10.}])
    state = {session.SUMMARY_KEY: original.copy(), session.SIGNATURE_KEY: signature,
             "_app_holdings_table": holdings}
    result = session.restore_cached_summary(state, "owner", "current", load_today_queue_summary_snapshot=Mock())
    if signature == "current":
        assert result.iloc[0]["qty"] == 7 and is_held(result.iloc[0])
        assert pd.isna(result.iloc[1]["qty"]) and not is_held(result.iloc[1])
        pd.testing.assert_frame_equal(result[original.columns], original)
    else:
        assert "qty" not in result.columns
    assert pd.isna(result.iloc[0]["현재비중"]) and result.iloc[0]["현재가"] == "-"
    assert "qty" not in original.columns


def test_legacy_repair_does_not_overwrite_explicit_zero_quantity():
    original = snapshot_frame()
    original["qty"] = 0
    state = {session.SUMMARY_KEY: original, session.SIGNATURE_KEY: "current",
             "_app_holdings_table": pd.DataFrame([{"티커": "RAM", "보유량": 7}])}
    result = session.restore_cached_summary(state, "owner", "current", load_today_queue_summary_snapshot=Mock())
    assert result.iloc[0]["qty"] == 0 and not is_held(result.iloc[0])
