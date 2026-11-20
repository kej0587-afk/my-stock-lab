"""Offline refresh regression contracts; no app startup, credentials or DB."""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import requests

from stock_lab_core.financial_refresh import financial_refresh_is_newer, financial_refresh_period_issues
from stock_lab_core.financial_score import resolve_fin_score_source
from stock_lab_core.formatters import clean_float, finite_num, is_kr_listed


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    blocked = Mock(side_effect=AssertionError("Financial refresh tests must stay offline"))
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    yield
    blocked.assert_not_called()


@pytest.mark.parametrize("kind", ["annual", "quarter"])
@pytest.mark.parametrize("incoming,expected", [
    ("2026-03-31", "older"), ("2026-09-30", ""), ("2026-12-31", ""),
    (None, "unverified"), ("2026-02-30", "unverified"),
    ("20260930", "unverified"), ("2026-09-30T00:00:00", "unverified"),
])
def test_known_end_dates_cannot_regress_or_disappear(kind, incoming, expected):
    baseline = {f"{kind}_latest": {"date": "2026-09-30", "fiscal_year": "2027"}}
    candidate = {f"{kind}_latest": {"date": incoming, "fiscal_year": "2026"}}
    before = deepcopy((candidate, baseline))
    issues = financial_refresh_period_issues(candidate, baseline,
        candidate_source="sec_edgar", baseline_source="fmp")
    assert bool(issues) is bool(expected)
    if expected:
        assert expected in issues[0]
    assert (candidate, baseline) == before


@pytest.mark.parametrize("kind,old,new", [
    ("annual", {"date": "2025", "fiscal_year": "2025"}, {"date": "2024", "fiscal_year": "2024"}),
    ("quarter", {"date": "2026-Q3", "fiscal_year": "2026", "fiscal_quarter": 3},
     {"date": "2026-Q2", "fiscal_year": "2026", "report_code": "Q2"}),
    ("quarter", {"date": "2026-11014", "fiscal_year": "2026", "fiscal_quarter": 3},
     {"date": "2025-Q4", "fiscal_year": "2025", "fiscal_quarter": 4}),
])
def test_dart_fiscal_periods_use_order_without_inventing_calendar_dates(kind, old, new):
    baseline, candidate = {f"{kind}_latest": old}, {f"{kind}_latest": new}
    assert "older" in financial_refresh_period_issues(candidate, baseline,
        candidate_source="dart", baseline_source="dart_annual_only")[0]
    assert not financial_refresh_period_issues(baseline, candidate,
        candidate_source="dart", baseline_source="dart")


@pytest.mark.parametrize("candidate", [
    {}, {"date": "2026-09-30"},
    {"date": "2026-Q3", "fiscal_year": "2026", "fiscal_quarter": 3, "report_code": "Q1"},
    {"date": "2026-02-30", "fiscal_year": "2026", "fiscal_quarter": 3},
    {"date": "2026-Q1", "fiscal_year": "2026", "fiscal_quarter": True},
])
def test_dart_unknown_conflicting_and_incomparable_periods_are_held(candidate):
    baseline = {"quarter_latest": {"date": "2026-Q3", "fiscal_year": "2026", "fiscal_quarter": 3}}
    assert "unverified" in financial_refresh_period_issues({"quarter_latest": candidate}, baseline,
        candidate_source="dart", baseline_source="dart")[0]


def test_annual_and_quarterly_periods_are_guarded_independently():
    baseline = {"annual_latest": {"date": "2025-12-31"}, "quarter_latest": {"date": "2026-06-30"}}
    candidate = {"annual_records": [{"date": "2024-12-31"}], "quarter_records": [{"date": "2026-09-30"}]}
    issues = financial_refresh_period_issues(candidate, baseline)
    assert len(issues) == 1 and issues[0].startswith("annual:")


@pytest.mark.parametrize("baseline", [None, {}, {"quarter_latest": {}}, {"quarter_latest": {"date": "unknown"}}])
def test_unknown_legacy_baseline_does_not_invent_a_regression(baseline):
    assert not financial_refresh_period_issues({"quarter_latest": {"date": "2026-03-31"}}, baseline)


@pytest.mark.parametrize("annual,quarter,expected", [
    ("2025-12-31", "2026-09-30", True),
    ("2026-01-31", "2026-03-31", True),
    ("2025-12-31", "2026-03-31", False),
    ("2024-12-31", "2026-09-30", False),
    ("2026-01-31", "2025-12-31", False),
    (None, "2026-09-30", False), ("2025-12-31", None, False),
    ("2025-12-31", "2026-Q3", False),
])
def test_newer_requires_two_verified_nonregressing_periods(annual, quarter, expected):
    baseline = {"annual_latest": {"date": "2025-12-31"}, "quarter_latest": {"date": "2026-03-31"}}
    candidate = {"annual_latest": {"date": annual}, "quarter_latest": {"date": quarter}}
    before = deepcopy((candidate, baseline))
    assert financial_refresh_is_newer(candidate, baseline,
        candidate_source="sec_edgar", baseline_source="fmp") is expected
    assert (candidate, baseline) == before


def test_missing_baseline_period_is_not_proof_of_strictly_newer_statements():
    candidate = {"annual_latest": {"date": "2025-12-31"}, "quarter_latest": {"date": "2026-09-30"}}
    assert not financial_refresh_is_newer(candidate, {"annual_latest": {"date": "2025-12-31"}})


@pytest.fixture(scope="module")
def refresh_definitions():
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    names = {
        "safe_float", "pct_change", "calc_ratio", "fmt_num", "fmt_pct", "is_order_based_ticker",
        "is_financial_statement_profile", "enrich_fin_record", "fetch_us_financials_auto",
        "getsymbol_score", "judge_text", "build_missing_quarter_judgements",
        "get_financial_profile_from_fin", "build_fin_judgements", "calc_weighted_fin_total",
        "calc_generic_fin_total", "calc_order_fin_total", "round_half_up", "calc_middle_fin_total",
        "get_auto_fin_score_for_ticker", "get_final_fin_score", "parse_notes_json", "load_fin_score_meta_fast",
    }
    constants = {"ORDER_BASED_TICKERS", "FINANCIAL_PROFILE_LABELS", "FIN_S_KEYS", "FIN_A_KEYS", "FIN_B_KEYS",
                 "AUTO_FIN_FAIL_SCORE", "UNCALCULATED_FIN_DEFAULT_SCORE"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
            nodes.append(node)
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == names
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec")


@pytest.fixture
def refresh_app(refresh_definitions):
    app = SimpleNamespace(pd=pd, np=np, datetime=datetime, timezone=timezone, json=json,
        finite_num=finite_num, clean_float=clean_float, is_kr_listed=is_kr_listed,
        normalize_ticker=lambda ticker: ticker.strip().lower(), resolve_fin_score_source=resolve_fin_score_source,
        fetch_us_financials_fmp=Mock(), fetch_us_financials_sec=Mock(return_value={"ok": False}),
        fetch_kr_financials_auto=Mock(), upsert_fin_score_db=Mock(return_value=True),
        load_fin_scores_db=Mock(return_value=pd.DataFrame(columns=["ticker"])))
    exec(refresh_definitions, app.__dict__)
    return app


def statements(app, *, source="fmp", annual_year=2025, quarter=3):
    def record(year, period, value):
        month_day = "12-31" if period == "FY" else {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}[period]
        end = f"{year}-{month_day}"
        row = dict(date=end, fiscal_year=str(year), report_code="FY" if period == "FY" else f"Q{period}",
                   revenue=value, op_income=value * .1, net_income=value * .05, ocf=value * .08,
                   equity=value * .5, liabilities=value * .2, assets=value * .7, cash=value * .1)
        if period != "FY":
            row["fiscal_quarter"] = period
        return app.enrich_fin_record(row)
    previous = (2025, 4) if quarter == 1 else (2026, quarter - 1)
    return {"ok": True, "source": source,
            "annual": [record(year, "FY", 100 + 20 * i) for i, year in enumerate(range(annual_year - 2, annual_year + 1))],
            "quarter": [record(*previous, 30), record(2026, quarter, 40)]}


def save_baseline(app, fin, *, manual=None, ticker="GOOGL"):
    auto, _, notes, metrics = app.get_auto_fin_score_for_ticker(ticker, False, financials=fin)
    notes = dict(notes, metrics=metrics, computed_at="2026-10-31T00:00:00+00:00")
    saved = pd.DataFrame([dict(ticker=ticker.lower(), auto_score=auto, manual_score=manual,
        final_score=auto if manual is None else manual, source=fin["source"], notes_json=json.dumps(notes))])
    app.load_fin_scores_db.side_effect = lambda: saved.copy(deep=True)
    return saved


@pytest.mark.parametrize("manual", [None, 0, 2])
def test_stale_success_preserves_saved_score_all_evidence_and_timestamp(refresh_app, manual):
    app = refresh_app
    saved = save_baseline(app, statements(app), manual=manual)
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == saved.iloc[0].final_score
    assert meta["manual_score"] == manual and meta["save_ok"] is False
    assert meta["refresh_status"] == "stale" and "2026-03-31" in meta["refresh_error"]
    assert json.dumps(meta["notes"], sort_keys=True) == json.dumps(json.loads(saved.iloc[0].notes_json), sort_keys=True)
    app.upsert_fin_score_db.assert_not_called()
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


@pytest.mark.parametrize("manual", [None, 0, 2])
def test_stale_fmp_uses_one_complete_sec_set_with_unchanged_scoring(refresh_app, manual):
    app = refresh_app
    save_baseline(app, statements(app), manual=manual)
    fmp, sec = statements(app, quarter=1), statements(app, source="sec_edgar", quarter=4)
    sec["quarter"][-1]["revenue"] = 80
    before = deepcopy((fmp, sec))
    expected_auto = app.get_auto_fin_score_for_ticker("GOOGL", False, financials=sec)[0]
    app.fetch_us_financials_fmp.return_value = fmp
    app.fetch_us_financials_sec.return_value = sec
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == (expected_auto if manual is None else manual)
    assert meta["auto_score"] == expected_auto and meta["source"] == "sec_edgar" and meta["save_ok"]
    assert meta["metrics"]["quarter_latest"]["revenue"] == 80
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-12-31"
    assert meta["metrics"]["fallback_from"]["source"] == "fmp"
    assert meta["notes"]["computed_at"] != "2026-10-31T00:00:00+00:00"
    assert (fmp, sec) == before
    app.fetch_us_financials_fmp.assert_called_once_with("GOOGL")
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    app.upsert_fin_score_db.assert_called_once()
    assert app.upsert_fin_score_db.call_args.kwargs["notes"] == meta["notes"]


@pytest.mark.parametrize("failure", ["unavailable", "raises", "missing_ocf", "missing_quarter", "old_quarter", "old_annual", "unknown_date"])
def test_unusable_sec_fallback_never_overwrites_or_retries(refresh_app, failure):
    app = refresh_app
    save_baseline(app, statements(app))
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    sec = statements(app, source="sec_edgar", quarter=4)
    if failure == "unavailable":
        sec = {"ok": False}
    elif failure == "raises":
        app.fetch_us_financials_sec.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAIL")
    elif failure == "missing_ocf":
        sec["quarter"][-1]["ocf"] = None
    elif failure == "missing_quarter":
        sec["quarter"] = []
    elif failure == "old_quarter":
        sec = statements(app, source="sec_edgar", quarter=2)
    elif failure == "old_annual":
        sec = statements(app, source="sec_edgar", annual_year=2024, quarter=4)
    elif failure == "unknown_date":
        sec["quarter"][-1]["date"] = None
    app.fetch_us_financials_sec.return_value = sec
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["refresh_status"] == "stale" and not meta["save_ok"]
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-09-30"
    assert "PRIVATE_PROVIDER_DETAIL" not in str(meta)
    app.upsert_fin_score_db.assert_not_called()
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_sec_must_not_regress_the_other_new_fmp_period(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app, annual_year=2024))
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", annual_year=2024, quarter=4)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["refresh_status"] == "stale"
    app.upsert_fin_score_db.assert_not_called()


@pytest.mark.parametrize("quarter", [3, 4])
def test_equal_or_newer_success_keeps_fmp_when_sec_is_unavailable(refresh_app, quarter):
    app = refresh_app
    save_baseline(app, statements(app), manual=0)
    fin = statements(app, quarter=quarter)
    expected = app.get_auto_fin_score_for_ticker("GOOGL", False, financials=fin)[0]
    app.fetch_us_financials_fmp.return_value = fin
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == 0 and meta["auto_score"] == expected and meta["save_ok"]
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    assert meta["notes"]["provider_comparison"]["status"] == "unavailable"
    app.upsert_fin_score_db.assert_called_once()


def test_annual_regression_is_rejected_even_when_quarter_advances(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app))
    app.fetch_us_financials_fmp.return_value = statements(app, annual_year=2024, quarter=4)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert "annual:" in meta["refresh_error"]
    app.upsert_fin_score_db.assert_not_called()


def test_already_selected_stale_sec_is_not_retried(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app))
    app.fetch_us_financials_fmp.return_value = {"ok": False}
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", quarter=1)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["refresh_status"] == "stale"
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    app.upsert_fin_score_db.assert_not_called()


def test_kr_fiscal_regression_preserves_evidence_without_sec(refresh_app):
    app = refresh_app
    def dart(quarter):
        fin = statements(app, source="dart", quarter=quarter)
        for row in fin["annual"]:
            row["date"] = row["fiscal_year"]
        for row in fin["quarter"]:
            row["date"] = f"{row['fiscal_year']}-Q{row['fiscal_quarter']}"
        return fin
    save_baseline(app, dart(3), ticker="005930.KS")
    app.fetch_kr_financials_auto.return_value = dart(1)
    _, meta = app.get_final_fin_score("005930.KS", False, "kr_stock")
    assert meta["refresh_status"] == "stale" and "FY2026 Q3" in meta["refresh_error"]
    app.fetch_us_financials_sec.assert_not_called()
    app.upsert_fin_score_db.assert_not_called()


@pytest.mark.parametrize("saved", [False, True])
def test_first_or_legacy_refresh_retains_existing_success_behavior(refresh_app, saved):
    app = refresh_app
    if saved:
        frame = save_baseline(app, statements(app))
        frame.at[0, "notes_json"] = json.dumps({"ok": True})
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["save_ok"] and meta["source"] == "fmp"
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_failed_fetch_keeps_existing_failure_path(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app), manual=2)
    app.fetch_us_financials_fmp.return_value = {"ok": False}
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == 2 and meta["refresh_status"] == "failed" and not meta["save_ok"]
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    app.upsert_fin_score_db.assert_not_called()


def test_success_without_incoming_period_cannot_erase_known_saved_evidence(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app))
    candidate = statements(app)
    candidate["quarter"][-1]["date"] = None
    app.fetch_us_financials_fmp.return_value = candidate
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["refresh_status"] == "stale" and "unverified" in meta["refresh_error"]
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-09-30"
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    app.upsert_fin_score_db.assert_not_called()


def test_successful_sec_recovery_reports_actual_save_failure(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app), manual=0)
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar")
    app.upsert_fin_score_db.return_value = False
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == 0 and meta["source"] == "sec_edgar" and meta["save_ok"] is False
    app.upsert_fin_score_db.assert_called_once()
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_etf_still_skips_statement_providers(refresh_app):
    app = refresh_app
    score, meta = app.get_final_fin_score("SPY", True, "us_etf")
    assert score == 0 and meta["source"] == "etf"
    app.fetch_us_financials_fmp.assert_not_called()
    app.fetch_us_financials_sec.assert_not_called()
    app.fetch_kr_financials_auto.assert_not_called()
    app.load_fin_scores_db.assert_not_called()


@pytest.mark.parametrize("manual", [None, 0, 2])
def test_same_old_saved_and_fmp_period_advances_to_verified_newer_sec(refresh_app, manual):
    app = refresh_app
    fmp = statements(app, quarter=1)
    save_baseline(app, fmp, manual=manual)
    sec = statements(app, source="sec_edgar", quarter=3)
    sec["quarter"][-1]["revenue"] = 80
    before = deepcopy((fmp, sec))
    expected = app.get_auto_fin_score_for_ticker("GOOGL", False, financials=sec)[0]
    app.fetch_us_financials_fmp.return_value = fmp
    app.fetch_us_financials_sec.return_value = sec
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert score == (expected if manual is None else manual)
    assert meta["auto_score"] == expected and meta["source"] == "sec_edgar"
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-09-30"
    assert meta["metrics"]["annual_records"] == sec["annual"]
    assert meta["metrics"]["quarter_records"] == sec["quarter"]
    assert meta["notes"]["provider_comparison"]["status"] == "selected_newer"
    assert meta["save_ok"] and (fmp, sec) == before
    app.fetch_us_financials_fmp.assert_called_once_with("GOOGL")
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")
    app.upsert_fin_score_db.assert_called_once()


@pytest.mark.parametrize("legacy_saved", [False, True])
def test_first_or_undated_saved_refresh_also_compares_sec(refresh_app, legacy_saved):
    app = refresh_app
    fmp = statements(app, quarter=1)
    if legacy_saved:
        frame = save_baseline(app, fmp, manual=0)
        frame.at[0, "notes_json"] = json.dumps({"ok": True})
    app.fetch_us_financials_fmp.return_value = fmp
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", quarter=3)
    score, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["source"] == "sec_edgar" and meta["save_ok"]
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-09-30"
    if legacy_saved:
        assert score == 0
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_normal_sec_failure_fallback_is_not_compared_twice(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app, quarter=1))
    app.fetch_us_financials_fmp.return_value = {"ok": False}
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", quarter=3)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["source"] == "sec_edgar" and meta["save_ok"]
    app.fetch_us_financials_fmp.assert_called_once_with("GOOGL")
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


@pytest.mark.parametrize("case,status", [
    ("equal", "not_proven_newer"), ("older_quarter", "not_proven_newer"),
    ("older_annual", "not_proven_newer"), ("missing_date", "not_proven_newer"),
    ("missing_ocf", "incomplete"), ("missing_net_income", "incomplete"),
    ("unavailable", "unavailable"), ("raises", "unavailable"),
])
def test_no_verified_sec_improvement_keeps_usable_fmp_without_inference(refresh_app, case, status):
    app = refresh_app
    fmp = statements(app, quarter=2)
    save_baseline(app, fmp)
    app.fetch_us_financials_fmp.return_value = fmp
    sec = statements(app, source="sec_edgar", quarter=3)
    if case == "equal":
        sec = statements(app, source="sec_edgar", quarter=2)
        sec["quarter"][-1]["revenue"] = 999
    elif case == "older_quarter":
        sec = statements(app, source="sec_edgar", quarter=1)
    elif case == "older_annual":
        sec = statements(app, source="sec_edgar", annual_year=2024)
    elif case == "missing_date":
        sec["quarter"][-1]["date"] = None
    elif case == "missing_ocf":
        sec["quarter"][-1]["ocf"] = None
    elif case == "missing_net_income":
        sec["quarter"][-1]["net_income"] = None
    elif case == "unavailable":
        sec = {"ok": False}
    elif case == "raises":
        app.fetch_us_financials_sec.side_effect = RuntimeError("PRIVATE_PROVIDER_DETAIL")
    app.fetch_us_financials_sec.return_value = sec
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["save_ok"] and meta["source"] == "fmp"
    assert meta["metrics"]["quarter_records"] == fmp["quarter"]
    assert meta["notes"]["provider_comparison"]["status"] == status
    assert "PRIVATE_PROVIDER_DETAIL" not in str(meta)
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_newer_than_fmp_but_older_than_saved_sec_does_not_replace_saved(refresh_app):
    app = refresh_app
    save_baseline(app, statements(app, quarter=4))
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", quarter=3)
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["refresh_status"] == "stale" and "regresses_saved" in meta["refresh_error"]
    assert meta["metrics"]["quarter_latest"]["date"] == "2026-12-31"
    app.upsert_fin_score_db.assert_not_called()
    app.fetch_us_financials_sec.assert_called_once_with("GOOGL")


def test_verified_zero_is_not_missing_in_newer_sec_statements(refresh_app):
    app = refresh_app
    fmp = statements(app, quarter=1)
    save_baseline(app, fmp)
    app.fetch_us_financials_fmp.return_value = fmp
    sec = statements(app, source="sec_edgar", quarter=3)
    sec["quarter"][-1].update(ocf=0, net_income=0)
    app.fetch_us_financials_sec.return_value = sec
    _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
    assert meta["source"] == "sec_edgar" and meta["save_ok"]
    assert meta["metrics"]["quarter_latest"]["ocf"] == 0
    assert meta["metrics"]["quarter_latest"]["net_income"] == 0


def test_nonrefresh_auto_scoring_does_not_add_sec_comparison(refresh_app):
    app = refresh_app
    app.fetch_us_financials_fmp.return_value = statements(app, quarter=1)
    app.fetch_us_financials_sec.return_value = statements(app, source="sec_edgar", quarter=3)
    _, fin, _, _ = app.get_auto_fin_score_for_ticker("GOOGL", False)
    assert fin["source"] == "fmp"
    app.fetch_us_financials_sec.assert_not_called()
    app.load_fin_scores_db.assert_not_called()
    app.upsert_fin_score_db.assert_not_called()


def test_repeated_explicit_refresh_reuses_sec_cache_without_clearing_it(refresh_app):
    from stock_lab_core.result_cache import cache_result
    app = refresh_app
    fmp = statements(app, quarter=1)
    save_baseline(app, fmp)
    app.fetch_us_financials_fmp.return_value = fmp
    provider = Mock(return_value=statements(app, source="sec_edgar", quarter=3))

    @cache_result(ttl=21600)
    def cached_sec(ticker):
        return provider(ticker)

    cached_sec.clear()
    app.fetch_us_financials_sec = Mock(wraps=cached_sec)
    app.fetch_us_financials_sec.clear = Mock(side_effect=AssertionError("Refresh comparison must respect SEC cache"))
    try:
        for _ in range(2):
            _, meta = app.get_final_fin_score("GOOGL", False, "us_stock")
            assert meta["source"] == "sec_edgar"
        assert app.fetch_us_financials_sec.call_count == 2
        provider.assert_called_once_with("GOOGL")
        app.fetch_us_financials_sec.clear.assert_not_called()
    finally:
        cached_sec.clear()
