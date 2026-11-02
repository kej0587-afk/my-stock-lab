"""Synthetic publisher contracts; no remote articles or credentials in fixtures."""

from datetime import datetime
from html import escape
import json

import pytest

from stock_lab_core import article_context as a

URL = "https://www.fnnews.com/news/SYNTHETIC"
TITLE = "조선주, 해외 수주 소식에 강세"
NOW = datetime.fromisoformat("2026-11-02T22:00:00+09:00")


def page(body, *, title=TITLE, modified="2026-11-02T16:00:00+09:00", free=True):
    metadata = {"@context": "https://schema.org", "@graph": [{
        "@type": "NewsArticle", "headline": title, "datePublished": "2026-11-02T16:00:00+09:00",
        "dateModified": modified, "isAccessibleForFree": free}]}
    return ('<meta charset="utf-8"><script type="application/ld+json">' + json.dumps(metadata)
            + '</script><aside>조선 수주 소식이 실적 기대를 높였다.</aside>'
            + '<div class="article-view__body">' + body + '</div>').encode()


def test_direct_publisher_body_and_evidence_are_scoped_not_full_article():
    result = a.parse_article(page('<p>조선 관련 해외 수주 소식과 향후 사업 확대 기대가 업종에 거론됐다.</p>'), URL, TITLE)
    assert result['body_status'] == 'verified'
    assert result['body_facts'][0]['topic'] == 'shipbuilding_orders'
    assert '확정 계약은 다릅니다' in result['body_facts'][0]['implication']
    assert all(len(f['evidence']) <= 141 for f in result['body_facts'])
    assert 'articleBody' not in result and 'paragraphs' not in result


def test_related_news_and_captions_cannot_create_body_evidence():
    body = '<figure>조선 관련 수주 소식과 기대가 확산됐다는 사진 설명입니다.</figure>'
    body += '<p>회사는 기자 간담회에서 일반적인 사업 운영 현황을 설명했다.</p>'
    result = a.parse_article(page(body), URL, TITLE)
    assert result['body_status'] == 'no_supported_context'
    assert not result['body_facts']
    assert a.parse_article(page(''), URL, TITLE)['body_status'] == 'article_body_unavailable'


@pytest.mark.parametrize('body', [
    '조선 관련 수주 소식은 없었다는 회사의 공식 확인이 공개됐다.',
    '지난해 조선 수주 소식으로 기대가 커졌다는 과거 사례를 회고했다.',
])
def test_sector_body_does_not_turn_negation_or_history_into_current_fact(body):
    result = a.parse_article(page('<p>' + escape(body) + '</p>'), URL, TITLE)
    assert not result.get('body_facts')


def test_bank_governance_has_specific_interpretation_without_price_claim():
    title = '금융지주 회장 연임 요건 강화'
    result = a.parse_article(page('<p>금융지주 회장의 연임 요건이 강화돼 주주의 찬성 기준이 달라진다.</p>', title=title), URL, title)
    assert result['body_facts'][0]['topic'] == 'bank_governance'
    assert '상승을 뜻하지 않습니다' in result['body_facts'][0]['implication']


def test_inline_emphasis_preserves_bank_sentence_and_block_boundaries():
    title = '금융지주 회장 연임 요건 강화'
    plain = '<p>금융지주 회장의 연임 요건이 강화돼 주주의 찬성 기준이 달라진다.</p>'
    marked = plain.replace('연임', '<strong>연임</strong>').replace('찬성', '<a href="/">찬성</a>')
    expected = a.parse_article(page(plain, title=title), URL, title)
    actual = a.parse_article(page(marked, title=title), URL, title)
    assert actual['body_status'] == 'verified'
    assert actual['body_facts'] == expected['body_facts']
    unrelated = '<p>금융지주 회장의 연임 문제를 살펴봤다는 일반적인 설명입니다.</p><p>이번 행사에서는 별도 안건의 주주 찬성 요건을 발표했습니다.</p>'
    assert not a.parse_article(page(unrelated, title=title), URL, title).get('body_facts')


def test_identity_and_access_checks_also_apply_to_new_publisher():
    assert a.parse_article(page('text', free=False), URL, TITLE)['body_status'] == 'restricted_article'
    assert a.parse_article(page('text', title='different'), URL, TITLE)['body_status'] == 'headline_mismatch'
    assert not a._safe_url('https://fnnews.com.attacker.invalid/news/a')


def test_entity_escaped_metadata_title_matches_same_headline_but_not_different_news():
    body = '<p>조선 관련 해외 수주 소식과 향후 사업 확대 기대가 업종에 거론됐다.</p>'
    data = page(body, title='조선주 &apos;수주 소식&apos;')
    assert a.parse_article(data, URL, "조선주 '수주 소식'")['body_status'] == 'verified'
    assert a.parse_article(data, URL, "조선주 '수주 취소'")['body_status'] == 'headline_mismatch'


def test_feeds_include_sector_articles_with_correct_publisher_and_uncertain_market():
    xml = ('<rss><channel><item><title>조선주, 해외 수주 소식</title><link>' + URL
           + '</link><pubDate>Mon, 02 Nov 2026 16:00:00 +0900</pubDate></item></channel></rss>').encode()
    rows = a.parse_publisher_feed(xml)
    assert len(rows) == 1 and rows[0]['publisher'] == '파이낸셜뉴스'
    assert rows[0]['market'] == 'GLOBAL'  # Korean language alone is not a market identity.


def test_other_market_bodies_are_read_with_same_budget_and_version_check(monkeypatch):
    item = dict(title=TITLE, link=URL, market='GLOBAL', published_at='2026-11-02T16:00:00+09:00')
    result = {'other_market_news': [item]}
    evidence = a.parse_article(page('<p>회사는 기자 간담회에서 일반적인 사업 운영 현황을 설명했다.</p>',
                                    modified='2026-11-03T16:00:00+09:00'), URL, TITLE)
    monkeypatch.setattr(a, '_article', lambda *args: evidence)
    a.enrich_article_context(result, NOW)
    assert item['body_status'] == 'article_version_after_report'
    assert result['news_retrieval']['article_body_attempted'] == 1
    assert result['news_retrieval']['article_body_statuses'] == {'article_version_after_report': 1}


def test_ipo_rally_does_not_displace_market_wrap_and_four_article_budget(monkeypatch):
    titles = ['[특징주] 신규기업, 코스닥 상장 첫날 급등 마감',
              '코스피, 기술주 하락 딛고 반등(종합)', '코스피 상승 마감',
              '금융지주 회장 연임 요건 강화', '조선주 수주 소식에 상승',
              'Bank stocks earnings beat estimates']
    rows = [dict(title=title, link=URL + str(i), market='KR' if i < 3 else 'GLOBAL',
                 published_at='2026-11-02T16:00:00+09:00', is_close_wrap=i < 3) for i, title in enumerate(titles)]
    calls = []
    def read(url, title):
        calls.append(title)
        return {'body_status': 'fetch_unavailable'}
    monkeypatch.setattr(a, '_article', read)
    a.enrich_article_context({'session_news': rows}, NOW)
    assert len(calls) == a.MAX_ARTICLES == 4
    assert calls[0] == titles[1]
    assert titles[2] not in calls


def test_new_publisher_reaches_source_curator():
    from stock_lab_core.report_evidence import curate_news
    result = curate_news([dict(title='금융지주 회장 연임 요건 강화', publisher='파이낸셜뉴스',
                              link=URL, published_at='2026-11-02T16:00:00+09:00')], now=NOW)
    assert len(result) == 1 and result[0]['category'] == '금융·은행'


def test_opening_selloff_background_does_not_become_all_day_cause():
    facts = a._body_facts(['기업 실적이 시장 기대에 미치지 못하면서 코스피는 하락 출발했다.',
                           '기관은 유가증권시장에서 순매수하며 지수의 반등을 뒷받침했다.'])
    assert [f['topic'] for f in facts] == ['earnings', 'institution_buying']
    assert facts[0]['market_phase'] == 'opening'
    assert '종가까지 같은 영향' in facts[0]['implication']
    reading = a.body_context_sentence({'body_status': 'verified', 'body_facts': facts})
    assert '장 초반 기업 실적·전망 부진' in reading and '기관 순매수' in reading
    assert not a._body_facts(['기관의 순매수는 없었다는 확인이 뒤늦게 공개됐다.'])
