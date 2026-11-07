"""Offline profile of summary glue using existing seeded decision fixtures.

No app/rule edits. Upstream decision/indicator/provider results are fixed, so
this measures the residual worker path, not full Today Check or its I/O waits.
Run: .venv311/Scripts/python.exe scripts/profile_summary_local.py --repeat 3
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import cProfile
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import pstats
import statistics
import sys
from time import perf_counter, thread_time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['STOCK_LAB_FORCE_AUTH_MODE'] = 'public_demo'


def profile(repeat=3, workers=1):
    import pandas as pd
    from tests.fixtures_price import make_price_df
    from tests.test_decision_refactor_parity import scenarios
    from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable
    from stock_lab_core.signal_basis import build_signal_basis
    from stock_lab_core import prices

    network_attempts = []
    def forbidden(*args, **kwargs):
        import traceback
        network_attempts.append([(Path(f.filename).name, f.name) for f in traceback.extract_stack(limit=12)])
        raise AssertionError('Network disabled in fixed-input profile')

    with ExitStack() as stack:
        # Public-demo initialization is outside timings; block its network too.
        for target in ('socket.socket.connect', 'socket.create_connection',
                       'requests.sessions.Session.request', 'urllib.request.urlopen'):
            stack.enter_context(patch(target, forbidden))
        try:
            import curl_cffi.requests
            stack.enter_context(patch.object(curl_cffi.requests.Session, 'request', forbidden))
        except ImportError:
            pass
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            import app
        initialization_attempts = len(network_attempts)
        frozen = json.loads((ROOT / 'tests/golden/decision_refactor_full_snapshots.json').read_text(encoding='utf-8'))
        cases = []
        for sid, px, _, _, kwargs, _ in scenarios():
            frame = make_price_df(**px)
            item = dict(ticker=kwargs['ticker'], name=kwargs['name'],
                        is_etf=kwargs['is_etf'], asset_class=kwargs['asset_class'])
            cases.append((sid, item, frame, kwargs))
        originals = [frame.copy(deep=True) for _, _, frame, _ in cases]
        # Thread-local inputs allow a fixed four-worker replay without mutable
        # global per-symbol fixtures (some scenarios intentionally reuse tickers).
        from contextvars import ContextVar
        current = ContextVar('summary_profile_case')
        def selected(): return current.get()
        def decision(**kwargs): return deepcopy(frozen[selected()[0]])
        replacements = {
            'holdings_table': pd.DataFrame(),
            'lookup_yfinance_display_name': lambda ticker: 'Synthetic company',
            'load_price_df': forbidden, 'load_latest_price': forbidden,
            'load_display_live_price': lambda _: 0.,
            'build_indicators': lambda frame: frame.copy(deep=True),
            'apply_live_price_with_indicators': lambda frame, *args: (frame.copy(deep=True), False, ''),
            'load_fin_score_meta_fast': lambda *args: (selected()[3]['fin_score'], {}),
            'get_my_price': lambda *args: selected()[3]['my_price'],
            'has_position': lambda *args: selected()[3]['has_pos'],
            'calc_scores_and_decision': decision,
            'build_precision_multi_timeframe_pack': lambda *a, **k: {},
            'apply_precision_mtf_decision_guard': lambda value, *a, **k: value,
            'apply_leveraged_dca_dashboard_override': lambda value: value,
            'apply_leveraged_precision_decision_override': lambda value, *a: value,
            'get_auto_benchmark_info': lambda *args: _bench_info(),
            '_today_flow_candidate_status': lambda *args: '미등록',
            'build_signal_basis': lambda frame, context: build_signal_basis(frame, context, calculated_at='fixed-profile'),
        }
        for name, value in replacements.items():
            stack.enter_context(patch.object(app, name, value))
        for name in ('load_price_df', 'load_latest_price', 'load_price_frames_batch'):
            stack.enter_context(patch.object(prices, name, forbidden))

        def run(case):
            sid, item, frame, kwargs = case
            token = current.set(case)
            try:
                result = app._compute_summary_item(
                    item, kwargs['app_mode'], kwargs['_macro_penalty'], kwargs['_final_macro_risk'],
                    kwargs['_total_eval'], kwargs['_cash_available'], kwargs['_reserve_available'],
                    _price_df=frame, _long_price_df=frame)
                assert result and result['f_score'] is not None, 'Worker returned error row'
                return result
            finally:
                current.reset(token)

        def serialize(result):
            return json.dumps(_to_jsonable(result), sort_keys=True, default=str, allow_nan=False)

        baseline = [serialize(run(case)) for case in cases]
        timing = ContextVar('summary_profile_timing', default=None)
        stages = {
            'sanitize_asset_name': 'name_normalization',
            'build_source_flow_context': 'source_flow',
            'detect_chart_pattern_candidates': 'pattern_detection',
            'summarize_chart_pattern_for_dashboard': 'pattern_summary',
            'build_decision_workflow': 'workflow',
            'build_sideways_quality_state': 'sideways',
            'build_signal_basis': 'signal_basis',
            'calc_series_mdd': 'mdd',
        }
        def timed(fn, label):
            def wrapped(*args, **kwargs):
                wall, cpu = perf_counter(), thread_time()
                try: return fn(*args, **kwargs)
                finally:
                    bucket = timing.get()
                    if bucket is not None:
                        bucket[label][0] += perf_counter() - wall
                        bucket[label][1] += thread_time() - cpu
                        bucket[label][2] += 1
            return wrapped
        for name, label in stages.items():
            stack.enter_context(patch.object(app, name, timed(getattr(app, name), label)))

        def measured(case):
            bucket = defaultdict(lambda: [0., 0., 0])
            token = timing.set(bucket)
            wall, cpu = perf_counter(), thread_time()
            try: result = run(case)
            finally:
                wall, cpu = perf_counter()-wall, thread_time()-cpu
                timing.reset(token)
            bucket['other_glue'] = [wall-sum(v[0] for v in bucket.values()),
                                    cpu-sum(v[1] for v in bucket.values()), 1]
            return serialize(result), dict(bucket)

        samples, totals = [], defaultdict(lambda: [0., 0., 0])
        for _ in range(repeat):
            start = perf_counter()
            if workers == 1:
                results = [measured(case) for case in cases]
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(measured, cases))
            samples.append(perf_counter()-start)
            assert [r[0] for r in results] == baseline, 'Full row changed under profiling'
            for _, bucket in results:
                for label, values in bucket.items():
                    for i in range(3): totals[label][i] += values[i]

        profiler = cProfile.Profile()
        profiler.enable()
        profiled = [serialize(run(case)) for case in cases]
        profiler.disable()
        assert profiled == baseline
        for (_, _, frame, _), original in zip(cases, originals):
            pd.testing.assert_frame_equal(frame, original, check_exact=True)
            assert frame.attrs == original.attrs
        assert len(network_attempts) == initialization_attempts, (
            'Unexpected replay network path: ' + str(network_attempts[initialization_attempts:initialization_attempts+1]))
        stats = pstats.Stats(profiler)
        top = []
        for (filename, line, name), (cc, nc, tt, ct, _) in stats.stats.items():
            path = Path(filename)
            if 'stock_lab_core' in filename or path.name == 'app.py':
                top.append(dict(file=path.name, line=line, function=name, calls=nc,
                                self_seconds=tt, cumulative_seconds=ct))
        return dict(scope='fixed upstream outputs; residual summary path only',
                    cases=len(cases), repeat=repeat, workers=workers,
                    batch_wall_seconds=samples, median_batch_seconds=statistics.median(samples),
                    stage_totals={k:dict(wall_sum=v[0], thread_cpu_sum=v[1], calls=v[2]) for k,v in totals.items()},
                    profile_top=sorted(top, key=lambda v:v['cumulative_seconds'], reverse=True)[:20],
                    outputs_exact=True, frames_unchanged=True, replay_network_attempts=0,
                    initialization_network_attempts_blocked=initialization_attempts,
                    output_sha256=hashlib.sha256(''.join(baseline).encode()).hexdigest(),
                    app_sha256=hashlib.sha256((ROOT/'app.py').read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--workers', type=int, choices=[1, 4], default=1)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1: parser.error('repeat must be positive')
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        report = profile(args.repeat, args.workers)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['cases','workers','median_batch_seconds','outputs_exact','replay_network_attempts']}, ensure_ascii=False))
