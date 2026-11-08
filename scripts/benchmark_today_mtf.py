"""Offline A/B of Today MTF preparation, not full Cloud/price I/O timing."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import logging
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['STOCK_LAB_FORCE_AUTH_MODE'] = 'public_demo'


def benchmark():
    import pandas as pd
    from tests.fixtures_price import make_price_df
    from tests.test_today_mtf_snapshot import stable
    attempts = []
    def forbidden(*a, **k):
        attempts.append(True)
        raise AssertionError('Network disabled')
    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.create_connection',
                       'requests.sessions.Session.request', 'urllib.request.urlopen',
                       'curl_cffi.requests.Session.request'):
            stack.enter_context(patch(target, forbidden))
        import app
        stack.enter_context(patch.object(app, 'load_price_df', forbidden))
        initialized = len(attempts)
        inputs = []
        for seed in range(20):
            frame = make_price_df(days=2600, seed=seed)
            frame['Volume'] = frame.Volume.astype('int64')
            daily = app.build_indicators(frame.tail(260))
            inputs.append((daily, frame))
        saved = [(d.copy(deep=True), f.copy(deep=True)) for d, f in inputs]
        decision = dict(decision_code='S_PULLBACK_ENTRY', dec='fixture', fin_score=4)
        samples = {}
        reference = None
        for workers in (1, 6):
            modes = {'before': [], 'after': []}
            for repeat in range(3):
                for mode in (('before', 'after') if repeat % 2 == 0 else ('after', 'before')):
                    def run(pair):
                        daily, long = pair
                        pack = app.build_precision_multi_timeframe_pack('FIXTURE', daily,
                            _long_price_df=long, _include_daily_snapshot=mode == 'before')
                        return pack, app.apply_precision_mtf_decision_guard(decision, pack)
                    start = perf_counter()
                    if workers == 1:
                        results = list(map(run, inputs))
                    else:
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            results = list(pool.map(run, inputs))
                    modes[mode].append(perf_counter() - start)
                    if reference is None:
                        reference = results
                    for (pack, guarded), (old, old_guard) in zip(results, reference):
                        assert stable(guarded) == stable(old_guard)
                        for label in ('일봉', '주봉', '월봉'):
                            pd.testing.assert_frame_equal(pack[label]['df'], old[label]['df'], check_exact=True)
                            if label != '일봉':
                                assert stable(pack[label]['snapshot']) == stable(old[label]['snapshot'])
            samples[str(workers)] = {'samples': modes, 'median_seconds': {k: median(v) for k, v in modes.items()}}
        for (daily, long), (old_daily, old_long) in zip(inputs, saved):
            pd.testing.assert_frame_equal(daily, old_daily, check_exact=True)
            pd.testing.assert_frame_equal(long, old_long, check_exact=True)
        assert len(attempts) == initialized
        return dict(scope='20 fixed MTF packs, source I/O excluded', samples=samples,
                    frames_and_guarded_decisions_exact=True, replay_network_attempts=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        result = benchmark()
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
