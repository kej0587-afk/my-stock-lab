from datetime import datetime

import pandas as pd
import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import (
    KST, curate_news, macro_stress, price_observation, reported_cause, comparison_lines,
)
from stock_lab_core.today_snapshot import save_today_queue_summary_snapshot, load_previous_today_summary


NOW = datetime(2026, 10, 18, 18, tzinfo=KST)


def article(title, *, link="https://www.reuters.com/markets/example/", **kwargs):
    return dict(title=title, publisher="Reuters", link=link,
                published="2026-10-18 12:00", **kwargs)


def test_calendar_fallback_hides_redundant_primary_failure_and_keeps_source():
    context = {"calendar_events": [{"event": "Consumer Price Index", "date": "2026-10-20",
                "source": "FRED release calendar", "source_url": "https://fred.stlouisfed.org/release?rid=10"}],
               "calendar_sources": [{"name": "BLS CPI", "status": "connected", "provider": "FRED",
                "reason": "", "primary_reason": "http_403"}]}
    memo = build_auto_market_memo(report_context=context, now=NOW)
    assert "FRED release calendar" in memo and "http_403" not in memo
    assert "2026-10-20 (발표 시각 미제공)" in memo
    assert "일정 미연결: BLS CPI" not in memo


def test_news_clusters_cxmt_and_excludes_promotional_price_and_irrelevant():
    rows = [article("CXMT 기술 추격에 반도체 주가 급락"), article("CXMT 반도체 매출 7배 증가"),
            article("Ethereum ETF outflows rise as oil declines", market_category="에너지",
                    link="https://www.reuters.com/markets/ethereum/"),
            dict(title="RWUSD price today to USD", publisher="CoinMarketCap"),
            dict(title="NVIDIA announces new GPU", publisher="NVIDIA"),
            article("구리경찰서에 소동"), dict(title="유가 소식", publisher="TMGM")]
    rows = curate_news(rows, now=NOW)
    assert len(rows) == 2
    assert rows[1]["category"] == "암호화폐"
    assert "이더리움" in rows[1]["reading_ko"]
    assert "유출" in rows[1]["reading_ko"]


def test_weekend_news_is_not_a_friday_cause_and_unknown_market_is_not_guessed():
    row = article("CXMT 기술 추격에 반도체 주가 급락", market="US")
    assert reported_cause(row, {"US": "2026-10-16"}) == ""
    row["published"] = "2026-10-17 04:00"
    assert "보도 해석" in reported_cause(row, {"US": "2026-10-16"})
    row.pop("market")
    assert reported_cause(row, {"US": "2026-10-16"}) == ""


@pytest.mark.parametrize("ticker,clock,expected", [
    ("005930.KS", datetime(2026, 10, 16, 14, tzinfo=KST), "2026-10-15"),
    ("AAPL", datetime(2026, 10, 17, 4, tzinfo=KST), "2026-10-15"),
    ("AAPL", datetime(2026, 10, 17, 6, tzinfo=KST), "2026-10-16"),
    ("BTC-USD", datetime(2026, 10, 16, 18, tzinfo=KST), "2026-10-15"),
])
def test_regular_close_and_crypto_cutoffs(ticker, clock, expected):
    frame = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range("2026-10-14", periods=3))
    assert price_observation(frame, ticker, clock)["date"] == expected


def test_macro_surge_and_high_declining_oil_share_report_score_components():
    result = macro_stress({"10Y 금리": {"val": 5.1, "chg": 2},
                           "VIX": {"val": 19.99, "chg": 35}, "MOVE": {"val": 101.1, "chg": 25.4},
                           "유가": {"val": 99.02, "chg": -1.3}, "환율": {"val": 1329.6, "chg": -3.6}})
    assert result["score"] == 74
    assert "급등 주의" in result["rows"][1]["state"]
    assert result["rows"][3]["contribution"] == 0
    assert "고수준 부담" in result["rows"][3]["state"]
    assert "유가 +0" in result["explanation"]


def test_previous_day_snapshot_survives_same_day_reruns_and_is_owner_scoped(tmp_path):
    path = tmp_path / "report.json"
    for date, value in (("2026-10-15 18:00", "대기"), ("2026-10-16 18:00", "관측"), ("2026-10-16 19:00", "확인")):
        save_today_queue_summary_snapshot(pd.DataFrame([{"티커": "001820.KS", "최종읽기": value}]),
                                          last_run=date, owner_scope="alice", path=path)
    frame, date = load_previous_today_summary(owner_scope="alice", path=path)
    assert date == "2026-10-15"
    assert frame.iloc[0]["티커"] == "001820.KS"
    assert frame.iloc[0]["최종읽기"] == "대기"
    assert load_previous_today_summary(owner_scope="bob", path=path)[0].empty
    assert "이전 기준일 비교 없음" in comparison_lines([], [], previous_date="2026-10-16", current_date="2026-10-16")[0]


def test_report_front_order_missing_reasons_and_leverage_not_double_multiplied():
    context = {"sessions": {"KR": "2026-10-16", "US": "2026-10-16"},
               "prices": {"^IXIC": {"date": "2026-10-16", "return": -.02},
                          "SOXL": {"date": "2026-10-16", "return": -.12},
                          "SOXX": {"date": "2026-10-16", "return": -.04}},
               "economic_releases": [{"indicator": "US_CPI", "period": "2026-09", "basis": "YoY", "unit": "%",
                                       "actual": 3.2, "forecast": 3.0, "previous": 3.1, "actual_minus_forecast": .2,
                                       "source": "BLS", "source_url": "https://www.bls.gov/cpi/", "status": "released"}]}
    memo = build_auto_market_memo(report_context=context, now=NOW,
                                  market_news_rows=[article("CXMT 반도체 매출 증가")],
                                  summary_rows=[{"티커": "SOXL", "보유량": 1, "현재비중": 6, "목표비중": 5}])
    assert memo.index("## 내 보유 종목 영향") < memo.index("## 오늘의 시장 스토리") < memo.index("## 경제지표")
    assert "🧭 오늘점검" not in memo
    assert "전년비" in memo and "예상대비 +0.20 %p" in memo
    assert "× 3 = -12.00%" in memo and "-36.00%" not in memo
    assert "비중초과, 레버리지 보유" in memo
    assert memo.count("CXMT 반도체 매출 증가") < 6
    assert "원자료" not in memo
    assert "일정 미연결" in memo
    assert memo.count("오늘의 전략:") <= 1


def test_zero_forecast_actual_are_not_missing_and_pending_no_surprise():
    context = {"economic_releases": [{"indicator": "US_CPI", "period": "2026-10", "basis": "MoM", "unit": "%",
                                       "actual": None, "forecast": 0, "previous": 0, "status": "pending"}]}
    memo = build_auto_market_memo(report_context=context, now=NOW)
    assert "발표 예정 | 0% | 0%" in memo
    assert "예상대비" not in memo


def test_saved_financial_percentage_points_are_not_multiplied_again():
    from stock_lab_core.chart_review import saved_financial_chart_info
    from stock_lab_core.chart_enrichment import build_financial_snapshot_rows
    fields = saved_financial_chart_info({"returnOnEquity": 12.5, "profitMargins": 0, "earningsGrowth": -4})
    rows = {row["key"]: row["value"] for row in build_financial_snapshot_rows(fields)}
    assert rows == {"returnOnEquity": 12.5, "profitMargins": 0, "earningsGrowth": -4}
    rows = build_financial_snapshot_rows(saved_financial_chart_info({"returnOnEquity": "12.5"}))
    assert rows[0]["value"] == 12.5


def test_korean_leverage_and_us_proxy_same_date_are_not_the_same_session():
    memo = build_auto_market_memo(now=NOW, summary_rows=[{"티커": "418660.KS", "보유량": 1}],
                                  report_context={"sessions": {"US": "2026-10-16"}, "prices": {
                                      "418660.KS": {"date": "2026-10-16", "return": .03},
                                      "QQQ": {"date": "2026-10-16", "return": -.02}}})
    assert "월요일 갭 예상 영향(추정)" in memo
    assert "× 2 = -4.00%" in memo
    assert "+3.00% (2026-10-16 확정 종가)" in memo


def test_unparseable_and_missing_news_dates_do_not_bypass_recency():
    rows = [article("미국 CPI 물가 상승"), dict(title="미국 CPI 물가 하락", publisher="Reuters", published="06/01 12:00"),
            dict(title="반도체 실적 발표", publisher="Reuters")]
    assert len(curate_news(rows, now=NOW)) == 1


def test_new_and_removed_symbols_are_reported_not_called_unchanged():
    lines = comparison_lines([{"티커": "SOXL", "최종읽기": "대기", "입력출처": "등록"}], [{"티커": "AAPL", "최종읽기": "정밀확인", "입력출처": "등록"}],
                             previous_date="2026-10-15", current_date="2026-10-16")
    assert "변경 없음" not in lines[0]
    assert "추가 | SOXL(종목명 미저장) | 이전 저장 기준일" in "\n".join(lines)
    assert "이탈 | AAPL(종목명 미저장) | 이전 저장 기준일" in "\n".join(lines)
