"""Offline regression tests for report-only oil/bond provenance."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_dashboard import market_board_lines
from stock_lab_core.report_energy_basis import (
    MISSING, REPORT_ONLY_DAILY, energy_basis_lines, energy_daily_observations,
    oil_discrepancy_warnings, rate_hike_probability_line,
)
from stock_lab_core.report_session import market_session_states

NOW = datetime.fromisoformat("2026-11-04T10:00:00+09:00")


def context():
    return {"macro_data": {"유가": {"val": 96.55, "day_ret": .0071, "chg": -3,
            "as_of": "2026-11-03", "previous_date": "2026-11-02",
            "as_of_at": "2026-11-03T16:00:00-05:00",
            "previous_as_of_at": "2026-11-02T16:00:00-05:00", "source": "Yahoo 5m"}}}


def article(**changes):
    return dict({"title": "WTI fell 7% over two days", "publisher": "Reuters",
                 "published_at": "2026-11-04T07:00:00+09:00",
                 "link": "https://www.reuters.com/markets/oil-test", "session_date": "2026-11-03", "market": "US"}, **changes)


def daily(values=(100, 99), dates=("2026-11-02", "2026-11-03")):
    frame = pd.DataFrame({key: values for key in ("Open", "High", "Low", "Close")}, index=pd.to_datetime(dates))
    frame.attrs["source"] = "Yahoo Finance daily fixture"
    return frame


def test_audit_four_columns_korean_missing_and_no_back_calculation():
    ctx = context()
    before = deepcopy(ctx)
    lines = energy_basis_lines(ctx, [article()], NOW)
    output = "\n".join(lines)
    assert "기준 | 현재·이전 | 등락·날짜 | 출처" in output
    assert all(line.count(" | ") == 3 for line in lines if " | " in line)
    assert "현재 96.55 / 이전 미연결" in output
    assert "+0.71%" in output and "2026-11-02T16:00:00-05:00" in output
    assert "공식 자료 미연결" in output and "계약월·롤오버 미확인" in output
    assert "금리 인상 확률: 미연결" in output
    assert "주의: 유가 방향 불일치" in output and "가격을 보정하지 않습니다" in output
    assert ctx == before and MISSING == "미연결"
    ctx["macro_data"]["유가"]["previous_val"] = 95.87
    assert "현재 96.55 / 이전 95.87" in "\n".join(energy_basis_lines(ctx, [], NOW))


@pytest.mark.parametrize("changes", [
    {"published_at": ""}, {"published_at": "2026-11-05T07:00:00+09:00"},
    {"published_at": "2026-10-01T07:00:00+09:00"}, {"link": "https://reuters.com.evil.test/oil"},
    {"session_date": "2026-11-02"}, {"title": "WTI may fall 7%"},
    {"title": "WTI rose while stocks fell 7%"},
])
def test_warning_rejects_undated_untrusted_stale_or_unrelated_claims(changes):
    assert not oil_discrepancy_warnings(context(), [article(**changes)], NOW)


def test_warning_uses_daily_reference_return_not_monthly_and_can_read_verified_body():
    ctx = context()
    ctx["macro_data"]["유가"].update(day_ret=-.01, chg=7)
    assert not oil_discrepancy_warnings(ctx, [article()], NOW)
    ctx["macro_data"]["유가"]["day_ret"] = .0071
    row = article(title="Oil market update", body_status="verified",
                  body_published_at="2026-11-04T07:00:00+09:00", body_modified_at="2026-11-04T07:00:00+09:00",
                  body_source_url="https://www.reuters.com/markets/oil-test",
                  body_facts=[{"topic": "oil_easing", "evidence": "WTI fell 7% over two days"}])
    assert oil_discrepancy_warnings(ctx, [row], NOW)
    for changes in ({"body_status": "unverified"}, {"body_published_at": ""},
                    {"body_modified_at": "2026-11-05T07:00:00+09:00"},
                    {"body_source_url": "https://www.reuters.com/markets/other"},
                    {"body_published_at": "2026-10-31T07:00:00+09:00"},
                    {"body_facts": [{"topic": "oil_easing", "evidence": "stocks fell 7%"}]}):
        assert not oil_discrepancy_warnings(ctx, [dict(row, **changes)], NOW)


def test_warning_merges_all_context_buckets_and_deduplicates_urls():
    ctx = context()
    row = article(market="KR", session_date="2026-11-04")
    for bucket in ("session_news", "next_session_news", "current_session_news", "other_market_news"):
        ctx[bucket] = [row]
        assert len(oil_discrepancy_warnings(ctx, [], NOW)) == 1
    before = deepcopy(ctx)
    assert len(oil_discrepancy_warnings(ctx, [row], NOW)) == 1
    assert ctx == before


def test_existing_1430_bar_is_never_official_settlement_and_must_be_completed():
    ctx = context()
    frame = pd.DataFrame({"Close": [96.56, 96.16]}, index=pd.to_datetime([
        "2026-11-02T14:25:00-05:00", "2026-11-03T14:25:00-05:00"]))
    frame.attrs["interval"] = "5m"
    ctx["scenario_frames"] = {"CL=F": frame}
    output = "\n".join(energy_basis_lines(ctx, [], NOW))
    assert "현재 96.16 / 이전 96.56" in output and "-0.41%" in output
    assert "WTI 14:30 완료봉 참고 · 정산가 아님" in output
    assert "공식 자료 미연결" in output
    before_close = datetime.fromisoformat("2026-11-03T14:29:00-05:00")
    assert "현재 96.16" not in "\n".join(energy_basis_lines(ctx, [], before_close))
    for invalid in (frame.tz_localize(None), frame.set_axis(frame.index + pd.Timedelta(minutes=1))):
        ctx["scenario_frames"]["CL=F"] = invalid
        assert "현재 96.16" not in "\n".join(energy_basis_lines(ctx, [], NOW))
    frame.attrs["interval"] = "1m"
    ctx["scenario_frames"]["CL=F"] = frame
    assert "현재 96.16" not in "\n".join(energy_basis_lines(ctx, [], NOW))


def test_daily_endpoints_single_row_missing_and_board_yield_bp():
    frames = {"CL=F": daily(), "BZ=F": daily([104.77], ["2026-11-02"]), "^TYX": daily([5.269, 5.324])}
    before = deepcopy(frames)
    observations = energy_daily_observations(frames, NOW)
    assert observations["BZ=F"]["price"] == 104.77
    assert observations["BZ=F"]["previous_price"] is None and observations["BZ=F"]["return"] is None
    assert observations["CL=F"]["previous_price"] == 100
    assert energy_daily_observations({}, NOW) == {"CL=F": {}, "BZ=F": {}, "^TYX": {}}
    ctx = dict(context(), energy_daily=observations)
    board = "\n".join(market_board_lines(ctx, market_session_states(NOW), NOW))
    assert "브렌트유(BZ=F)" in board and "104.77 USD/배럴" in board
    assert "미국 30년물 금리(^TYX)" in board and "+5.50bp" in board
    assert "2026-11-02 → 2026-11-03" in board and "Yahoo Finance daily fixture" in board
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], before[ticker])


def test_verified_external_evidence_is_explicit_and_stale_probability_historical():
    ctx = context()
    provenance = {"verified": True, "source": "CME", "source_url": "https://www.cmegroup.com/fixture",
                  "as_of": "2026-11-03T17:00:00-05:00"}
    ctx["oil_contract_metadata"] = {"CL=F": dict(provenance, contract_month="2026-12", rollover=True)}
    ctx["oil_settlements"] = {"CL=F": dict(provenance, contract_month="2026-12", kind="official_settlement", price=96, date="2026-11-03")}
    output = "\n".join(energy_basis_lines(ctx, [], NOW))
    assert "계약월 2026-12" in output and "롤오버 확인" in output
    assert "공식 자료 미연결" not in output and "가격 불일치 원인 확정 아님" in output
    ctx["oil_settlements"]["CL=F"]["verified"] = False
    assert "공식 자료 미연결" in "\n".join(energy_basis_lines(ctx, [], NOW))
    row = dict(provenance, as_of="2026-10-01T12:00:00-04:00", probability_pct=25,
               meeting_date="2026-10-28", basis="선물 내재확률")
    ctx["rate_hike_probability"] = row
    assert "과거 회의의 역사적 관측" in rate_hike_probability_line(ctx, NOW)
    assert "25.00%" in rate_hike_probability_line(ctx, NOW)
    for changes in ({"verified": False}, {"source_url": ""}, {"as_of": "2027-01-01"},
                    {"probability_pct": 101}, {"probability_pct": True}, {"meeting_date": ""}):
        ctx["rate_hike_probability"] = dict(row, **changes)
        assert "금리 인상 확률: 미연결" in rate_hike_probability_line(ctx, NOW)


def test_collection_adds_daily_only_no_live_rotation_or_macro_changes(monkeypatch):
    from stock_lab_core import prices, report_live, report_quotes, report_reference
    from stock_lab_core import market_observation, report_prices
    import requests

    def forbidden(*args, **kwargs):
        pytest.fail("Unexpected network call")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    dates = pd.bdate_range(end="2026-11-02", periods=25)
    calls, live_calls, quote_calls = [], [], []
    def batch(tickers, period):
        calls.append(tickers)
        return {ticker: daily(list(range(100, 125)), dates) for ticker in tickers}
    monkeypatch.setattr(prices, "load_price_frames_batch", batch)
    monkeypatch.setattr(prices, "load_price_df", lambda *args: daily(list(range(100, 125)), dates))
    monkeypatch.setattr(report_live, "supplement_kr_indices", lambda frames: frames)
    monkeypatch.setattr(report_live, "load_us_live_frames", lambda tickers: live_calls.append(tickers) or {})
    monkeypatch.setattr(report_quotes, "load_report_quotes", lambda tickers, **kwargs: quote_calls.append(tickers) or {})
    monkeypatch.setattr(report_reference, "load_macro_reference_frame", lambda *args: pd.DataFrame())
    before = deepcopy((market_observation.ROTATION_UNIVERSE, report_prices.MACRO_SYMBOLS))
    rows = [{"티커": "SOXX", "보유량": 1, "현재비중": 10, "게이트상태": "방어우선"}]
    original = deepcopy(rows)
    ctx = collect_report_context(rows, now=datetime.fromisoformat("2026-11-03T15:00:00-05:00"),
                                 economic_releases=[], calendar={"events": [], "sources": []})
    extra = set(REPORT_ONLY_DAILY)
    assert len(calls) == 1 and extra <= set(calls[0])
    assert live_calls and quote_calls
    assert all(not extra.intersection(call) for call in live_calls + quote_calls)
    for key in ("rotation_rows", "closed_flow_rows", "sector_rows"):
        assert not extra.intersection(row["Ticker"] for row in ctx[key])
    assert not extra.intersection(ctx["intraday_prices"])
    assert extra <= set(ctx["energy_daily"])
    assert not extra.intersection(row.get("symbol") for row in ctx["macro_data"].values())
    assert before == (market_observation.ROTATION_UNIVERSE, report_prices.MACRO_SYMBOLS)
    assert rows == original


def test_probability_uses_us_meeting_date_and_settlement_requires_completed_window():
    now = datetime.fromisoformat("2026-11-04T12:00:00-05:00")
    provenance = dict(verified=True, source="CME", source_url="https://www.cmegroup.com/fixture",
                      as_of=now.isoformat())
    ctx = dict(rate_hike_probability=dict(provenance, probability_pct=25, meeting_date="2026-11-04", basis="선물 내재확률"))
    assert "25.00%" in rate_hike_probability_line(ctx, now)
    ctx["oil_settlements"] = {"CL=F": dict(provenance, date="2026-11-04", contract_month="2026-12",
                                           kind="official_settlement", price=96)}
    assert "공식 자료 미연결" in "\n".join(energy_basis_lines(ctx, [], now))
    later = datetime.fromisoformat("2026-11-04T15:00:00-05:00")
    ctx["oil_settlements"]["CL=F"]["as_of"] = later.isoformat()
    assert "공식 자료 미연결" not in "\n".join(energy_basis_lines(ctx, [], later))
