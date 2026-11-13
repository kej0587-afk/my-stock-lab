from copy import deepcopy
from datetime import datetime

import pytest

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_input_status import history_panel_lines, report_count_status
from stock_lab_core.report_news_ads import is_financing_promotion

NOW = datetime.fromisoformat("2026-11-13T10:39:00+09:00")
AD = "AI 호실적에도 경계감…신용미수 이자를 연5%대 금리로"


@pytest.mark.parametrize("title", [AD, "주식담보대출 최저 금리 상담 신청", "스탁론 이자 면제 혜택"])
def test_promotion_excluded(title):
    assert is_financing_promotion({"title": title})


@pytest.mark.parametrize("title", ["신용융자잔고 급증, 반대매매 경계", "증권사 신용대출 금리 상승에 투자자 부담",
                                  "AI 실적 발표, 금리 인상 가능성", "5일간 3000억 강제청산"])
def test_market_credit_reporting_retained(title):
    assert not is_financing_promotion({"title": title})


def test_empty_input_is_not_zero_or_deleted_history():
    ctx = {"history_status": "점검 판정 미연결: 비교 저장 보류", "history_durable": False}
    out = "\n".join(history_panel_lines([], ctx))
    assert "수행하지 않았습니다" in out
    assert "재배포" not in out and "비교 가능한 과거" not in out
    assert report_count_status([], 0, 0) == "매수 허용 여부 미확인 / 보유 미수집, 관심 미수집"
    assert report_count_status([{"ticker": "X"}], 1, 0) == "신규매수 허용 0개 / 보유 1, 관심 0"


@pytest.mark.parametrize("backend,durable,warning", [("supabase", True, False), ("local", False, True), ("none", False, False)])
def test_history_warning_matches_actual_backend(backend, durable, warning):
    out = "\n".join(history_panel_lines([{"ticker": "X"}],
        {"history_backend": backend, "history_durable": durable, "history_status": "status"}))
    assert ("재배포" in out) == warning
    if backend == "none":
        assert "조회 미확인" in out


@pytest.mark.parametrize("rows", [[], [{"티커": "MSFT", "보유수량": 1, "현재비중": 10, "게이트상태": "방어우선"}]])
def test_full_report_scope_and_ads_do_not_mutate_inputs(rows):
    news = {"title": AD, "publisher": "아시아경제", "published_at": NOW.isoformat(),
            "link": "https://www.asiae.co.kr/article/test", "market": "KR", "session_date": "2026-11-13"}
    ctx = {"sessions": {"KR": "2026-11-12", "US": "2026-11-12"},
           "session_news": [], "current_session_news": [news], "prices": {}}
    saved = deepcopy((rows, ctx))
    out = build_auto_market_memo(summary_rows=rows, report_context=ctx, now=NOW)
    assert (rows, ctx) == saved
    assert AD not in out
    if not rows:
        assert "시장 전용 리포트" in out and "보유 미수집, 관심 미수집" in out
        assert "입력 미수집 — 이 리포트의 계좌 판단 불가" in out
        assert "보유 0, 관심 0" not in out and "연결 0.0%" not in out
        assert "과거 이력의 존재 여부나 소실을 뜻하지 않습니다" in out
    else:
        assert "계좌 연결 리포트" in out
