"""Replay close-basis disagreement across report, rotation and account display."""

from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.market_observation import build_sector_rotation
from stock_lab_core.report_account import cumulative_account_metrics, cumulative_account_table
from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_evidence import price_observation
from stock_lab_core.report_intraday import latest_account_line, layered_market_headline
from stock_lab_core.report_quotes import repair_kr_report_closes
from stock_lab_core.report_session import market_session_states


NOW = pd.Timestamp("2026-10-29T16:00:00+09:00")
DAY = "2026-10-29"


def daily(previous=96, close=99):
    dates = pd.bdate_range(end=DAY, periods=130)
    values = [80 + i / 10 for i in range(128)] + [previous, close]
    frame = pd.DataFrame({col: values for col in ("Open", "High", "Low", "Close")}, index=dates)
    frame["Volume"] = 1234
    frame.loc[dates[-1], ["Open", "High", "Low"]] = [97, 100, 95]
    frame.attrs["source"] = "Naver daily (HTTPS)"
    return frame


def payload(row=None, *, indices=False):
    row = row or {"cd": "396500", "ms": "CLOSE", "nv": 99, "cv": 3, "pcv": 960,
                  "rf": "2", "ov": 97, "hv": 100, "lv": 95, "aq": 1234}
    areas = [{"name": "SERVICE_ITEM", "datas": [row]}]
    if indices:
        index = dict(row, pcv=9600, nv=9900, ov=9700, hv=10000, lv=9500, cv=300)
        areas.append({"name": "SERVICE_INDEX", "datas": [dict(index, cd=code) for code in ("KOSPI", "KOSDAQ")]})
    return {"time": (NOW - pd.Timedelta(seconds=15)).timestamp() * 1000, "areas": areas}


@pytest.mark.parametrize("ticker,previous,bar,change,pcv", [
    ("379810.KS", 26319, [26165, 26172, 25830, 26060, 31812011], 260, 26390),
    ("379800.KS", 23210, [23245, 23255, 23060, 23185, 27637458], 25, 23325),
    ("0167A0.KS", 16190, [16175, 16575, 15495, 16025, 26848039], 165, 16190),
])
def test_oct29_same_ohlcv_confirms_existing_basis_not_quote_previous(ticker, previous, bar, change, pcv):
    frame = daily(previous, bar[3])
    frame.loc[DAY, ["Open", "High", "Low", "Close", "Volume"]] = bar
    before = frame.copy(deep=True)
    row = dict(zip(("ov", "hv", "lv", "nv", "aq"), bar), cd=ticker.split(".")[0],
               ms="CLOSE", cv=change, pcv=pcv, rf="5")
    fixed = repair_kr_report_closes({ticker: frame}, payload(row), NOW, tickers=(ticker,))[ticker]
    pd.testing.assert_frame_equal(fixed, before)
    pd.testing.assert_frame_equal(frame, before)
    assert frame.attrs == before.attrs
    assert not fixed.attrs.get("report_close_pending_date")
    assert fixed.attrs["report_close_verification"] == "daily_ohlcv_match"
    obs = price_observation(fixed, ticker, NOW)
    assert obs["date"] == DAY
    assert obs["return"] == pytest.approx(bar[3] / previous - 1)
    if pcv != previous:
        assert "기존 일봉 기준 유지" in obs["basis_note"]
    else:
        assert not obs["basis_note"]


@pytest.mark.parametrize("defect", ["partial", "volume", "no_volume", "open", "stale", "future", "no_day", "duplicate", "wrong_symbol", "high", "bad_close"])
def test_conflicting_quote_basis_cannot_confirm_only_a_matching_close(defect):
    frame, data = daily(), payload()
    row = data["areas"][0]["datas"][0]
    if defect == "partial":
        frame.loc[DAY, "Open"] = 98
    elif defect == "volume":
        frame.loc[DAY, "Volume"] = 12
    elif defect == "no_volume":
        frame = frame.drop(columns="Volume")
    elif defect == "open":
        row["ms"] = "OPEN"
    elif defect in {"stale", "future"}:
        data["time"] += (-300 if defect == "stale" else 300) * 1000
    elif defect == "no_day":
        frame = frame.iloc[:-1]
    elif defect == "duplicate":
        frame = pd.concat([frame, frame.iloc[[-1]]])
    elif defect == "wrong_symbol":
        row["cd"] = "000660"
    elif defect == "high":
        row["hv"] = 90
    elif defect == "bad_close":
        row["nv"] = float("nan")
    before = frame.copy(deep=True)
    fixed = repair_kr_report_closes({"396500.KS": frame}, data, NOW, tickers=("396500.KS",))["396500.KS"]
    pd.testing.assert_frame_equal(frame, before)
    assert price_observation(fixed, "396500.KS", NOW)["date"] != DAY


@pytest.mark.parametrize("unconfirmed", [False, True])
def test_shared_context_date_return_ranking_and_account_agree(unconfirmed):
    frames = {t: daily() for t in ("^KS11", "^KQ11", "396500.KS")}
    if unconfirmed:
        frames["396500.KS"].loc[DAY, "Volume"] = 1
    held = [{"ticker": "396500.KS", "current_w": 100, "qty": 1}]
    before = deepcopy(frames)
    ctx = collect_report_context(held, now=NOW, price_frames=frames,
                                 quote_data={"KR": payload(indices=True)},
                                 economic_releases=[], calendar={"events": [], "sources": []})
    rotation = build_sector_rotation(ctx["price_frames"], sessions=ctx["sessions"], as_of=NOW,
                                    sector_map={"396500.KS": {"market": "KR", "sector": "반도체", "kind": "sector_etf"}})
    metrics = cumulative_account_metrics(held, ctx, market_session_states(NOW, ctx["sessions"]), NOW)
    assert ctx["sessions"]["KR"] == DAY
    if unconfirmed:
        assert ctx["prices"]["396500.KS"]["date"] == "2026-10-28"
        assert not rotation["markets"]
        assert metrics["coverage"] == 0 and metrics["total"] is None
        assert "396500.KS" in metrics["missing"]
        assert any("전일가격 기준 불일치" in note for note in ctx["missing"])
    else:
        assert ctx["prices"]["396500.KS"]["date"] == DAY
        assert rotation["markets"]["KR"]["rows"][0]["date"] == DAY
        assert rotation["markets"]["KR"]["rows"][0]["rs_5d_change"] == pytest.approx(0)
        assert metrics["coverage"] == 100
        assert metrics["total"] == pytest.approx((99 / 96 - 1) * 100)
        assert ctx["price_basis_notes"] and "기존 일봉 기준 유지" in ctx["price_basis_notes"][0]
        from stock_lab_core.market_memo import build_auto_market_memo
        report = build_auto_market_memo(summary_rows=held, report_context=ctx, now=NOW)
        assert "가격 기준 확인:" in report and "기존 일봉 기준 유지" in report
    for ticker in frames:
        pd.testing.assert_frame_equal(frames[ticker], before[ticker])
        assert frames[ticker].attrs == before[ticker].attrs


@pytest.mark.parametrize("pending_ticker", ["396500.KS", "^KS11"])
@pytest.mark.parametrize("offset", [-1, -6])
def test_rotation_respects_pending_asset_and_benchmark_in_both_price_columns(pending_ticker, offset):
    frames = {t: daily() for t in ("^KS11", "396500.KS")}
    for frame in frames.values():
        frame["Adj Close"] = frame.Close
    frame = frames[pending_ticker]
    frame.attrs["report_close_pending_date"] = str(frame.index[offset].date())
    result = build_sector_rotation(frames, sessions={"KR": DAY}, as_of=NOW,
                                   sector_map={"396500.KS": {"market": "KR", "kind": "sector_etf"}})
    assert not result["markets"] and result["excluded"]


@pytest.mark.parametrize("coverage", [0, 33.9, 89.99, 90, 99.9, 100])
@pytest.mark.parametrize("cumulative", [True, False])
def test_headline_never_advertises_partial_contribution_as_whole_account(coverage, cumulative):
    metrics = {"total": .36, "coverage": coverage, "by_market": {"KR": -.18, "US": .54}, "groups": {}}
    if cumulative:
        metrics["basis"] = "completed_session_to_latest"
    before = deepcopy(metrics)
    line = latest_account_line(metrics, compact=True)
    if coverage < 90:
        assert "계좌 추정 보류" in line and "%p" not in line
        assert "+0.36%p" in latest_account_line(metrics)
        assert "연결분 기여(전체 추정 아님) | +0.36%p" in "\n".join(cumulative_account_table(metrics))
        assert "90.0%" not in line
    else:
        assert "+0.36%p" in line
    assert metrics == before


def test_layered_headline_hides_339_percent_partial_account():
    metrics = {"basis": "completed_session_to_latest", "total": .36, "coverage": 33.9,
               "by_market": {"KR": -.18, "US": .54}, "groups": {}}
    headline = layered_market_headline({}, [], market_session_states(NOW), NOW, {}, latest_metrics=metrics)
    assert "계좌 추정 보류(연결 33.9%" in headline
    assert "+0.36%p" not in headline and "+0.54%p" not in headline
