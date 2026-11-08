"""On-demand 8-K cash reconciliation; no issuer/date exceptions or score writes.

An explicit quarterly release must independently agree with BOTH the current
10-Q YTD amount and its held adjacent-quarter difference. Raw packets stay intact.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import math
import re
from urllib.parse import urljoin

from lxml import html

from stock_lab_core.company_cash_reading import _checked_field, prior_year_cash_row
from stock_lab_core.earnings_result_sources import _table_grid, _text
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.sec_financial_periods import _date, _finite, _quarter_span
from stock_lab_core.sec_quarter_review import _signature

register_loaded_source(__name__, __file__)
MAX_BYTES = 4_000_000
FIELDS = ('ocf', 'cash_capex')
LABELS = {
    'ocf': r'Net cash provided by(?: \(used in\))? operating activities',
    'PaymentsToAcquirePropertyPlantAndEquipment': r'(?:Less:\s*)?Purchases of property and equipment',
    'PaymentsToAcquireProductiveAssets': r'(?:Less:\s*)?Purchases related to property and equipment and intangible assets',
    'software': r'(?:Less:\s*)?Capitalized software development costs',
    'company_fcf': r'Free cash flow',
}


def cash_anchors(packet):
    """Validate held operands without treating cross-filing arithmetic as proof."""
    try:
        row = packet['quarter'][-1]
        cutoff, start, end = (_date(packet['as_of']), _date(row['start']), _date(row['end']))
        if (packet.get('review_only') is not True or packet.get('eligible_for_scoring') is not False
                or packet.get('status') != 'quarter_evidence_only' or packet.get('currency') != 'USD'
                or not re.fullmatch(r'\d{10}', packet['cik']) or not cutoff or not start or not end
                or end > cutoff or _quarter_span(start,end) != 1 or row.get('is_single_quarter') is not True
                or row.get('unit') != 'USD'):
            return None
        for field in FIELDS:
            evidence = row['provenance'][field]
            if evidence.get('status') != 'cross_filing_difference_review' or evidence.get('method') != 'cumulative_difference':
                return None
            current, previous = evidence['facts']
            if current['filed'] < previous['filed'] or current['accession'] == previous['accession']:
                return None
            # Reuse the field validator for dates, concepts, scope and arithmetic.
            # A validation-only copy removes the cross-filing guard. This NEVER
            # leaves this function or becomes reported/recovered evidence itself.
            copy = deepcopy(row)
            checked = copy['provenance'][field]
            checked.pop('status')
            for key in ('filed','accession','form'):
                checked['facts'][1][key] = current[key]
            # Validate the original previous fact as a standalone quarter/flow
            # operand too: future/malformed filing metadata must not be masked.
            if (not _date(previous['filed']) or not _date(previous['end'])
                    or not _date(previous['end']) <= _date(previous['filed']) <= cutoff
                    or previous['form'] not in {'10-Q','10-Q/A','10-K','10-K/A'}
                    or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', previous['accession'])):
                return None
            if _checked_field(copy,field,start,end,cutoff)[0] is None:
                return None
        if _signature(row['provenance']['ocf']) != _signature(row['provenance']['cash_capex']):
            return None
        return row
    except (KeyError,TypeError,ValueError,IndexError):
        return None


def _root(content):
    if not isinstance(content,bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError('document_size')
    return html.fromstring(content,parser=html.HTMLParser(no_network=True))


def _amount(row, col):
    raw = row[col].strip().replace(',','').replace('$','').strip()
    if not re.fullmatch(r'\(?-?\d+(?:\.\d+)?\)?',raw):
        return None
    # Accounting punctuation/currency may occupy separate cells. Stop at the
    # previous amount/label; never borrow the sign of a neighbouring period.
    prefix = []
    for cell in reversed(row[:col]):
        token = cell.strip()
        if not re.fullmatch(r'[\s$()\-]*',token):
            break
        prefix.append(token)
    negative = raw.startswith(('(','-')) or '(' in ''.join(prefix) or '-' in ''.join(prefix)
    return float(raw.strip('()-')) * (-1 if negative else 1)


def parse_cash_release(content, packet):
    """Extract current quarter AND YTD under explicit dates, units and headings."""
    anchor = cash_anchors(packet)
    if anchor is None:
        return None
    end = _date(anchor['end'])
    date_pattern = rf'{end.strftime("%b")}(?:{end.strftime("%B")[3:]})?\.?\s+{end.day},?\s+{end.year}'
    ytd = {2:'Six',3:'Nine',4:'Twelve'}.get(anchor['fiscal_quarter'])
    if not ytd:
        return None
    verified = []
    root = _root(content)
    capex_tag = anchor['provenance']['cash_capex']['facts'][0]['tag']
    for table in root.xpath('.//table')[:160]:
        if table.xpath('.//table') or 'Net cash provided' not in _text(table):
            continue
        grid = _table_grid(table)
        first_data = next((i for i,r in enumerate(grid) if any(re.fullmatch(LABELS['ocf'],v,re.I) for v in r)),None)
        if first_data is None:
            continue
        # Only the heading between this table and the preceding table belongs
        # to it. Do not reuse a consolidated heading for an affiliate table.
        header = ' '.join(' '.join(r) for r in grid[:first_data])
        heading_pattern = r'\b(?:Consolidated Statements of Cash Flows?|Reconciliation of GAAP Cash Flow from Operating Activities to Free Cash Flow)\s*\(In (?:millions|thousands)'
        context = header
        if not re.search(heading_pattern,header,re.I):
            # Keep complete nearby heading blocks, including scope qualifiers
            # before "Consolidated"; exclude distant prose/footnotes entirely.
            prefix = []
            for parent in [table,*list(table.iterancestors())[:2]]:
                siblings = list(parent.itersiblings(preceding=True))
                if not siblings:
                    continue
                for node in siblings[:8]:
                    if node.tag == 'table' or node.xpath('.//table'):
                        break
                    text = _text(node)
                    if text:
                        prefix.append(text)
                    if len(prefix)==3:
                        break
                break
            context = ' '.join(reversed(prefix)) + ' ' + header
        if not re.search(heading_pattern,context,re.I):
            continue
        if re.search(r'\b(?:unconsolidated|affiliate|segment|projected|projection|forecast|estimated|outlook)\b',context,re.I):
            continue
        units = re.findall(r'\(\s*in (millions|thousands)\b',context,re.I)
        if not units or len({u.lower() for u in units}) != 1 or '$' not in _text(table):
            continue
        scale = 1_000_000 if units[-1].lower() == 'millions' else 1000
        columns = {}
        for basis, duration in (('quarter','Three'),('ytd',ytd)):
            columns[basis] = [c for c in range(128) if
                re.search(date_pattern,' '.join(r[c] for r in grid[:first_data]),re.I)
                and re.search(rf'{duration} Months Ended',' '.join(r[c] for r in grid[:first_data]),re.I)
                and not re.search(r'TTM|trailing|outlook',' '.join(r[c] for r in grid[:first_data]),re.I)]
        found = {key:{'quarter':set(),'ytd':set()} for key in (*FIELDS,'software','company_fcf')}
        for key in found:
            pattern = LABELS[capex_tag if key=='cash_capex' else key]
            for row in grid[first_data:]:
                if not any(re.fullmatch(pattern,cell,re.I) for cell in row):
                    continue
                for basis, cols in columns.items():
                    for col in cols:
                        value = _amount(row,col)
                        if value is not None:
                            found[key][basis].add((abs(value) if key in {'cash_capex','software'} else value)*scale)
        # Each table must independently contain BOTH flows and BOTH periods.
        # Incomplete/other-scope tables cannot supply missing operands.
        if any(not found[key][basis] for key in FIELDS for basis in ('quarter','ytd')):
            continue
        values = {}
        for key in FIELDS:
            if any(len(found[key][basis])!=1 for basis in ('quarter','ytd')):
                return None
            q, y = (next(iter(found[key][b])) for b in ('quarter','ytd'))
            expected = anchor['provenance'][key]['facts'][0]['value']
            if not math.isclose(q,anchor[key],rel_tol=1e-10,abs_tol=1e-6) or not math.isclose(y,expected,rel_tol=1e-10,abs_tol=1e-6):
                return None
            values[key] = q
        for key in ('software','company_fcf'):
            if len(found[key]['quarter'])==1:
                values[key] = next(iter(found[key]['quarter']))
        if capex_tag != 'PaymentsToAcquirePropertyPlantAndEquipment':
            # A broad productive-assets tag may already include software.
            values.pop('software',None)
            values.pop('company_fcf',None)
        verified.append(values)
    if not verified:
        return None
    values = dict(verified[0])
    for item in verified[1:]:
        if any(key in values and values[key]!=value for key,value in item.items()):
            return None
        values.update(item)
    # Additional cost lines are not silently folded into the app's CAPEX tag.
    values['company_fcf_reconciled'] = bool('company_fcf' in values and 'software' in values
        and math.isclose(values['ocf']-values['cash_capex']-values['software'],values['company_fcf'],abs_tol=.01))
    return values


def collect_cash_release(packet, *, fetch_json, user_agent, get=None):
    """Explicit issuer-query path only; at most one JSON and two HTML requests."""
    row = cash_anchors(packet)
    if row is None:
        return {'status':'not_applicable'}
    try:
        import requests
        get = get or requests.get
        if not user_agent:
            raise ValueError('missing_contact')
        cik = packet['cik']
        submissions = fetch_json(f'https://data.sec.gov/submissions/CIK{cik}.json')
        if str(submissions['cik']).zfill(10) != cik:
            raise ValueError('issuer_mismatch')
        recent = submissions['filings']['recent']
        cutoff = _date(packet['as_of'])
        filed = _date(row['provenance']['ocf']['facts'][0]['filed'])
        candidates=[]
        for i, form in enumerate(recent['form'][:1000]):
            day = _date(recent['filingDate'][i])
            if (form == '8-K' and '2.02' in recent['items'][i].split(',') and day
                    and _date(row['end']) <= day <= min(filed,cutoff) and filed-day <= timedelta(days=10)):
                candidates.append((day,i))
        if not candidates:
            raise ValueError('earnings_filing_missing')
        nearest = max(day for day,_ in candidates)
        choices = [i for day,i in candidates if day==nearest]
        if len(choices)!=1:
            raise ValueError('ambiguous_filing')
        i=choices[0]; accession=recent['accessionNumber'][i]; primary=recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession) or not re.fullmatch(r'[\w.-]+\.htm[l]?',primary):
            raise ValueError('invalid_filing_path')
        base=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/'
        def document(url):
            response=get(url,headers={'User-Agent':user_agent,'Accept':'text/html'},timeout=15)
            response.raise_for_status()
            if response.url != url:
                raise ValueError('unexpected_redirect')
            return response.content
        primary_body=document(base+primary)
        links=set()
        for tr in _root(primary_body).xpath('.//tr'):
            for link in tr.xpath('.//a[@href]'):
                # Prefer an explicitly numbered link; otherwise require an
                # exact exhibit-number cell, not a mention in its description.
                label = _text(link).strip()
                numbers = re.findall(r'\b99\.\d+\b',label)
                if numbers:
                    is_release = set(numbers) == {'99.1'}
                else:
                    is_release = any(_text(cell).strip() == '99.1' for cell in tr.xpath('./td|./th'))
                if not is_release:
                    continue
                href = link.get('href')
                url=urljoin(base+primary,href)
                if url.startswith(base) and re.fullmatch(r'[\w.-]+\.htm[l]?',url[len(base):]):
                    links.add(url)
        if len(links)!=1:
            raise ValueError('release_exhibit_ambiguous')
        url=links.pop();content=document(url);values=parse_cash_release(content,packet)
        if values is None:
            raise ValueError('release_period_or_amount_unverified')
        result = dict(status='verified_release',cik=cik,ticker=packet.get('ticker'),start=row['start'],end=row['end'],
                    as_of=packet['as_of'],accession=accession,filed=nearest.isoformat(),source_url=url,
                    document_sha256=sha256(content).hexdigest(),values=values,
                    anchors={k:deepcopy(row['provenance'][k]) for k in FIELDS},
                    review_only=True,eligible_for_scoring=False)
        # Reuse the same downloaded exhibit, never fetch another filing.
        prior = prior_year_cash_row(packet)
        if prior is not None:
            prior_values = parse_cash_release(content,dict(packet,quarter=[prior]))
            result['prior_year'] = (dict(result, start=prior['start'],end=prior['end'],values=prior_values,
                anchors={k:deepcopy(prior['provenance'][k]) for k in FIELDS}) if prior_values else
                {'status':'held','reason':'prior_period_or_amount_unverified'})
        return result
    except Exception as error:
        # Never put provider bodies, contact details or exception strings in UI.
        return {'status':'held','reason':str(error) if type(error) is ValueError and str(error) in {
            'missing_contact','issuer_mismatch','earnings_filing_missing','ambiguous_filing','invalid_filing_path',
            'unexpected_redirect','release_exhibit_ambiguous','release_period_or_amount_unverified','document_size'} else 'source_unavailable'}


def recovered_cash_reading(packet,recovery):
    """Bind separate release evidence to exact held operands; never mutate raw data."""
    row=cash_anchors(packet)
    try:
        if (not row or recovery.get('status')!='verified_release' or recovery.get('review_only') is not True
                or recovery.get('eligible_for_scoring') is not False
                or any(recovery.get(k)!=packet.get(k) for k in ('cik','ticker','as_of'))
                or any(recovery.get(k)!=row.get(k) for k in ('start','end'))
                or recovery['anchors']!={k:row['provenance'][k] for k in FIELDS}
                or not re.fullmatch(r'[0-9a-f]{64}',recovery['document_sha256'])
                or not _date(recovery['filed']) or not _date(row['end']) <= _date(recovery['filed']) <= _date(packet['as_of'])):
            return None
        base=f"https://www.sec.gov/Archives/edgar/data/{int(packet['cik'])}/{recovery['accession'].replace('-','')}/"
        if (not re.fullmatch(r'\d{10}-\d{2}-\d{6}',recovery['accession'])
                or not recovery['source_url'].startswith(base)
                or not re.fullmatch(r'[\w.-]+\.htm[l]?',recovery['source_url'][len(base):])):
            return None
        values=recovery['values']
        if any(not _finite(values[k]) or values[k]!=row[k] for k in FIELDS):
            return None
        ocf,capex=values['ocf'],values['cash_capex'];amount=lambda v:f'{v/1e6:,.1f}백만 USD'
        facts=(f"{row['start']} ~ {row['end']} · 실적발표 원문 대조 복구 · 영업현금흐름 {amount(ocf)}; "
               f"현금 투자지출 {amount(capex)} ({row['cash_capex_scope']}); 단순차액 {amount(ocf-capex)}")
        if ocf>0:
            facts+=f'; 투자지출/영업현금흐름 {capex/ocf*100:.1f}%'
        why=('분기 영업현금보다 해당 현금 투자지출이 큽니다. ' if ocf<capex else
             '분기 영업현금과 해당 현금 투자지출이 같습니다. ' if ocf==capex else
             '분기 영업현금으로 해당 현금 투자지출을 충당하고 단순차액이 남습니다. ')
        if 'software' in values and _finite(values['software']) and values['software']>=0:
            facts+=f"; 별도 자본화 소프트웨어 개발비 {amount(values['software'])}"
            why+='소프트웨어 개발비는 기존 유형자산 투자지출에 포함되지 않아 단순차액을 회사 FCF로 보면 과대평가할 수 있습니다. '
            if (values.get('company_fcf_reconciled') is True and _finite(values.get('company_fcf'))
                    and math.isclose(ocf-capex-values['software'],values['company_fcf'],abs_tol=.01)):
                facts+=f"; 회사 공시 FCF {amount(values['company_fcf'])} (개발비 추가 차감과 일치)"
        why+='단순차액은 리스 원금·인수대금 등 모든 지출을 반영한 가용현금이나 AI 투자수익률이 아닙니다.'
        return {'검토축':'현금 창출·투자','확인된 사실':facts,'왜 중요한가':why,
                '다음 확인':'다음 분기 영업현금·운전자본과 투자지출이 같은 방향으로 움직이는지 확인. 개발비·리스·인수대금과 회사 FCF 정의도 별도로 비교'}
    except (KeyError,TypeError,ValueError,IndexError):
        return None
