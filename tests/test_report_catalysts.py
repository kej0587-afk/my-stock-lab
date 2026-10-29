from copy import deepcopy
from datetime import datetime

from stock_lab_core.report_catalysts import post_close_brief


NOW = datetime.fromisoformat("2026-10-29T10:32:00+09:00")


def context():
    return {"sessions": {"US": "2026-10-28"},
            "windows": [{"market": "US", "date": "2026-10-28", "end": "2026-10-28T16:00:00-04:00"}],
            "next_session_news": [{"title": "Alphabet stock falls in extended trading as capex and free cash flow worry investors",
                                   "market": "US", "published_at": "2026-10-28T17:00:00-04:00",
                                   "publisher": "CNBC", "link": "https://www.cnbc.com/fixture-earnings"}]}


def test_post_close_earnings_appears_separately_even_when_regular_close_rose():
    data = context()
    data["prices"] = {"^GSPC": {"date": "2026-10-28", "return": .0028}}
    before = deepcopy(data)
    result = post_close_brief(data, [], [{"티커": "GOOGL", "게이트상태": "방어우선"}], NOW)
    assert "시간외 하락 보도" in result["overview"]
    assert "현금 창출력" in result["overview"]
    assert "정규장 등락 원인으로 소급하지" in result["overview"]
    assert "제목 기준·기사 주장" in "\n".join(result["lines"])
    assert result["article_keys"] == [data["next_session_news"][0]["link"]]
    assert data == before


def test_no_guessed_close_time_or_misdated_news():
    data = context()
    data["windows"] = []
    assert not post_close_brief(data, [], [], NOW)["overview"]
    data = context()
    data["next_session_news"][0]["published_at"] = "2026-10-28T15:00:00-04:00"
    assert not post_close_brief(data, [], [], NOW)["overview"]
    data["next_session_news"][0]["published_at"] = "2026-10-29T20:00:00-04:00"
    assert not post_close_brief(data, [], [], NOW)["overview"]
