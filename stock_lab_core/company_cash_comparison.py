"""Same-quarter cash comparison for review, without collection or score changes."""
import math
import re

from stock_lab_core.company_cash_reading import _checked_field, prior_year_cash_row
from stock_lab_core.sec_cash_recovery import recovered_cash_reading
from stock_lab_core.sec_financial_periods import _date, _finite, _quarter_span
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)
FIELDS = ('ocf','cash_capex')


def _finite_values(*values):
    if not all(_finite(value) for value in values):
        raise ValueError('calculation_range')


def _period(packet,row,recovery):
    start,end,cutoff = (_date(row.get('start')),_date(row.get('end')),_date(packet.get('as_of')))
    if (not start or not end or not cutoff or end>cutoff or _quarter_span(start,end)!=1
            or row.get('unit')!='USD' or row.get('is_single_quarter') is not True):
        return None
    checks = {k:_checked_field(row,k,start,end,cutoff) for k in FIELDS}
    if all(checks[k][0] is not None for k in FIELDS) and checks['ocf'][1]==checks['cash_capex'][1]:
        values = {k:checks[k][0] for k in FIELDS}
        source = '10-Q/10-K 검증값'
    elif recovered_cash_reading(dict(packet,quarter=[row]),recovery):
        values = dict(recovery['values'])
        source = '동일 실적발표 원문 대조'
    else:
        return None
    facts = [row['provenance'][k]['facts'][0] for k in FIELDS]
    return dict(start=row['start'],end=row['end'],scope=row['cash_capex_scope'],values=values,
                tags=[f['tag'] for f in facts],filings=[(f['accession'],f['filed'],f['form']) for f in facts],
                source=source)


def build_cash_comparison(packet,recovery=None):
    """Compare only validated current/prior flows restated in the same filing."""
    result = dict(status='held',review_only=True,eligible_for_scoring=False,table=[],
                  headline='전년 동기 현금 부담 비교 보류',
                  reason='같은 회계분기의 비교 가능한 현금 근거가 부족합니다.',
                  interpretation='',next_check='최신 공시의 전년 동기 재작성 수치와 투자지출 정의를 확인합니다.')
    recovery = recovery or {}
    try:
        if (packet.get('review_only') is not True or packet.get('eligible_for_scoring') is not False
                or packet.get('currency')!='USD' or packet.get('status')!='quarter_evidence_only'
                or not re.fullmatch(r'\d{10}',packet.get('cik',''))):
            return result
        prior = prior_year_cash_row(packet)
        if prior is None:
            return result
        current = packet['quarter'][-1]
        a = _period(packet,prior,recovery.get('prior_year') or {})
        b = _period(packet,current,recovery)
        if not a or not b:
            result['reason']='최신 또는 전년 동기 분기값·누적값의 원문 대조가 완료되지 않았습니다. 다른 제출본 차감이나 금액 불일치를 추정으로 메우지 않습니다.'
            return result
        if a['scope']!=b['scope'] or a['tags']!=b['tags'] or a['filings']!=b['filings']:
            result['reason']='투자지출 범위·항목 정의 또는 비교 수치를 제시한 제출본이 달라 비교를 보류합니다.'
            return result
        if a['source']!=b['source'] or (a['source']=='동일 실적발표 원문 대조' and
                any(recovery.get(k)!=recovery['prior_year'].get(k) for k in ('document_sha256','source_url','filed','accession'))):
            result['reason']='현재와 전년 동기가 같은 근거로 대조되지 않았습니다.'
            return result
        x,y=a['values'],b['values']
        def money(label,old,new):
            delta=new-old
            _finite_values(old,new,delta,delta/old*100 if old>0 else 0)
            growth=f' ({delta/old*100:+.1f}%)' if old>0 else ' (증감률 보류: 이전값 0 이하)'
            result['table'].append({'항목':label,'전년 동기':f'{old/1e6:,.1f}',
                '이번 분기':f'{new/1e6:,.1f}','변화':f'{delta/1e6:+,.1f}'+growth})
        money('영업현금흐름',x['ocf'],y['ocf'])
        money('현금 투자지출 · '+b['scope'],x['cash_capex'],y['cash_capex'])
        old_res=x['ocf']-x['cash_capex'];new_res=y['ocf']-y['cash_capex']
        money('단순차액 · 회사 FCF와 다를 수 있음',old_res,new_res)
        ratios = None
        if x['ocf']>0 and y['ocf']>0:
            old_ratio=x['cash_capex']/x['ocf']*100;new_ratio=y['cash_capex']/y['ocf']*100
            _finite_values(old_ratio,new_ratio,new_ratio-old_ratio)
            ratios=(old_ratio,new_ratio)
            result['table'].append({'항목':'투자지출 / 영업현금흐름','전년 동기':f'{old_ratio:.2f}%',
                '이번 분기':f'{new_ratio:.2f}%','변화':f'{new_ratio-old_ratio:+.2f}%p'})
            direction = '커졌습니다' if new_ratio>old_ratio else '줄었습니다' if new_ratio<old_ratio else '같습니다'
            result['headline']=f"영업현금 대비 해당 투자지출 비중이 {direction} ({old_ratio:.2f}% → {new_ratio:.2f}%)."
        else:
            result['headline']='영업현금이 0 이하인 비교 기간이 있어 투자지출 비율 대신 절대금액으로 봅니다.'
        difference = new_res-old_res
        residual = '늘었습니다' if difference>0 else '줄었습니다' if difference<0 else '같습니다'
        result['interpretation']=f'해당 투자지출 차감 후 단순차액은 전년 동기보다 {residual}. 투자비율과 남는 금액을 함께 봐야 하며, 투자지출 증가만으로 과잉투자나 현금 고갈을 확정할 수 없습니다.'
        software = all(_finite(v.get('software')) and v['software']>=0 for v in (x,y))
        if software:
            money('별도 자본화 소프트웨어 개발비',x['software'],y['software'])
            if ratios:
                old_all=(x['cash_capex']+x['software'])/x['ocf']*100
                new_all=(y['cash_capex']+y['software'])/y['ocf']*100
                _finite_values(old_all,new_all,new_all-old_all)
                result['table'].append({'항목':'투자지출+개발비 / 영업현금흐름','전년 동기':f'{old_all:.2f}%',
                    '이번 분기':f'{new_all:.2f}%','변화':f'{new_all-old_all:+.2f}%p'})
            if all(v.get('company_fcf_reconciled') is True and _finite(v.get('company_fcf')) and
                    math.isclose(v['ocf']-v['cash_capex']-v['software'],v['company_fcf'],abs_tol=.01) for v in (x,y)):
                money('회사 공시 FCF · 개발비 추가 차감',x['company_fcf'],y['company_fcf'])
            result['interpretation']+=' 개발비가 별도이므로 유형자산 투자비율만으로 전체 현금 부담을 설명하지 않습니다.'
        elif 'software' in x or 'software' in y:
            result['interpretation']+=' 개발비의 양쪽 기간 근거가 없어 개발비 포함 비율은 비교하지 않습니다.'
        if any(not _finite(v) for v in (old_res,new_res,difference)):
            return dict(result,status='held',table=[],headline='금액 계산 범위 확인 전 비교 보류')
        result.update(status='verified_comparison',reason='',periods={'prior':a,'current':b},
            next_check='다음 공시에서 매출·주문·마진과 영업현금이 함께 늘어나는지, 운전자본·일회성 현금과 투자/개발비·리스·인수 지출이 어떻게 바뀌는지 확인합니다.')
        return result
    except (KeyError,TypeError,ValueError,IndexError,OverflowError,ZeroDivisionError):
        return dict(result,status='held',table=[],headline='전년 동기 현금 부담 비교 보류')


def render_cash_comparison(st,comparison):
    with st.expander('전년 동기와 비교한 현금 부담',expanded=True):
        st.write(comparison['headline'])
        if comparison['status']=='verified_comparison':
            a,b=comparison['periods']['prior'],comparison['periods']['current']
            st.caption(f"전년 {a['start']} ~ {a['end']} / 이번 {b['start']} ~ {b['end']} · 금액: 백만 USD · {b['source']}")
            st.dataframe(comparison['table'],hide_index=True,width='stretch')
            st.write('읽는 기준: '+comparison['interpretation'])
        else:
            st.caption(comparison['reason'])
        st.write('다음 확인: '+comparison['next_check'])
        st.caption('기업 전체의 과거 분기 비교입니다. 현재 업종 주도력·투자수익률·현금잔고·매매 판정과는 구분합니다.')
