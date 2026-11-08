"""User-selected issuer review, separate from market reports and scores."""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import re

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.sec_quarter_review_view import load_quarter_evidence, _safe_error
from stock_lab_core.sec_quarter_review import quarter_tables
from stock_lab_core.company_kr_evidence import load_company_kr_evidence

register_loaded_source(__name__, __file__)


def company_options(universe):
    result = {}
    for row in universe:
        symbol = str(row.get('ticker', '')).strip().upper()
        if (row.get('source') not in {'보유', '관심'} or row.get('is_etf')
                or not re.fullmatch(r'(?:[A-Z][A-Z0-9.-]{0,14}|[0-9A-Z]{6}(?:\.(?:KS|KQ))?)', symbol)):
            continue
        previous = result.get(symbol)
        if previous and previous.get('source') == '보유':
            continue
        result[symbol] = dict(row, ticker=symbol)
    return dict(sorted(result.items(), key=lambda pair: (pair[1]['source'] != '보유', pair[0])))


def render_company_deep_dive(st, *, universe, owner, configured, resolve_cik,
                             fetch_facts, load_kr, kr_identity_loader=None,
                             kr_store_factory=None, kr_extract_metrics=None, is_demo=False, now=None):
    st.subheader('기업 심층분석')
    st.caption('보유·관심 개별기업을 선택해 실적 → 현금 창출 → 투자 부담 → 다음 확인 순서로 봅니다. 시장 시황과 기존 점수·판정은 바뀌지 않습니다. ETF는 기업 재무 비교에서 제외됩니다.')
    if not owner or is_demo:
        st.info('개인 계정의 보유·관심목록에서 기업을 선택할 수 있습니다.')
        return
    options = company_options(universe)
    if not options:
        st.info('보유·관심목록에 분석할 개별기업이 없습니다.')
        return
    prefix = 'market_company_' + sha256(str(owner).strip().lower().encode()).hexdigest()[:20]
    if st.radio('기업 분석 방식', ['개별기업', '빅테크 같은 기간 비교'], horizontal=True, key=prefix+'_mode') == '빅테크 같은 기간 비교':
        from stock_lab_core.bigtech_cash_view import render_bigtech_comparison
        render_bigtech_comparison(st, options=options, prefix=prefix, configured=configured,
                                 resolve_cik=resolve_cik, fetch_facts=fetch_facts, now=now)
        return
    selection_key = prefix + '_selection'
    if st.session_state.get(selection_key) not in ['', *options]:
        st.session_state[selection_key] = ''
    symbol = st.selectbox('심층분석 기업 (보유·관심)', ['', *options], key=selection_key,
        format_func=lambda s: '기업을 선택하세요' if not s else f"{options[s]['name']} ({s}) · {options[s]['source']}")
    if not symbol:
        return
    from stock_lab_core.report_leadership import company_research_question
    question = company_research_question(symbol)
    st.markdown('**시장 흐름에서 이 기업에 확인할 질문**')
    st.write(question['시장 질문'])
    st.caption('검토할 조건: ' + question['다음 확인'])
    st.caption('조사 질문이며 아직 확인된 실적 변화가 아닙니다. 회사 전체 수치를 AI/데이터센터 사업부 수치로 대신하지 않습니다.')
    kr = bool(re.fullmatch(r'\d[0-9A-Z]{5}(?:\.(?:KS|KQ))?', symbol))
    if st.button('선택 기업 근거 조회 (점수 유지)', key=prefix+'_load', disabled=not kr and not configured):
        st.session_state.pop(prefix, None)
        try:
            with st.spinner('선택 기업 공시 확인 중...'):
                checked = now or datetime.now(timezone.utc)
                packet = (load_company_kr_evidence(symbol, owner=owner, load_live=load_kr,
                          identity_loader=kr_identity_loader, store_factory=kr_store_factory,
                          extract_metrics=kr_extract_metrics, now=checked) if kr else
                          load_quarter_evidence(symbol, resolve_cik=resolve_cik, fetch_facts=fetch_facts, now=checked))
            st.session_state[prefix] = dict(ticker=symbol, kind='kr' if kr else 'us', packet=packet,
                                            checked_at=checked.isoformat())
        except Exception as error:
            st.warning('DART 자료 연결 실패 · 이전 기업 자료를 대신 표시하지 않습니다.' if kr else _safe_error(error))
    if not kr and not configured:
        st.info('SEC 연락처(sec_user_agent) 설정이 필요합니다.')
    bundle = st.session_state.get(prefix)
    if not bundle or bundle['ticker'] != symbol:
        return
    age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(bundle['checked_at'])
    if not timedelta(0) <= age <= timedelta(hours=6):
        st.info('조회 후 6시간이 지났거나 조회시각 확인이 필요합니다. 버튼을 눌러 다시 확인하세요.')
        return
    packet = bundle['packet']
    download_bundle = bundle
    stored = packet.get('저장 근거') if kr else None
    if stored:
        stored_age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(stored['collected_at'])
        if not -timedelta(minutes=5) <= stored_age <= timedelta(days=7):
            st.info('개인 저장 자료의 수집 유효기간(7일)이 지났습니다. 새 DART 자료를 가져온 뒤 다시 조회하세요.')
            return
    st.subheader(f"{options[symbol]['name']} ({symbol})")
    st.caption(f"{options[symbol]['source']} 기업 · 조회 {bundle['checked_at']} · 회사 전체 자료이며 당일 주가 움직임의 원인으로 단정하지 않습니다.")
    if kr:
        st.write(packet['조회 상태'])
        st.caption(f"공급처: {packet['공급처']} · 보고기간: {packet['공급처 조회 기간']}")
        if stored:
            collected = datetime.fromisoformat(stored['collected_at']).astimezone(timezone(timedelta(hours=9)))
            freshness = '최근 수집' if stored_age <= timedelta(days=1) else '낡은 자료'
            st.caption(f"수집 {collected:%Y-%m-%d %H:%M} KST · {max(0, stored_age.total_seconds())/3600:.1f}시간 전 · {freshness}")
            st.caption('실시간 조회 사유: ' + packet['실패 사유'])
        if packet.get('저장 근거 상태'):
            st.info(packet['저장 근거 상태'])
        st.write('왜 중요한가: 매출·이익이 늘어도 영업현금이 따라오는지 함께 봐야 합니다. 누적 분기와 단독 분기, 연결·별도 기준을 맞춘 뒤 비교해야 합니다.')
        st.write('다음 확인: 최신 DART 보고기간, 영업현금흐름, 현금 투자지출의 수집 여부를 확인하세요. 현재 국내 조회는 기존 연간·분기 원자료 범위이며, 8분기 투자비율·전망 분석은 미연결입니다.')
        if packet['원자료']:
            st.dataframe(packet['원자료'], hide_index=True, width='stretch',
                         column_config={'공시 원문': st.column_config.LinkColumn('공시 원문', display_text='DART 원문')})
            if packet.get('수집 범위'):
                with st.expander('저장 자료의 보고기간·수집 상태'):
                    st.dataframe(packet['수집 범위'], hide_index=True, width='stretch')
        else:
            st.info(packet['실패 사유'] or '국내 재무 원자료 미연결 · 정밀관측소의 DART 파일 가져오기에서 확인할 수 있습니다.')
    else:
        from stock_lab_core.company_cash_reading import company_cash_reading
        from stock_lab_core.alphabet_cash_reading import alphabet_cash_reading, render_alphabet_cash_reading
        cash_review = alphabet_cash_reading(packet)
        readings = company_cash_reading(packet)
        if cash_review:
            render_alphabet_cash_reading(st, cash_review)
            download_bundle = dict(bundle, alphabet_cash_review=cash_review)
            # The raw extractor intentionally still holds these cash fields.
            # Avoid presenting its unrecovered coverage/cash prose as the final review.
            readings = [item for item in readings if item['검토축'] == '매출·이익']
        for item in readings:
            st.markdown('**' + item['검토축'] + '**')
            st.write(item['확인된 사실'])
            st.write('왜 중요한가: ' + item['왜 중요한가'])
            st.caption('다음 확인: ' + item['다음 확인'])
        financial, quality, sources = quarter_tables(packet)
        if financial:
            if cash_review:
                with st.expander('원자료 8분기·복구 전 보류 상태'):
                    st.caption('자동 추출 원자료입니다. 위 현금 비교는 원문 대조로 별도 복구했으며 원자료·점수에는 합산하지 않습니다.')
                    st.dataframe(financial, hide_index=True, width='stretch')
            else:
                st.dataframe(financial, hide_index=True, width='stretch')
            with st.expander('기간·누락·누적차감·공시 출처'):
                st.dataframe(quality, hide_index=True, width='stretch')
                st.dataframe(sources, hide_index=True, width='stretch')
        else:
            st.info('지원하는 US-GAAP 10-K/10-Q 분기자료가 없습니다. 20-F/6-K 기업은 현재 8분기 분석 미지원입니다.')
        st.caption('금액: 백만 USD. 회사 전망·컨센서스·사업부문 해석은 공통 자동 연결 전입니다. 자료 누락을 0이나 MSFT 자료로 대신 채우지 않습니다.')
        if symbol == 'MSFT':
            with st.expander('MSFT 검증된 현금 부담·사업 전망 추가 근거'):
                from stock_lab_core.report_msft_cash import msft_cash_lines
                st.markdown('\n'.join(msft_cash_lines({'msft_cash_evidence':{'packet':packet}}, now or datetime.now(timezone.utc))))
                from stock_lab_core.msft_ir_review_view import render_msft_business_review
                render_msft_business_review(st, ticker=symbol, owner=owner)
    st.download_button('선택 기업 검토 파일 받기', json.dumps(download_bundle, ensure_ascii=False, indent=2),
        file_name=f'company_review_{symbol}.json', mime='application/json', key=prefix+'_download', on_click='ignore')
