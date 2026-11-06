from copy import deepcopy
from datetime import datetime

from stock_lab_core import article_context
from stock_lab_core.news_priority import editorial_priority
from stock_lab_core.report_brief import build_news_brief


NOW = datetime.fromisoformat("2026-11-05T16:54:00+09:00")
CONTEXT = {
    "sessions": {"KR": "2026-11-05", "US": "2026-11-04"},
    "sector_rows": [{"Ticker": "396500.KS", "섹터": "반도체", "기준일": "2026-11-05", "1일수익률": -.06}],
}


def news(title, suffix, **kwargs):
    return dict(title=title, link="https://www.yna.co.kr/view/" + suffix,
                market="KR", session_date="2026-11-05", news_bucket="session_news",
                published_at="2026-11-05T16:19:00+09:00", **kwargs)


def test_same_session_crash_beats_flash_and_company_body_in_both_stages(monkeypatch):
    flash = news("[속보] 코스피 매도 사이드카 발동", "flash")
    close = news("'블루웨이브 쇼크' 코스피·코스닥 5%대 급락…반도체주 추락(종합)", "close", is_close_wrap=True)
    company = dict(news("엔비디아 중국 칩 공급", "company"), market="US", session_date="2026-11-04")
    result = {"session_news": [flash, company, close]}
    calls = []
    def fetch(url, title):
        calls.append(url)
        return {"body_status": "fetch_unavailable", "body_failure_reason": "timeout"}
    monkeypatch.setattr(article_context, "_article", fetch)
    article_context.enrich_article_context(result, NOW, priority_context=CONTEXT)
    assert calls[0] == close["link"]
    # The visible top three now take precedence over the old one-wrap quota.
    assert flash["link"] in calls
    assert len(calls) <= article_context.MAX_ARTICLES
    before = deepcopy(result)
    brief = build_news_brief(CONTEXT, result["session_news"], [], NOW, limit=1)
    assert brief["article_keys"] == [close["link"]]
    assert "제목만 확인" in "\n".join(brief["lines"])
    assert "본문 조회 실패: 본문 응답 시간 초과" in "\n".join(brief["lines"])
    assert result == before
    reused = build_news_brief(CONTEXT, result["session_news"], [], NOW, limit=1,
                              exclude_keys=[close["link"]])
    assert reused["article_keys"] == [close["link"]]
    reversed_brief = build_news_brief(CONTEXT, list(reversed(result["session_news"])), [], NOW, limit=1)
    assert reversed_brief["article_keys"] == [close["link"]]


def test_observed_move_bonus_never_crosses_market_or_session():
    item = news("반도체 급락", "chips")
    base = editorial_priority(item)
    assert editorial_priority(item, CONTEXT) > base + 20
    foreign = dict(item, market="US", session_date="2026-11-04")
    assert editorial_priority(foreign, CONTEXT) == editorial_priority(foreign) + 20
    old = dict(item, session_date="2026-11-04")
    assert editorial_priority(old, CONTEXT) == editorial_priority(old)
    empty = dict(CONTEXT, sector_rows=[dict(CONTEXT["sector_rows"][0], **{"1일수익률": float("nan")})])
    assert editorial_priority(item, empty) == base + 20
    unrelated = news("바이오 임상 시험 소식", "biotech")
    assert editorial_priority(unrelated, CONTEXT) == editorial_priority(unrelated) + 20


def test_table_and_workshop_do_not_receive_move_bonus():
    for title in ("[표] 코스피 종가 시세표", "공시담당자 워크숍"):
        assert editorial_priority(news(title, "noise"), CONTEXT) == -100
