"""Quick-summary market reading: today's change first, causes only at their confirmed level."""

from copy import deepcopy
from datetime import datetime

from stock_lab_core.report_market_summary import market_summary
from stock_lab_core.report_session import market_session_states


def close(date, ret, prev, r5, down=0, up=0, prior_down=0):
    return {"date": date, "return": ret, "previous_return": prev, "return_5d": r5,
            "down_days": down, "up_days": up, "prior_down_days": prior_down}


def day(kr, us, kospi, nasdaq, sox, macro=None):
    """Public daily closes (Yahoo chart) for 2026-11-23 and 2026-11-24, rounded."""
    context = {"sessions": {"KR": kr, "US": us},
               "prices": {"^KS11": close(kr, *kospi), "^IXIC": close(us, *nasdaq), "^SOX": close(us, *sox)},
               "macro_data": macro or {"VIX": {"val": 26.62, "as_of": us}},
               "sector_rows": [], "closed_flow_rows": []}
    now = datetime.fromisoformat(kr + "T17:00:00+09:00")
    return context, now


CRASH = day("2026-11-23", "2026-11-20", (-.0331, -.0521, -.0768, 2), (-.0528, -.0225, -.1002, 2), (-.1073, -.0241, -.1713, 2),
            {"VIX": {"val": 35.89, "as_of": "2026-11-20"}})
REBOUND = day("2026-11-24", "2026-11-23", (.0632, -.0331, .0076, 0, 1, 2), (.0651, -.0528, -.0171, 0, 1, 2),
              (.1403, -.1073, -.0024, 0, 1, 2))


def reading(case, news=()):
    context, now = deepcopy(case)
    before = deepcopy(context)
    result = market_summary(context, list(news), [], market_session_states(now, context["sessions"]), now)
    assert context == before
    return result


def test_crash_and_rebound_days_read_differently_from_the_first_sentence():
    crash, rebound = reading(CRASH), reading(REBOUND)
    first = [r["interpretation"].split(". ")[0] for r in (crash, rebound)]
    assert first[0].startswith("코스피가 -3.31% 급락해 2거래일째 하락했습니다(2026-11-23 확정 종가)")
    assert first[1].startswith("코스피가 +6.32% 급등해 전 거래일 -3.31% 급락을 하루 만에 되돌렸습니다")
    assert "나스닥 -5.28%, 필라델피아 반도체 -10.73%로 급락" in crash["interpretation"]
    assert "나스닥 +6.51%, 필라델피아 반도체 +14.03%로 급반등" in rebound["interpretation"]
    assert "하락이 다른 업종으로 번지는지" in crash["interpretation"]
    assert "반도체가 다음 종가에서 반등폭을 지키는지" in rebound["interpretation"]
    for result in (crash, rebound):
        assert "확인할 국면입니다" not in result["interpretation"]  # the old fixed ending
        assert result["interpretation"].endswith("(종합 해석).")


def test_today_changes_list_only_observed_comparisons():
    assert reading(REBOUND)["daily_changes"] == [
        "코스피 방향 전환: 전 거래일 -3.31% → +6.32%(2026-11-24 확정 종가)",
        "나스닥 방향 전환: 전 거래일 -5.28% → +6.51%(2026-11-23 확정 종가)",
        "필라델피아 반도체 방향 전환: 전 거래일 -10.73% → +14.03%(2026-11-23 확정 종가)"]
    assert reading(CRASH)["daily_changes"][0] == "코스피 2거래일 연속 하락(-3.31%, 2026-11-23)"


def test_title_only_background_is_never_a_confirmed_cause():
    news = [{"title": title, "publisher": publisher, "link": link, "market": "KR", "session_date": "2026-11-24",
             "news_bucket": "session_news", "published_at": "2026-11-24T09:05:00+09:00"}
            for title, publisher, link in (
                ("[속보] 젠슨 황 컴백에 삼전닉스 나란히 급등…코스피 상승", "매일경제", "https://www.mk.co.kr/fixture"),
                ("코스피 급등, 삼전닉스 쌍끌이", "한국경제", "https://www.hankyung.com/fixture"))]
    text = reading(REBOUND, news)["interpretation"]
    assert "삼성전자·SK하이닉스 강세가 제목 기준으로 보도됐지만(2개 매체 제목 일치, 본문 미확인) 원인으로 확정하지 않습니다" in text
    assert "때문" not in text and "덕분" not in text


def test_story_no_longer_repeats_the_summary_or_the_macro_warning():
    result = reading(REBOUND)
    assert result["interpretation"] not in result["headline"]
    assert "같은 의미로 보기는 어렵습니다" not in result["overview"]
    assert "VIX 26.62(수준 경고)" in result["interpretation"]


def test_sparse_input_gives_a_useful_reading_without_numbers():
    now = datetime.fromisoformat("2026-11-24T17:00:00+09:00")
    context = {"sessions": {"KR": "2026-11-24", "US": "2026-11-23"}}
    result = market_summary(context, [], [], market_session_states(now, context["sessions"]), now)
    text = result["interpretation"]
    assert text.startswith("확정 종가·검증된 장중 지수가 없어 당일 방향은 판단하지 않습니다.")
    assert "배경 보도가 없어 원인은 비워 둡니다" in text and "%" not in text
    assert result["daily_changes"] == []


def test_investor_turn_uses_the_completed_history_run(monkeypatch):
    import stock_lab_core.report_daily_change as daily
    flows = ([{"market": "KOSPI", "label": "외국인", "value": 7455.91}, {"market": "KOSPI", "label": "개인", "value": -20636.33}],
             {("KOSPI", "외국인"): {"direction": "buy", "prior_days": 8, "sum_5": -13546.55}})
    monkeypatch.setattr(daily, "_flow_turns", lambda context, date: flows)
    result = reading(REBOUND)
    assert "외국인은 직전 8거래일 순매도에서 순매수로 돌아섰습니다" in result["interpretation"]
    assert "외국인 5거래일 누적 -13,547억원(여전히 순매도)" in result["interpretation"]
    assert "외국인(KOSPI) 순매도 8거래일 → 순매수 전환" in result["daily_changes"]


def test_prior_run_is_counted_only_when_its_start_is_observed():
    from stock_lab_core.public_market_flow_history import summarize_daily_values
    days = [f"d{i}" for i in range(6)]
    turned = summarize_daily_values(dict(zip(days, [5, -1, -2, -3, -4, 9])), days)
    assert (turned["streak_direction"], turned["streak_days"], turned["prior_streak_days"]) == ("buy", 1, 4)
    edge = summarize_daily_values(dict(zip(days, [-1, -1, -2, -3, -4, 9])), days)
    assert edge["prior_streak_days"] is None  # the sell run may start before the window
    gap = summarize_daily_values(dict(zip(days, [5, None, -2, -3, -4, 9])), days)
    assert gap["prior_streak_days"] is None


def test_quick_summary_shows_today_changes_below_the_reading():
    from stock_lab_core.report_reading import _quick_summary_lines
    lines = _quick_summary_lines([], "", [], {}, "해석", {}, changes=["코스피 방향 전환"])
    assert lines[lines.index("**시장 해석** · 해석") + 2:][:2] == ["**오늘 달라진 점**", "- 코스피 방향 전환"]
