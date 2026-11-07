"""Synthetic report contract: provenance, failure isolation, zero scoring writes."""
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_msft_ir_review import packet, NOW, HOME, HOME_HTML, RELEASE_URL, RELEASE, CALL_URL, CALL
from stock_lab_core.report_msft import msft_business_lines, usable_packet
from stock_lab_core import report_msft_source as source
from stock_lab_core.msft_ir_source import load_msft_business_evidence


def render(p, **kwargs):
    return '\n'.join(msft_business_lines({'msft_business_evidence': {'packet': p}}, NOW, **kwargs))


def test_story_actual_guidance_and_review_have_distinct_roles():
    p = packet()
    rows = [{'티커': 'MSFT', '보유수량': 2, '판정': '원래 판정', 'Adj점수': 42}]
    before = deepcopy((p, rows))
    text = render(p, summary_rows=rows)
    assert all(s in text for s in ['발표 2026-10-28', '2026-09-30 종료', 'Azure 매출 전년 대비 +40%',
        '영업현금흐름 60십억 달러', '현금 유형자산 지출 40십억 달러', '2026-12-31 종료 예상',
        '55십억 달러 초과', '해석(추정)', '다음 실적에서', '컨센서스 대비 평가는 미연결', RELEASE_URL, CALL_URL])
    assert '999' not in text and '적정가 40' not in text
    assert (p, rows) == before


@pytest.mark.parametrize('key,value', [('checked_at', (NOW+timedelta(seconds=1)).isoformat()),
    ('checked_at', (NOW-timedelta(days=2)).isoformat()), ('release_date', '2026-12-01'),
    ('ticker', 'OTHER'), ('source_url', 'https://evil.example'), ('period_end', '2026-06-30'),
    ('eligible_for_scoring', True)])
def test_future_stale_or_mismatched_packet_withheld(key, value):
    p=packet(); p[key]=value
    assert not usable_packet(p, NOW)
    assert '해석을 보류' in render(p) and '60십억' not in render(p)


@pytest.mark.parametrize('field,value', [('kind','reported_actual'), ('scope','cash_ppe'),
    ('period','FY2026Q4'), ('source_url',RELEASE_URL), ('operator','eq'), ('value',float('nan'))])
def test_guidance_never_becomes_actual_or_consensus(field,value):
    p=packet(); next(m for m in p['metrics'] if m['key']=='next_capex')[field]=value
    text=render(p)
    assert '회사 투자 전망 미확인' in text and '55십억' not in text
    assert 'Azure 매출' in text


def test_missing_partial_and_negative_cash_coverage():
    p=packet(); p['metrics']=[m for m in p['metrics'] if m['key']!='next_capex']; p['status']='partial'
    next(m for m in p['metrics'] if m['key']=='cash_ppe')['value']=70
    assert '영업현금흐름을 넘습니다' in render(p)
    assert '회사 투자 전망 미확인' in render(p)
    p['metrics']=[m for m in p['metrics'] if m['key']!='ocf']
    assert '현금 부담 판단 보류' in render(p)
    assert msft_business_lines({}, NOW)==[]


def test_duplicate_conflicting_metric_is_not_silently_chosen():
    p=packet(); p['metrics'].append(dict(next(m for m in p['metrics'] if m['key']=='azure_growth'),value=99))
    assert '수요 해석 보류' in render(p)


def test_old_release_not_a_current_catalyst_and_expired_packet_withheld():
    p=packet()
    assert '오늘의 등락 원인과 분리' in render(p)
    late=NOW+timedelta(days=151); p['checked_at']=late.isoformat()
    assert not usable_packet(p,late)


def test_past_forecast_period_is_not_presented_as_current_guidance():
    now=NOW+timedelta(days=60)
    p=packet(); p['checked_at']=now.isoformat()
    text='\n'.join(msft_business_lines({'msft_business_evidence':{'packet':p}},now))
    assert '투자 전망 대상기간 종료' in text and '55십억' not in text


def test_collect_three_pages_once_and_reuse_success_without_render_io(monkeypatch):
    calls=[]
    def read(url,deadline):
        calls.append(url)
        return {HOME:HOME_HTML,RELEASE_URL:RELEASE,CALL_URL:CALL}[url]
    monkeypatch.setattr(source,'_CACHE',{})
    monkeypatch.setattr(source,'load_msft_business_evidence',lambda now: load_msft_business_evidence(now,read_page=read))
    first=source.collect_msft_report_evidence(NOW)
    second=source.collect_msft_report_evidence(NOW+timedelta(minutes=1))
    msft_business_lines({'msft_business_evidence':first},NOW)
    msft_business_lines({'msft_business_evidence':first},NOW)
    assert calls==[HOME,RELEASE_URL,CALL_URL]
    assert first['collection']=='collected' and second['collection']=='success_cache'
    second['packet']['metrics'].clear()
    assert source._CACHE['packet']['metrics']


def test_failed_query_not_cached_or_silently_replaced_by_old_success(monkeypatch):
    calls=[]
    def failed(now): calls.append(now); raise ValueError('sensitive provider body')
    monkeypatch.setattr(source,'_CACHE',{})
    monkeypatch.setattr(source,'load_msft_business_evidence',failed)
    for _ in range(2):
        result=source.collect_msft_report_evidence(NOW)
        assert result['packet'] is None and 'sensitive' not in str(result)
    assert len(calls)==2 and source._CACHE=={}


def test_presentation_order_keeps_explanation_near_front():
    from stock_lab_core.report_editorial import reading_order
    text='\n'.join(reading_order(['## 내 보유 종목 영향','holding','## MSFT 사업·투자 점검','msft','## 핵심 해석','market']))
    assert text.index('핵심 해석')<text.index('MSFT 사업')<text.index('내 보유')


def test_full_report_consumes_packet_once_and_preserves_decision_inputs(monkeypatch):
    from tests.test_report_section_contract import report_case
    from stock_lab_core.report_evidence import report_sections
    args=report_case(NOW.isoformat())
    args['context']['msft_business_evidence']={'packet':packet()}
    before=deepcopy(args)
    def no_requests(*a,**kw):
        pytest.fail('render must not fetch issuer pages')
    monkeypatch.setattr(source,'load_msft_business_evidence',no_requests)
    lines,_=report_sections(**args)
    text='\n'.join(lines)
    assert text.count('## MSFT 사업·투자 점검')==1
    assert '55십억 달러 초과' in text
    assert text.index('## 핵심 해석')<text.index('## MSFT 사업')<text.index('## 내 보유 종목 영향')
    assert args==before
