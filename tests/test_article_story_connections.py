"""Synthetic body → reading regressions; no publisher text or network."""
from copy import deepcopy

import pytest

from stock_lab_core.article_context import body_context_sentence, verified_body_facts
from stock_lab_core.report_brief import build_news_brief, news_observation
from tests.test_article_market_events import article, context, NOW


def test_governance_collection_filter_requires_financial_subject():
    from stock_lab_core.report_brief import material_news
    assert material_news({'title': '금융지주 회장 연임 요건 강화'})
    assert not material_news({'title': '축구 감독 연임 요건 강화'})


def test_named_company_market_wrap_retains_risks_and_specific_checks():
    row = article([
        "경영진 공백과 규제 불확실성에 대한 우려가 투자자들 사이에서 커졌다.",
        "AI 인프라 확충 부담으로 관련 서버 업종에 대한 경계가 이어졌다고 전했다.",
        "미국 국채 금리는 상승하며 기업 자금조달 비용에 대한 관심을 높였다.",
    ], title="뉴욕증시, NVIDIA 약세와 국채금리 상승에 혼조 마감")
    facts = verified_body_facts(row)
    assert {f['topic'] for f in facts} >= {'business_uncertainty', 'ai_credit', 'rates'}
    assert "인프라 확충 부담" in body_context_sentence(row)
    assert "규제 불확실성" in body_context_sentence(row)
    held = [{'티커': 'SOXL', '보유량': 1, '게이트상태': '방어우선'},
            {'티커': 'CIBR', '보유량': 1, '게이트상태': '방어우선'}]
    ctx = context()
    saved = deepcopy((ctx, row, held))
    output = '\n'.join(build_news_brief(ctx, [row], held, NOW, compact=True, limit=None)['lines'])
    ai = next(line for line in output.splitlines() if '인프라 확충 부담' in line)
    rates = next(line for line in output.splitlines() if '국채 금리는 상승' in line)
    assert 'SOXL' in ai and 'CIBR' not in ai
    assert 'AI 투자 계획' in ai and '현금흐름' in ai
    assert '보유 전반의 금리·환율 민감도' in rates and 'SOXL' not in rates
    assert '2년·10년 금리' in rates and '해석(추정)' in rates
    assert '공식 발표와 보도 시점·적용 대상 확인' not in output
    assert output.count('인프라 확충 부담') == 1
    assert (ctx, row, held) == saved


@pytest.mark.parametrize('sentence', [
    '경영진 공백과 규제 불확실성에 대한 우려는 사실이 아니라고 회사가 발표했다.',
    '지난해 경영진 공백과 규제 불확실성에 대한 우려가 커졌던 일을 설명했다.',
    '경영진 공백과 규제 불확실성에 대한 우려가 해소됐다고 회사가 발표했다.',
])
def test_denied_past_or_resolved_risk_is_not_current_risk(sentence):
    assert not any(f['topic'] == 'business_uncertainty' for f in article([sentence])['body_facts'])


def test_non_market_company_article_does_not_donate_generic_index_cause():
    row = article(['AI 인프라 확충 부담이 기업의 현금 지출을 늘렸다는 분석이 나왔다.'],
                  title='Amazon 현금흐름 분석')
    assert '시장 배경' not in body_context_sentence(row)
    assert not any(f['topic'] == 'ai_credit' for f in row['body_facts'])


def test_datacenter_borrowing_concern_is_attributed_not_an_actual_default():
    sentence = '클라우드 사업자들이 차입으로 설비투자를 확대하는 가운데 전력 확보와 인허가 절차 및 장비 조달 일정이 영향을 주면서 데이터센터의 투자 회수까지 시간이 길어질 수 있다는 우려가 나온다.'
    row = article([sentence], title='AI 데이터센터 건설 투자 부담 점검')
    fact = next(f for f in verified_body_facts(row) if f['topic'] == 'ai_credit')
    assert sentence in fact['summary'] and '우려' in fact['summary']
    assert '지연될 수' in fact['implication'] and '현금흐름' in fact['check']
    assert '불이행' not in fact['summary']


def test_actual_treasury_response_survives_generic_policy_prose():
    row = article(['물가 발표는 기준금리 인상에 대한 우려를 일부 덜었다.',
                   '그러나 미 국채 금리는 상승했고 달러는 강세를 이어갔다.'])
    fact = next(f for f in verified_body_facts(row) if f['topic'] == 'rates')
    assert '그러나 미 국채' in fact['summary']


def test_same_sentence_multiple_channels_keep_checks_without_repeating_evidence():
    sentence = '미국 국채 금리는 상승했고 금융권 신용 부담도 커졌다.'
    row = article([sentence])
    output = '\n'.join(build_news_brief(context(), [row], [], NOW, compact=True, limit=None)['lines'])
    assert output.count(sentence) == 1
    assert '2년·10년 금리' in output and '부채 만기' in output


def test_post_close_body_connects_holdings_without_rewriting_last_close():
    from stock_lab_core.report_coverage import context_news_lines
    row = article(['클라우드 사업자들이 차입으로 설비투자를 확대하면서 데이터센터의 투자 회수 부담이 커졌다는 우려가 나온다.'],
                  title='AI 데이터센터 투자 부담 점검')
    row.update(market='GLOBAL', news_bucket='other_market_news')
    ctx = dict(context(), other_market_news=[row])
    held = [{'티커': 'SOXL', '보유량': 1}, {'티커': 'CIBR', '보유량': 1}]
    before = deepcopy((ctx,held))
    out = '\n'.join(context_news_lines(ctx, NOW, bucket='other_market_news', summary_rows=held))
    assert 'SOXL' in out and 'CIBR' not in out
    assert '타시장' in out and '현금흐름' in out
    assert (ctx,held) == before


def test_main_intro_does_not_repeat_the_body_evidence_table():
    from stock_lab_core.report_reading import compose_reading_report
    sentence = 'AI 인프라 확충 부담으로 관련 서버 업종에 대한 경계가 이어졌다고 전했다.'
    row = article([sentence])
    output = compose_reading_report('# Stock Lab\n', context=context(), news=[row],
                                    summary_rows=[], now=NOW)
    main = output.split('## 상세 근거', 1)[0]
    assert main.count(sentence) == 1
    assert '발주·가동' in main and '현금흐름' in main


@pytest.mark.parametrize('change', [
    {'body_status': 'fetch_unavailable'}, {'session_date': '2026-11-11'},
    {'news_bucket': 'next_session_news'}, {'published_at': '2026-11-14T07:00:00+09:00'},
])
def test_story_keeps_existing_verification_and_session_guards(change):
    row = article(['AI 인프라 확충 부담으로 관련 서버 업종에 대한 경계가 이어졌다고 전했다.'])
    row.update(change)
    output = '\n'.join(build_news_brief(context(), [row], [], NOW, compact=True, limit=None)['lines'])
    assert '해석(추정)' not in output


@pytest.mark.parametrize('title,label', [
    ('S&P500 선물 상승…금리 하락', '선물 관측'),
    ('Wall Street futures rise after cash close', '선물 관측'),
    ('나스닥 시간외 반등', '정규장 외 보도'),
    ('뉴욕증시, 혼조 마감', '이전 종가 관측'),
    ('S&P500 기업 설비투자 분석', '이전 거래일 보도'),
])
def test_prior_night_futures_and_generic_index_mentions_are_not_cash_close(title, label):
    row = dict(title=title, market='US', session_date='2026-11-13',
               published_at='2026-11-13T12:15:00+09:00')
    output = news_observation(row, {'sessions': {'US': '2026-11-13'}})[1]
    assert label in output and '2026-11-12' in output
    if label != '이전 종가 관측':
        assert '이전 종가 관측' not in output
