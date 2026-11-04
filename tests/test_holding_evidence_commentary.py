from copy import deepcopy

import pandas as pd
import pytest

from stock_lab_core.holding_evidence_commentary import build_holding_evidence_commentary as build
from stock_lab_core.portfolio_market_review import holding_market_review


NOW = "2026-11-04T10:00:00+09:00"


def choices(label="축소/교체 검토"):
    return pd.DataFrame([
        {"검토 방향": "보유 유지", "현재 근거": label + " · 밸류 미점검", "확인할 조건": "이익·FCF 대조"},
        {"검토 방향": "축소 / 손절 검토", "현재 근거": "비중 9% / 목표 6%", "확인할 조건": "기존 손실·비중 조건"},
        {"검토 방향": "현금 대기", "현재 근거": "방어우선", "확인할 조건": "기존 게이트 해제 조건"},
    ])


def evidence():
    return {"flow_evidence": [{"ticker": "DRAM", "date": "2026-11-03", "five": -.08, "medium": .20, "flow_score": -2}],
            "facts": [{"대상": "RAM", "근거": "보유 종목 · 시간외", "관측": "-7.13%", "기준": "11/04 09:55 KST"}],
            "earnings": [{"기업": "기업A", "발표/기간": "2026-11-01 / Q3", "항목": "매출",
                          "근거": "Revenue 12 billion", "구분": "공식 발표", "출처": "https://example.com/ir",
                          "연결": "기초 ETF DRAM 구성기업"}], "news": []}


def test_synthesis_links_current_flow_earnings_and_existing_conditions_without_mutation():
    view, options = evidence(), choices()
    before, options_before = deepcopy(view), options.copy(deep=True)
    result = build("RAM", view, options)
    assert "노출 조절 조건부터" in result["headline"]
    assert "-7.13%" in result["current"]
    assert "-8.00%" in result["flow"] and "+20.00%" in result["flow"]
    assert "중기 상승 안에서 단기" in result["flow"]
    assert "기업A" in result["company"] and "FCF" in result["company"]
    assert "ETF 전체 실적" in result["company"]
    assert "공식 실적 자료는 연결됐지만 최근 가격 흐름은 약합니다" in result["connection"]
    assert result["conditions"][1]["대응을 바꾸기 전 확인"] == "기존 손실·비중 조건"
    assert result["conditions"][2]["대응을 바꾸기 전 확인"] == "기존 게이트 해제 조건"
    assert result["evidence"][0]["확인 근거 · 원문"] == "Revenue 12 billion"
    assert view == before
    pd.testing.assert_frame_equal(options, options_before)
    assert not {"score", "decision", "gate", "order"}.intersection(result)


@pytest.mark.parametrize("label,phrase", [("위성/집중 축소 검토", "노출 조절"), ("보유 유지", "추가매수 승인으로 바꾸지"),
                                         ("조건부 대기", "재개 조건"), ("미확인", "우선순위는 보류")])
def test_priority_only_uses_existing_management_label(label, phrase):
    assert phrase in build("TEST", evidence(), choices(label))["headline"]


def test_sources_and_forecasts_are_not_manufactured_or_used_as_sentiment_rules():
    view = evidence()
    original = view["earnings"][0]
    view["earnings"] += [dict(original, 항목=key, 근거="FCF -20 to +100 forecast, not current cash", 구분="회사 전망 · 실제치 아님")
                         for key in ("회사 전망", "설비투자(CAPEX)", "잉여현금흐름(FCF)")]
    result = build("TEST", view, choices("미확인"))
    assert "전망은 실제치가 아니며" in result["company"]
    assert "우선순위는 보류" in result["headline"]
    assert "FCF -20 to +100" in result["evidence"][0]["확인 근거 · 원문"]
    view["earnings"] = [dict(original, 출처="", 구분="확인 보류")]
    assert not build("TEST", view)["evidence"]


def test_stale_dates_and_memberships_do_not_reappear_in_synthesis():
    data = {"sessions": {"US": "2026-11-03"}, "prices": {"RAM": {"date": "2026-11-02", "return": .20}},
            "closed_flow_rows": [{"Ticker": "DRAM", "기준일": "2026-11-02", "5일수익률": .30, "3개월수익률": .40}],
            "earnings": [{"ticker": "MSFT", "date": "2026-11-01", "official": True}]}
    review = holding_market_review("RAM", data, {}, now=NOW)
    result = build("RAM", review)
    assert not result["current"] and not result["evidence"]
    assert "추세에 근거한 보유·축소 해석은 보류" in result["flow"]


def test_no_new_data_collection_when_rendering_or_switching():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from stock_lab_core.portfolio_market_review import render_market_review, EVIDENCE_KEY
st.session_state[EVIDENCE_KEY] = {'scope': 'A', 'data': {'quote_checked_at': datetime.now(timezone.utc).isoformat(), 'sessions': {}, 'prices': {}}}
ticker = st.selectbox('Holding', ['RAM', 'CIBR'])
render_market_review(st, ticker, 'A', choices=pd.DataFrame())
''').run(timeout=30)
    assert not app.exception
    assert len([e for e in app.expander if '변경 조건' in e.label]) == 3
    app.selectbox[0].select('CIBR').run(timeout=30)
    assert not app.exception
    assert any('CIBR:' in m.value for m in app.markdown)
