"""A reading path from sector prices to issuer research; no I/O or trade scores."""
from datetime import datetime
from zoneinfo import ZoneInfo
import re
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, first, number, records, safe_link, stamp, text

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
        if row.get('date') != result.get('date'):
            continue
        selected.setdefault(row['sector'], row)
    return list(selected.values())


def _names(rows):
    return '·'.join(NAMES.get(r['sector'], r['sector']) for r in rows)


def _market_story(rows):
    """Describe coexistence, not a causal fund transfer or a past leadership claim."""
    focus = [r for r in rows if r['ticker'] in FOCUS]
    weak = [r for r in focus if all(_value(r, k) is not None and _value(r, k) < 0
                                  for k in ('return_20d', 'rs_20d_change'))]
    weak.sort(key=lambda r: r['rs_20d_change'])
    other = [r for r in rows if r['ticker'] not in FOCUS]
    strong = sorted((r for r in other if price_reading(r)[0] == '상승 추세 후보'),
                    key=lambda r: (-r['rs_20d_change'], r['ticker']))
    defense = sorted((r for r in other if price_reading(r)[0] == '상대적 방어'), key=lambda r: -r['rs_20d_change'])
    recovery = sorted((r for r in other if price_reading(r)[0] == '반등·회복 관찰'), key=lambda r: -r['rs_20d_change'])
    facts = (f"{_names(weak[:2])}는 20일 실제 수익률과 시장 대비 상대강도가 함께 약합니다. " if weak else
             '반도체·기술 표본에서 20일 가격·상대강도의 동반 약세는 확인되지 않았습니다. ' if focus else
             '반도체·기술 표본이 없어 기존 관심 업종의 방향은 판단을 보류합니다. ')
    if strong:
        facts += f"반면 {_names(strong[:2])}는 5·20·63일 실제 상승과 5·20일 상대우위를 함께 유지했습니다."
        meaning = ('약해진 관심 업종과 다른 업종의 강세가 공존해 주도권 이동 가능성을 살필 구도입니다. ' if weak else
                   '다른 업종에서도 강세가 관측되지만 기존 업종에서 주도권이 넘어왔다고 확정할 수는 없습니다. ')
        meaning += '자금 이동이나 실적 개선까지 증명된 것은 아닙니다.'
    else:
        facts += '다른 업종에서도 실제 상승·상대우위 조건을 모두 충족한 대안은 없습니다.'
        meaning = '현재 표본만으로 새 주도업종이 생겼다고 읽기 어렵습니다.'
        if defense:
            meaning += f" {_names(defense[:2])}의 상대적 방어는 덜 하락한 것이며 상승 추세와 다릅니다."
        if recovery:
            meaning += f" {_names(recovery[:2])}의 단기 반등도 중기 회복 확인이 필요합니다."
    rebound = [r for r in weak if (_value(r, 'return_5d') or 0) > 0]
    if rebound:
        facts += f" {_names(rebound[:2])}의 5일 반등은 이 중기 약세와 함께 나타납니다."
    next_check = ('다음 확정 종가에서 대안 업종의 실제 상승·상대우위가 함께 유지되는지, 구성종목으로 확산되는지 확인합니다. '
                  '이후 실적·수주 근거가 따라오지 않거나 상대우위가 사라지면 교체 가설을 낮춰 봅니다.' if strong else
                  '다음 확정 종가에서 20·63일 실제 수익률과 5·20일 상대강도가 함께 회복되는 업종부터 확인합니다. '
                  '상대 순위만 오르면 대안 확정은 계속 보류합니다.')
    chosen = weak[:1] or sorted(focus, key=lambda r: (_value(r, 'rs_20d_change') or 0, r['ticker']))[:1]
    chosen += strong[:1] or defense[:1] or recovery[:1]
    return [facts, '해석(추정): ' + meaning, '다음 확인: ' + next_check], chosen


def _business_check(sector):
    checks = {
        'Semiconductors': '고객의 투자 계획이 실제 주문·매출로 이어지는지, 재고·마진과 함께 확인',
        'Memory': 'HBM·메모리 주문과 판매가격, 재고·마진을 함께 확인',
        'Software': '신규 계약·계약 잔액과 매출 성장, 마진·현금 회수 확인',
        'Technology': '사업부 매출·마진과 투자 집행을 함께 확인; 전체 투자액을 AI 투자로 치환하지 않음',
        'Shipbuilding': '신규 수주·수주잔고가 인도·매출·마진으로 이어지는지 확인',
        'Financials': '이자이익·대손비용·자본여력을 함께 확인; 일반기업 설비투자 기준으로 평가하지 않음',
        'Biotech': '임상·허가 결과와 현금 보유·조달 계획 확인; 기대를 확정 매출로 치환하지 않음',
        'Energy': '유가와 판매량·정제마진·생산비를 구분해 이익 전망 확인',
        'Power infrastructure': '전력설비 수주·수주잔고와 납기·마진 확인',
        'Infrastructure': '인프라 발주·수주잔고와 원가·마진 확인',
        'Industrials': '신규 수주·가동률과 원가·마진 확인',
        'Defense': '계약 확정·납기·수주잔고와 이익 전환 확인',
        'Aerospace and defense': '계약 확정·납기·수주잔고와 이익 전환 확인',
    }
    return checks.get(sector, '업종 대표기업의 매출·이익 전망과 수요 근거가 가격 강세를 뒷받침하는지 확인')


def _evidence_lines(selected, context, news, now):
    from stock_lab_core.article_context import verified_body_facts
    from stock_lab_core.report_presentation import sector_related_news
    from stock_lab_core.report_evidence import macro_components
    lines = ['', '**가격 관측을 사업 근거로 확인할 곳**',
             '시장·업종 | 연결된 보도와 확인 수준 | 왜 중요한가 · 다음 확인', '--- | --- | ---']
    seen, common = set(), []
    def citation(article, row, at, url):
        zone = ZoneInfo('Asia/Seoul' if row['market'] == 'KR' else 'America/New_York')
        close = datetime.fromisoformat(row['date']).replace(
            hour=15 if row['market'] == 'KR' else 16, minute=30 if row['market'] == 'KR' else 0, tzinfo=zone)
        timing = ' · 종가 이후 보도(당시 가격 원인으로 소급하지 않음)' if at > close else ''
        return f"[{_cell(text(article.get('title')))}]({url}) · {at:%m/%d %H:%M} KST{timing}"
    for row in selected:
        label = NAMES.get(row['sector'], row['sector'])
        linked = sector_related_news(row['ticker'], row['date'], records(news), sector_name=label)
        evidence, check = '미확인: 같은 세션의 관련 보도 원문 미연결', _business_check(row['sector'])
        for article in linked:
            at = stamp(first(article, 'published_at', 'published'))
            url = safe_link(article.get('link'))
            if not now or not at or at > now or not url:
                continue
            # Incidental sector words in listing notices or evergreen columns
            # do not supply evidence about that sector's demand/earnings shift.
            if re.search(r'신규\s*상장|상장\s*예비|기업\s*공개|\bIPO\b|칼럼|사설|기고|정석|\b(?:opinion|explainer|column)\b',
                         text(article.get('title')), re.I):
                continue
            if article.get('market_context_only'):
                common.append((row, article, at, url))
                continue
            if url in seen:
                evidence = '앞 행과 같은 보도; 독립적인 업종 근거로 중복 계산하지 않음'
                continue
            seen.add(url)
            source = citation(article, row, at, url)
            facts = [f for f in verified_body_facts(article)
                     if all(text(f.get(k)) for k in ('summary', 'implication', 'check'))]
            if facts:
                fact = facts[0]
                evidence = f"기사 주장 · 업종 관련 보도: {_cell(fact.get('summary'))} · {source}"
                check = f"해석(추정): {text(fact.get('implication'))} / 다음 확인: {text(fact.get('check'))}. {check}"
            else:
                evidence = f'제목 수준 · 업종 관련 보도: {source} · 본문 인과 미확인'
            break
        flow = _value(row, 'money_flow_score') if row.get('money_flow_date') == row['date'] else None
        if flow is not None:
            check += f". 보조 관측: 가격·거래량 점수 {flow:.1f}({row['date']}); 실제 자금 유입액·상승 확산의 증거는 아님"
        lines.append(' | '.join((_cell(f"{row['market']} {label} · {row['date']} 종가"), evidence, _cell(check))))
    common_markets = set()
    for row, article, at, url in common:
        if url in seen or row['market'] in common_markets:
            continue
        seen.add(url)
        common_markets.add(row['market'])
        lines += ['', f"{row['market']} 시장 공통 보도(업종 고유 원인 아님): " + citation(article, row, at, url)]
    macro = []
    for item in macro_components(context.get('macro_data')):
        region = 'KR' if item['name'] == '환율' else 'US'
        day = context.get('sessions', {}).get(region)
        if not day or item['as_of'] != day:
            continue
        change = item['change']
        change_text = f' · 1개월 변화 {change:+.1f}%' if change is not None else ' · 1개월 변화 미연결'
        unit = {'10Y 금리': '%', 'VIX': 'pt', 'MOVE': 'pt', '유가': '달러/배럴', '환율': '원/달러'}[item['name']]
        macro.append((abs(item['contribution']), f"{item['label']} {item['value']:,.2f}{unit}{change_text} · {item['state']}({day}, {item['source']})"))
    lines += ['', '**함께 볼 시장 환경**',
              (' / '.join(value for _, value in sorted(macro, key=lambda r: -r[0])[:2]) +
               '. 업종 순위와 별도로 금리·변동성·환율 부담이 완화되는지 확인합니다. 동시 관측이며 업종 등락 원인으로 단정하지 않습니다.' if macro else
               '같은 확정 거래일의 매크로 근거가 미연결되어 시장 환경과의 종합 해석을 보류합니다.'),
              '보도는 표시된 발표 시점의 자료이며 20·63일 흐름 전체의 원인 증명이 아닙니다. 종가 이후 보도는 사후 정보로 구분합니다. 확인 질문은 매수·매도 판정을 바꾸지 않습니다.', '']
    return lines


def leadership_lines(rotation, summary_rows, context=None, news=(), now=None):
    lines = ['', '## 주도 업종 교체 관측', '',
        '반도체·AI가 회복하는지와 다른 업종으로 강세가 확산되는지를 나누어 봅니다. 아래는 확정 종가의 가격 관측이며, 차기 주도주 확정이나 매수 허용 판정이 아닙니다.', '']
    markets = rotation.get('markets', {})
    if not markets:
        lines += ['동일 기준일의 업종·시장 가격 이력이 부족해 후보 선정을 보류합니다.']
    focus, alternatives, selected = [], [], []
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
        story, checks = _market_story(rows)
        for i, line in enumerate(story):
            lines += ['', line + ' [근거: 아래 동일 기준일 가격·RS 표]' if i == 0 else line]
        lines.append('')
        selected.extend(checks)
        for label, limit in (('상승 추세 후보',2),('상대적 방어',1),('반등·회복 관찰',1)):
            alternatives.extend(sorted(groups[label],key=lambda r:(-r['rs_20d_change'],r['ticker']))[:limit])
    if selected:
        lines += _evidence_lines(selected, context or {}, news, stamp(now))
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
