"""Report 61 (2026-11-24): wire-update duplicates and bank-as-forecaster labels."""
from stock_lab_core.report_brief import _comprehensive_theme
from stock_lab_core.today_news import _session_article_keys


def test_wire_update_versions_share_one_title_key():
    base = "코스피, '젠슨황 복귀'에 5~6%대 급등…'5천피' 탈환 시도"
    keys = {_session_article_keys({"title": t, "link": f"https://www.yna.co.kr/view/A{i}"})[1]
            for i, t in enumerate([base, base.replace("~", "∼") + "(종합)", base + " (종합2보)", "[속보] " + base])}
    assert len(keys) == 1
    other = _session_article_keys({"title": base.replace("5천피", "4천피"), "link": "https://x.test/a"})[1]
    assert other not in keys  # Different facts stay separate.


def test_bank_quoted_as_forecaster_is_classified_by_topic_not_as_finance():
    assert _comprehensive_theme({"title": 'JP모건 "내년 AI 자본지출 1.4조달러…올해의 2배"'}) == "반도체·AI"
    assert _comprehensive_theme({"title": '골드만삭스 "유가 80달러 간다"'}) == "에너지·지정학"
    assert _comprehensive_theme({"title": 'JP모건 "연준, 향후 3회 연속 25bp 금리인상 전망"'}) == "금리·경제지표"
    # The bank's own results remain financial news.
    assert _comprehensive_theme({"title": 'JP모건 "3분기 순이익 20% 증가"'}) == "금융"
    assert _comprehensive_theme({"title": "JP모건, 3분기 실적 호조"}) == "금융"


def test_broker_sector_call_is_not_filed_under_finance():
    theme = _comprehensive_theme({"title": '키움증권 "이차전지, 내년부터 실적회복…업종 투자의견 상향"'})
    assert theme != "금융"
    assert _comprehensive_theme({"title": '키움증권 "3분기 순이익 사상 최대"'}) == "금융"
