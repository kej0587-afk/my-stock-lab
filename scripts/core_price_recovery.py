"""Offline, single-empty-frame repair for a trusted private research snapshot.

No download, operational ticker alias, gate change, or candidate renaming.
Provider identity evidence and retrieval metadata belong in the private output.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def assert_only_target_changed(base, recovered, target):
    assert base.keys() == recovered.keys()
    assert base['frames'].keys() == recovered['frames'].keys()
    for key in base:
        if key == 'frames':
            for ticker, frame in base[key].items():
                if ticker != target:
                    pd.testing.assert_frame_equal(frame, recovered[key][ticker], check_exact=True)
                    assert frame.attrs == recovered[key][ticker].attrs
        elif key == 'sessions':
            assert base[key].keys() == recovered[key].keys()
            for region, sessions in base[key].items():
                pd.testing.assert_index_equal(sessions, recovered[key][region], exact=True)
        else:
            assert base[key] == recovered[key], f'Changed fixed metadata: {key}'


def recover_empty_frame(snapshot, target, provider_symbol, price):
    """Retain the research identity; correct only its proven provider price path."""
    if target not in snapshot['kinds'] or target not in snapshot['frames']:
        raise ValueError('Require an existing candidate frame')
    if target in snapshot['flow_tickers']:
        raise ValueError('This bounded recovery cannot change flow inputs')
    from scripts.sim_core_first_buy import BENCH
    if target in {ticker for ticker, _ in BENCH}:
        raise ValueError('This bounded recovery cannot change benchmark inputs')
    if not (target.endswith('.KS') and provider_symbol == target[:-3] + '.KQ'):
        raise ValueError('Require an explicitly verified same-code KOSDAQ correction')
    old = snapshot['frames'][target]
    if old.Close.notna().any():
        raise ValueError('Cannot replace a frame with existing Close observations')
    if not isinstance(price, pd.DataFrame) or price.empty or not price.columns.equals(old.columns):
        raise ValueError('Require nonempty prices with the original OHLCV schema')
    index = price.index
    if (not isinstance(index, pd.DatetimeIndex) or index.tz is not None
            or not index.is_unique or not index.is_monotonic_increasing
            or not index.equals(index.normalize())):
        raise ValueError('Require unique ordered naive daily dates')
    source = snapshot['source']
    if source['auto_adjust'] is not False:
        raise ValueError('Preserve the existing unadjusted OHLC contract')
    if (index.min() < pd.Timestamp(source['start'])
            or index.max() >= pd.Timestamp(source['end_exclusive'])
            or index.max() > pd.Timestamp(snapshot['cutoff'])):
        raise ValueError('Prices exceed the frozen study interval')
    observed = price.loc[price.Close.notna(), ['Open', 'High', 'Low', 'Close']]
    if len(observed) < 120 or not np.isfinite(observed.to_numpy()).all() or (observed <= 0).any().any():
        raise ValueError('Require 120 valid positive OHLC observations')
    # Preserve provider values, including range anomalies. The existing study
    # has no OHLC-range exclusion rule; adding one here would change the cohort.
    recovered = deepcopy(snapshot)
    recovered['frames'][target] = price.copy(deep=True)
    assert_only_target_changed(snapshot, recovered, target)
    return recovered


def compare_recovery(base, recovered, target):
    from scripts.core_gate_event_comparison import run_study
    from scripts.core_full_universe import selection_summary

    assert_only_target_changed(base, recovered, target)
    summaries, details, gates = {}, {}, {}
    for label, snapshot in (('before_recovery', base), ('after_recovery', recovered)):
        summary, details[label], gates[label] = run_study(snapshot)
        summary.pop('source', None)  # no provenance/identifiers in anonymous aggregates
        summary['selection'] = selection_summary(snapshot, details[label], snapshot['original_candidates'])
        summaries[label] = summary
    unchanged_events = {}
    for version in ('before', 'after'):
        for region in ('KR', 'US'):
            pd.testing.assert_frame_equal(gates['before_recovery'][version][region],
                                          gates['after_recovery'][version][region], check_exact=True)
        old = [r for r in details['before_recovery'][version] if r['ticker'] != target]
        new = [r for r in details['after_recovery'][version] if r['ticker'] != target]
        pd.testing.assert_frame_equal(pd.DataFrame(old), pd.DataFrame(new), check_exact=True)
        unchanged_events[version] = len(old)
    summaries['invariants'] = {
        'frame_count': len(base['frames']), 'unchanged_other_frames': len(base['frames']) - 1,
        'all_metadata_and_sessions_identical': True, 'all_four_gate_frames_identical': True,
        'unchanged_other_event_rows_all_costs': unchanged_events,
        'old_target_valid_close': int(base['frames'][target].Close.notna().sum()),
        'recovered_target_valid_close': int(recovered['frames'][target].Close.notna().sum()),
    }
    price = recovered['frames'][target]
    summaries['invariants']['provider_ohlc_range_anomalies_preserved'] = int((
        (price.High < price[['Open', 'Low', 'Close']].max(axis=1))
        | (price.Low > price[['Open', 'High', 'Close']].min(axis=1))).sum())
    return summaries, details, gates


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('prices', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--target', required=True)
    parser.add_argument('--provider-symbol', required=True)
    args = parser.parse_args()
    # Private data is restricted to this repository's ignored cache tree.
    cache = (Path(__file__).resolve().parents[1] / 'cache').resolve()
    for path in (args.snapshot, args.prices, args.out):
        if not path.resolve().is_relative_to(cache):
            raise ValueError('All private input/output paths must stay under repository cache')
    input_hash = hashlib.sha256(args.snapshot.read_bytes()).hexdigest()
    base = pd.read_pickle(args.snapshot)  # trusted, locally produced artifacts only
    repaired = recover_empty_frame(base, args.target, args.provider_symbol, pd.read_pickle(args.prices))
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / 'snapshot.pkl'
    if out_path.resolve() == args.snapshot.resolve():
        raise ValueError('Never overwrite the source snapshot')
    pd.to_pickle(repaired, out_path)
    assert_only_target_changed(base, pd.read_pickle(out_path), args.target)
    summaries, details, gates = compare_recovery(base, repaired, args.target)
    assert hashlib.sha256(args.snapshot.read_bytes()).hexdigest() == input_hash
    summaries['invariants'].update(source_snapshot_sha256=input_hash,
        recovered_snapshot_sha256=hashlib.sha256(out_path.read_bytes()).hexdigest())
    for label in details:
        for version, rows in details[label].items():
            pd.DataFrame(rows).to_csv(args.out / f'{label}_{version}_events.csv', index=False, encoding='utf-8-sig')
            for region, frame in gates[label][version].items():
                frame.to_csv(args.out / f'{label}_{version}_gate_{region}.csv')
    (args.out / 'anonymous_comparison.json').write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'invariants': summaries['invariants'], **{
        label: summaries[label]['selection']['after']['full']
        for label in ('before_recovery', 'after_recovery')}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
