"""After-close regressions. Prices/headlines from the report; weights are fixtures."""

from copy import deepcopy
from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_analysis import economic_story_lines, sector_evidence
from stock_lab_core.report_holdings import completed_scenario_comparison
from stock_lab_core.report_presentation import account_headline, sector_related_news
from stock_lab_core.report_prices import release_day_reaction
from stock_lab_core.report_session import report_mode
from stock_lab_core.today_news import partition_session_market_news

NOW = datetime.fromisoformat("2026-10-19T16:18:00+09:00")
SESSIONS = {"KR": {"date": "2026-10-19", "previous_date": "2026-10-16"},
            "US": {"date": "2026-10-16", "previous_date": "2026-10-15"}}
DEBT_TITLE = "美증시 덮친 AI 차입우려…삼전닉스 6%대 급락 [마켓시그널]"
KR_TITLE = "[마켓뷰] 반도체 불안에 급락 출발했지만… 코스피, 반등 성공"
REVERSAL_TITLE = "외인·기관 매수에 삼전닉스 반전…코스피, 1.8% 상승 마감"


def close_case():
    moves = {"^KS11": .0176, "^KQ11": .0178, "^GSPC": -.0109, "^IXIC": -.0215, "^DJI": -.0034,
             "SOXX": -.0414, "IGV": -.048, "XLK": -.0302, "DRAM": -.0584, "QQQ": -.025,
             "305540.KS": .0781, "139250.KS": .0378, "396500.KS": .001,
             "379810.KS": -.0119, "379800.KS": -.006, "418660.KS": -.0254,
             "0167A0.KS": .0003, "SOXL": -.1274, "CIBR": -.0455, "RAM": -.1188, "BITX": -.0196, "MAGS": -.0197}
    prices = {t: dict(return_=v) for t, v in moves.items()}
    for ticker, row in prices.items():
        region = "KR" if ticker.endswith(".KS") or ticker in {"^KS11", "^KQ11"} else "US"
        row.update(SESSIONS[region])
        row["return"] = row.pop("return_")
    prices["^KS11"].update(previous_return=.0205, return_5d=-.0965, down_days=0)
    news = [dict(title=DEBT_TITLE, market="KR", published_at="2026-10-19T08:25:00+09:00",
                 publisher="서울경제", link="https://news.google.com/rss/articles/CBMiakFVX3lxTE05U2c1QkJJUm5RRGZNcC14UkN5aGc1V0duaUxCak1YSS1ETTlDYVhiQXNOc0V5bmpULXRHVG9FRTBCWFk2eThCTXpFNFlIeXM3S0QxMGpUcW1pNVZ6aTJMNmdUcGJ1ZlZzR3c?oc=5"),
            dict(title=KR_TITLE, market="KR", published_at="2026-10-19T15:49:00+09:00",
                 publisher="조선비즈", link="https://news.google.com/rss/articles/CBMiiAFBVV95cUxNbWxaT3FhYnk2SmV2cVYtM3FzUm91aUNvVkRNbE8tX1pzb0psUC1YQmw1bnN2elVSYWtfMkcwbFN0T3EwbTNNSnhWZ0R6MDhacExtNWJWeG5VZnNhaURIVG9VR3hyMFI5US1rODFkTWlXU2xkdTFsMnIyeDRPQnRHVzFQWnVsc19w0gGcAUFVX3lxTE5XSTVNeGtRSkg1WFpwS0F3ZWtwRjJWQi01dGE5N0duRVVlekZzNXFXb00tY0QyOVZMcUpuRnZHcUR0SjlhWjVKejhMOHJ5NHhpaWszcVphRGxST3BDTXExa3Z5Y2dWdXZGUW5hN3pTMnBveVkyRGJKSGVNYnJiQ0N6THZVQzU0WUNVQjk5V1RzNkNsZHNldEhfUTdiaA?oc=5"),
            dict(title=REVERSAL_TITLE, market="KR", published_at="2026-10-19T16:07:00+09:00",
                 publisher="머니투데이", link="https://news.google.com/rss/articles/CBMiaEFVX3lxTE85U0lMYTkzWURLS1g0bFVkVXpndE1aQ19qQ2M4X1NFdDBXNEFEemNLbzJFb21lVkxvNnFUYkdxZmpaUmg5MXB5VGQ5Q25tdU11WGc5NWxkbGFqTTNVTVNKV2I0ZlRaSUU40gFuQVVfeXFMUGNUNVNLdFZaRVZYenY3ejlHRjh5LW5Pc0czUFI5VEhJTHpkUjAtSU9OeUEwM3pUTS03ZFNqUTAtSGtSQ1Z4azhXbGsxV0M4d1ZydlFjOHlRcm9WeEhueVNYNldOZ2owakFMeG5YY3c?oc=5")]
    # Fixture weights only: the uploaded report does not contain each holding weight.
    weights = {"379810.KS": 30, "379800.KS": 35, "418660.KS": 4.3, "0167A0.KS": 6.2,
               "SOXL": 5, "CIBR": 5, "RAM": 10, "BITX": 2, "MAGS": 2.4}
    rows = [dict(티커=t, 종목명=t + "(검증용)", 현재비중=w, 보유량=1, 게이트상태="방어우선") for t, w in weights.items()]
    sector_names = {"SOXX": "반도체", "IGV": "소프트웨어", "XLK": "기술", "DRAM": "메모리",
                    "305540.KS": "2차전지", "139250.KS": "에너지", "396500.KS": "한국 반도체"}
    sectors = [dict(Ticker=t, 섹터=name, 구분="국내 섹터" if t.endswith(".KS") else "미국 섹터",
                    기준일=prices[t]["date"], **{"1일수익률": moves[t]}) for t, name in sector_names.items()]
    # BLS November 2026 schedule: https://www.bls.gov/schedule/2026/11_sched.htm
    events = [dict(indicator=i, event=label, date=day, release_at=day, source="FRED release calendar")
              for i, label, day in (("US_CPI", "CPI", "2026-11-10"), ("US_PPI", "PPI", "2026-11-13"),
                                    ("US_NONFARM_PAYROLLS", "Employment Situation", "2026-11-06"))]
    context = dict(sessions={m: r["date"] for m, r in SESSIONS.items()}, news_sessions=SESSIONS,
                   prices=prices, session_news=news, sector_rows=sectors, calendar_events=events,
                   missing=["US: 채택 뉴스 없음", "Census: HTTP 오류"],
                   economic_releases=[dict(indicator="KR_EXPORTS", actual=83.7, previous=68.9,
                                           period="2026-09", unit="%", basis="YoY", status="verified_snapshot",
                                           source="관세청 수출입 현황", source_url="https://www.customs.go.kr/kcs/na/ntt/selectNttInfo.do?bbsId=1362&mi=2891&nttSn=10179763",
                                           verified_at="2026-10-19", expires_at="2026-11-03")])
    flow = [dict(Ticker="305540.KS", 기준일="2026-10-19", **{"3개월수익률": .235, "가속도": .502, "상태": "강세 가속"})]
    return context, rows, flow


@pytest.mark.parametrize("stamp,expected", [("2026-10-19T08:30:00+09:00", "preopen"),
    ("2026-10-19T09:00:00+09:00", "intraday"), ("2026-10-19T15:29:00+09:00", "intraday"),
    ("2026-10-19T06:30:00+00:00", "closed"), ("2026-10-18T16:00:00+09:00", "holiday")])
def test_modes(stamp, expected):
    assert report_mode(datetime.fromisoformat(stamp)) == expected
    assert report_mode(NOW, is_trading_day=False) == "holiday"


def test_reported_aggregates_choose_full_close_not_partial_replacement():
    metrics = dict(daily=-3.00, coverage=99.9, replacement=-2.29, replacement_coverage=24.4)
    sessions = {m: r["date"] for m, r in SESSIONS.items()}
    line = account_headline(metrics, sessions, "closed")
    assert "-3.00%p" in line and "99.9%" in line and "-2.29" not in line
    assert "미국 2026-10-16 / 한국 2026-10-19" in line
    assert "보류" in account_headline(dict(metrics, coverage=89.9), sessions, "closed")
    assert "보류" in account_headline(None, sessions, "closed")
    assert "-3.00%p" in account_headline(dict(metrics, replacement_coverage=95), sessions, "preopen")


def test_close_report_acceptance_and_immutable_inputs():
    context, rows, flow = close_case()
    original = deepcopy((context, rows, flow))
    report = build_auto_market_memo(report_context=context, summary_rows=rows, flow_snapshot={"flow_df": flow}, now=NOW)
    assert (context, rows, flow) == original
    assert "보고서 모드: 마감 후" in report
    conclusion = report.split("## 한 줄 결론")[1].split("## 내 보유 종목 영향")[0]
    assert "계좌 추정" not in conclusion and "99.9%" not in conclusion
    assert "최신 종가 기준 계좌 추정" in report and "99.9%" in report
    assert "코스피는 반등했습니다(+1.76%, 2026-10-19 확정 종가)" in conclusion
    assert "당일 코스피 +1.76%" in report and "직전 거래일 +2.05%" in report
    assert REVERSAL_TITLE in report.split("## 경제지표")[0]
    assert KR_TITLE.replace("[", "(").replace("]", ")") in report
    story = report.split("## 오늘의 시장 스토리")[1].split("## 경제지표")[0]
    table = report.split("## 경제지표")[1].split("## 업종별 왜")[0]
    assert "83.7" not in story  # Publication date is unknown; observation month is not a release date.
    assert "한국 수출 2026-09 전년비" in table and "83.7%" in table and "이전 대비 +14.80%p" in table
    assert "만료 2026-11-03" in report
    assert "누적 비교 보류" in report  # No price histories in this saved-context fixture.
    assert "시나리오 -2.50% vs 당일 종가 -1.19%" not in report and "차이(실제−시나리오)" not in report
    assert "-1.19% (2026-10-19 확정 종가)" in report and "-2.54% (2026-10-19 확정 종가)" in report
    assert "당일 현재(실제)" not in report and "갭다운 위험(추정)" not in report
    assert "오늘 밤 미국장" in report
    sectors = report.split("## 업종별 왜")[1].split("## 관심 후보")[0]
    for ticker in ("SOXX", "IGV", "XLK"):
        line = next(line for line in sectors.splitlines() if f"({ticker})" in line)
        assert "개별 원인 미확인" in line and "AI 차입 우려" not in line
    line = next(line for line in sectors.splitlines() if "305540.KS" in line)
    assert "3M +23.5%" in line and "가속도 +50.2%p" in line
    assert "한국 반도체(396500.KS)" in sectors
    for day in ("2026-11-06", "2026-11-10", "2026-11-13"):
        assert day in report
    assert "US: 채택 뉴스 없음" not in report and "Census: HTTP 오류" in report


def test_cumulative_comparison_requires_history_and_missing_actual_not_zero():
    context, rows, _ = close_case()
    row = rows[0]
    context["prices"]["QQQ"]["date"] = "2026-10-15"
    line = completed_scenario_comparison(row, context["prices"], context["sessions"], NOW)
    assert "누적 비교 보류" in line and "차이(실제−시나리오)" not in line
    context["prices"][row["티커"]]["return"] = None
    assert "종가 미수집" in completed_scenario_comparison(row, context["prices"], context["sessions"], NOW)


def test_close_report_uses_cumulative_frames_without_replacing_daily_actual():
    # Rebased fixture prices reproduce the supplied two-day Nasdaq moves.
    # The leveraged KR path is synthetic; it tests daily-reset compounding only.
    context = dict(sessions={"KR": "2026-10-20", "US": "2026-10-19"}, prices={
        "QQQ": {"date": "2026-10-19", "previous_date": "2026-10-16", "return": .0121},
        "379810.KS": {"date": "2026-10-20", "previous_date": "2026-10-19", "return": -.0073},
        "418660.KS": {"date": "2026-10-20", "previous_date": "2026-10-19", "return": -.01}},
        price_frames={
            "QQQ": pd.DataFrame({"Close": [100., 97.5, 97.5 * 1.0121]},
                                index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"])),
            "379810.KS": pd.DataFrame({"Close": [100., 98.81, 98.81 * .9927]},
                                      index=pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"])),
            "418660.KS": pd.DataFrame({"Close": [100., 97.46, 97.46 * .99]},
                                      index=pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"]))})
    rows = [{"티커": ticker, "보유량": 1} for ticker in ("379810.KS", "418660.KS")]
    original = {ticker: frame.copy(deep=True) for ticker, frame in context["price_frames"].items()}
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=NOW.replace(day=20, hour=22))
    nasdaq = next(line for line in report.splitlines() if "(379810.KS)" in line)
    leveraged = next(line for line in report.splitlines() if "(418660.KS)" in line)
    assert "-0.73% (2026-10-20 확정 종가)" in nasdaq and "실제 -1.91%" in nasdaq and "잔차 -0.59%p" in nasdaq
    assert "누적 -1.32%" in nasdaq
    assert "-1.00% (2026-10-20 확정 종가)" in leveraged and "실제 -3.51%" in leveraged and "잔차 -0.81%p" in leveraged
    assert "2배 일간복리 참고 -2.70%" in leveraged
    assert "한국 2026-10-16→2026-10-20" in nasdaq and "미국 2026-10-15→2026-10-19" in nasdaq
    assert "한국 시작 종가 시점에 확정돼 있던 미국 종가를 기준" in report
    assert "양국 종가 시각이 달라 잔차를 추적오차로 해석하지 않습니다" in report
    assert nasdaq.count("환노출") == 1 and leveraged.count("환노출") == 1
    for ticker, frame in context["price_frames"].items():
        pd.testing.assert_frame_equal(frame, original[ticker])


def test_market_recap_partition_and_wrong_cxmt_connection():
    context, _, _ = close_case()
    result = partition_session_market_news(context["session_news"], SESSIONS, now=NOW)
    by_title = {r["title"]: r for r in result["session_news"]}
    assert by_title[DEBT_TITLE]["market"] == "US" and by_title[DEBT_TITLE]["session_date"] == "2026-10-16"
    assert by_title[KR_TITLE]["market"] == "KR" and by_title[KR_TITLE]["session_date"] == "2026-10-19"
    bad = dict(by_title[DEBT_TITLE], title="Wall Street doubts CXMT DRAM edge as Korea retains density and yield lead")
    assert not sector_related_news("DRAM", "2026-10-16", [bad])


def test_korean_release_reaction_uses_local_date_and_korean_assets():
    frame = pd.DataFrame({"Close": [100, 102]}, index=pd.to_datetime(["2026-10-16", "2026-10-19"]))
    row = dict(indicator="KR_CPI", release_at="2026-10-18T23:00:00Z", actual=2.9)
    frames = {"^KS11": frame, "USDKRW=X": frame}
    line = release_day_reaction(row, frames, NOW.replace(day=20))
    assert "2026-10-19" in line and "코스피 +2.00%" in line and "원/달러 +2.00%" in line
    assert "나스닥" not in line and "10Y" not in line
    assert "원/달러 동일일 종가 없음" in release_day_reaction(row, frames, NOW)
    assert "보류" in release_day_reaction(dict(row, release_at="invalid"), {}, NOW)


@pytest.mark.parametrize("bps,contradiction", [(-2.7, False), (-4.99, False), (-5, True), (-10.1, True)])
def test_inflation_opposite_reaction_has_same_materiality_threshold(bps, contradiction):
    row = dict(indicator="US_PPI", actual=1.3, previous=.5, unit="%", basis="MoM",
               reaction=f"10Y {bps:+.2f}bp", reaction_source="Yahoo daily")
    assert ("동일일 움직임이 단순 해석과 어긋남" in "\n".join(economic_story_lines([row]))) == contradiction
