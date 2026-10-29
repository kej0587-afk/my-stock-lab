from types import SimpleNamespace

import pytest

from stock_lab_core.market_sentiment import parse_credit_spread, sentiment_evidence
from stock_lab_core.event_swing import EventSwingLedger, slot_check
from stock_lab_core.report_observation_panel import observation_report_lines
from stock_lab_core.report_session import kst_now
from datetime import datetime


@pytest.mark.parametrize("payload", [None, [], {}, {"observations": None}, {"observations": [None]}])
def test_bad_credit_payload_is_missing_not_zero(payload):
    assert not parse_credit_spread(payload, "2026-10-28")["ok"]


def test_credit_units_and_future_filter():
    payload = {"observations": [{"date": d, "value": v} for d, v in
        [("2026-10-25", "."), ("2026-10-26", "3.4"), ("2026-10-27", "3.3"), ("2026-10-29", "9")]]}
    result = parse_credit_spread(payload, "2026-10-28")
    assert result["value"] == 3.3 and result["change_bp"] == pytest.approx(-10)
    assert result["date"] == "2026-10-27"


def test_slot_never_grants_execution_and_default_is_unconfigured():
    assert slot_check(100, 95, 10, 1300, 0, True)["status"] == "건별 손실한도 미설정"
    assert slot_check(100, 95, 10, 1300, 100000, True)["loss_krw"] == 65000
    assert "매수 허용 아님" in slot_check(100, 95, 10, 1300, 100000, True)["status"]
    assert "초과" in slot_check(100, 95, 10, 1300, 10000, True)["status"]
    assert slot_check(100, 105, 10, 1300, 100000, True)["loss_krw"] is None


def test_missing_and_stale_flows_not_mistaken_for_risk_appetite():
    ctx = {"quote_checked_at": "2026-10-28T17:00:00+09:00", "market_observation_evidence": {
        "sector_kospi": {"ok": True, "fetched_at": "2026-10-27T15:00:00+09:00", "rows": [
            {"업종": "전체", "외국인 순매수(억원)": 10000, "기관 순매수(억원)": 10000}]}}}
    evidence = sentiment_evidence(ctx)
    assert "종합 상태 확정 보류" in evidence["state"]
    assert all(r["관측"] == "미연결" for r in evidence["rows"] if "순매수" in r["지표"])


def test_disconnected_journal_does_not_claim_saved():
    store = EventSwingLedger(None, "")
    assert store.load()[1]
    assert store.save("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", {}) is False


def test_report_extensions_are_pure_and_never_fake_event_samples():
    rows = [{"티커": "RAM", "게이트상태": "방어우선"}]
    result = "\n".join(observation_report_lines({}, rows, [], kst_now(datetime(2026, 10, 28, 17))))
    assert "표본 0건" in result and "현재 LLM 미연결" in result
    assert "기존 판정 유지 · 실행가능 0개" in result
    assert "스윙 슬롯" not in result
    assert rows == [{"티커": "RAM", "게이트상태": "방어우선"}]
