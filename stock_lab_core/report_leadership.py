"""A reading path from sector prices to issuer research; no I/O or trade scores."""
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, first, number, records, text

register_loaded_source(__name__, __file__)

FOCUS = ('SOXX', 'SMH', 'DRAM', 'IGV', 'XLK', '396500.KS', '139260.KS')
NAMES = {'Technology':'기술', 'Communication':'통신', 'Financials':'금융',
    'Health care':'헬스케어', 'Energy':'에너지', 'Industrials':'산업재', 'Materials':'소재',
    'Consumer discretionary':'경기소비재', 'Consumer staples':'필수소비재', 'Utilities':'유틸리티',
    'Real estate':'부동산', 'Semiconductors':'반도체', 'Memory':'메모리', 'Software':'소프트웨어',
    'Biotech':'바이오', 'Infrastructure':'인프라', 'Aerospace and defense':'항공·방산',
    'Cybersecurity':'사이버보안', 'Homebuilders':'주택건설', 'Batteries':'2차전지',
    'Power infrastructure':'전력인프라', 'Shipbuilding':'조선', 'Defense':'방산'}
GROUPS = (
    ('빅테크 투자·회수', ('MSFT','AMZN','GOOGL','GOOG','META'),
     '투자지출 증가가 매출·마진·영업현금 증가로 회수되는가?',
     '사업부 성장·회사 투자 전망과 현금 투자지출을 구분. 회수 둔화·투자 축소가 확인되면 공급망 수요 가설 재검토'),
    ('반도체 공급기업 수요', ('NVDA','MU','005930.KS','000660.KS'),
     '고객의 투자 계획이 실제 주문·매출·현금으로 이어지는가?',
     '데이터센터/HBM 매출·재고·마진·고객 주문 확인. 매출 둔화와 재고 증가가 동반되면 단순 가격 조정 가설 재검토'),
)


def _value(row, field):
    value = row.get(field)
    return None if isinstance(value, bool) else number(value)


def price_reading(row):
    """Report observations only; never changes the app's candidate/trade grades."""
    short, month, quarter, rs5, rs20 = [_value(row, k) for k in
        ('return_5d','return_20d','return_3m','rs_5d_change','rs_20d_change')]
    if any(v is None for v in (short, month, quarter, rs5, rs20)):
        return '자료 부족', '기간 이력 확인 전 추세 결론 보류', '동일 기준일의 20·63거래일 가격 이력 확보'
    if short > 0 and month > 0 and quarter > 0 and rs5 > 0 and rs20 > 0:
        return '상승 추세 후보', '5·20·63일 실제 상승과 시장 대비 우위가 함께 관측됨', '다음 종가의 상승·RS 유지와 구성종목 확산, 실적 근거 확인'
    if month <= 0 and rs20 > 0:
        return '상대적 방어', '시장보다 덜 하락했지만 20일 실제 수익률은 상승이 아님', '실제 상승 전환 전 차기 주도 업종으로 확정하지 않음'
    if short is not None and short > 0 and (month <= 0 or quarter <= 0):
        return '반등·회복 관찰', '최근 5일 반등과 중기 약세가 공존함', '20·63일 회복 및 시장 대비 우위의 지속 확인'
    if month < 0 and rs20 < 0:
        return '가격·상대강도 약세', '20일 실제 하락과 시장 대비 열위가 함께 관측됨', '하락 원인 공시·주문·실적 점검; 하루 반등을 추세 회복으로 보지 않음'
    return '추세 확인 대기', '실제 상승과 단기·중기 상대우위가 아직 함께 확인되지 않음', '20·63일 실제 방향과 5·20일 RS가 같은 방향으로 이어지는지 확인'


def company_research_question(ticker):
    symbol = text(ticker).upper()
    for title, symbols, question, check in GROUPS:
        if symbol in symbols:
            if symbol == 'META':
                question = 'AI 인프라 지출이 광고 효율·매출·현금 창출 개선으로 이어지는가?'
            return {'검토축':title, '시장 질문':question, '다음 확인':check}
    return {'검토축':'업종 흐름과 기업 실적', '시장 질문':'업종 가격 강세가 이 기업의 매출·이익·현금 개선과 함께 나타나는가?',
            '다음 확인':'같은 기간 실적과 현금흐름, 해당 사업부·수주 원문을 비교. 업종 상승을 회사 실적 개선으로 대신 해석하지 않음'}


def _pct(value):
    return '자료 없음' if value is None else f'{value*100:+.1f}%'


def _unique_rows(result):
    """Avoid giving duplicated sector ETFs extra votes; prefer SOXX to SMH."""
    selected = {}
    for row in sorted(result.get('rows', []), key=lambda r:(r['ticker'] != 'SOXX', r['ticker'])):
        selected.setdefault(row['sector'], row)
    return list(selected.values())


def leadership_lines(rotation, summary_rows):
    lines = ['', '## 주도 업종 교체 관측', '',
        '반도체·AI가 회복하는지와 다른 업종으로 강세가 확산되는지를 나누어 봅니다. 아래는 확정 종가의 가격 관측이며, 차기 주도주 확정이나 매수 허용 판정이 아닙니다.', '']
    markets = rotation.get('markets', {})
    if not markets:
        lines += ['동일 기준일의 업종·시장 가격 이력이 부족해 후보 선정을 보류합니다.']
    focus, alternatives = [], []
    for market in ('US','KR'):
        result = markets.get(market)
        if not result:
            lines += [f'**{market}: 비교 가능한 업종 이력 없음.**']
            continue
        rows = _unique_rows(result)
        focus.extend(row for row in rows if row['ticker'] in FOCUS)
        other = [r for r in rows if r['ticker'] not in FOCUS]
        groups = {label:[r for r in other if price_reading(r)[0] == label] for label in
                  ('상승 추세 후보','상대적 방어','반등·회복 관찰')}
        strong = groups['상승 추세 후보']
        names = ', '.join(NAMES.get(r['sector'],r['sector']) for r in sorted(strong,key=lambda r:-r['rs_20d_change'])[:2])
        conclusion = f'{names}에서 실제 상승·상대우위가 함께 관측됩니다.' if strong else '반도체·기술 외 상승 추세 후보 조건을 충족한 업종이 없습니다. 순위 1위만으로 대체 주도주를 정하지 않습니다.'
        lines += [f"**{market} · {result['date']} 확정 종가:** {conclusion} 비교 {len(rows)}업종(ETF {result['sample_count']}개; 동일 업종 중복 제외)."]
        if len(rows) < 6:
            lines += ['비교 표본이 6업종 미만이므로 시장 전체의 주도권 변화로 일반화하기 어렵습니다.']
        for label, limit in (('상승 추세 후보',2),('상대적 방어',1),('반등·회복 관찰',1)):
            alternatives.extend(sorted(groups[label],key=lambda r:(-r['rs_20d_change'],r['ticker']))[:limit])
    for heading, rows in (('반도체·AI 연관 업종의 현재 방향', focus), ('다른 업종에서 확인할 후보', alternatives)):
        if not rows:
            continue
        lines += ['', '**'+heading+'**', '시장·업종·기준일 | 실제 수익률 5일 / 20일 / 63일 | RS 변화 5일 / 20일 | 관측 해석 | 다음 확인', '--- | --- | --- | --- | ---']
        for row in rows:
            label, reading, check = price_reading(row)
            lines.append(' | '.join(_cell(v) for v in (
                f"{row['market']} {NAMES.get(row['sector'],row['sector'])}({row['ticker']}) · {row['date']}",
                _pct(_value(row,'return_5d'))+' / '+_pct(_value(row,'return_20d'))+' / '+_pct(_value(row,'return_3m')),
                _pct(_value(row,'rs_5d_change'))+' / '+_pct(_value(row,'rs_20d_change')),
                label+' · '+reading, check)))
    lines += ['', '근거: 이미 수집한 일별 가격 이력. US는 S&P500, KR은 코스피의 같은 거래일과 비교하며 장중 값은 섞지 않습니다. RS 변화=(ETF/시장 가격비율)의 기간 수익률로, 단순 수익률 차(%p)와 다릅니다.',
        '상승 추세 후보 조건은 5·20·63일 실제 수익률과 5·20일 RS 변화가 모두 양수인 경우입니다. 조건 충족 업종 중 20일 RS순 최대 2개씩 표시하며, 미래 수익·실적 개선을 보장하지 않습니다. 돈흐름 점수는 실제 자금 유입액이 아니며 구성종목의 상승 확산도 이 표만으로 확인되지 않습니다.', '',
        '**가격 가설을 기업 근거로 확인하기**',
        '확인할 축 | 보유·관심에서 심층분석할 기업 | 왜 확인하는가 | 해석을 바꿀 조건', '--- | --- | --- | ---']
    symbols = {text(first(r,'티커','Ticker','ticker')).upper() for r in records(summary_rows)}
    for title, candidates, question, check in GROUPS:
        selected = [t for t in candidates if t in symbols]
        if 'GOOGL' in selected and 'GOOG' in selected:
            selected.remove('GOOG')
        lines.append(' | '.join(_cell(v) for v in (title, ', '.join(selected) or '해당 기업의 보유·관심 연결 없음',question,check)))
    lines += ['', '위 질문은 조사 방향이며 확인된 실적 변화나 하락 원인 주장이 아닙니다. 시황 보기 → 기업 심층분석에서 해당 기업을 선택해 근거를 조회하세요. 회사 전체 매출·현금흐름은 데이터센터/AI 부문 수치와 다릅니다. 공통 SEC/DART 자료로 확인되지 않는 사업부·주문·전망은 미확인으로 남깁니다.', '']
    return lines
