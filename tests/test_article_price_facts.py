import pytest

from stock_lab_core.article_context import _body_facts, body_context_sentence
from stock_lab_core.article_price_facts import oil_price_fact


@pytest.mark.parametrize("sentence,topic", [
    ("국제유가 급등 속에 주가지수가 하락 마감했다.", "oil_rising"),
    ("주가지수가 국제유가 급등 속에 일제히 하락 마감했다.", "oil_rising"),
    ("주가지수가 국제유가 급등으로 하락했다.", "oil_rising"),
    ("유가가 상승했고 금값은 하락했다.", "oil_rising"),
    ("WTI도 3.8% 상승한 배럴당 103달러에 마감했다.", "oil_rising"),
    ("Oil prices rose while stocks fell.", "oil_rising"),
    ("유가가 하락하고 주가는 상승했다.", "oil_easing"),
    ("Oil prices fell while equities rose.", "oil_easing"),
    ("Oil prices rose early but fell by the close.", "oil_mixed"),
    ("유가는 오전 상승했다가 오후 하락했다.", "oil_mixed"),
    ("유가 상승세가 진정됐다.", None),
    ("유가 하락 우려에 주가가 떨어졌다.", None),
    ("유가가 하락하지 않았고 주가가 하락했다.", None),
    ("유가 하락이 예상된다.", None),
    ("Oil prices are expected to rise while stocks fell.", None),
    ("유가증권시장이 하락했다.", None),
    ("유가 부담에 주가지수가 하락했다.", None),
    ("유가에 대한 우려로 증시가 하락했다.", None),
])
def test_oil_direction_belongs_to_oil_not_the_stock_market(sentence, topic):
    fact = oil_price_fact([sentence])
    assert (fact or {}).get("topic") == topic


def test_mixed_periods_do_not_force_a_direction():
    fact = oil_price_fact(["전날 유가는 하락했다.", "오늘 WTI는 상승했다."])
    assert fact["topic"] == "oil_mixed"


def test_verified_article_cannot_turn_oil_rise_into_easing():
    facts = _body_facts(["국제유가 급등 속에 주가지수가 하락 마감했다.",
                         "금 현물가격은 하락했다."])
    assert [fact["topic"] for fact in facts] == ["oil_rising"]
    result = body_context_sentence({"body_status": "verified", "body_facts": facts})
    assert "유가 상승" in result and "유가 하락" not in result
