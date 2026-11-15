from datetime import datetime, timezone

import pytest
import requests

from stock_lab_core import article_context as a
from stock_lab_core.report_news_selection import selected_category_lines


@pytest.mark.parametrize('error,code', [
    (requests.Timeout('private URL'), 'timeout'),
    (requests.ConnectionError('private token'), 'network_error'),
    (ValueError('http_403'), 'http_403'),
    (ValueError('response_too_large'), 'response_too_large'),
    (ValueError('private token'), 'parse_error'),
])
def test_fetch_diagnostics_preserve_only_safe_failure_codes(monkeypatch, error, code):
    def fail(url):
        raise error
    monkeypatch.setattr(a, '_public_bytes', fail)
    result = a._article.__wrapped__('https://www.fnnews.com/news/test', 'test')
    assert result == {'body_status': 'fetch_unavailable', 'body_failure_reason': code}
    assert 'private' not in str(result)


def test_report_distinguishes_failed_fetch_from_unselected_body(monkeypatch):
    rows = [dict(title='금융지주 회장 연임 요건 강화', publisher='파이낸셜뉴스',
                 market='GLOBAL', link='https://www.fnnews.com/news/test',
                 published_at='2026-11-02T20:00:00+09:00')]
    context = {'other_market_news': rows, 'news_retrieval': {
        'requested_categories': ['금융·은행'], 'per_category': 1}}
    now = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
    before = '\n'.join(selected_category_lines(context, now))
    assert '이번 본문 조회 대상에서 제외' in before
    monkeypatch.setattr(a, '_article', lambda *args: {
        'body_status': 'fetch_unavailable', 'body_failure_reason': 'http_403'})
    a.enrich_article_context(context, now)
    after = '\n'.join(selected_category_lines(context, now))
    assert '출처 응답 HTTP 403' in after
    assert '본문 근거 연결 완료' not in after and '사실(본문)' not in after
    assert context['news_retrieval']['article_body_attempted'] == 1
    assert context['news_retrieval']['article_body_verified'] == 0


def test_no_body_read_for_unconnected_source_is_not_network_failure():
    assert a.body_unavailable_reason({'link': 'https://news.google.com/rss/articles/test'}) == '본문 자동연결 대상 출처 아님'
    assert a.body_unavailable_reason({'body_status': 'headline_mismatch'}) == '기사 제목 대조 불일치'
    assert 'private' not in a.body_unavailable_reason({'body_status': 'fetch_unavailable', 'body_failure_reason': 'private'})


@pytest.mark.parametrize('row,expected', [
    ({'link': 'https://www.yna.co.kr/view/synthetic'}, '조회 대상 제외'),
    ({'link': 'https://news.google.com/rss/articles/synthetic'}, '미지원 출처'),
    ({'body_status': 'no_supported_context'}, '본문 확인·해석 보류'),
    ({'body_status': 'verified', 'body_scenarios': [{'condition': 'synthetic'}]}, '본문 확인·해석 보류'),
    ({'body_status': 'fetch_unavailable', 'body_failure_reason': 'http_403'}, '접근·검증 실패'),
    ({'body_status': 'headline_mismatch', 'body_facts': [{'summary': 'stale'}]}, '접근·검증 실패'),
    ({'body_status': 'verified', 'body_facts': [{'summary': 'supported'}]}, '근거 연결'),
])
def test_body_coverage_categories_do_not_conflate_budget_parse_or_http_failure(row, expected):
    assert a.body_connection_state(row) == expected


def test_theme_evidence_explains_unread_articles_without_claiming_all_facts_checked():
    from stock_lab_core.report_digest import weekly_themes, weekly_source_lines, connection_checks
    now = datetime.fromisoformat('2026-11-16T00:17:00+09:00')
    base = dict(title='이란 제재 발표', publisher='연합뉴스', market='GLOBAL',
                published_at='2026-11-15T10:00:00+09:00')
    rows = [dict(base, link='https://www.yna.co.kr/view/synthetic'),
            dict(base, title='중동 원유 공급 보도', link='https://news.google.com/rss/articles/synthetic'),
            dict(base, title='이란 원유 수출 제재 확대', link='https://www.yna.co.kr/view/failed',
                 body_status='fetch_unavailable', body_failure_reason='http_403')]
    digest = weekly_themes({}, rows, [], now)
    text = '\n'.join(weekly_source_lines(digest))
    assert '조회 대상 제외' in text and '미지원 출처' in text and 'HTTP 403' in text
    checks = connection_checks({}, [], digest, '', now)
    check = next(row for row in checks if row[0] == '상위 테마 본문')
    assert check[1] == '미확인'
    assert all(term in check[2] for term in ('조회 대상 제외 1건', '미지원 출처 1건', '접근·검증 실패 1건'))
