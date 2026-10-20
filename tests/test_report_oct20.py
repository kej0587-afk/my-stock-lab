"""October 20 report regressions; account weights are synthetic, not user data."""
from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_evidence import comparison_lines
from stock_lab_core.report_history import normalized_decisions
from stock_lab_core.report_presentation import account_metrics, account_estimate, sector_related_news
from stock_lab_core.today_news import partition_session_market_news

NOW = datetime.fromisoformat("2026-10-20T17:03:00+09:00")
SESSIONS = {"KR": {"date": "2026-10-20", "previous_date": "2026-10-19"},
            "US": {"date": "2026-10-19", "previous_date": "2026-10-16"}}
KR_CREDIT = "[마감] 코스피, AI 신용우려에 3% 빠져 다시 5500선"
KR_SELLING = "外人·기관 동반 매도 공세…코스피, 3.73% 급락 마감"
JP_WORRY = "日증시, AI 투자 불안에 혼조 마감…닛케이 0.62%↓"


def news_case():
    return [dict(title=title, market=market, query_market=market, source="Google News RSS",
                 publisher="연합뉴스", link=f"https://www.yna.co.kr/view/fixture-{index}",
                 published_at=at)
            for index, (title, market, at) in enumerate([
                (KR_CREDIT, "KR", "2026-10-20T16:15:00+09:00"),
                (KR_SELLING, "KR", "2026-10-20T16:10:00+09:00"),
                (JP_WORRY, "US", "2026-10-19T17:38:00+09:00"),
            ])]


@pytest.mark.parametrize("ticker", ["SOXX", "XLK", "IGV"])
def test_korean_next_day_and_japan_theme_are_not_us_sector_causes(ticker):
    result = partition_session_market_news(news_case(), SESSIONS, now=NOW)
    assert len(result["other_market_news"]) == 1
    assert result["other_market_news"][0]["market"] == "JP"
    assert not sector_related_news(ticker, "2026-10-19", result["session_news"])


@pytest.mark.parametrize("ticker,name", [("396500.KS", "한국 반도체"),
                                        ("139250.KS", "에너지"), ("305540.KS", "2차전지")])
def test_matching_kr_session_gets_market_context_not_fabricated_sector_cause(ticker, name):
    result = partition_session_market_news(news_case(), SESSIONS, now=NOW)
    linked = sector_related_news(ticker, "2026-10-20", result["session_news"], sector_name=name)
    assert linked[0]["title"] == KR_CREDIT
    assert all(row["market_context_only"] for row in linked)
    assert not sector_related_news(ticker, "2026-10-19", result["session_news"], sector_name=name)


def test_account_region_components_sum_to_total_and_closed_copy_is_clean():
    held = [{"티커": "RAM", "현재비중": 30}, {"티커": "379810.KS", "현재비중": 70}]
    prices = {"RAM": {"date": "2026-10-19", "return": .04},
              "379810.KS": {"date": "2026-10-20", "return": -.72 / 70}}
    dates = {m: s["date"] for m, s in SESSIONS.items()}
    metrics = account_metrics(held, prices, dates)
    assert metrics["daily"] == pytest.approx(.48)
    assert sum(metrics["by_market"].values()) == pytest.approx(metrics["daily"])
    line = account_estimate(held, prices, dates, mode="closed")
    assert "미국 상장 +1.20%p / 한국 상장 -0.72%p" in line
    assert "장전 대체 합산" not in line and "단순 합산하지 않음" not in line
    prices["RAM"]["date"] = "2026-10-16"
    assert account_metrics(held, prices, dates)["by_market"]["US"] == 0


def test_history_preserves_names_and_held_status_without_account_details():
    rows = [{"티커": "RAM", "종목명": "DRAM 2배", "보유량": 186, "매입가": 14.84, "최종읽기": "대기",
             "게이트상태": "방어우선", "owner_email": "private@example.com"},
            {"티커": "AAPL", "종목명": "애플", "보유량": 0, "최종읽기": "대기"}]
    old = normalized_decisions(rows)
    assert old[0]["종목명"] == "DRAM 2배" and old[0]["보유여부"] is True
    assert not ({"매입가", "보유량", "owner_email"} & old[0].keys())
    current = deepcopy(rows)
    current[1]["최종읽기"] = "관찰"
    current.append({"티커": "MSFT", "종목명": "마이크로소프트", "보유량": 0, "최종읽기": "대기"})
    text = "\n".join(comparison_lines(current, old, previous_date="2026-10-19", current_date="2026-10-20"))
    assert "보유 1개 | 1 | 0 | 0개" in text
    assert "관심·미보유 2개 | 1 | 1 | 1개" in text and "애플(AAPL)" in text
    assert "추가 | 마이크로소프트(MSFT)" in text
    removed = "\n".join(comparison_lines(current[:1], old, previous_date="2026-10-19", current_date="2026-10-20"))
    assert "이탈 | 애플(AAPL)" in removed
    assert "상위 10개 변화가 아닌 입력 목록 차이" in removed


def report_case():
    context = dict(sessions={m: s["date"] for m, s in SESSIONS.items()}, news_sessions=SESSIONS,
                   session_news=news_case(), prices={"^KS11": {"date": "2026-10-20", "return": -.0373}})
    context["sector_rows"] = [dict(Ticker=t, 섹터=name, 구분="한국 섹터" if t.endswith(".KS") else "미국 섹터",
                                 기준일="2026-10-20" if t.endswith(".KS") else "2026-10-19",
                                 **{"1일수익률": ret})
                             for t, name, ret in [("SOXX", "반도체", .0173), ("XLK", "기술", .0136),
                                                 ("IGV", "소프트웨어", .0158), ("396500.KS", "한국 반도체", -.0501),
                                                 ("139250.KS", "에너지", -.0717), ("305540.KS", "2차전지", -.0572)]]
    return context


def test_full_report_catalysts_same_market_and_foreign_news_separate():
    context = report_case()
    original = deepcopy(context)
    report = build_auto_market_memo(report_context=context, now=NOW)
    headline = report.split("## 한 줄 결론")[1].split("## 오늘의 시장 스토리")[0]
    assert "코스피는 하락했습니다(-3.73%, 2026-10-20 확정 종가)" in headline
    assert "AI 신용우려" in headline and "외국인·기관 동반 매도" in headline and "기사 주장" in headline
    sectors = report.split("## 업종별 왜")[1].split("## 관심 후보")[0]
    for symbol in ("SOXX", "XLK", "IGV"):
        line = next(line for line in sectors.splitlines() if f"({symbol})" in line)
        assert "AI 신용우려" not in line and "日증시" not in line
    for symbol in ("396500.KS", "139250.KS", "305540.KS"):
        line = next(line for line in sectors.splitlines() if f"({symbol})" in line)
        assert "AI 신용우려" not in line and "개별 원인 미확인" in line
        assert {"396500.KS": "-1.28%p", "139250.KS": "-3.44%p", "305540.KS": "-1.99%p"}[symbol] in line
    assert JP_WORRY in report.split("## 다른 시장/다른 날짜 맥락")[1]
    assert "- 당일 종가: 코스피" not in report
    assert context == original


def test_tickerless_themes_survive_and_bad_aligned_names_do_not_overwrite_labels():
    context = report_case()
    context["closed_flow_rows"] = [dict(Ticker=t, 섹터=t, 구분=group, 기준일=day,
                                      **{"3개월수익률": .02, "돈흐름점수": 1, "1일수익률": .01})
                                   for t, group, day in [("EWZ", "글로벌", "2026-10-19"),
                                                        ("329200.KS", "한국 섹터", "2026-10-20"),
                                                        ("SMH", "미국 섹터", "2026-10-19")]]
    flow = {"flow_df": [dict(Ticker="SMH", 섹터="반도체 VanEck")],
            "global_top": [dict(Ticker="EWZ", 섹터="브라질")],
            "kr_top5": [dict(Ticker="329200.KS", 섹터="부동산")],
            "theme_top5": [dict(테마="2차전지 밸류체인", 테마돈흐름점수=12, **{"3개월수익률": .15})]}
    old = deepcopy((context, flow))
    report = build_auto_market_memo(report_context=context, flow_snapshot=flow, now=NOW)
    tail = report.split("## 기존 점검")[1]
    assert "부동산(329200.KS)" in tail and "브라질(EWZ)" in tail and "반도체 VanEck(SMH)" in tail
    assert "2차전지 밸류체인" in tail and "원천 기준일 미제공" in tail
    assert (context, flow) == old


def test_next_session_bucket_cannot_explain_previous_sector_close():
    raw = dict(title="한국 증시 에너지주 반등", market="KR", query_market="KR",
               publisher="연합뉴스", source="Google News RSS",
               published_at="2026-10-21T09:30:00+09:00")
    result = partition_session_market_news([raw], SESSIONS,
        now=datetime.fromisoformat("2026-10-21T10:00:00+09:00"))
    future = result["next_session_news"]
    assert len(future) == 1 and future[0]["session_date"] == "2026-10-20"
    assert not sector_related_news("139250.KS", "2026-10-20", future, sector_name="에너지")


def test_intraday_rebound_does_not_inherit_previous_day_decline_claims():
    context = report_case()
    context["intraday_prices"] = {"^KS11": {
        "date": "2026-10-21", "return": .02, "retrieved_at": "2026-10-21T10:00:00+09:00"}}
    report = build_auto_market_memo(report_context=context,
        now=datetime.fromisoformat("2026-10-21T10:00:00+09:00"))
    headline = report.split("## 한 줄 결론")[1].split("## 오늘의 시장 스토리")[0]
    assert "코스피는 반등을 시도 중입니다(+2.00%, 2026-10-21 장중·확정 아님)" in headline
    assert "AI 신용우려" not in headline and "외국인·기관 동반 매도" not in headline


def test_known_publisher_suffix_does_not_change_headline_market():
    raw = dict(title="Nasdaq rises as chip stocks rebound - Nikkei Asia",
               publisher="Nikkei Asia", market="US", query_market="US", source="Google News RSS",
               published_at="2026-10-19T15:30:00-04:00")
    result = partition_session_market_news([raw], SESSIONS, now=NOW)
    assert len(result["session_news"]) == 1
    assert result["session_news"][0]["market"] == "US"
    assert result["other_market_news"] == []
