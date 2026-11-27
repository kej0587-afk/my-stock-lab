"""Fixed worker inputs reused by timing and quote-scope contracts; no live data."""
from copy import deepcopy
import json
from pathlib import Path

import pandas as pd

from stock_lab_core import decision_engine
from stock_lab_core.signal_basis import build_signal_basis
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import _bench_info, _to_jsonable


def prepare_worker(app, monkeypatch, case):
    sid, px, _, _, kwargs, live_gap = case
    frame, long = make_price_df(**px), make_price_df(days=600)
    originals = frame.copy(deep=True), long.copy(deep=True)
    frozen = json.loads((Path(__file__).parent / 'golden/decision_refactor_full_snapshots.json')
                        .read_text(encoding='utf-8'))[sid]
    live = float(frame.Close.iloc[-1]) * (1 + live_gap) if live_gap else 0.

    def forbidden(*a, **kw):
        raise AssertionError('Unexpected provider request')

    replacements = {
        'holdings_table': pd.DataFrame(), 'lookup_yfinance_display_name': lambda ticker: 'Synthetic company',
        'load_price_df': forbidden, 'load_latest_price': forbidden, 'load_display_live_price': lambda _: live,
        'load_fin_score_meta_fast': lambda *a: (kwargs['fin_score'], {}),
        'get_my_price': lambda *a: kwargs['my_price'], 'has_position': lambda *a: kwargs['has_pos'],
        'calc_scores_and_decision': lambda **k: deepcopy(frozen),
        'apply_leveraged_dca_dashboard_override': lambda value: value,
        'apply_leveraged_precision_decision_override': lambda value, *a: value,
        'get_auto_benchmark_info': lambda *a: _bench_info(), '_today_flow_candidate_status': lambda *a: '미등록',
        'build_signal_basis': lambda f, c, **kw: build_signal_basis(
            f, c, calculated_at='fixed', ticker=kwargs['ticker'], input_price=live),
    }
    for key, value in replacements.items():
        monkeypatch.setattr(app, key, value)
    monkeypatch.setattr(decision_engine, '_get_live_price_row_date', lambda _: frame.index[-1])
    item = {k: kwargs[k] for k in ('ticker', 'name', 'is_etf', 'asset_class')}
    args = (item, kwargs['app_mode'], kwargs['_macro_penalty'], kwargs['_final_macro_risk'],
            kwargs['_total_eval'], kwargs['_cash_available'], kwargs['_reserve_available'])

    def run(worker):
        result = worker(*args, _price_df=frame, _long_price_df=long)
        assert result['f_score'] is not None
        for current, saved in zip((frame, long), originals):
            pd.testing.assert_frame_equal(current, saved, check_exact=True)
        return json.loads(json.dumps(_to_jsonable(result), sort_keys=True, default=str, allow_nan=False))
    return run
