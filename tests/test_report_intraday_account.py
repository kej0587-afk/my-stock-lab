"""Oct 21 report regressions: collection clock, real holding quotes and missingness."""
from copy import deepcopy
from datetime import datetime, timedelta

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_intraday import intraday_account_metrics, intraday_account_line
from stock_lab_core.report_session import market_session_states
from stock_lab_core.report_scenario import build_scenario_context, latest_futures_line, interval_observation

NOW = datetime.fromisoformat("2026-10-21T10:32:00+09:00")
SESSIONS = {"KR": "2026-10-20", "US": "2026-10-20"}


def case():
    # Rounded values from the supplied report; not a fresh account valuation.
    points = [("379810.KS", 30.30, 1.06), ("379800.KS", 32.26, .54), ("418660.KS", 6.12, 2.02),
              ("CIBR", 2.38, None), ("SOXL", 4.94, 8.46), ("0167A0.KS", 6.26, 4.94),
              ("RAM", 12.96, 7.19), ("0025N0.KS", .36, .48), ("BITX", 2.23, .63), ("MAGS", 2.13, .60)]
    held, live, extended = [], {}, {}
    for ticker, weight, change in points:
        held.append({"티커": ticker, "종목명": ticker + " 이름", "보유량": 1, "현재비중": weight,
                     "게이트상태": "방어우선", "최종읽기": "추가매수 보류"})
        if change is not None:
            obs = {"date": "2026-10-21", "return": change / 100, "as_of": NOW.isoformat(),
                   "kind": "데이마켓", "previous_date": "2026-10-20", "source": "fixture"}
            (live if ticker.endswith(".KS") else extended)[ticker] = obs
    return held, live, extended


def test_rounded_report_holdings_contribute_without_proxies_or_double_leverage():
    held, live, extended = case()
    result = intraday_account_metrics(held, live, extended, states=market_session_states(NOW), now=NOW)
    assert result["coverage"] == pytest.approx(97.56)
    assert result["groups"]["KR"]["contribution"] == pytest.approx(.92998)
    assert result["groups"]["US_EXT"]["contribution"] == pytest.approx(1.376577)
    assert result["total"] == pytest.approx(2.306557)
    assert result["missing"] == ["CIBR"]
    line = intraday_account_line(result)
    assert "한국 상장 +0.93%p" in line and "미국 데이마켓·시간외 +1.38%p" in line
    assert "장중 계좌 영향 추정 +2.31%p" in line and "97.6%" in line


def test_missing_not_zero_partial_not_full_and_stale_quotes_not_used():
    held, live, extended = case()
    assert "미연결" in intraday_account_line(intraday_account_metrics(held, {}, now=NOW))
    assert "0.00%p" not in intraday_account_line(intraday_account_metrics(held, {}, now=NOW))
    result = intraday_account_metrics(held, {}, extended, now=NOW)
    assert "전체 계좌 추정 보류" in intraday_account_line(result)
    assert intraday_account_metrics(held, live, extended, now=NOW + timedelta(minutes=21))["total"] is None
    assert intraday_account_metrics(held + held[:1], live, extended)["error"]
    untimed = deepcopy(live)
    for obs in untimed.values():
        obs["retrieved_at"] = obs.pop("as_of")
    assert intraday_account_metrics(held, untimed, now=NOW)["total"] is None


def test_full_report_has_three_layers_current_account_and_unchanged_decisions():
    held, live, extended = case()
    original = deepcopy(held)
    live["^KS11"] = {"date": "2026-10-21", "return": .0228, "as_of": NOW.isoformat()}
    context = {"sessions": SESSIONS, "intraday_prices": live, "extended_prices": extended,
               "prices": {"^KS11": {"date": "2026-10-20", "return": -.0373, "previous_return": .0176},
                          "SOXX": {"date": "2026-10-20", "return": -.0038, "previous_return": .0173, "return_5d": -.12}},
               "closed_flow_rows": [{"Ticker": "SOXX", "기준일": "2026-10-20", "3개월수익률": -.10}]}
    report = build_auto_market_memo(report_context=context, summary_rows=held, now=NOW)
    headline = report.split("## 한 줄 결론\n", 1)[1].split("\n## ", 1)[0]
    for part in ("[중기]", "3M -10.00%", "[최근 2거래일]", "+1.34%", "[장중]", "+2.28%", "+2.31%p"):
        assert part in headline
    assert "약세 지속" not in headline
    assert "개장 전 갭 시나리오 기여" not in report and "장전 대체 합산" not in report
    assert "미국 2026-10-21 장중 별도 추정" not in report
    assert held == original


def test_response_seconds_after_collection_start_is_not_future():
    from stock_lab_core.report_quotes import kr_index_observations
    received = NOW + timedelta(seconds=8)
    payload = {"time": int(received.timestamp() * 1000), "areas": [{"name": "SERVICE_INDEX", "datas": [
        {"cd": "KOSPI", "ms": "OPEN", "nv": 567934, "cv": 12660, "rf": "2"}]}]}
    payload["areas"].append({"name": "SERVICE_ITEM", "datas": [
        {"cd": "379810", "ms": "OPEN", "nv": 10200, "cv": 200, "pcv": 10000, "rf": "2"}]})
    assert not kr_index_observations(payload, NOW)
    frame = pd.DataFrame({"Close": [100, 99]}, index=pd.to_datetime(["2026-10-19", "2026-10-20"]))
    frames = {ticker: frame for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")}
    held = [{"티커": "379810.KS", "보유량": 1, "현재비중": 100}]
    context = collect_report_context(held, now=NOW, price_frames=frames, economic_releases=[],
                                     calendar={"events": [], "sources": []}, scenario_frames={},
                                     quote_data={"KR": payload, "US": {}, "retrieved_at": received.isoformat()})
    assert context["intraday_prices"]["^KS11"]["return"] == pytest.approx(.02279955)
    assert context["intraday_prices"]["379810.KS"]["price"] == 10200
    assert context["intraday_prices"]["379810.KS"]["return"] == pytest.approx(.02)
    assert context["intraday_prices"]["379810.KS"]["as_of"] == context["intraday_prices"]["^KS11"]["as_of"]
    report = build_auto_market_memo(report_context=context, summary_rows=held, now=NOW)
    assert "장중 계좌 영향 추정 +2.00%p" in report
    assert context["sessions"] == SESSIONS


def test_batched_future_nan_tail_uses_last_valid_bar_without_filling():
    index = pd.to_datetime(["2026-10-20T19:55:00Z", "2026-10-21T01:20:00Z", "2026-10-21T01:25:00Z"])
    frame = pd.DataFrame({"Close": [100, 101, float("nan")]}, index=index)
    original = frame.copy(deep=True)
    result = build_scenario_context({"NQ=F": frame}, SESSIONS, NOW)
    assert result["latest"]["NQ=F"]["return"] == pytest.approx(.01)
    assert "NQ=F +1.00%" in latest_futures_line(result)
    delayed = build_scenario_context({"NQ=F": frame}, SESSIONS, NOW + timedelta(minutes=10))
    assert not delayed["latest"]["NQ=F"]
    assert "마지막 유효 시각" in delayed["latest_status"]["NQ=F"]
    pd.testing.assert_frame_equal(frame, original)
    assert not interval_observation(frame, NOW, NOW)


def test_live_cumulative_comparison_includes_observed_kr_endpoint():
    from stock_lab_core.report_holdings import completed_scenario_comparison
    dates = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])
    frames = {"379810.KS": pd.DataFrame({"Close": [100, 101, 99]}, index=dates),
              "QQQ": pd.DataFrame({"Close": [100, 102, 101]}, index=dates)}
    obs = {"379810.KS": {"date": "2026-10-20", "return": -2 / 101},
           "QQQ": {"date": "2026-10-20", "previous_date": "2026-10-19", "return": -1 / 102}}
    live = {"379810.KS": {"date": "2026-10-21", "price": 103, "return": 103 / 99 - 1, "as_of": NOW.isoformat()}}
    scenario = {"379810.KS": pd.DataFrame({"Close": [103]}, index=pd.to_datetime(["2026-10-21T10:25:00+09:00"])),
                "NQ=F": pd.DataFrame({"Close": [100, 102]}, index=pd.to_datetime(["2026-10-20T15:25:00+09:00", "2026-10-21T10:25:00+09:00"]))}
    line = completed_scenario_comparison({"티커": "379810.KS"}, obs, SESSIONS, NOW, price_frames=frames, intraday_prices=live, scenario_frames=scenario)
    assert "장중·미확정" in line and "실제 +4.04%" in line and "NQ=F +2.00%" in line and "차이 +2.04%p" in line
    live["379810.KS"]["as_of"] = (NOW - timedelta(hours=1)).isoformat()
    line = completed_scenario_comparison({"티커": "379810.KS"}, obs, SESSIONS, NOW, price_frames=frames, intraday_prices=live)
    assert "누적 비교 보류" in line and "실제 +1.98%" not in line


def test_exact_measurement_timestamp_only():
    from stock_lab_core.report_build import completed_measurement_reference
    reference = {"measurement_id": "a", "measurement_finished_at": None}
    archive = {"a": {"measurement_id": "a", "measurement_finished_at": NOW.isoformat()},
               "b": {"measurement_id": "b", "measurement_finished_at": "future"}}
    assert completed_measurement_reference(reference, archive)["measurement_finished_at"] == NOW.isoformat()
    assert completed_measurement_reference(reference, {"b": archive["b"]})["measurement_finished_at"] is None


def test_current_news_priority_close_recap_grouping_and_no_empty_english_reading():
    from stock_lab_core.report_evidence import curate_news, korean_headline_reading
    def article(title, date, **extra):
        return dict(title=title, market="KR", session_date=date, publisher="뉴시스",
                    published_at=date + "T10:00:00+09:00", **extra)
    yesterday = article("코스피 3.73% 급락 마감", "2026-10-20")
    duplicate = article("코스피 5552.74, 3.73% 급락 마감…매도 우위", "2026-10-20")
    today = article("코스피 장중 2% 반등", "2026-10-21")
    rows = curate_news([yesterday, duplicate, today], now=NOW, limit=10, session_scoped=True)
    assert rows[0]["title"] == today["title"] and len(rows) == 2
    assert rows[1]["duplicate_count"] == 2
    assert rows[1]["related_articles"][0]["title"] == duplicate["title"]
    assert "관련 소식" not in korean_headline_reading({"title": "US equities in focus", "category": "시장 공통 배경"})
    # The same closing move groups across publishers without losing attribution.
    different = dict(duplicate, publisher="한국경제")
    cross_source = curate_news([yesterday, different], now=NOW, session_scoped=True)
    assert len(cross_source) == 1
    assert cross_source[0]["related_articles"][0]["publisher"] == "한국경제"
    buyers = article("코스피 3.73% 급락 마감, 연기금 저가 매수", "2026-10-20", link="https://newsis.com/buyers")
    grouped = curate_news([yesterday, buyers], now=NOW, session_scoped=True)
    assert "연기금 저가 매수" in grouped[0]["related_articles"][0]["title"]
    from stock_lab_core.report_evidence import report_sections
    seller = article("코스피 3.73% 하락 마감, 외국인 매도 확대", "2026-10-20", link="https://newsis.com/sellers")
    grouped = curate_news([seller, buyers], now=NOW, session_scoped=True)
    lines, _ = report_sections(context={"sessions": SESSIONS}, summary_rows=[], flow_rows=[], event_rows=[], news=grouped, now=NOW)
    report = "\n".join(lines)
    assert "https://newsis.com/sellers" in report and "https://newsis.com/buyers" in report


def test_retail_diagnostics_keep_safe_params_without_api_key():
    context = {"sessions": SESSIONS, "economic_releases": [{"indicator": "US_RETAIL_SALES", "unit": "%", "basis": "MoM",
        "actual": None, "status": "unavailable", "missing_reason": "http_403", "publication_status": "unconfirmed",
        "request_metadata": {"http_status": 403, "response_status": "http_error",
                             "parameters": {"category_code": "44X72", "key": "do-not-print-secret"}}}]}
    report = build_auto_market_memo(report_context=context, now=NOW)
    assert "소매판매 수집 진단: HTTP 403" in report and "44X72" in report
    assert "do-not-print-secret" not in report
