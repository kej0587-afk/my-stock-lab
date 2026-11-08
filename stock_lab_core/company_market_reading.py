"""Join existing, scoped market observations to validated company readings.

Display only: no collection, scores, forecasts, storage or issuer exceptions.
The caller supplies readings from the existing financial evidence validators.
"""
from datetime import datetime, timedelta, timezone

from stock_lab_core.portfolio_market_review import MAX_AGE
from stock_lab_core.data_freshness import session_reference
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import number, records, safe_link, stamp, text
from stock_lab_core.report_leadership import company_research_question
from stock_lab_core.report_presentation import sector_related_news

register_loaded_source(__name__, __file__)


def _number(value):
    return None if isinstance(value, bool) else number(value)


def _pct(value):
    return '미연결' if value is None else f'{value * 100:+.2f}%'


def build_company_market_reading(ticker, data, *, sector=(), readings=(), now=None):
    now = stamp(now or datetime.now(timezone.utc).isoformat())
    checked = stamp((data or {}).get('quote_checked_at'))
    fresh = bool(now and checked and timedelta(0) <= now - checked <= MAX_AGE)
    data = data if fresh else {}
    market = 'KR' if ticker.endswith(('.KS', '.KQ')) or ticker.isdigit() else 'US'
    benchmark = '^KS11' if market == 'KR' else '^GSPC'
    session = text((data.get('sessions') or {}).get(market))
    expected = session_reference(benchmark, now=now).get('completed') if now and data else ''
    if not session or not expected or session != expected:
        data, session = {}, ''
    proxy, label = sector if len(sector) == 2 else ('', '')
    # Never turn a cross-market proxy or the market itself into a sector signal.
    if proxy == benchmark or (proxy and proxy.endswith(('.KS', '.KQ')) != (market == 'KR')):
        proxy, label = '', ''
    flows = {text(r.get('Ticker')): r for r in records(data.get('closed_flow_rows'))
             if session and text(r.get('기준일')) == session}
    observed, values = [], {}
    for symbol, relation in ((benchmark, '시장'), (proxy, f'업종 대용 · {label}'), (ticker, '선택 기업')):
        if not symbol:
            continue
        quote = (data.get('prices') or {}).get(symbol) or {}
        if quote.get('stale'):
            continue
        flow = flows.get(symbol, {})
        daily = _number(quote.get('return')) if session and quote.get('date') == session else None
        source = text(quote.get('source')) if daily is not None else ''
        if daily is None:
            daily = _number(flow.get('1일수익률'))
            source = '시황과 동일한 종가 이력' if daily is not None else ''
        five, quarter = (_number(flow.get(key)) for key in ('5일수익률', '3개월수익률'))
        if all(v is None for v in (daily, five, quarter)):
            continue
        values[symbol] = daily
        observed.append({'범위': relation, '대상': symbol, '기준': session + ' 종가',
                         '일간': _pct(daily), '5일': _pct(five), '3개월': _pct(quarter),
                         '출처': source or '시황과 동일한 종가 이력'})
    base, industry = values.get(benchmark), values.get(proxy)
    excess = (industry - base) * 100 if industry is not None and base is not None else None
    if industry is not None:
        headline = f'{label or proxy}({proxy}) {_pct(industry)}'
        if excess is not None:
            headline += f', 시장 대비 {excess:+.2f}%p'
        headline += f' · {session} 종가'
        if industry < 0:
            meaning = ('업종 가격이 하락한 상황에서는 이 기업의 주문·매출·마진까지 약해졌는지 먼저 구분해야 합니다. '
                       '실적이 유지되면 가격 조정과 사업 악화가 다를 수 있지만, 과거 분기 호조만으로 현재 우려가 해소되지는 않습니다.')
        elif industry > 0:
            meaning = ('업종 가격 상승을 이 기업의 수요 회복으로 확인하려면 매출뿐 아니라 마진과 현금 회수도 따라와야 합니다. '
                       '좋은 가격 흐름만으로 회사 실적이나 투자 회수 개선을 확정할 수 없습니다.')
        else:
            meaning = '업종 일간 등락이 보합입니다. 하루 방향보다 다음 실적의 매출·마진·현금 회수가 함께 개선되는지 확인합니다.'
    elif base is not None:
        headline = f'시장({benchmark}) {_pct(base)} · {session} 종가 / 업종 비교 미연결'
        meaning = '시장 전체 등락을 이 기업의 사업 상황으로 대신 해석하지 않습니다. 업종 근거가 연결되기 전에는 기업 공시로만 실적·현금 상태를 판단합니다.'
    else:
        headline = '현재 시장·업종 근거를 연결하지 못해 시장과 기업의 종합 해석을 보류합니다.'
        meaning = '시장 전체에서 자동 뉴스픽을 생성하면 같은 계좌의 수집 자료를 재사용합니다. 기업 선택만으로 외부 조회를 추가하지 않습니다.'
    question = company_research_question(ticker)
    financial = [dict(row) for row in readings if row.get('검토축') in {'매출·이익', '현금 창출·투자'}]
    coverage = [row['확인된 사실'] for row in readings if row.get('검토축') == '자료 범위']
    cash = next((row for row in financial if row['검토축'] == '현금 창출·투자'), None)
    connection = ('현금 관점: ' + cash['왜 중요한가'] if cash else
                  '동일 기준의 현금 근거는 아래 기업 상세에서 확인해야 합니다. 미수집 항목을 현금 악화나 개선으로 대신 판단하지 않습니다.')
    connection += ' 이 분기 자료는 당일 가격 변화의 원인 증명이 아닙니다. 다음 공시에서 수요와 현금 회수가 함께 유지되는지가 연결 고리입니다.'
    news = []
    if proxy and session:
        for row in sector_related_news(proxy, session, data.get('news') or []):
            published = stamp(row.get('published_at') or row.get('published'))
            url = safe_link(row.get('link'))
            if not url or not published or not timedelta(0) <= now - published <= timedelta(days=3):
                continue
            news.append({'보도 쟁점 · 기사 주장': text(row.get('title')), '기준 세션': session,
                         '범위': '시장 공통 배경' if row.get('market_context_only') else '업종 관련 보도', '출처': url})
            if len(news) == 2:
                break
    return dict(ticker=ticker, review_only=True, eligible_for_scoring=False,
                quote_checked_at=checked.isoformat() if checked else '',
                headline=headline, observations=observed, sector_proxy=proxy,
                sector_excess_pp=excess, interpretation=meaning, question=question['시장 질문'],
                connection=connection, financial=financial, coverage=coverage, news=news,
                next_check=question['다음 확인'],
                limits='업종 ETF는 사업의 대용 지표입니다. 회사 전체 재무를 해당 업종·AI 사업부 실적으로 치환하지 않습니다. 종가와 분기 실적은 기준 기간이 다릅니다.')


def render_company_market_reading(st, review, status):
    st.markdown('### 시장에서 이 기업을 읽는 순서')
    st.write('사실: ' + review['headline'])
    st.caption(status + ' · 기업 선택 시 재수집하지 않음')
    if review['observations']:
        st.dataframe(review['observations'], hide_index=True, width='stretch')
    st.write('해석(추정): ' + review['interpretation'])
    st.write('이 기업에 중요한 질문: ' + review['question'])
    if review['financial']:
        st.write('해석(추정): ' + review['connection'])
        st.markdown('**공시로 확인된 근거 → 다음에 확인할 변화**')
        # Wrapped prose avoids a wide, clipped grid for long financial evidence.
        for row in review['financial']:
            with st.expander(row['검토축'] + ' · 근거와 다음 확인', expanded=True):
                st.write('사실: ' + row['확인된 사실'])
                if row['검토축'] == '매출·이익':
                    st.caption('읽는 기준: ' + row['왜 중요한가'])
                st.write('다음 확인: ' + row['다음 확인'])
    for note in review['coverage']:
        st.caption(note)
    if review['news']:
        st.dataframe(review['news'], hide_index=True, width='stretch',
                     column_config={'출처': st.column_config.LinkColumn('출처', display_text='기사 원문')})
        st.caption('기사 주장이며 해당 기업의 등락 원인으로 확정하지 않습니다.')
    else:
        st.caption('미확인: 같은 세션의 관련 업종 기사 근거 없음. 주가 원인을 추측으로 채우지 않습니다.')
    st.write('다음 확인: ' + review['next_check'])
    st.caption(review['limits'])
