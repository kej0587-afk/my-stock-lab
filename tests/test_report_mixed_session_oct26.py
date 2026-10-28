"""Synthetic Oct 26 observations; no pasted review values are treated as live data."""

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from stock_lab_core.report_intraday import (
    account_overview_lines,
    extended_quote_text,
    intraday_account_metrics,
    latest_account_line,
    latest_account_metrics,
    layered_market_headline,
)
from stock_lab_core.report_session import market_session_states


NOW = datetime.fromisoformat("2026-10-26T23:15:00+09:00")
HELD = [{"티커": "0167A0.KS", "현재비중": 60}, {"티커": "DRAM", "현재비중": 40}]


def quote(now, move=.03, *, previous="2026-10-23", date="2026-10-26"):
    return {"date": date, "previous_date": previous, "return": move, "as_of": now.isoformat(),
            "source": "synthetic quote"}


def context_at(now=NOW):
    context = {
        "sessions": {"KR": "2026-10-26", "US": "2026-10-23"},
        "prices": {
            "^KS11": {"date": "2026-10-26", "previous_date": "2026-10-23", "return": .01, "previous_return": -.02},
            "396500.KS": {"date": "2026-10-26", "previous_date": "2026-10-23", "return": -.01},
            "0167A0.KS": {"date": "2026-10-26", "previous_date": "2026-10-23", "return": .02},
            "DRAM": {"date": "2026-10-23", "previous_date": "2026-10-22", "return": -.05},
            "SOXX": {"date": "2026-10-23", "return": -.01, "previous_return": -.02},
        },
        "intraday_prices": {"DRAM": quote(now), "SOXX": quote(now, .04)},
        "extended_prices": {"DRAM": quote(now, .99), "SOXX": quote(now, .98)},
    }
    return context, market_session_states(now, context["sessions"])


def test_kr_close_plus_us_regular_once_per_holding_without_changing_original_estimates():
    context, states = context_at()
    before = deepcopy((HELD, context, states))
    live_before = intraday_account_metrics(HELD, context["intraday_prices"], context["extended_prices"], states=states, now=NOW)
    result = latest_account_metrics(HELD, context, states, NOW)
    assert result["total"] == pytest.approx(2.4)
    assert result["coverage"] == 100 and not result["missing"]
    assert result["by_market"] == pytest.approx({"KR": 1.2, "US": 1.2})
    assert result["groups"]["KR_CLOSE"]["count"] == result["groups"]["US"]["count"] == 1
    assert result["groups"]["US_EXT"]["count"] == result["groups"]["US_CLOSE"]["count"] == 0
    assert set(result["observations"]) == {"0167A0.KS", "DRAM"}
    assert result["observations"]["DRAM"]["source"] == "synthetic quote"
    assert (HELD, context, states) == before
    assert live_before == intraday_account_metrics(HELD, context["intraday_prices"], context["extended_prices"], states=states, now=NOW)
    assert live_before["total"] == pytest.approx(1.2) and live_before["coverage"] == 40


@pytest.mark.parametrize("clock,previous", [
    ("2026-10-26T16:00:00+09:00", "2026-10-23"),
    ("2026-10-26T20:00:00+09:00", "2026-10-23"),
    ("2026-10-27T06:00:00+09:00", "2026-10-26"),
])
def test_kr_close_plus_us_extended_day_pre_and_after_market(clock, previous):
    now = datetime.fromisoformat(clock)
    context, _ = context_at(now)
    context["sessions"]["US"] = previous
    context["extended_prices"]["DRAM"] = quote(now, -.01, previous=previous)
    states = market_session_states(now, context["sessions"])
    result = latest_account_metrics(HELD, context, states, now)
    assert result["total"] == pytest.approx(.8) and result["coverage"] == 100
    assert result["groups"]["US_EXT"]["contribution"] == pytest.approx(-.4)
    assert result["groups"]["US"]["count"] == 0
    line = latest_account_line(result, compact=True)
    assert "한국 확정 종가 +1.20%p" in line and "미국 데이마켓·시간외 -0.40%p" in line
    assert "2026-10-26" in line
    assert f"기준 종가 {previous}" in latest_account_line(result)


@pytest.mark.parametrize("change", [
    {"as_of": (NOW - timedelta(minutes=16)).isoformat()},
    {"as_of": (NOW + timedelta(seconds=1)).isoformat()},
    {"as_of": ""}, {"date": "2026-10-23"}, {"previous_date": "2026-10-22"},
    {"return": float("nan")}, {"return": float("inf")}, {"stale": True},
])
def test_unusable_us_regular_falls_back_only_to_explicitly_dated_closed_group(change):
    context, states = context_at()
    context["intraday_prices"]["DRAM"].update(change)
    result = latest_account_metrics(HELD, context, states, NOW)
    assert result["groups"]["US"]["count"] == 0
    assert result["groups"]["US_CLOSE"]["dates"] == ["2026-10-23"]
    assert result["total"] == pytest.approx(-.8)
    line = latest_account_line(result, compact=True)
    assert "미국 확정 종가 -2.00%p" in line and "2026-10-23" in line
    assert "미국 정규장" not in line


@pytest.mark.parametrize("change", [
    {"as_of": "2026-10-26T19:39:00+09:00"},
    {"as_of": "2026-10-26T20:01:00+09:00"},
    {"as_of": ""}, {"date": "2026-10-23"}, {"previous_date": "2026-10-22"},
    {"delayed": True}, {"stale": True},
])
def test_invalid_extended_is_not_current_even_with_delayed_reference(change):
    now = NOW.replace(hour=20, minute=0)
    context, states = context_at(now)
    context["extended_prices"]["DRAM"].update(change)
    context["extended_reference_prices"] = {"DRAM": quote(now, .8)}
    result = latest_account_metrics(HELD, context, states, now)
    assert result["groups"]["US_EXT"]["count"] == 0
    assert result["observations"]["DRAM"]["group"] == "US_CLOSE"


def test_fresh_timestamp_from_previous_window_is_not_current_regular_or_extended():
    now = NOW.replace(hour=22, minute=32)
    context, states = context_at(now)
    context["intraday_prices"]["DRAM"] = quote(now - timedelta(minutes=5))
    assert latest_account_metrics(HELD, context, states, now)["groups"]["US"]["count"] == 0
    now = NOW.replace(hour=17, minute=2)
    context, states = context_at(now)
    context["extended_prices"]["DRAM"] = quote(now - timedelta(minutes=5))
    assert latest_account_metrics(HELD, context, states, now)["groups"]["US_EXT"]["count"] == 0


def test_overnight_accepts_ny_calendar_date_or_target_trade_date():
    now = datetime.fromisoformat("2026-10-27T10:00:00+09:00")
    context, _ = context_at(now)
    context["sessions"]["US"] = "2026-10-26"
    states = market_session_states(now, context["sessions"])
    for day in ("2026-10-26", "2026-10-27"):
        context["extended_prices"]["DRAM"] = quote(now, previous="2026-10-26", date=day)
        assert latest_account_metrics(HELD, context, states, now)["groups"]["US_EXT"]["count"] == 1


@pytest.mark.parametrize("bad", [{"date": "2026-10-22"}, {"stale": True}, {"return": None}, {"previous_date": "2026-10-26"}])
def test_invalid_closed_fallback_is_missing_not_zero(bad):
    context, states = context_at()
    context["intraday_prices"] = {}
    context["prices"]["DRAM"].update(bad)
    result = latest_account_metrics(HELD, context, states, NOW)
    assert result["coverage"] == 60 and result["missing_weight"] == 40
    assert result["missing"] == ["DRAM"] and result["by_market"]["US"] is None
    assert "전체 계좌 추정 보류" in latest_account_line(result)


def test_kr_active_missing_live_never_uses_previous_close_and_closed_requires_today():
    for hour in (10, 16):
        now = NOW.replace(hour=hour)
        context, _ = context_at(now)
        context["sessions"]["KR"] = "2026-10-23"
        context["prices"]["0167A0.KS"]["date"] = "2026-10-23"
        context["prices"]["0167A0.KS"]["previous_date"] = "2026-10-22"
        states = market_session_states(now, context["sessions"])
        result = latest_account_metrics(HELD[:1], context, states, now)
        assert result["total"] is None and result["coverage"] == 0
        assert result["missing"] == ["0167A0.KS"]


def test_kr_active_selects_valid_live_and_rejects_stale_live():
    now = NOW.replace(hour=10)
    context, _ = context_at(now)
    context["sessions"]["KR"] = "2026-10-23"
    context["intraday_prices"]["0167A0.KS"] = quote(now, -.01)
    states = market_session_states(now, context["sessions"])
    assert latest_account_metrics(HELD[:1], context, states, now)["total"] == pytest.approx(-.6)
    context["intraday_prices"]["0167A0.KS"]["as_of"] = (now - timedelta(minutes=16)).isoformat()
    assert latest_account_metrics(HELD[:1], context, states, now)["total"] is None


@pytest.mark.parametrize("held", [
    HELD + HELD[:1], [HELD[1], {"ticker": "dram", "current_w": 1}],
    [{"ticker": "DRAM"}], [{"current_w": 30}], [{"ticker": "DRAM", "current_w": -1}],
    [{"ticker": "DRAM", "current_w": 101}], [{"ticker": "DRAM", "current_w": float("nan")}],
    [{"ticker": "DRAM", "current_w": float("inf")}],
    [{"ticker": "DRAM", "current_w": 60}, {"ticker": "SOXX", "current_w": 41}],
])
def test_duplicate_missing_and_invalid_weights_fail_closed(held):
    context, states = context_at()
    result = latest_account_metrics(held, context, states, NOW)
    assert result.get("error") and "보류" in latest_account_line(result)


def test_all_closed_zero_valid_return_and_no_valid_observation_are_distinct():
    now = datetime.fromisoformat("2026-10-27T06:00:00+09:00")
    context, _ = context_at(now)
    context["sessions"]["US"] = "2026-10-26"
    context["prices"]["DRAM"].update(date="2026-10-26", previous_date="2026-10-23", **{"return": -.03})
    context["intraday_prices"] = context["extended_prices"] = {}
    states = market_session_states(now, context["sessions"])
    result = latest_account_metrics(HELD, context, states, now)
    assert result["total"] == pytest.approx(0) and result["coverage"] == 100
    assert result["groups"]["US_CLOSE"]["count"] == 1 and result["earliest"] == ""
    context["prices"]["0167A0.KS"]["return"] = 0
    result = latest_account_metrics(HELD[:1], context, states, now)
    assert result["total"] == 0 and "+0.00%p" in latest_account_line(result)
    context["prices"] = {}
    result = latest_account_metrics(HELD, context, states, now)
    assert result["total"] is None and "0%가 아님" in latest_account_line(result)
    assert "+0.00%p" not in latest_account_line(result)


def test_overview_prepends_combined_and_dated_breakdown_without_replacing_existing_rows():
    context, states = context_at()
    live = intraday_account_metrics(HELD, context["intraday_prices"], states=states, now=NOW)
    latest = latest_account_metrics(HELD, context, states, NOW)
    closed = {"daily": -.8, "coverage": 100, "by_market": {"KR": 1.2, "US": -2}, "concentration": 0}
    old = account_overview_lines(live, closed, context["sessions"], "closed")
    new = account_overview_lines(live, closed, context["sessions"], "closed", latest_metrics=latest)
    assert new[2].startswith("최신 관측 통합 계좌 추정 | +2.40%p")
    assert all(line in new for line in old if not line.startswith("장중 연결분 기여"))
    live_row = next(line for line in new if line.startswith("장중 연결분 기여"))
    assert live_row.split(" | ")[:3] == next(line for line in old if line.startswith("장중 연결분 기여")).split(" | ")[:3]
    assert "전체는 위 통합행 참조" in live_row and "전체 계좌 추정 보류" not in live_row
    assert any("한국 확정 종가 | +1.20%p" in line and "2026-10-26" in line for line in new)
    assert any("미국 정규장 | +1.20%p" in line and "기준 종가 2026-10-23" in line for line in new)


def test_closed_headline_keeps_dated_kr_facts_us_regular_and_synthesis():
    context, states = context_at()
    metrics = latest_account_metrics(HELD, context, states, NOW)
    result = layered_market_headline(context, [], states, NOW, {}, latest_metrics=metrics,
                                    synthesis={"overview": "기존 근거 기반 종합 개요."})
    assert result.startswith("기존 근거 기반 종합 개요.")
    for part in ("[중기]", "[최근 2거래일]", "[한국 마감·미국 현재]", "코스피 +1.00%(2026-10-26 확정 종가)",
                 "한국 반도체 -1.00%(2026-10-26 확정 종가)", "SOL AI반도체 +2.00%(2026-10-26 확정 종가)",
                 "SOXX +4.00%", "DRAM +3.00%", "미국 정규장·미확정", "최신 관측 통합 계좌 영향 추정 +2.40%p",
                 "기존 판정을 유지합니다"):
        assert part in result
    assert "코스피 지수 장중 시세 미연결" not in result and "+99.00%" not in result


@pytest.mark.parametrize("clock", ["2026-10-26T08:00:00+09:00", "2026-10-26T10:00:00+09:00",
                                    "2026-10-26T20:00:00+09:00", "2026-10-25T12:00:00+09:00"])
def test_all_kr_modes_keep_three_layers(clock):
    now = datetime.fromisoformat(clock)
    context, states = context_at(now)
    result = layered_market_headline(context, [], states, now, {})
    current_label = {"intraday": "[장중]", "closed": "[한국 마감·미국 현재]"}.get(states["KR"]["phase"], "[정규장 외·현재]")
    assert all(label in result for label in ("[중기]", "[최근 2거래일]", current_label))
    if states["KR"]["phase"] == "intraday":
        assert "코스피 장중 시세 미연결" in result
    if now.hour == 20:
        assert "SOXX 시간외 +98.00%" in result and "DRAM 시간외 +99.00%" in result and "프리마켓" in result


def test_stale_us_regular_is_not_printed_as_current_in_headline():
    context, states = context_at()
    for obs in context["intraday_prices"].values():
        obs["as_of"] = (NOW - timedelta(hours=1)).isoformat()
    result = layered_market_headline(context, [], states, NOW, {})
    assert "미국 정규장: 시각이 검증된 시세 미확보" in result
    assert "DRAM +3.00%" not in result and "SOXX +4.00%" not in result


def test_source_dates_remain_explicit_when_us_live_and_closed_holdings_coexist():
    context, states = context_at()
    context["intraday_prices"]["DRAM"]["as_of"] = (NOW - timedelta(hours=1)).isoformat()
    held = [HELD[0], {"ticker": "DRAM", "current_w": 20}, {"ticker": "SOXX", "current_w": 20}]
    result = latest_account_metrics(held, context, states, NOW)
    assert result["total"] == pytest.approx(1)
    assert result["groups"]["US"]["dates"] == ["2026-10-26"]
    assert result["groups"]["US_CLOSE"]["dates"] == ["2026-10-23"]
    line = latest_account_line(result, compact=True)
    assert "미국 정규장 +0.80%p(2026-10-26)" in line
    assert "미국 확정 종가 -1.00%p(2026-10-23)" in line
    detail = latest_account_line(result)
    assert "미국 정규장 +0.80%p(비중 20.0%; 2026-10-26" in detail
    assert "미국 확정 종가 -1.00%p(비중 20.0%; 2026-10-23" in detail


def test_misaligned_daily_baseline_is_not_a_daily_return():
    context, states = context_at()
    context["news_sessions"] = {"KR": {"previous_date": "2026-10-23"}}
    context["prices"]["0167A0.KS"]["previous_date"] = "2026-10-22"
    assert latest_account_metrics(HELD[:1], context, states, NOW)["total"] is None


def test_invalid_extended_date_is_not_printed_as_current():
    now = NOW.replace(hour=20)
    context, states = context_at(now)
    for obs in context["extended_prices"].values():
        obs["date"] = "2026-10-23"
    result = layered_market_headline(context, [], states, now, {})
    assert "+99.00%" not in result and "+98.00%" not in result
    assert "시각이 검증된 시세 미확보" in result


@pytest.mark.parametrize("age", [2, 21])
def test_reference_only_extended_is_always_labeled_excluded_from_current_sum(age):
    now = NOW.replace(hour=20)
    context, states = context_at(now)
    context["extended_prices"] = {}
    context["extended_reference_prices"] = {"DRAM": quote(now - timedelta(minutes=age), .07)}
    line = extended_quote_text(context, "DRAM", now)
    assert "+7.00%" in line and "현재 합산 제외" in line
    result = latest_account_metrics(HELD, context, states, now)
    assert result["groups"]["US_EXT"]["count"] == 0
    assert result["observations"]["DRAM"]["group"] == "US_CLOSE"


@pytest.mark.parametrize("change", [{"date": "2026-10-23"}, {"previous_date": "2026-10-22"},
                                    {"as_of": "2026-10-26T20:16:00+09:00"}])
def test_invalid_extended_reference_is_hidden_not_just_excluded(change):
    now = NOW.replace(hour=20)
    context, _ = context_at(now)
    context["extended_prices"] = {}
    reference = quote(now, .07)
    reference.update(change)
    context["extended_reference_prices"] = {"DRAM": reference}
    assert extended_quote_text(context, "DRAM", now) == ""
