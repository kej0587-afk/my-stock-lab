"""Offline regressions for report display fixes 4/5/6 and public-flow context."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import re
import socket
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from stock_lab_core.market_guard_explanation import _guard_summary_lines, guard_explanation_lines
from stock_lab_core.market_observation import DEFAULT_SECTOR_MAP, build_sector_rotation
from stock_lab_core.public_market_data import FLOW_SOURCE, SOURCE
from stock_lab_core.report_account import (
    cumulative_account_decomposition, cumulative_account_metrics, cumulative_account_table,
)
from stock_lab_core.report_dashboard import current_state_lines
from stock_lab_core.report_intraday import latest_account_line
from stock_lab_core.report_observation_panel import observation_report_lines
from stock_lab_core.report_session import market_session_states


NOW = datetime(2026, 11, 2, 15, 36, tzinfo=ZoneInfo("Asia/Seoul"))
DAY = "2026-11-02"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Display must not acquire data")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def account():
    held = [{"ticker": "379810.KS", "current_w": 60}, {"ticker": "RAM", "current_w": 40}]
    context = {"sessions": {"KR": DAY, "US": "2026-10-30"}, "prices": {
        "379810.KS": {"date": DAY, "previous_date": "2026-10-30", "return": .02},
        "RAM": {"date": "2026-10-30", "previous_date": "2026-10-29", "return": -.25}},
        "extended_prices": {"RAM": {"date": DAY, "previous_date": "2026-10-30", "return": .10,
                                     "as_of": NOW.isoformat()}}}
    return held, context


def metrics(account):
    return cumulative_account_metrics(*account, market_session_states(NOW), NOW)


def test_split_is_compounding_consistent_and_all_surfaces_keep_same_total(account):
    original = deepcopy(account)
    result = metrics(account)
    assert result["components"] == pytest.approx({"US_REGULAR": -10, "US_SUBSEQUENT": 3, "KR": 1.2})
    assert sum(result["components"].values()) == pytest.approx(result["total"])
    assert result["total"] == pytest.approx(40 * ((1-.25)*(1+.10)-1) + 60*.02)
    assert result["regular_dates"] == ["2026-10-30"]
    assert account == original
    rendered = ["\n".join(cumulative_account_table(result)), latest_account_line(result),
                "\n".join(current_state_lines(account[1], market_session_states(NOW), NOW, result))]
    for out in rendered:
        assert "미국 2026-10-30 정규장 -10.00%p" in out
        assert "미국 야간·시간외 증분 +3.00%p" in out
        assert "연결분 합계 -5.80%p" in out
    assert "한국 상장 +1.20%p / 미국 상장 -7.00%p" in latest_account_line(result)


@pytest.mark.parametrize("defect", ["return", "previous_date", "date", "stale"])
def test_missing_regular_baseline_excludes_both_us_legs(account, defect):
    if defect == "stale":
        account[1]["prices"]["RAM"][defect] = True
    else:
        account[1]["prices"]["RAM"].pop(defect)
    result = metrics(account)
    assert result["coverage"] == 60
    assert result["components"] == {"US_REGULAR": None, "US_SUBSEQUENT": None, "KR": 1.2}
    assert result["total"] == pytest.approx(1.2)
    assert result["missing"] == ["RAM"]
    assert result["regular_dates"] == []
    out = "\n".join(cumulative_account_table(result))
    assert "미국 기준일 미연결 정규장 미연결(합산 제외)" in out
    assert "전체 추정 보류" in out


@pytest.mark.parametrize("defect", ["absent", "delayed", "stale"])
def test_closed_fallback_does_not_invent_zero_overnight(account, defect):
    if defect == "absent":
        account[1]["extended_prices"] = {}
    else:
        account[1]["extended_prices"]["RAM"][defect] = True
    result = metrics(account)
    assert result["components"]["US_REGULAR"] == -10
    assert result["components"]["US_SUBSEQUENT"] is None
    assert result["total"] == pytest.approx(-8.8)
    assert "미국 야간·시간외 증분 미연결(합산 제외)" in cumulative_account_decomposition(result)


def test_zero_later_return_is_not_missing_and_all_missing_has_no_split(account):
    account[1]["extended_prices"]["RAM"]["return"] = 0
    assert metrics(account)["components"]["US_SUBSEQUENT"] == 0
    account[1]["prices"] = {}
    result = metrics(account)
    assert result["total"] is None
    assert all(value is None for value in result["components"].values())
    assert cumulative_account_decomposition(result) == ""


def test_display_rounding_is_labeled_reconciles_and_does_not_mutate():
    result = {"components": {"US_REGULAR": .334, "US_SUBSEQUENT": .334, "KR": .334}, "total": 1.002}
    original = deepcopy(result)
    out = cumulative_account_decomposition(result)
    values = [Decimal(value) for value in re.findall(r"([+-]\d+\.\d+)%p", out)]
    assert sum(values[:-1]) == values[-1]
    assert "표시 반올림 조정" in out
    assert "기준일 미연결" in out
    assert result == original


@pytest.fixture
def guard():
    stats = {"circuit_day": 0, "panic_day": 0, "below20": 4, "below50": 4,
             "down3": 0, "weak5": 0, "sharp_day": 0}
    return {"score": 9, "mode": "위험", "tactical_rebound": False,
            "kr_stats": dict(stats, score=4), "us_stats": dict(stats, score=5, below20=5, below50=6, sharp_day=5),
            "mode_score_parts": {"regional": 5, "flow": 2, "macro": 2, "event": 0, "combined": 0},
            "flow_breadth": .276, "flow_accel": .495, "macro_pressure": 4, "macro_risk": 1,
            "macro_score": 2, "event_score": 0, "event_risk": 0,
            "circuit_day": 0, "panic_day": 0, "strong_rebound_count": 0, "max_day_gain": .0224}


def test_guard_summary_is_two_lines_with_actual_contributions_and_nearest_boundaries(guard):
    original = deepcopy(guard)
    summary = _guard_summary_lines(guard)
    assert len(summary) == 2
    assert "통합 9점 = 지역 최대 5 + 흐름 2 + 매크로 2" in summary[0]
    assert "최소 2점 감소" in summary[0]
    assert "27.6%·+2점 → 35% 이상(+7.4%p)" in summary[1]
    assert "부담 4 → 4 미만" in summary[1]
    assert "가속 49.5/50% 미달" in summary[1]
    out = "\n".join(guard_explanation_lines(guard))
    assert "+0.5%p 필요" in out
    assert "+3% 반등 지수 0 (2개 추가 필요)" in out
    assert "최대 상승 2.2% (+2.8%p 필요)" in out
    assert "다음 완화: 3개 미만까지 3개 회복" in out
    assert guard == original


@pytest.mark.parametrize("changes,missing", [
    ({"flow_accel": .5, "strong_rebound_count": 2}, False),
    ({"flow_breadth": .55, "max_day_gain": .05}, False),
    ({"flow_accel": .499999, "strong_rebound_count": 2}, True),
])
def test_tactical_thresholds_remain_exact_and_or_alternatives_work(guard, changes, missing):
    guard.update(changes)
    out = "\n".join(guard_explanation_lines(guard))
    assert ("미달/미확인: 없음" not in out) is missing
    assert "전술 반등 예외 현재: 미충족" in out  # Never override the supplied decision.
    if missing:
        assert "+0.1%p 미만 필요" in out


def test_missing_guard_components_and_tactical_inputs_are_not_zero(guard):
    guard["mode_score_parts"].pop("macro")
    for key in ("flow_breadth", "flow_accel", "strong_rebound_count", "max_day_gain", "panic_day"):
        guard.pop(key)
    out = "\n".join(guard_explanation_lines(guard))
    assert "매크로 미연결" in out
    assert "확산/가속 미연결" in out
    assert "-5% 급락 미연결개" in out
    assert "미연결·확인 필요" in out


@pytest.mark.parametrize("missing", [None, float("nan")])
def test_null_score_component_is_explicit_in_summary_and_detail(guard, missing):
    guard["mode_score_parts"]["macro"] = missing
    out = "\n".join(guard_explanation_lines(guard))
    assert "매크로 미연결" in out and "macro 미연결" in out


def rotation_context(count=10):
    dates = pd.bdate_range(end=DAY, periods=130)
    frames = {"^KS11": pd.DataFrame({"Close": 100.0}, index=dates)}
    tickers = [ticker for ticker, meta in DEFAULT_SECTOR_MAP.items() if meta["market"] == "KR"]
    for i, ticker in enumerate(tickers[:count]):
        frames[ticker] = pd.DataFrame({"Close": [100 * (1+i*.001)**n for n in range(len(dates))]}, index=dates)
    return {"sessions": {"KR": DAY}, "price_frames": frames}, tickers


@pytest.mark.parametrize("count", range(11))
def test_small_universe_top_bottom_are_disjoint_even_with_ties(count):
    context, tickers = rotation_context(count)
    for ticker in tickers[:count]:
        context["price_frames"][ticker]["Close"] = 100
    result = build_sector_rotation(context["price_frames"], sessions=context["sessions"], as_of=NOW)
    market = result["markets"].get("KR", {})
    top = [row["ticker"] for row in market.get("top3", [])]
    bottom = [row["ticker"] for row in market.get("bottom3", [])]
    assert len(top) == min(3, (count+1)//2)
    assert len(bottom) == min(3, count//2)
    assert not set(top) & set(bottom)
    assert top == sorted(tickers[:count])[:len(top)]


def test_kr_four_valid_six_pending_report_explains_every_exclusion():
    context, tickers = rotation_context()
    for ticker in tickers[4:]:
        context["price_frames"][ticker].attrs.update(report_close_pending_date=DAY,
                                                     report_close_pending_reason="해당 종목의 유효한 마감 응답 미확인")
    out = "\n".join(observation_report_lines(context, [], [], NOW))
    assert "KR 유효 4개 / KR 제외 6개" in out
    for ticker in tickers[4:]:
        assert f"{ticker} | {DAY} | 당일 종가 확인 대기 · 해당 종목의 유효한 마감 응답 미확인" in out
    assert out.count("KR 상위 |") == out.count("KR 하위 |") == 2
    for ticker in tickers[4:]:
        assert context["price_frames"][ticker].attrs["report_close_pending_date"] == DAY


@pytest.mark.parametrize("defect,detail", [("absent", "missing_asset_history"),
    ("stale", "missing_asset_close"), ("gap", "missing_aligned_21_session_history"),
    ("benchmark", "missing_benchmark_close"), ("short", "insufficient_benchmark_history"),
    ("basis", "missing_shared_price_basis")])
def test_rotation_exclusion_reason_identifies_actual_missing_evidence(defect, detail):
    context, tickers = rotation_context(1)
    frames, ticker = context["price_frames"], tickers[0]
    if defect == "absent":
        frames.pop(ticker)
    elif defect == "stale":
        frames[ticker] = frames[ticker].iloc[:-1]
    elif defect == "gap":
        frames[ticker] = frames[ticker].drop(frames[ticker].index[-8])
    elif defect == "benchmark":
        frames["^KS11"] = frames["^KS11"].iloc[:-1]
    elif defect == "short":
        frames = {key: frame.tail(10) for key, frame in frames.items()}
    elif defect == "basis":
        frames[ticker] = frames[ticker].rename(columns={"Close": "Adj Close"})
    result = build_sector_rotation(frames, sessions=context["sessions"], as_of=NOW,
                                   sector_map={ticker: DEFAULT_SECTOR_MAP[ticker]})
    row = result["excluded"][0]
    assert row["detail"] == detail
    assert row["market"] == "KR" and row["date"] == DAY
    assert result["markets"] == {}


@pytest.fixture
def public_context():
    def observation(value):
        return {"ok": True, "status": "available", "source": SOURCE, "source_url": FLOW_SOURCE,
                "is_mock": False, "asof": DAY, "fetched_at": NOW.isoformat(), "unit": "억원", "value": value}
    return {"sessions": {"KR": DAY}, "market_evidence_checked_at": NOW.isoformat(),
            "prices": {"396500.KS": {"date": DAY, "return": .0414}},
            "public_market_evidence": {"flows": {"KOSPI": {
                "foreign": observation(1234), "institution": observation(-567)}}}}


def test_public_provenance_survives_four_column_panel_and_background_is_narrow(public_context):
    original = deepcopy(public_context)
    out = "\n".join(observation_report_lines(public_context, [], [], NOW))
    assert f"[출처]({FLOW_SOURCE})" in out
    assert "조회 " + NOW.isoformat() in out
    assert "한국 반도체(396500.KS) +4.14%(2026-11-02) / 같은 날 KOSPI 외국인 +1,234.00억원·기관 -567.00억원" in out
    assert "시장 전체 수급, 반도체 매수액/상승 원인으로 확정하지 않음" in out
    assert public_context == original


@pytest.mark.parametrize("defect", ["flow_date", "price_date", "price_stale", "missing", "mock", "fetched", "unit"])
def test_background_requires_both_valid_public_flows_and_same_price_date(public_context, defect):
    institution = public_context["public_market_evidence"]["flows"]["KOSPI"]["institution"]
    if defect == "flow_date":
        institution["asof"] = "2026-10-30"
    elif defect == "price_date":
        public_context["prices"]["396500.KS"]["date"] = "2026-10-30"
    elif defect == "price_stale":
        public_context["prices"]["396500.KS"]["stale"] = True
    elif defect == "missing":
        institution["value"] = None
    elif defect == "mock":
        institution["is_mock"] = True
    elif defect == "fetched":
        institution["fetched_at"] = "2026-11-02T15:20:00+09:00"
    elif defect == "unit":
        institution["unit"] = "KRW"
    out = "\n".join(observation_report_lines(public_context, [], [], NOW))
    assert "같은 날 KOSPI" not in out
