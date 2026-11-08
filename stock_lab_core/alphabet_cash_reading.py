"""Dated, source-bound Alphabet cash explanation; no fetching or score changes."""
from stock_lab_core.bigtech_cash_comparison import _periods, _cash, _growth, _million
from stock_lab_core.sec_financial_periods import _date
from stock_lab_core.alphabet_cash_q3 import RELEASE_URL, RELEASE_FILED, REVIEWED_ON
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

CALL_URL = 'https://abc.xyz/investor/events/event-details/2026/2026-Q3-Earnings-Call-2026-Ujou16CTw9/default.aspx'


def alphabet_cash_reading(packet):
    """Only explain the reviewed latest quarter. Never substitute an older one.

    Reuses the same cash/source checks as the Big Tech comparison. Missing prior
    evidence holds the YoY comparison, not the independently recovered current
    quarter. The caller retains the existing six-hour display guard.
    """
    if not isinstance(packet, dict) or packet.get('ticker') not in {'GOOG', 'GOOGL'}:
        return None
    periods = _periods(packet)
    latest = max(periods, default=None)
    if latest != ('2026-07-01', '2026-09-30'):
        return None
    current = _cash(periods[latest], _date(packet['as_of']), packet)
    if not current.get('recovery'):
        return None
    previous_key = ('2025-07-01', '2025-09-30')
    prior = _cash(periods[previous_key], _date(packet['as_of']), packet) if previous_key in periods else {}
    # Both reviewed quarters come directly from the same comparative exhibit.
    comparable = bool(prior.get('recovery')) and prior['filings'] == current['filings']
    rows = []
    for period, values in ((previous_key, prior if comparable else {}), (latest, current)):
        rows.append({'기간': ' ~ '.join(period),
                     '영업현금(백만$)': _million(values.get('ocf')),
                     '현금 투자(백만$)': _million(values.get('capex')),
                     '단순차액(백만$)': _million(values.get('residual')),
                     '투자/영업현금(%)': round(values['ratio'], 1) if values else None,
                     '확인 상태': '실적발표 원문 대조(미감사)' if values else '전년 근거 보류'})
    changes = ({'ocf_yoy_pct': round(_growth(current['ocf'], prior['ocf']), 1),
                'capex_yoy_pct': round(_growth(current['capex'], prior['capex']), 1),
                'ratio_change_pp': round(current['ratio'] - prior['ratio'], 1)} if comparable else {})
    summary = (f"현금 투자지출이 영업에서 번 현금의 {current['ratio']:.1f}%로, "
               f"두 항목의 단순차액은 {_million(current['residual']):,.0f}백만 달러입니다.")
    if comparable:
        summary += (f" 전년 동기보다 영업현금은 {changes['ocf_yoy_pct']:+.1f}%, "
                    f"현금 투자는 {changes['capex_yoy_pct']:+.1f}%로 현금 부담이 커졌습니다.")
    else:
        summary += ' 전년 근거 확인 전에는 부담이 늘었는지 비교하지 않습니다.'
    # Paraphrases of CFO remarks and Q&A; not a live transcript or consensus feed.
    drivers = [
        {'구분': '회사 설명 · 설비투자',
         '확인된 근거': '지출 대부분은 AI 지원 기술 인프라. 기술 인프라 투자 중 서버·네트워크 약 65%, 데이터센터 약 35%.',
         '읽는 법': '설비 지출과 이후 수익 회수 시점은 다를 수 있음(해석·추정). 전체 투자를 AI 전용으로 환산하지 않음.'},
        {'구분': '회사 설명 · 운전자본',
         '확인된 근거': 'TPU 시스템 판매를 위한 재고 축적이 영업현금에 부담. 회사는 계약 후 재고를 만들고 납품·청구하며 회수하는 구조라고 설명.',
         '읽는 법': '판매용 재고는 자체 설비투자와 별개. 현금이 먼저 나간다는 설명이며 재고가 전부 회수된다는 보장은 아님.'},
        {'구분': '회사 설명 · 과거 사건 지급',
         '확인된 근거': '2018년 EC 벌금 관련 항소 종료 후 현금 52억 달러 지급이 영업현금에 부담.',
         '읽는 법': '해당 사건의 지급을 분리해 보되, 다른 법적 비용까지 비반복으로 가정하지 않음.'},
    ]
    checks = [
        {'다음 확인': 'TPU 재고 → 납품·현금 회수', '볼 근거': '다음 실적의 재고·매출채권·영업현금과 TPU 납품 설명',
         '부담 완화 / 지속 조건': '재고 회전·현금 회수 개선 / 재고·채권 증가가 현금 유입을 계속 앞섬'},
        {'다음 확인': '투자 속도와 사업 수익', '볼 근거': '현금 투자·감가상각, Google Cloud 매출·영업이익률',
         '부담 완화 / 지속 조건': '현금 창출이 투자 증가를 따라감 / 투자·운영비 증가가 수익 회수를 앞섬'},
        {'다음 확인': '과거 사건 지급 이후', '볼 근거': '다음 분기 법적 지급·기타 운전자본과 현금·차입 만기',
         '부담 완화 / 지속 조건': '해당 지급 소멸 후 현금 개선 / 다른 지급·운전자본 부담이 이어짐'},
    ]
    return dict(period=' ~ '.join(latest), reviewed_on=REVIEWED_ON, source_date=RELEASE_FILED,
                review_only=True, eligible_for_scoring=False, summary=summary, rows=rows,
                changes=changes, drivers=drivers, checks=checks,
                recoveries=[v['recovery'] for v in (prior if comparable else {}, current) if v.get('recovery')],
                sources={'cash_statement': RELEASE_URL, 'management_call': CALL_URL},
                interpretation='해석(추정): 공급업체 관점에서는 기술 인프라 지출이 수요 근거지만, Alphabet에서는 회수 전 현금 부담입니다. '
                'TPU 재고 지출을 설비투자에 다시 더하지 않고, 납품·회수와 Cloud 수익성을 함께 확인해야 합니다.',
                limits='재고 영향의 개별 금액은 이 검토에 미연결입니다. 영업현금 감소분 전체를 재고·벌금 탓으로 배분하거나 '
                '벌금을 임의로 더한 조정 현금흐름을 계산하지 않습니다. 단순차액만으로 현금 고갈·적정가·당일 주가 원인을 판단하지 않습니다.')


def render_alphabet_cash_reading(st, review):
    from stock_lab_core.bigtech_cash_view import _display_rows
    st.markdown('**Alphabet 현금 부담: 투자 확대와 회수 시차**')
    st.caption(f"대상 {review['period']} · 공시·회사 설명 {review['source_date']} · 원문 검토 {review['reviewed_on']} · 미감사")
    st.write(review['summary'])
    st.markdown(f"[근거: Alphabet Q3 실적발표 현금흐름표]({RELEASE_URL})")
    st.dataframe(_display_rows(review['rows']), hide_index=True, width='stretch')
    st.markdown(f"**왜 현금이 묶였나 — [회사 실적발표 설명]({CALL_URL})**")
    st.table(review['drivers'], hide_index=True)
    st.write(review['interpretation'])
    st.markdown(f"[해석 근거: 회사 설명·질의응답]({CALL_URL})")
    st.markdown('**다음 실적에서 확인할 조건**')
    st.table(review['checks'], hide_index=True)
    st.caption(review['limits'])
    st.caption('전년 비교는 같은 실적발표에 수록된 동일 분기로 한정합니다. 원문 복구 근거는 검토 파일에 별도로 담고 원자료의 보류 상태는 유지합니다.')
