"""Explicit, owner-scoped comparison; never loaded by the default report collector."""
from datetime import datetime, timezone, timedelta
import json

from stock_lab_core.bigtech_cash_comparison import compare_bigtech_cash, comparison_options
from stock_lab_core.sec_quarter_review_view import load_quarter_evidence, _safe_error
from stock_lab_core.sec_quarter_review import quarter_tables
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def render_bigtech_comparison(st, *, options, prefix, configured, resolve_cik, fetch_facts, now=None):
    st.subheader('빅테크 현금 창출·투자 부담')
    available = comparison_options(options)
    st.caption('보유·관심 빅테크의 최근 8개 관측 분기에서 같은 시작일·종료일을 찾아 비교합니다. 버튼을 눌렀을 때만 조회하며 기존 점수·판정은 유지합니다.')
    if len(available) < 2:
        st.info('보유·관심목록에 비교할 MSFT·AMZN·Alphabet·META 중 두 기업 이상이 필요합니다.')
        return
    key = prefix + '_bigtech'
    selected_key = key + '_selection'
    if selected_key in st.session_state:
        kept = [t for t in st.session_state[selected_key] if t in available]
        if kept != list(st.session_state[selected_key]):
            st.session_state[selected_key] = kept
    selected = st.multiselect('같은 기간으로 비교할 빅테크', available, default=available[:4],
                              max_selections=4, key=selected_key)
    if st.button('선택 빅테크 비교 조회 (점수 유지)', key=key+'_load', disabled=len(selected)<2 or not configured):
        st.session_state.pop(key, None)
        checked = now or datetime.now(timezone.utc)
        packets, errors = {}, []
        with st.spinner('선택 기업의 현금흐름 공시를 같은 기간으로 맞추는 중...'):
            for t in selected:
                try:
                    packets[t] = load_quarter_evidence(t, resolve_cik=resolve_cik, fetch_facts=fetch_facts, now=checked)
                except Exception as error:
                    packets[t] = {}
                    errors.append({'기업': t, '조회 상태': _safe_error(error)})
        st.session_state[key] = dict(selected=sorted(selected), packets=packets, errors=errors,
            checked_at=checked.isoformat(), comparison=compare_bigtech_cash(packets))
    if not configured:
        st.info('SEC 연락처(sec_user_agent) 설정이 필요합니다.')
    bundle = st.session_state.get(key)
    if not bundle or bundle['selected'] != sorted(selected):
        return
    if not timedelta(0) <= (now or datetime.now(timezone.utc)) - datetime.fromisoformat(bundle['checked_at']) <= timedelta(hours=6):
        st.info('조회 후 6시간이 지났거나 조회시각 확인이 필요합니다. 다시 조회하세요.')
        return
    if bundle['errors']:
        st.dataframe(bundle['errors'], hide_index=True, width='stretch')
    result = bundle['comparison']
    st.markdown('**무엇을 읽어야 하나**')
    st.write(result['conclusion'])
    st.caption('조회 ' + bundle['checked_at'] + ' · 최근 실적발표·가이던스 전체 반영은 미확인')
    if result['period']:
        st.markdown('**같은 기간 현금 비교 · ' + result['period'] + '**')
        st.dataframe(result['rows'], hide_index=True, width='stretch')
        st.caption(result['scope_note'] + ' 빈칸은 0이 아닙니다. 공통 기간이 기업의 최신 분기보다 과거일 수 있습니다.')
        st.markdown('**전년 동기 대비 · ' + result['previous_period'] + '**')
        st.dataframe(result['trends'], hide_index=True, width='stretch')
        for item in result['readings']:
            st.markdown('**' + item['기업'] + ' · 왜 중요한가**')
            st.write('사실: ' + item['사실'])
            st.write('해석(추정): ' + item['해석(추정)'])
            st.caption('다음 확인: ' + item['다음 확인'])
            st.caption('근거: ' + item['근거'])
    st.caption(result['limits'])
    with st.expander('기업별 최신 기간·공시 원문·보류 근거'):
        st.dataframe(result['coverage'], hide_index=True, width='stretch')
        for t, packet in bundle['packets'].items():
            if packet.get('quarter'):
                _, quality, sources = quarter_tables(packet)
                st.markdown('**' + t + '**')
                st.dataframe(quality, hide_index=True, width='stretch')
                st.dataframe(sources, hide_index=True, width='stretch')
    st.download_button('빅테크 비교 검토 파일 받기', json.dumps(bundle, ensure_ascii=False, indent=2),
                       file_name='bigtech_cash_comparison.json', mime='application/json', key=key+'_download', on_click='ignore')
