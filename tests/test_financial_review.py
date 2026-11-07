"""Financial review is read-only, and provider failures retain their cause."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core.financial_review import (
    DartProviderError, build_financial_review, stored_financial_diagnostic, sec_statement_coverage,
)


@pytest.mark.parametrize("manual", [None, 0, 4])
def test_review_preserves_scores_and_exposes_missing_inputs(manual):
    meta = {"auto_score": None, "manual_score": manual, "final_score": manual or 3}
    fin = {"ok": True, "source": "dart", "annual": [], "quarter": [
        {"fiscal_year": "2026", "fiscal_quarter": 2, "revenue": 100, "ocf": 0, "net_income": float('nan')} ]}
    before = deepcopy(meta)
    result = build_financial_review(meta, fin, checked_at="2026-11-07T00:00:00+00:00")
    assert meta == before
    assert result["저장 점수 기준"] == "보고기간 미저장"
    assert result["공급처 조회 기간"] == "분기 FY2026 Q2"
    assert result["원자료"][0]["영업현금흐름"] == 0
    assert result["원자료"][0]["순이익"] is None
    assert result["원자료"][0]["통화"] == "미확인"  # Do not infer reporting currency from listing country.
    assert "전체 반영 보장은 아님" in result["조회 상태"]
    assert (stored_financial_diagnostic(meta)["점수 적용"] == "수동 점수 우선") is (manual is not None)


def test_diagnostic_summarizes_failure_without_echoing_credentials():
    meta = {"auto_score": 3, "source": "fmp/sec_edgar", "notes": {"ok": False,
            "reason": "HTTP 402 https://example/?apikey=PRIVATE / SEC annual financials under 2 years"}}
    result = stored_financial_diagnostic(meta)
    assert "402" in result["입력 사유"] and "SEC" in result["입력 사유"]
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize("status", ["010", "020", "100", "900", "invalid"])
def test_dart_failure_is_not_empty_or_retried_for_every_year(app_module, monkeypatch, status):
    app = app_module
    monkeypatch.setattr(app, "get_dart_api_key", lambda: "PRIVATE")
    monkeypatch.setattr(app, "get_dart_corp_code", lambda code: "00126380")
    request = Mock(return_value=SimpleNamespace(raise_for_status=lambda: None,
        json=lambda: {"status": status, "message": "PRIVATE"}))
    monkeypatch.setattr(app.requests, "get", request)
    monkeypatch.setattr(app, "attach_krx_context_to_kr_failure", lambda ticker, source, reason: {"ok": False, "reason": reason})
    app.fetch_dart_finstate_all_raw.clear()
    app.fetch_kr_financials_auto.clear()
    result = app.fetch_kr_financials_auto("005930.KS")
    assert result["ok"] is False and "DART status" in result["reason"]
    assert "PRIVATE" not in result["reason"]
    assert request.call_count == 1


def test_dart_no_data_still_tries_separate_statements(app_module, monkeypatch):
    app = app_module
    monkeypatch.setattr(app, "get_dart_api_key", lambda: "test")
    monkeypatch.setattr(app, "get_dart_corp_code", lambda code: "test")
    request = Mock(side_effect=[SimpleNamespace(raise_for_status=lambda: None,
        json=lambda: {"status": "013"}), SimpleNamespace(raise_for_status=lambda: None,
        json=lambda: {"status": "000", "list": [{"account_nm": "매출액", "thstrm_amount": "100"}]})])
    monkeypatch.setattr(app.requests, "get", request)
    app.fetch_dart_finstate_all_raw.clear()
    result = app.fetch_dart_finstate_all_raw("005930", 2025, "11011")
    assert result.iloc[0]["fs_div"] == "OFS" and request.call_count == 2


def test_missing_ocf_uses_exact_standard_total_not_operating_subtotal(app_module):
    app = app_module
    frame = pd.DataFrame([
        {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperations", "account_nm": "영업활동에서 창출된 현금흐름", "thstrm_amount": "900"},
        {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "account_nm": "영업활동으로 인한 순현금흐름", "thstrm_amount": "700"},
        {"sj_div": "CF", "account_id": "ifrs-full_CashFlowsFromUsedInInvestingActivities", "account_nm": "투자활동 순현금흐름", "thstrm_amount": "-500"}])
    assert app.pick_dart_operating_cash_flow(frame, ["thstrm_amount"]) == 700
    assert pd.isna(app.pick_dart_operating_cash_flow(frame[frame.sj_div != 'CF'], ["thstrm_amount"]))
    frame.loc[1, "account_nm"] = "영업활동현금흐름"
    frame.loc[1, "thstrm_amount"] = "0"
    assert app.pick_dart_operating_cash_flow(frame, ["thstrm_amount"]) == 0


@pytest.mark.parametrize("ticker", ["005930.KS", "NBIS"])
def test_refresh_review_never_scores_or_persists(app_module, monkeypatch, ticker):
    app = app_module
    meta = {"auto_score": 2, "manual_score": 4, "final_score": 4}
    original = deepcopy(meta)
    corporate_map = Mock()
    corporate_map.clear = Mock()
    monkeypatch.setattr(app, "fetch_dart_corp_code_map", corporate_map)
    for name in ("fetch_kr_financials_auto", "fetch_us_financials_auto", "fetch_us_financials_fmp",
                 "fetch_us_financials_sec", "fetch_dart_finstate_all_raw"):
        fn = Mock(return_value={"ok": False, "source": "test"})
        fn.clear = Mock()
        monkeypatch.setattr(app, name, fn)
    monkeypatch.setattr(app, "get_sec_user_agent", lambda: "")
    forbidden = Mock(side_effect=AssertionError("Evidence review cannot change scores"))
    for name in ("get_final_fin_score", "get_auto_fin_score_for_ticker", "upsert_fin_score_db", "load_fin_scores_db"):
        monkeypatch.setattr(app, name, forbidden)
    result = app.inspect_financial_inputs(ticker, meta)
    assert "저장 점수 유지" in result["조회 상태"] and meta == original
    assert corporate_map.clear.call_count == int(ticker.endswith('.KS'))
    forbidden.assert_not_called()


def test_sec_foreign_forms_are_diagnosed_not_promoted_to_supported():
    facts = {"facts": {"ifrs-full": {"Revenue": {"units": {"USD": [{"form": "20-F"}, {"form": "6-K"}]}}}}}
    coverage = sec_statement_coverage(facts)
    assert coverage["limitation"] == "unsupported_statement_forms"
    assert coverage["namespaces"] == ["ifrs-full"]


def test_explicit_corporate_map_refresh_recovers_empty_response(app_module, monkeypatch):
    import io
    import zipfile
    app = app_module
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('CORPCODE.xml', '<result><list><corp_code>00123456</corp_code><stock_code>329180</stock_code></list></result>')
    monkeypatch.setattr(app, 'get_dart_api_key', lambda: 'test')
    request = Mock(side_effect=[SimpleNamespace(raise_for_status=lambda: None, content=b'not a zip'),
        SimpleNamespace(raise_for_status=lambda: None, content=payload.getvalue())])
    monkeypatch.setattr(app.requests, 'get', request)
    app.fetch_dart_corp_code_map.clear()
    assert app.get_dart_corp_code('329180') is None
    app.fetch_dart_corp_code_map.clear()
    assert app.get_dart_corp_code('329180') == '00123456'
    assert request.call_count == 2
