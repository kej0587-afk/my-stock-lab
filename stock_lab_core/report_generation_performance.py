"""Run-local, observation-only timing; never changes retrieval or report content."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
from threading import get_ident

from stock_lab_core.performance import PerformanceTrace, count_event, measure
from stock_lab_core.report_build import get_report_build_info, register_loaded_source

register_loaded_source(__name__, __file__)
_run = ContextVar('auto_report_measurement', default=None)
LABELS = {'preparation': '자료 준비', 'prices': '시세 조회·가격 정렬',
          'flow_snapshot': '돈흐름 스냅샷 조회·계산', 'macro_official': '매크로·공시·수급',
          'news': '뉴스 RSS·분류', 'articles': '기사 본문 조회·해석',
          'calculations': '종가 지표 계산', 'persistence': '이력 저장·연결',
          'assembly': '리포트 조립'}


def set_report_stage(name):
    run = _run.get()
    if run is None or get_ident() != run['owner']:
        return
    if name not in LABELS:
        raise ValueError('unknown report measurement stage')
    now = run['trace'].clock()
    old = run['stage']
    run['seconds'][old] = run['seconds'].get(old, 0.0) + max(0, now - run['stage_started'])
    run.update(stage=name, stage_started=now)


def report_phase(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            run = _run.get()
            previous = run['stage'] if run else None
            set_report_stage(name)
            try:
                return component(fn, *args, **kwargs)
            finally:
                if previous is not None:
                    set_report_stage(previous)
        return wrapped
    return decorate


def component(fn, *args, **kwargs):
    with measure('report_component', fn.__name__):
        return fn(*args, **kwargs)


def report_http_attempt(provider):
    # Only fixed origin labels; never retain URLs, query strings, keys or bodies.
    run = _run.get()
    if run is not None:
        count_event(f'report_http.{run["stage"]}.{provider}.attempt')


def report_degraded(reason):
    run = _run.get()
    if run is not None:
        run['degraded'].add(reason)


def report_hash(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


@contextmanager
def generation_measurement(state, *, options=None, entrypoint=None, script_started=None, clock=None):
    trace = PerformanceTrace(scope='auto_market_report_generation', **({'clock': clock} if clock else {}))
    before = max(0, trace.clock() - script_started) if script_started is not None else None
    run = {'trace': trace, 'owner': get_ident(), 'stage': 'preparation', 'seconds': {}, 'degraded': set()}
    token = _run.set(run)
    try:
        with trace:
            run['stage_started'] = trace.clock()
            try:
                yield
            finally:
                set_report_stage(run['stage'])
    finally:
        _run.reset(token)
        report = trace.report()
        output = state.get('today_market_memo_text', '')
        report.update(stages_seconds=run['seconds'], stages_are_exclusive_wall_time=True,
                      stage_unattributed_seconds=max(0, report['elapsed_seconds'] - sum(run['seconds'].values())),
                      script_before_generation_seconds=before,
                      script_to_report_seconds=before + report['elapsed_seconds'] if before is not None else None,
                      output_sha256=report_hash(output) if output and report['measurement_status'] == 'completed' else None,
                      generation_path='fallback' if run['degraded'] else 'normal',
                      degraded_reasons=sorted(run['degraded']),
                      options=dict(options or {}), cache_state={'policy': 'unchanged_no_clear', 'initial_warmth': 'unknown'},
                      build=get_report_build_info(entrypoint),
                      request_count_coverage='report_http.* counts instrumented economic HTTP, Google RSS and public feed/body HTTP attempts, including redirects. Other providers may be uncounted. Existing price events include both HTTP and SDK calls: download_call is not a remote-request count. Function calls/cache lookups are not HTTP requests.',
                      timing_limits='Starts when generation branch is entered; includes collection through saved Markdown. App entry/render before this branch and browser paint are excluded. Diagnostic serialization/build hashing is excluded.')
        state['auto_report_last_attempt'] = report
        if report['measurement_status'] == 'completed' and report['output_sha256']:
            state['auto_report_performance'] = report


def render_generation_timing(st, state, report_text):
    report = state.get('auto_report_performance', {})
    if not report or report.get('output_sha256') != report_hash(report_text):
        return
    with st.expander('이 시황 생성 시간 · 전체 작업', expanded=False):
        st.write(f"자동 시황 생성 {report['elapsed_seconds']:.1f}초 · 완료 · 측정ID {report['measurement_id']}")
        if report.get('degraded_reasons'):
            st.caption('일부 수집·조립이 대체 경로로 완료됐습니다: ' + ', '.join(report['degraded_reasons']))
        st.dataframe([{'구간': LABELS[key], '경과시간(초)': round(value, 3)}
                      for key, value in report['stages_seconds'].items()], hide_index=True, width='stretch')
        st.caption('구간은 중첩 없는 경과시간입니다. 병렬 작업을 더한 함수별 누적시간과 구분합니다. 캐시는 비우지 않았으며 화면 재표시로 이 기록을 덮어쓰지 않습니다. 앱 진입 처리·브라우저 그리기는 제외됩니다.')
        st.download_button('이 시황 생성 전체 진단 JSON', json.dumps(report, ensure_ascii=False, indent=2),
                           file_name=f"auto_report_{report['measurement_id']}.json", mime='application/json',
                           key='auto_report_generation_diagnostic', on_click='ignore')
