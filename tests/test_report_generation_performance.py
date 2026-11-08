"""Dedicated report measurement survives Streamlit reruns without changing output."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from stock_lab_core import report_generation_performance as p
from stock_lab_core.performance import PerformanceTrace, count_event, submit_with_context


@pytest.fixture(autouse=True)
def no_build_io(monkeypatch):
    monkeypatch.setattr(p, 'get_report_build_info', lambda entrypoint: {'id': 'offline'})


def test_nested_stages_exclusive_and_same_result():
    now, state = [0.0], {}

    @p.report_phase('articles')
    def article(value):
        now[0] += 3
        return value

    @p.report_phase('news')
    def news(value):
        now[0] += 2
        result = article(value)
        now[0] += 1
        return result

    data = {'judgment': '유지', 'score': 4}
    with p.generation_measurement(state, clock=lambda: now[0]):
        p.set_report_stage('prices')
        now[0] = 4
        assert news(data) is data
        now[0] += 1
        p.set_report_stage('assembly')
        now[0] += 2
        state['today_market_memo_text'] = 'same output'
    report = state['auto_report_performance']
    assert report['elapsed_seconds'] == 13
    assert report['stages_seconds'] == {'preparation': 0, 'prices': 5, 'news': 3, 'articles': 3, 'assembly': 2}
    assert report['stage_unattributed_seconds'] == 0
    assert report['output_sha256'] == p.report_hash('same output')
    assert report['generation_path'] == 'normal'
    assert data == {'judgment': '유지', 'score': 4}


def test_worker_inherits_counter_but_cannot_change_main_stage():
    state = {}

    @p.report_phase('articles')
    def worker():
        p.report_http_attempt('economic_api')
        return 'unchanged'

    with p.generation_measurement(state):
        p.set_report_stage('macro_official')
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [submit_with_context(pool, worker) for _ in range(3)]
            assert [f.result() for f in futures] == ['unchanged'] * 3
        state['today_market_memo_text'] = 'done'
    report = state['auto_report_performance']
    assert 'articles' not in report['stages_seconds']
    assert report['transport_events']['report_http.macro_official.economic_api.attempt'] == 3
    assert sum(report['stages_seconds'].values()) <= report['elapsed_seconds'] + 0.00001


@pytest.mark.parametrize('error', [RuntimeError('private-secret'), KeyboardInterrupt('private-secret')])
def test_failure_or_rerun_preserves_previous_complete_and_parent_trace(error):
    prior = {'measurement_id': 'previous'}
    state = {'auto_report_performance': prior, 'today_market_memo_text': 'previous output'}
    with PerformanceTrace() as parent:
        with pytest.raises(type(error)):
            with p.generation_measurement(state):
                count_event('inner')
                raise error
        count_event('parent')
    report = state['auto_report_last_attempt']
    assert state['auto_report_performance'] is prior
    assert report['output_sha256'] is None
    assert 'private-secret' not in json.dumps(report)
    assert parent.report()['transport_events'] == {'parent': 1}
    assert report['transport_events'] == {'inner': 1}
    assert p._run.get() is None


def test_fallback_is_completed_but_identified_and_no_clear_claim():
    state = {}
    with p.generation_measurement(state):
        p.report_degraded('report_context_unavailable')
        state['today_market_memo_text'] = 'fallback output'
    report = state['auto_report_performance']
    assert report['measurement_status'] == 'completed'
    assert report['generation_path'] == 'fallback'
    assert report['degraded_reasons'] == ['report_context_unavailable']
    assert report['cache_state'] == {'policy': 'unchanged_no_clear', 'initial_warmth': 'unknown'}
    assert 'download_call is not a remote-request count' in report['request_count_coverage']


def test_mismatched_or_absent_report_does_not_render_old_measurement():
    class NoUI:
        def __getattr__(self, name):
            raise AssertionError('stale measurement shown')
    p.render_generation_timing(NoUI(), {}, 'new')
    p.render_generation_timing(NoUI(), {'auto_report_performance': {'output_sha256': p.report_hash('old')}}, 'new')


def test_no_measurement_is_noop_and_return_identity_preserved():
    p.set_report_stage('prices')
    p.report_http_attempt('economic_api')
    p.report_degraded('unused')
    value = {'score': 4}
    assert p.report_phase('news')(lambda: value)() is value


def test_app_diff_contains_only_reviewed_measurement_not_decision_or_report_changes():
    import ast
    from pathlib import Path
    import subprocess
    from tests.report_timing_ast_contract import before_report_timing
    root = Path(__file__).resolve().parents[1]
    base = subprocess.check_output(['git', 'show', 'e56b95e0:app.py'], cwd=root, encoding='utf-8-sig')
    current = (root / 'app.py').read_text(encoding='utf-8-sig')
    def functions(source):
        return {n.name: ast.dump(before_report_timing(n)) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    assert functions(base) == functions(current)


@pytest.mark.parametrize('mutation', ['call_side_effect', 'import_alias', 'with_binding', 'with_argument', 'duplicate_context'])
def test_ast_normalization_rejects_hidden_semantic_mutations(mutation):
    import ast
    from pathlib import Path
    from tests.report_timing_ast_contract import before_report_timing
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8-sig')
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'render_today_market_memo_panel')
    for n in ast.walk(node):
        if mutation == 'duplicate_context' and isinstance(n, ast.With) and any(isinstance(item.context_expr, ast.Call) and ast.unparse(item.context_expr.func) == 'generation_measurement' for item in n.items):
            n.items.append(ast.withitem(context_expr=ast.parse('generation_measurement(st.session_state.clear())', mode='eval').body))
            break
        if mutation == 'call_side_effect' and isinstance(n, ast.Call) and ast.unparse(n.func) == 'set_report_stage':
            n.args[0] = ast.parse("(st.session_state.clear(), 'flow_snapshot')[1]", mode='eval').body
            break
        if mutation == 'import_alias' and isinstance(n, ast.ImportFrom) and n.module == 'stock_lab_core.report_generation_performance':
            n.names[0].asname = 'build_auto_market_memo'
            break
        if mutation.startswith('with_') and isinstance(n, ast.withitem) and isinstance(n.context_expr, ast.Call) and ast.unparse(n.context_expr.func) == 'generation_measurement':
            if mutation == 'with_binding':
                n.optional_vars = ast.Name(id='memo_summary_df', ctx=ast.Store())
            else:
                n.context_expr.args[0] = ast.parse('st.session_state.clear()', mode='eval').body
            break
    with pytest.raises(AssertionError):
        before_report_timing(node)
