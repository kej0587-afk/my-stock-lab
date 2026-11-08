"""Read-only comparison of trusted SEC review packets on exact calendar periods."""
from stock_lab_core.company_cash_reading import _checked_field, _same_basis
from stock_lab_core.sec_financial_periods import _date, _finite, _quarter_span
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

BIGTECH = ('MSFT', 'AMZN', 'GOOGL', 'GOOG', 'META')
CHECKS = {
    'MSFT': 'Azure 성장·클라우드 마진과 현금 투자/금융리스의 구분, 설비 가동 시점을 확인',
    'AMZN': 'AWS 성장·수주잔고와 AWS/물류 투자 배분, 자산매각·인센티브 차감 여부를 확인',
    'GOOGL': 'Google Cloud 성장·마진과 서버/데이터센터 투자, 감가상각 증가를 확인',
    'GOOG': 'Google Cloud 성장·마진과 서버/데이터센터 투자, 감가상각 증가를 확인',
    'META': '광고 현금 창출과 AI 투자·감가상각, AI 기능의 광고 수익 기여를 확인',
}
LIMIT = ('회사 전체 공시 현금지출이며 AI·데이터센터 전용 지출이 아닙니다. '
         '비현금 금융리스·구매약정·인수대금은 제외됩니다. 단순차액은 회사 조정 FCF와 다를 수 있습니다. '
         '현재 주가 하락의 원인이나 다음 주도주를 이 수치만으로 확정하지 않습니다.')


def comparison_options(options):
    """Only the caller's eligible companies; one Alphabet share class."""
    return [t for t in BIGTECH if t in options and not (t == 'GOOG' and 'GOOGL' in options)]


def _periods(packet):
    if (packet.get('currency') != 'USD' or packet.get('review_only') is not True
            or packet.get('eligible_for_scoring') is not False
            or packet.get('status') != 'quarter_evidence_only' or not _date(packet.get('as_of'))):
        return {}
    result = {}
    for row in packet.get('quarter', []):
        start, end = _date(row.get('start')), _date(row.get('end'))
        if (not start or not end or end > _date(packet['as_of']) or _quarter_span(start, end) != 1
                or row.get('is_single_quarter') is not True or row.get('unit') != 'USD'):
            return {}
        key = (start.isoformat(), end.isoformat())
        if key in result:
            return {}
        result[key] = row
    return result


def _cash(row, cutoff):
    start, end = _date(row['start']), _date(row['end'])
    checked = {f: _checked_field(row, f, start, end, cutoff) for f in ('ocf', 'cash_capex')}
    ocf, capex = (checked[f][0] for f in ('ocf', 'cash_capex'))
    paired = _same_basis(checked, 'ocf', 'cash_capex')
    residual = ocf - capex if paired else None
    ratio = capex / ocf * 100 if paired and ocf > 0 else None
    return dict(ocf=ocf, capex=capex, residual=residual if _finite(residual) else None,
                ratio=ratio if _finite(ratio) else None, paired=paired,
                filings=frozenset(part[2:] for part in checked['ocf'][1]) if paired else frozenset(),
                reason='; '.join(f + ': ' + checked[f][2] for f in checked if checked[f][2]),
                scope=row.get('cash_capex_scope', '범위 미확인'))


def _million(value):
    return round(value / 1e6, 1) if value is not None else None


def _growth(value, previous):
    result = (value / previous - 1) * 100 if value is not None and previous is not None and previous > 0 else None
    return result if _finite(result) else None


def compare_bigtech_cash(packets):
    """No I/O, mutation, scores, older-good-row fallback, totals or issuer ranking."""
    result = dict(period='', previous_period='', rows=[], trends=[], readings=[], coverage=[],
                  conclusion='', limits=LIMIT, status='held')
    if (len(packets) < 2 or len(packets) > 4 or any(t not in BIGTECH for t in packets)
            or ('GOOG' in packets and 'GOOGL' in packets)):
        result['conclusion'] = '서로 다른 빅테크 2~4개를 선택해 비교하세요. Alphabet은 한 주식 종류만 포함합니다.'
        return result
    periods = {t: _periods(p) if isinstance(p, dict) and p.get('ticker') == t else {}
               for t, p in packets.items()}
    for t, p in packets.items():
        result['coverage'].append({'기업': t, '최근 관측 분기': max((k[1] for k in periods[t]), default='미확인'),
                                   '조회 기준일': p.get('as_of', '미확인') if isinstance(p, dict) else '미확인'})
    common = set.intersection(*(set(p) for p in periods.values()))
    if not common:
        result['conclusion'] = '선택 기업 모두의 시작일·종료일이 일치하는 분기가 없어 비교 보류입니다. 누락 기업을 0으로 합산하지 않습니다.'
        return result
    key = max(common, key=lambda k: k[1])
    result['period'] = ' ~ '.join(key)
    prior_key = (str(int(key[0][:4]) - 1) + key[0][4:], str(int(key[1][:4]) - 1) + key[1][4:])
    result['previous_period'] = ' ~ '.join(prior_key)
    rising, falling, unchanged, held = [], [], [], []
    scopes = set()
    for t, packet in packets.items():
        row = periods[t][key]
        current = _cash(row, _date(packet['as_of']))
        previous_row = periods[t].get(prior_key)
        previous = _cash(previous_row, _date(packet['as_of'])) if previous_row else None
        compatible = bool(previous and current['paired'] and previous['paired']
                          and current['scope'] == previous['scope'] and current['filings'] == previous['filings'])
        ocf_yoy = _growth(current['ocf'], previous['ocf']) if compatible else None
        capex_yoy = _growth(current['capex'], previous['capex']) if compatible else None
        delta = (current['ratio'] - previous['ratio'] if compatible and
                 current['ratio'] is not None and previous['ratio'] is not None else None)
        if delta is not None and not _finite(delta):
            delta = None
        scopes.add(current['scope'])
        result['rows'].append({'기업': t, '영업현금(백만$)': _million(current['ocf']),
            '현금 투자(백만$)': _million(current['capex']), '단순차액(백만$)': _million(current['residual']),
            '투자/영업현금(%)': round(current['ratio'], 1) if current['ratio'] is not None else None,
            '투자 범위': current['scope'], '확인 상태': current['reason'] or
                ('동일 제출본 확인' if current['paired'] else '두 항목 제출본 불일치')})
        result['trends'].append({'기업': t, '전년 영업현금(백만$)': _million(previous['ocf']) if compatible else None,
            '전년 현금 투자(백만$)': _million(previous['capex']) if compatible else None,
            '영업현금 YoY(%)': round(ocf_yoy, 1) if ocf_yoy is not None else None,
            '현금 투자 YoY(%)': round(capex_yoy, 1) if capex_yoy is not None else None,
            '투자 비율 변화(%p)': round(delta, 1) if delta is not None else None,
            '비교 상태': '전년 동기·동일 비교공시·투자 정의' if compatible else '전년 근거·동일 비교공시·투자 정의 확인 필요'})
        if delta is None:
            held.append(t)
            fact = '전년 동기 대비 투자 비율 변화는 확인 보류입니다. 양의 영업현금과 같은 기간·투자 정의의 공시가 필요합니다.'
        else:
            (rising if delta > 0 else falling if delta < 0 else unchanged).append(t)
            fact = f"투자/영업현금은 {previous['ratio']:.1f}% → {current['ratio']:.1f}%({delta:+.1f}%p)입니다."
            if ocf_yoy is not None and capex_yoy is not None:
                fact += f' 영업현금 {ocf_yoy:+.1f}%, 현금 투자 {capex_yoy:+.1f}%로 변했습니다.'
        why = '회사 전체 투자의 현금 조달 부담을 확인하는 지표입니다.'
        if delta is not None and delta > 0:
            why += ' 같은 영업현금 대비 투자에 쓰는 몫이 커져, 투자 지출과 실제 매출·현금 회수의 균형이 더 중요해졌습니다.'
            if ocf_yoy is not None and ocf_yoy < 0:
                why += ' 영업현금 감소도 비율 상승에 영향을 줍니다.'
        elif delta is not None and delta < 0:
            why += ' 현금 대비 투자 비율은 낮아졌지만, 현금 개선인지 투자 축소인지 함께 봐야 합니다.'
        if current['residual'] is not None and current['residual'] < 0:
            why += ' 해당 분기의 투자가 영업현금을 넘었으며 부족분 조달·기존 현금도 확인해야 합니다. 이것만으로 현금 고갈을 뜻하지 않습니다.'
        if capex_yoy is not None and capex_yoy > 0:
            why += ' 현금 투자는 늘었으나 반도체·데이터센터 수요로 연결하려면 서버·설비 몫과 납품 시점 근거가 필요합니다.'
        elif capex_yoy is not None and capex_yoy < 0:
            why += ' 현금 투자는 줄었으나 지출 시점·비현금 리스 이동과 실제 발주 감소를 구분해야 합니다.'
        result['readings'].append({'기업': t, '사실': fact, '해석(추정)': why,
            '다음 확인': CHECKS[t] + '. 투자 전망 유지·상향과 사업 현금 회수가 함께 확인되는지 다음 실적에서 재점검',
            '근거': f'{t} SEC 현금흐름 · {result["period"]} / {result["previous_period"]}'})
    result['status'] = 'partial' if held else 'compared'
    parts = []
    if rising:
        parts.append(', '.join(rising) + ': 전년 동기보다 영업현금에서 투자에 쓰는 비율이 커졌습니다.')
    if falling:
        parts.append(', '.join(falling) + ': 같은 비율이 낮아졌습니다.')
    if unchanged:
        parts.append(', '.join(unchanged) + ': 같은 비율에 변화가 없습니다.')
    if held:
        parts.append(', '.join(held) + ': 전년 대비 변화 해석을 보류합니다.')
    result['conclusion'] = ' '.join(parts) + ' 반도체·데이터센터의 다음 관건은 투자 계획의 유지와 실제 가동·매출·현금 회수입니다.'
    result['scope_note'] = ('기업별 투자 범위가 달라 금액 합계·부담 순위를 만들지 않습니다.' if len(scopes) > 1
                            else '같은 공시 항목도 사업 구성이 달라 부담 순위나 AI 투자 합계로 해석하지 않습니다.')
    return result
