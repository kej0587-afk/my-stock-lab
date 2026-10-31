"""Stored fundamentals and derived views share evidence identity, not price time."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.financial_freshness import financial_basis, financial_input_signature


def records():
    return pd.DataFrame([dict(ticker="googl", auto_score=4, manual_score=None, final_score=4,
        source="fmp", notes_json=json.dumps({"ok": True, "metrics": {"quarter_latest": {"date": "2026-03-31"}}}))])


def test_financial_identity_tracks_period_even_when_score_is_unchanged():
    frame = records()
    old = financial_input_signature(frame)
    assert old == financial_input_signature(frame.iloc[::-1])
    frame.loc[0, "notes_json"] = json.dumps({"metrics": {"quarter_latest": {"date": "2026-09-30"}}})
    assert old != financial_input_signature(frame)
    frame.loc[0, "manual_score"] = 2
    assert old != financial_input_signature(frame)
    assert financial_input_signature(None) == financial_input_signature(pd.DataFrame())


def test_basis_does_not_promote_old_reports_or_unknown_computation_to_fresh():
    meta = {"auto_score": 4, "metrics": {"quarter_latest": {"date": "2026-03-31"}}, "notes": {"ok": True}}
    original = deepcopy(meta)
    result = financial_basis(meta)
    assert result["재무자료기간"] == "분기 2026-03-31"
    assert result["재무계산시각"] == "계산 시각 미저장"
    assert "최신 발표 반영 여부 미확인" in result["재무자료상태"]
    assert meta == original
    meta["notes"]["computed_at"] = "2026-10-31T00:00:00+00:00"
    result = financial_basis(meta, now=datetime(2026, 10, 31, 8, tzinfo=timezone.utc))
    assert "6시간 경과" in result["재무자료상태"]
    assert financial_basis({}, is_etf=True)["재무자료상태"] == "기업재무 해당없음"


@pytest.mark.parametrize("manual", [None, 2])
def test_failed_refresh_keeps_saved_good_score_and_never_writes(app_module, monkeypatch, manual):
    app = app_module
    frame = records()
    frame.loc[0, "manual_score"] = manual
    frame.loc[0, "final_score"] = manual if manual is not None else 4
    monkeypatch.setattr(app, "load_fin_scores_db", lambda: frame.copy())
    monkeypatch.setattr(app, "get_auto_fin_score_for_ticker", lambda *args: (3, {"ok": False}, {"ok": False}, {}))
    save = Mock(side_effect=AssertionError("Failed retrieval must not overwrite saved fundamentals"))
    monkeypatch.setattr(app, "upsert_fin_score_db", save)
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == (manual if manual is not None else 4)
    assert meta["auto_score"] == 4 and meta["save_ok"] is False
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-03-31"
    save.assert_not_called()


@pytest.mark.parametrize("saved", [True, False])
def test_successful_retrieval_records_time_and_reports_actual_save_result(app_module, monkeypatch, saved):
    app = app_module
    frame = records()
    frame.loc[0, "manual_score"] = 2
    monkeypatch.setattr(app, "load_fin_scores_db", lambda: frame.copy())
    monkeypatch.setattr(app, "get_auto_fin_score_for_ticker", lambda *args: (4, {"ok": True}, {"ok": True}, {"fresh": 1}))
    save = Mock(return_value=saved)
    monkeypatch.setattr(app, "upsert_fin_score_db", save)
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == 2 and meta["manual_score"] == 2
    assert meta["save_ok"] is saved
    assert datetime.fromisoformat(save.call_args.kwargs["notes"]["computed_at"]).tzinfo is not None


@pytest.mark.parametrize("saved", [True, False])
def test_only_successful_account_scoped_save_invalidates_derived_views(app_module, monkeypatch, saved):
    app = app_module
    state = {"fin_score_map": {"googl": 2}, "today_queue_summary_df": "old", "dashboard_summary_df": "old"}
    body = {}
    table = SimpleNamespace(upsert=lambda payload, **kwargs: body.update(payload) or object())
    monkeypatch.setattr(app, "supabase", SimpleNamespace(table=lambda name: table))
    monkeypatch.setattr(app, "CURRENT_USER_EMAIL", "local-user@example.invalid")
    monkeypatch.setattr(app, "IS_PUBLIC_DEMO", False)
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app, "run_supabase", lambda *args, **kwargs: object() if saved else None)
    clear = Mock()
    monkeypatch.setattr(app, "load_fin_scores_db_for_user", SimpleNamespace(clear=clear))
    assert app.upsert_fin_score_db("GOOGL", 4, 2, 2, "fmp", {}) is saved
    assert body["owner_email"] == "local-user@example.invalid"
    assert ("today_queue_summary_df" not in state) is saved
    assert ("dashboard_summary_df" not in state) is saved
    assert clear.call_count == int(saved)


def test_refresh_clears_every_valuation_earnings_and_target_layer(app_module, monkeypatch):
    app = app_module
    clears = {}
    for name in ("fetch_fin_meta_for_valuation_fallback", "fetch_valuation_snapshot", "get_analyst_snapshot", "fetch_earnings_date"):
        clears[name] = Mock()
        monkeypatch.setattr(app, name, SimpleNamespace(clear=clears[name]))
    app.clear_financial_api_cache()
    assert all(call.call_count == 1 for call in clears.values())


def test_saved_percentage_points_are_normalized_at_valuation_boundary(app_module):
    app = app_module
    fields = app.build_valuation_fields_from_fin_meta({"metrics": {
        "annual_latest": {"revenue": 100, "op_margin": 2, "net_margin": .5, "roe": 1},
        "derived": {"rev_growth": 2, "net_growth": -.5}}})
    assert fields["operatingMargins"] == .02 and fields["profitMargins"] == .005
    assert fields["revenueGrowth"] == .02
    assert app.fmt_growth_pct(fields["revenueGrowth"]) == "2.0%"
    assert app.valuation_factor_label("growth", fields["revenueGrowth"])[0] == "둔화"
    assert app.valuation_factor_label("margin", fields["operatingMargins"])[0] != "우수"


@pytest.mark.parametrize("rule", ["W-FRI", pd.offsets.MonthEnd()])
def test_resampling_does_not_convert_unobserved_volume_to_zero(app_module, rule):
    frame = pd.DataFrame({"Open": [1.] * 60, "High": [2.] * 60, "Low": [.5] * 60,
                          "Close": [1.5] * 60, "Volume": [np.nan] * 60}, index=pd.bdate_range("2026-01-01", periods=60))
    result = app_module.resample_ohlcv_timeframe(frame, rule)
    assert result["Volume"].isna().all()
