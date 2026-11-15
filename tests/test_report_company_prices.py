from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_lab_core import report_company_prices as target

NOW = datetime(2026, 11, 15, 20, tzinfo=ZoneInfo("Asia/Seoul"))
SESSIONS = {"US": "2026-11-13", "KR": "2026-11-13"}


def frame(values=(100., 110.), dates=("2026-11-12", "2026-11-13")):
    return pd.DataFrame({"Close": values}, index=pd.to_datetime(dates))


def benchmarks():
    return {ticker: {"date": "2026-11-13", "previous_date": "2026-11-12", "return": -.01}
            for ticker in ("^KS11", "^GSPC")}


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(target, "company_catalog", lambda _: {
        "MSFT": {"market": "US"}, "NVDA": {"market": "US"}, "005930.KS": {"market": "KR"}})


def test_catalog_excludes_new_funds_without_changing_issuer_catalog():
    rows = [{"티커": "0025N0.KS", "종목명": "TDF 2045 적격 엑티브"},
            {"티커": "SOXL", "종목명": "Direxion Semiconductor ETF"},
            {"티커": "NEWCO", "종목명": "New company"}]
    assert "0025N0.KS" in target.issuer_catalog(rows)  # report-only fix
    catalog = target.company_catalog(rows)
    assert {"MSFT", "NVDA", "005930.KS", "NEWCO"} <= catalog.keys()
    assert not {"0025N0.KS", "SOXL"} & catalog.keys()


def test_reuses_frames_fetches_only_missing_and_leaves_decision_inputs_untouched(small):
    original = {"MSFT": frame(), "QQQ": frame()}
    copy = {k: v.copy(deep=True) for k, v in original.items()}
    calls = []
    def load(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return {"NVDA": frame((100, 98)), "005930.KS": frame((100, 103))}
    base = benchmarks()
    result, diag = target.collect_company_prices([], original, base, SESSIONS, NOW, loader=load)
    assert calls == [(("005930.KS", "NVDA"), {"period": "1y", "max_workers": 4})]
    assert result["MSFT"]["return"] == pytest.approx(.1)
    assert diag["coverage"] == {"US": {"expected": 2, "connected": 2}, "KR": {"expected": 1, "connected": 1}}
    assert diag["reused_frames"] == 1
    assert base == benchmarks()
    assert original.keys() == copy.keys()
    for ticker in copy:
        pd.testing.assert_frame_equal(original[ticker], copy[ticker])


@pytest.mark.parametrize("dates", [("2026-11-11", "2026-11-12"), ("2026-11-11", "2026-11-13")])
def test_rejects_different_latest_or_previous_session(small, dates):
    result, _ = target.collect_company_prices([], {"MSFT": frame(dates=dates)}, benchmarks(), SESSIONS, NOW, allow_fetch=False)
    assert result["MSFT"]["return"] is None
    assert result["MSFT"]["stale"]


@pytest.mark.parametrize("invalid", [{"return": None}, {"stale": True}, {"previous_date": ""}])
def test_missing_or_stale_benchmark_cannot_certify_company_price(small, invalid):
    base = benchmarks()
    base["^GSPC"].update(invalid)
    result, _ = target.collect_company_prices([], {"MSFT": frame()}, base, SESSIONS, NOW, allow_fetch=False)
    assert result["MSFT"]["return"] is None


def test_injected_frames_never_fetch_and_future_bar_does_not_change_close(small):
    def unexpected(*a, **kw):
        pytest.fail("injected report inputs must not fetch")
    prices = {"MSFT": frame((100, 110, 999), ("2026-11-12", "2026-11-13", "2026-11-16"))}
    result, diag = target.collect_company_prices([], prices, benchmarks(), SESSIONS, NOW, allow_fetch=False, loader=unexpected)
    assert result["MSFT"]["return"] == pytest.approx(.1)
    assert result["NVDA"]["return"] is None
    assert diag["requested_symbols"] == 0


def test_fetch_error_retains_existing_prices_and_explains_gap(small):
    def failed(*a, **kw):
        raise TimeoutError("private request details")
    result, diag = target.collect_company_prices([], {"MSFT": frame()}, benchmarks(), SESSIONS, NOW, loader=failed)
    assert result["MSFT"]["return"] == pytest.approx(.1)
    assert diag["error"] == "TimeoutError"
    assert "private" not in str(diag)
    assert result["NVDA"]["return"] is None


def test_existing_large_move_guard_blocks_unverified_split(small):
    result, diag = target.collect_company_prices([], {"MSFT": frame((100, 30))}, benchmarks(), SESSIONS, NOW, allow_fetch=False)
    assert result["MSFT"]["return"] is None
    assert diag["issues"]


def test_old_app_contract_only_allows_exact_report_opt_in():
    import ast
    from tests.report_timing_ast_contract import before_report_timing
    def function(argument):
        return ast.parse("def _collect_today_report_context():\n    collect_report_context(rows" + argument + ")").body[0]
    assert ast.dump(before_report_timing(function(", include_company_prices=True"))) == ast.dump(function(""))
    with pytest.raises(AssertionError):
        before_report_timing(function(", include_company_prices=False"))
    # All other arguments stay visible to the original golden comparison.
    assert "changed_score" in ast.dump(before_report_timing(function(", changed_score=1, include_company_prices=True")))
