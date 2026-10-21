"""Report-only quality checks. All prices and headlines here are synthetic."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_analysis import economic_story_dates, recent_economic_releases, sector_evidence
from stock_lab_core.report_evidence import curate_news, report_sections, reported_cause
from stock_lab_core.report_presentation import is_preopen_outlook, sector_related_news
from stock_lab_core.today_news import partition_session_market_news


NOW = datetime.fromisoformat("2026-10-20T22:00:00+09:00")


def quality_context():
    sessions = {"KR": "2026-10-20", "US": "2026-10-19"}
    frames = {symbol: pd.DataFrame({"Close": [100., 101., 102., 999.]}, index=pd.to_datetime(days))
              for symbol, days in (("^KS11", ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]),
                                   ("^GSPC", ["2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20"]))}
    return dict(sessions=sessions, price_frames=frames,
                prices={"^KS11": {"date": sessions["KR"], "return": -.0373},
                        "^GSPC": {"date": sessions["US"], "return": .01}})


def release(indicator="US_PPI", release_at="2026-10-16T08:30:00-04:00", **overrides):
    return dict(dict(indicator=indicator, period="2026-09", basis="MoM", unit="%", actual=1.3,
                     previous=.5, status="released", release_at=release_at, source="Fixture official release",
                     source_url="https://www.bls.gov/ppi/"), **overrides)


@pytest.mark.parametrize("indicator,at,accepted", [
    ("US_PPI", "2026-10-15T08:30:00-04:00", False),
    ("US_PPI", "2026-10-16T00:30:00+09:00", False),
    ("US_PPI", "2026-10-15", False),
    ("US_PPI", "2026-10-16T08:30:00-04:00", True),
    ("US_PPI", "2026-10-17T00:30:00+09:00", True),
    ("US_PPI", "2026-10-19T08:30:00-04:00", True),
    ("US_PPI", "2026-10-14T08:30:00-04:00", False),
    ("US_PPI", "2026-10-15T00:30:00+09:00", False),
    ("US_PPI", "2026-10-20T08:30:00-04:00", True),
    ("US_PPI", "2026-10-21T08:30:00-04:00", False),
    ("US_PPI", "", False),
    ("US_PPI", "2026-09", False),
    ("US_PPI", "invalid", False),
    ("KR_EXPORTS", "2026-10-16T09:00:00+09:00", True),
    ("KR_EXPORTS", "2026-10-20T09:00:00+09:00", True),
    ("KR_EXPORTS", "2026-10-15T09:00:00+09:00", False),
    ("KR_EXPORTS", "2026-10-20T23:00:00+09:00", False),
])
def test_story_uses_publication_date_and_local_generation_trading_date(indicator, at, accepted):
    context = quality_context()
    row = release(indicator, at)
    assert bool(recent_economic_releases([row], context, NOW)) == accepted


@pytest.mark.parametrize("status", ["pending", "scheduled", "예정", "stale"])
def test_unreleased_and_stale_values_cannot_become_current_stories(status):
    assert not recent_economic_releases([release(status=status)], quality_context(), NOW)


def test_us_holiday_calendar_and_kr_missing_history_do_not_use_stale_closes():
    context = dict(sessions={"US": "2026-07-06"}, price_frames={"^GSPC": pd.DataFrame(
        {"Close": [100., 101., 102.]}, index=pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-06"]))})
    now = datetime.fromisoformat("2026-07-07T08:00:00+09:00")
    assert economic_story_dates(context, "US", now) == ["2026-07-01", "2026-07-02", "2026-07-06"]
    assert recent_economic_releases([release(release_at="2026-07-01")], context, now)
    assert not recent_economic_releases([release(release_at="2026-06-30")], context, now)
    kr = dict(sessions={"KR": "2026-07-02"})
    assert economic_story_dates(kr, "KR", now) == []
    assert not recent_economic_releases([release("KR_CPI", "2026-07-01")], kr, now)


@pytest.mark.parametrize("at,days", [
    ("2026-10-20T22:00:00+09:00", ["2026-10-16", "2026-10-19", "2026-10-20"]),
    ("2026-10-18T22:00:00+09:00", ["2026-10-14", "2026-10-15", "2026-10-16"]),
    ("2026-07-03T22:00:00+09:00", ["2026-06-30", "2026-07-01", "2026-07-02"]),
])
def test_us_preopen_weekend_and_holiday_use_local_calendar(at, days):
    assert economic_story_dates(quality_context(), "US", datetime.fromisoformat(at)) == days


def test_nontrading_release_dates_and_unknown_dates_are_not_story_dates():
    now = datetime.fromisoformat("2026-07-06T22:00:00+09:00")
    for at in ("2026-07-03", "2026-07-04", "2026-07-05", ""):
        assert not recent_economic_releases([release(release_at=at)], {}, now)
    frame = pd.DataFrame({"Close": [100., 101., 102.]}, index=pd.to_datetime(["2026-10-06", "2026-10-07", "2026-10-08"]))
    context = dict(sessions={"KR": "2026-10-08"}, kr_is_trading_day=False, price_frames={"^KS11": frame})
    now = datetime.fromisoformat("2026-10-09T22:00:00+09:00")
    assert economic_story_dates(context, "KR", now) == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert not recent_economic_releases([release("KR_CPI", "2026-10-09")], context, now)


def test_old_future_and_undated_releases_stay_in_table_but_not_either_story_path():
    context = quality_context()
    context["economic_releases"] = [release("KR_EXPORTS", "", actual=83.7, basis="YoY"),
                                    release("US_NONFARM_PAYROLLS", "2026-10-02", actual=29, previous=133, unit="thousand persons"),
                                    release("US_CPI", "2026-10-14", actual=7.7),
                                    release("US_PPI", "2026-10-15", actual=1.3),
                                    release("US_CPI", "2026-10-21", actual=9.9),
                                    release("US_RETAIL_SALES", "2026-10-16", actual=.9)]
    before = deepcopy(context)
    report = build_auto_market_memo(report_context=context, now=NOW)
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    table = report.split("## 경제지표")[1].split("## 업종별 왜")[0]
    assert "83.7" not in story and "7.7" not in story and "9.9" not in story
    assert "미국 PPI" not in story and "비농업고용" not in story
    assert "미국 소매판매 전월비 0.9%" in story
    assert all(value in table for value in ("83.7", "7.7", "9.9", "0.9", "29천 명", "1.3%"))
    assert "최근 3거래일 이내 발표일" in story
    assert context["economic_releases"] == before["economic_releases"]
    for ticker, frame in context["price_frames"].items():
        pd.testing.assert_frame_equal(frame, before["price_frames"][ticker])


def sector_row(ticker="139250.KS", daily=-.0717):
    return {"Ticker": ticker, "기준일": "2026-10-20" if ticker.endswith(".KS") else "2026-10-19",
            "1일수익률": daily, "섹터": "에너지", "구분": "한국 섹터" if ticker.endswith(".KS") else "미국 섹터"}


def market_news(title="[마감] 코스피 AI 신용우려에 하락", **overrides):
    return dict(dict(title=title, publisher="연합뉴스", market="KR", session_date="2026-10-20",
                     news_bucket="session_news", link="https://www.yna.co.kr/view/quality-fixture",
                     published="2026-10-20T16:00:00+09:00", market_context_only=True), **overrides)


@pytest.mark.parametrize("ticker,daily,expected", [("139250.KS", -.0717, "-3.44%p"),
                                                  ("XLK", .025, "+1.50%p")])
def test_sector_excess_is_same_market_daily_return_in_percentage_points(ticker, daily, expected):
    result = sector_evidence(sector_row(ticker, daily), {}, [], observations=quality_context()["prices"])
    assert expected in result["excess"]
    assert ("^KS11" if ticker.endswith(".KS") else "^GSPC") in result["excess"]


@pytest.mark.parametrize("mismatch", ["date", "return", "kind"])
def test_missing_or_intraday_benchmark_cannot_produce_sector_excess(mismatch):
    observations = quality_context()["prices"]
    observations["^KS11"][mismatch] = {"date": "2026-10-19", "return": None, "kind": "장중 진행·확정 아님"}[mismatch]
    result = sector_evidence(sector_row(), {}, [], observations=observations)
    assert result["excess"].startswith("미확인:") and "-3.44%p" not in result["excess"]


@pytest.mark.parametrize("excess", [.0099, -.0099, .01, -.01])
def test_small_excess_uses_market_context_large_excess_requires_direct_article(excess):
    observations = quality_context()["prices"]
    row = sector_row(daily=observations["^KS11"]["return"] + excess)
    linked = [dict(market_news(), ticker=row["Ticker"])]
    result = sector_evidence(row, {}, linked, observations=observations)
    if abs(excess) < .01:
        assert "시장 공통 맥락" in result["reading"] and "직접 원인 아님" in result["reading"]
    else:
        assert "개별 원인 미확인" in result["reading"]
        assert "AI 신용우려" not in result["reading"]
    direct = dict(linked[0], title="한국 에너지주 실적 발표 후 하락", market_context_only=False)
    result = sector_evidence(row, {}, [linked[0], direct], observations=observations)
    assert direct["title"] in result["reading"] and "인과 기여 미확정" in result["reading"]


def test_broad_ai_wrap_is_indirect_for_technology_and_software():
    wrap = market_news("미국 AI주 중심 약세 마감", market="US", session_date="2026-10-19")
    for ticker in ("SOXX", "XLK", "IGV"):
        linked = sector_related_news(ticker, "2026-10-19", [wrap])
        assert linked and linked[0]["market_context_only"]


def test_sector_table_names_benchmark_and_report_only_threshold():
    context = quality_context()
    context["sector_rows"] = [sector_row()]
    context["session_news"] = [market_news()]
    report = build_auto_market_memo(report_context=context, now=NOW)
    table = report.split("## 업종별 왜")[1].split("## 관심 후보")[0]
    assert "시장 대비 초과수익" in table and "-3.44%p" in table
    assert "1.00%p" in table and "매매 임계값은 변경하지 않습니다" in table
    line = next(line for line in table.splitlines() if "에너지(139250.KS)" in line)
    assert "개별 원인 미확인" in line and "AI 신용우려" not in line


@pytest.mark.parametrize("symbols", [("NQ=F", "ES=F"), ("NQ=F",), ()])
def test_22h_preopen_futures_in_conclusion_and_next_check_with_missing_reason(symbols):
    context = quality_context()
    context["scenario_observations"] = {"latest": {symbol: dict(return_=-.01,
        as_of="2026-10-20T21:55:00+09:00") for symbol in symbols}}
    for item in context["scenario_observations"]["latest"].values():
        item["return"] = item.pop("return_")
    report = build_auto_market_memo(report_context=context, now=NOW)
    conclusion = report.split("## 한 줄 결론")[1].split("## 내 보유 종목 영향")[0]
    check = next(line for line in report.splitlines() if line.startswith("- 다음 체크:"))
    for section in (conclusion, check):
        for symbol in symbols:
            assert f"{symbol} -1.00%" in section and "21:55 KST" in section
        for symbol in {"NQ=F", "ES=F"} - set(symbols):
            assert f"{symbol} 미수집(" in section and "수집 실패/지연 또는 비교 시각 자료 미수집" in section


def test_close_report_excludes_korean_forecast_without_relabeling_us_close():
    context = quality_context()
    context["news_sessions"] = {"KR": {"date": "2026-10-20", "previous_date": "2026-10-19"},
                                "US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
    outlook = market_news("[증시전망] 코스피 AI 신용우려에 하락 예상", published="2026-10-20T08:00:00+09:00")
    us_close = market_news("뉴욕증시 마감, 반도체 상승", market="US", query_market="US",
                          published="2026-10-20T05:30:00+09:00", link="https://www.yna.co.kr/view/us-close-fixture")
    context["session_news"] = [outlook, us_close]
    report = build_auto_market_memo(report_context=context, now=NOW)
    assert outlook["title"] not in report and "장전전망 1건" in report
    assert us_close["title"] in report and not is_preopen_outlook(us_close)
    partitioned = partition_session_market_news([us_close], context["news_sessions"], now=NOW)
    assert partitioned["session_news"][0]["market"] == "US"
    assert partitioned["session_news"][0]["kr_news_timing"] == "장전 보도"
    assert not reported_cause(outlook, context["sessions"])


def test_holdings_pass_frames_keep_daily_actual_and_group_residual_references(monkeypatch):
    from stock_lab_core import report_holdings

    context = quality_context()
    context["scenario_observations"] = {"kr_close": {symbol: {"return": -.01, "base_at": "2026-10-20T05:00:00+09:00",
        "as_of": "2026-10-20T15:30:00+09:00"} for symbol in ("NQ=F", "ES=F", "USDKRW=X")}}
    held = [{"티커": ticker, "종목명": ticker, "보유량": 1} for ticker in ("379810.KS", "418660.KS", "379800.KS", "SOXL")]
    for row in held:
        context["prices"][row["티커"]] = {"date": "2026-10-20", "return": -.02}
    seen = []

    def cumulative(row, observations, sessions, now, *, price_frames=None, intraday_prices=None):
        seen.append(price_frames)
        return None if row["티커"] == "SOXL" else "누적 비교 보류: 검증용 이력 부족"

    monkeypatch.setattr(report_holdings, "completed_scenario_comparison", cumulative)
    monkeypatch.setattr(report_holdings, "holding_estimate", lambda *a, **kw: ("일간 배수 환산(추정): -3.00%", False))
    monkeypatch.setattr(report_holdings, "hedge_policy_line", lambda row: "환노출 확인상태(검증용)", raising=False)
    monkeypatch.setattr(report_holdings, "hedge_source_lines", lambda rows: ["공식 환헤지 출처(검증용)"], raising=False)
    lines, _ = report_sections(context=context, news=curate_news([], now=NOW), flow_rows=[], event_rows=[], summary_rows=held, now=NOW)
    report = "\n".join(lines)
    table = report.split("## 내 보유 종목 영향")[1].split("## 오늘의 시장 스토리")[0]
    assert all(frames is context["price_frames"] for frames in seen) and len(seen) == 4
    for row in held[:3]:
        line = next(line for line in table.splitlines() if f"({row['티커']})" in line)
        assert "-2.00% (2026-10-20 확정 종가)" in line and "누적 비교 보류" in line
        assert "환노출 확인상태" in line and "비교 구간 관측" not in line
    assert table.count("보유표 공통 각주") == 1
    assert table.count("NQ=F -1.00%") == 1 and table.count("ES=F -1.00%") == 1
    assert table.count("같은 시각 NAV/iNAV 미연결") == 1
    assert "누적 비교 잔차와 별개" in table and "인과분해·기여도 합산 아님" in table
    assert "마지막 미국 종가부터 해당 관측 시각까지의 부분 구간" in table
    assert "누적 잔차의 인과분해·기여도 합산이 아니며" in table
    assert table.count("공식 환헤지 출처") == 1
    assert "일간 참고(누적 비교 아님): 일간 배수 환산(추정): -3.00%" in table
