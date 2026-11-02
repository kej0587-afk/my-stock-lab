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
