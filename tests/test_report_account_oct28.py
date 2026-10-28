from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stock_lab_core.report_account import cumulative_account_metrics, cumulative_account_table
from stock_lab_core.report_intraday import layered_market_headline, latest_account_line
from stock_lab_core.report_presentation import candidate_fields, macro_change
from stock_lab_core.report_evidence import curate_news
from stock_lab_core.report_session import market_session_states


NOW = datetime(2026, 10, 28, 16, 54, tzinfo=ZoneInfo("Asia/Seoul"))


def fixture():
    context = {
        "sessions": {"KR": "2026-10-28", "US": "2026-10-27"},
        "prices": {
            "379810.KS": {"date": "2026-10-28", "previous_date": "2026-10-27", "return": .02},
            "RAM": {"date": "2026-10-27", "previous_date": "2026-10-26", "return": .10},
        },
        "extended_prices": {"RAM": {"date": "2026-10-28", "previous_date": "2026-10-27",
                                    "return": .05, "as_of": NOW.isoformat()}},
    }
    held = [{"ticker": "379810.KS", "current_w": 60}, {"ticker": "RAM", "current_w": 40}]
    return held, context


def test_compound_regular_and_extended_once_and_keep_input_unchanged():
    held, context = fixture()
    original = deepcopy(context)
    metrics = cumulative_account_metrics(held, context, market_session_states(NOW), NOW)
    assert metrics["coverage"] == 100
    assert metrics["total"] == pytest.approx(60 * .02 + 40 * .155)
    assert metrics["observations"]["RAM"]["previous_date"] == "2026-10-26"
    assert context == original
    table = "\n".join(cumulative_account_table(metrics))
    assert "최신 종가 기준 계좌 추정" not in table
    assert "장중 연결분 기여" not in table
    assert "2026-10-26 → 2026-10-28" in table
    assert "일간 손익 아님" in latest_account_line(metrics)


@pytest.mark.parametrize("missing", ["return", "previous_date", "date"])
def test_no_synthetic_zero_or_partial_leg_on_missing_regular_baseline(missing):
    held, context = fixture()
    context["prices"]["RAM"].pop(missing)
    metrics = cumulative_account_metrics(held, context, market_session_states(NOW), NOW)
    assert metrics["coverage"] == 60
    assert metrics["total"] == pytest.approx(1.2)
    assert "RAM" in metrics["missing"]


def test_closed_only_is_the_same_definition_without_extra_leg():
    held, context = fixture()
    context["extended_prices"] = {}
    metrics = cumulative_account_metrics(held, context, market_session_states(NOW), NOW)
    assert metrics["total"] == pytest.approx(5.2)


def test_market_mode_label_and_candidate_punctuation():
    held, context = fixture()
    result = layered_market_headline(context, [], market_session_states(NOW), NOW, {}, latest_metrics={"error": "test"})
    assert "[한국 마감·미국 현재]" in result
    assert "[장중]" not in result
    assert candidate_fields({"name": "Okta,", "ticker": "OKTA"})[0].startswith("Okta(OKTA)")


def test_move_sign_transition_does_not_claim_rising_level():
    report = macro_change({"MOVE": {"val": 102.2, "chg": -2.29}}, {"MOVE": {"val": 97.9, "chg": 1.95}})
    assert "102.20→97.90" in report
    assert "-8→+18" in report
    assert "부호 전환으로 인한 구간 점수 변화" in report


def test_quote_table_not_core_news_but_price_article_is_preserved():
    base = dict(publisher="연합뉴스", published_at=NOW.isoformat(), market="KR", session_date="2026-10-28")
    rows = [dict(base, title="[표] 국내 증시 시세표", link="https://www.yna.co.kr/view/a"),
            dict(base, title="코스피 상승 마감…반도체 강세", link="https://www.yna.co.kr/view/b")]
    assert [r["title"] for r in curate_news(rows, now=NOW)] == [rows[1]["title"]]
