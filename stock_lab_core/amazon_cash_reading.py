"""Dated Amazon cash/segment context from one reviewed 10-Q. No I/O or scoring."""
from datetime import date, datetime, timedelta, timezone

from stock_lab_core.bigtech_cash_comparison import _periods, _cash, _growth
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CIK = '0001018724'
FACTS_URL = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json'
ACCESSION, FILED, REVIEWED_ON = '0001018724-26-000040', '2026-10-30', '2026-11-08'
SOURCE_URL = 'https://www.sec.gov/Archives/edgar/data/1018724/000101872426000040/amzn-20260930.htm'
RELEASE_URL = 'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/'
SOURCE_SHA256 = 'e0cefa4c19d9ce4662e0541a2ea8fc91aefcfcce53bd6d715372ebf4ca361f8f'
# Public statement amounts, USD millions, Q3 only (not YTD or TTM).
# Net additions include non-cash/unpaid assets; they are NOT segment cash capex.
REVIEW = {
    2025: dict(ocf=35525, gross=35095, proceeds=867, other_investing=786,
               additions={'AWS': 28301, '북미': 8638, '국제': 1439, '본사': 507},
               additions_total=38885, aws_revenue=33006, aws_op_income=11434),
    2026: dict(ocf=42422, gross=77259, proceeds=1381, other_investing=23986,
               additions={'AWS': 57116, '북미': 14530, '국제': 6068, '본사': 548},
               additions_total=78262, aws_revenue=45984, aws_op_income=17773),
}


def _reviewed_cash(packet, row, year, cutoff):
    if not row:
        return None
    cash = _cash(row, cutoff, packet)
    if not cash['paired'] or row.get('cash_capex_scope') != '유형·소프트웨어·무형자산':
        return None
    for field, key, tag in [('ocf', 'ocf', 'NetCashProvidedByUsedInOperatingActivities'),
                            ('cash_capex', 'gross', 'PaymentsToAcquireProductiveAssets')]:
        expected = dict(start=f'{year}-07-01', end=f'{year}-09-30', value=REVIEW[year][key]*1_000_000,
                        tag=tag, unit='USD', accession=ACCESSION, filed=FILED, form='10-Q')
        evidence = row['provenance'][field]
        if (row[field] != expected['value'] or evidence.get('method') != 'reported'
                or evidence.get('facts') != [expected]):
            return None
    return REVIEW[year]


def amazon_cash_reading(packet):
    """Use the verified latest quarter only; any revised operand requires review.

    Existing caller owns the six-hour display expiry. A missing prior quarter
    withholds comparisons without inventing values or losing valid current data.
    """
    try:
        cutoff = date.fromisoformat(packet['as_of'])
        checked = datetime.fromisoformat(packet['checked_at'])
        if (packet.get('ticker') != 'AMZN' or packet.get('cik') != CIK
                or packet.get('source_url') != FACTS_URL or checked.tzinfo is None
                or checked.astimezone(timezone(timedelta(hours=9))).date() != cutoff
                or cutoff < date.fromisoformat(REVIEWED_ON)):
            return None
        periods = _periods(packet)
        if max(periods, default=None) != ('2026-07-01', '2026-09-30'):
            return None
        current = _reviewed_cash(packet, periods[('2026-07-01', '2026-09-30')], 2026, cutoff)
        if not current:
            return None
        previous = _reviewed_cash(packet, periods.get(('2025-07-01', '2025-09-30')), 2025, cutoff)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None

    def measures(values):
        if not values:
            return {}
        net = values['gross'] - values['proceeds']
        return {'영업현금': values['ocf'], '설비 취득 총현금': values['gross'],
                '자산매각·인센티브 수입(차감)': values['proceeds'], '순현금 설비지출': net,
                '영업현금 − 총현금 취득(기존 기준)': values['ocf']-values['gross'],
                '영업현금 − 순현금 설비지출': values['ocf']-net,
                '기업인수·비시장성투자·기타 순지출(별도)': values['other_investing']}
    c, p = measures(current), measures(previous)
    cash_rows = [{'항목(백만 USD)': k, '2025년 3분기': p.get(k), '2026년 3분기': v} for k, v in c.items()]
    additions = [{'부문': name, '2025년 3분기': previous['additions'][name] if previous else None,
                  '2026년 3분기': value} for name, value in current['additions'].items()]
    additions.append({'부문': '전체', '2025년 3분기': previous['additions_total'] if previous else None,
                      '2026년 3분기': current['additions_total']})
    ratio = c['순현금 설비지출']/c['영업현금']*100
    changes = (dict(ocf_yoy_pct=round(_growth(c['영업현금'], p['영업현금']), 1),
                    net_capex_yoy_pct=round(_growth(c['순현금 설비지출'], p['순현금 설비지출']), 1),
                    aws_revenue_yoy_pct=round(_growth(current['aws_revenue'], previous['aws_revenue']), 1)) if previous else {})
    summary = (f"순현금 설비지출은 영업현금의 {ratio:.1f}%로, 영업현금에서 이를 차감하면 "
               f"{c['영업현금 − 순현금 설비지출']:,.0f}백만 달러입니다. ")
    summary += (f"영업현금은 전년 동기보다 {changes['ocf_yoy_pct']:+.1f}% 늘었지만 "
                f"순현금 설비지출은 {changes['net_capex_yoy_pct']:+.1f}% 늘어 현금 부담이 커졌습니다."
                if previous else '전년 근거 보류로 부담의 증감 비교는 하지 않습니다.')
    aws_margin = current['aws_op_income']/current['aws_revenue']*100
    aws = (f"AWS 매출 {current['aws_revenue']:,.0f}백만 달러, 영업이익률 {aws_margin:.1f}%. "
           + (f"매출은 전년 동기보다 {changes['aws_revenue_yoy_pct']:+.1f}%. " if previous else '')
           + '이익률은 현금 회수율이나 투자수익률과 다릅니다.')
    drivers = [
        {'구분': '회사 설명 · 기술 인프라와 물류',
         '왜 중요한가': '현금 설비투자는 주로 기술 인프라와 물류망 확장. 기술 인프라의 대부분은 AWS 성장 지원이며 AWS에는 일반 클라우드와 AI가 함께 포함됩니다.'},
        {'구분': '해석(추정) · 투자와 회수',
         '왜 중요한가': 'AWS 매출·이익과 설비 규모는 수요를 판단할 근거입니다. 공급망 주문·납품 시점과 투자금 회수 시점은 별도로 확인해야 합니다.'},
        {'구분': '사실 · 다른 현금 사용',
         '왜 중요한가': f"기업인수·비시장성투자·기타 순지출 {current['other_investing']:,.0f}백만 달러는 위 설비지출과 별도입니다. AWS 설비비나 전부 비AI 지출로 분류하지 않습니다."},
    ]
    checks = [
        {'다음 확인': 'AWS 설비 → 매출·현금 회수', '볼 근거': 'AWS 매출·마진, 수주 이행·가동률 설명, 감가상각',
         '판단을 바꿀 조건': '성장·마진 유지와 회수 개선 / 설비 증가에 비해 수익 전환 지연'},
        {'다음 확인': '북미·국제의 설비 효율', '볼 근거': '부문 설비 순증가, 매출·마진, 배송·물류 효율',
         '판단을 바꿀 조건': '비용 효율·마진 개선 / 설비와 운영비 부담 지속'},
        {'다음 확인': '전체 현금 여력', '볼 근거': '영업현금·순현금 설비지출, 별도 투자·리스·차입 만기',
         '판단을 바꿀 조건': '현금 창출이 지출을 따라감 / 추가 투자·금융 부담 확대'},
    ]
    return dict(period='2026-07-01 ~ 2026-09-30', previous_verified=bool(previous), reviewed_on=REVIEWED_ON,
                source_date=FILED, review_only=True, eligible_for_scoring=False,
                summary=summary, cash_rows=cash_rows, additions=additions, changes=changes,
                aws_reading=aws, drivers=drivers, checks=checks, net_capex_ratio_pct=round(ratio, 1),
                source=dict(url=SOURCE_URL, accession=ACCESSION, sha256=SOURCE_SHA256,
                            sections=['Consolidated Statements of Cash Flows', 'Note 8 Segment Information', 'Liquidity and Capital Resources']),
                release_url=RELEASE_URL,
                limits='부문별 현금 설비지출·AWS 내 AI 비중은 이 자료로 분리할 수 없습니다. '
                '설비 순증가에는 미지급 취득 등 비현금이 포함되며 공유 인프라는 사용량에 따라 부문에 배분됩니다. '
                '북미·국제를 전부 물류 투자로 보거나 부문 순증가를 현금지출에 다시 더하지 않습니다.')


def render_amazon_cash_reading(st, review):
    def display(rows):
        return [{k: '보류' if v is None else f'{v:,.0f}' if isinstance(v, (int, float)) else v
                 for k, v in row.items()} for row in rows]
    st.markdown('**Amazon 현금 부담: AWS 성장과 투자금 회수**')
    st.caption(f"대상 {review['period']} · 10-Q 제출 {review['source_date']} · 원문 검토 {review['reviewed_on']} · 미감사")
    st.write(review['summary'])
    st.markdown(f"[근거: Amazon 현금흐름표·투자 설명]({SOURCE_URL})")
    st.dataframe(display(review['cash_rows']), hide_index=True, width='stretch')
    st.caption('순현금 설비지출 = 총현금 취득 − 자산매각·인센티브 수입. 분기 비교이며 회사의 최근 12개월 FCF와 기간이 다릅니다. 기존 점수·총현금 기준은 유지합니다.')
    st.markdown('**AWS와 다른 부문: 설비 순증가액(비현금 포함, 백만 USD)**')
    st.dataframe(display(review['additions']), hide_index=True, width='stretch')
    st.caption(review['limits'])
    st.write(review['aws_reading'])
    st.markdown(f"[근거: 사업부문 주석]({SOURCE_URL}) · [실적발표 대조]({RELEASE_URL})")
    st.markdown('**왜 중요한가 — 위 공시의 사실·회사 설명·해석 구분**')
    st.table(review['drivers'], hide_index=True)
    st.markdown('**다음 실적에서 확인할 조건**')
    st.table(review['checks'], hide_index=True)
    st.caption('영업현금의 운전자본 효과는 별도 분해 전입니다. 이 자료만으로 현금 고갈·적정가·당일 주가 원인을 계산하지 않습니다. 검토 파일에 원자료와 해석 근거를 분리해 담습니다.')
