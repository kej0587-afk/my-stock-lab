"""Actuals never borrow consensus cells; calendar dates are not filing proof."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from stock_lab_core import news


@pytest.mark.parametrize("actual, expected", [(None, None), (0, 0.0), ("2.0", 0.02)])
def test_naver_actual_zero_and_missing_do_not_borrow_estimate(monkeypatch, actual, expected):
    periods = [{"key": "2025", "isConsensus": "N"}, {"key": "2026", "isConsensus": "Y"}]
    payload = {"financeInfo": {"trTitleList": periods, "rowList": [
        {"title": "ROE", "columns": {"2025": {"value": actual}, "2026": {"value": "25"}}},
        {"title": "EPS", "columns": {"2025": {"value": actual}, "2026": {"value": "5000"}}},
    ]}}
    monkeypatch.setattr(news, "_fetch_krx_fundamental_row", lambda *args: None)
    monkeypatch.setattr(news, "_HAS_REQUESTS", True)
    monkeypatch.setattr(news._requests, "get", lambda url, **kwargs: SimpleNamespace(
        status_code=200, json=lambda: payload if url.endswith("/finance/annual") else {}))
    news.fetch_naver_kr_snapshot.clear()
    result = news.fetch_naver_kr_snapshot("005930.KS")["data"]
    assert result.get("returnOnEquity") == expected
    assert result.get("trailingEps") == (None if actual is None else float(actual))


def test_naver_consensus_only_is_not_actual(monkeypatch):
    payload = {"financeInfo": {"trTitleList": [{"key": "2026", "isConsensus": "Y"}],
        "rowList": [{"title": "ROE", "columns": {"2026": "25"}}]}}
    monkeypatch.setattr(news, "_fetch_krx_fundamental_row", lambda *args: None)
    monkeypatch.setattr(news, "_HAS_REQUESTS", True)
    monkeypatch.setattr(news._requests, "get", lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: payload))
    news.fetch_naver_kr_snapshot.clear()
    assert "returnOnEquity" not in news.fetch_naver_kr_snapshot("005930.KS")["data"]


@pytest.mark.parametrize("now, scheduled, days", [
    ("2026-10-31T09:00:00+09:00", "2026-10-31", 1),
    ("2026-10-31T00:30:00+09:00", "2026-10-30", 0),
    ("2026-10-31T22:00:00+09:00", "2026-10-29", -2),
])
def test_earnings_calendar_uses_market_calendar_day(app_module, monkeypatch, now, scheduled, days):
    app = app_module
    monkeypatch.setattr(app, "get_kst_now", lambda: datetime.fromisoformat(now))
    monkeypatch.setattr(app.earnings_calendar_reader, "read", lambda *args: {
        "ok": True, "calendar": {"Earnings Date": [scheduled]}})
    app.fetch_earnings_date.clear()
    result = app.fetch_earnings_date("GOOGL")
    assert result["days_until"] == days
    assert result["high_risk"] is (0 <= days <= 7)
    if days < 0:
        assert "완료" not in result["label"]
        assert "미확인" in result["label"]


@pytest.mark.parametrize("saved", [False, True])
def test_manual_score_reports_save_failure(app_module, monkeypatch, saved):
    import pandas as pd
    app = app_module
    monkeypatch.setattr(app, "load_fin_scores_db", lambda: pd.DataFrame(columns=["ticker"]))
    monkeypatch.setattr(app, "upsert_fin_score_db", lambda **kwargs: saved)
    monkeypatch.setattr(app, "delete_manual_fin_score_db", lambda *args: saved)
    assert app.set_manual_fin_score("GOOGL", 2) is saved
    assert app.reset_manual_fin_score("GOOGL") is saved


def test_fmp_match_app_wiring_rejects_wrong_quarter(app_module):
    income = {"date": "2026-09-30", "calendarYear": "2026", "period": "Q3"}
    balance = {"date": "2026-03-31", "calendarYear": "2026", "period": "Q1"}
    assert app_module.find_fmp_match([balance], income) == {}


def test_nonadjacent_quarters_are_not_qoq(app_module):
    import numpy as np
    from stock_lab_core.financial_periods import adjacent_quarters
    before = {"fiscal_year": "2025", "report_code": "Q3", "revenue": 100}
    current = {"fiscal_year": "2026", "report_code": "Q1", "revenue": 120}
    assert not adjacent_quarters(before, current)
    _, _, _, metrics = app_module.build_fin_judgements({"quarter": [before, current]})
    assert np.isnan(metrics["derived"]["q_rev_growth"])
    assert adjacent_quarters(dict(before, report_code="Q4"), current)


def test_summary_ratios_above_one_are_not_small_percentages():
    from stock_lab_core.financial_score import estimate_kr_fin_score_from_naver_snapshot
    assert estimate_kr_fin_score_from_naver_snapshot({"returnOnEquity": 1.2}) == (
        estimate_kr_fin_score_from_naver_snapshot({"returnOnEquity": "120%"}))


def test_fiscal_report_code_is_not_displayed_as_calendar_date():
    from stock_lab_core.financial_freshness import financial_basis
    basis = financial_basis({"auto_score": 3, "metrics": {"quarter_latest": {
        "date": "2026-11014", "fiscal_year": "2026", "fiscal_quarter": 3}}})
    assert basis["재무자료기간"] == "분기 FY2026 Q3"


def test_missing_statement_fact_is_not_saved_as_bad_business(app_module, monkeypatch):
    app = app_module
    row = {"revenue": 100, "op_income": 10, "net_income": None, "ocf": 8, "equity": 50, "liabilities": 20}
    data = {"ok": True, "source": "sec_edgar", "annual": [row, row], "quarter": [row]}
    monkeypatch.setattr(app, "fetch_us_financials_auto", lambda *args: data)
    score, _, notes, metrics = app.get_auto_fin_score_for_ticker("GOOGL", False)
    assert notes["ok"] is False and notes["mode"] == "incomplete_statements"
    assert "annual: net_income" in notes["missing_inputs"]
    assert "quarter: net_income" in notes["missing_inputs"]
    assert notes["weighted_scores"] == {}


def test_core_statement_zero_is_known_and_finance_uses_appropriate_inputs():
    from stock_lab_core.financial_periods import missing_scoring_inputs
    row = dict.fromkeys(("revenue", "op_income", "net_income", "ocf", "equity", "liabilities"), 0)
    assert missing_scoring_inputs({"annual": [row], "quarter": [row]}) == []
    finance = {"annual": [{"net_income": 0, "equity": 100}], "quarter": [{"net_income": 0, "equity": 100}]}
    assert missing_scoring_inputs(finance, financial_business=True) == []
    assert missing_scoring_inputs(finance)
