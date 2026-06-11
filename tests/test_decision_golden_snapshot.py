"""Golden-snapshot regression tests for `calc_scores_and_decision` (app.py).

Purpose
-------
`calc_scores_and_decision` (app.py, ~1160 lines) is about to be decomposed
into a guard -> policy -> signal -> sizing pipeline. Before touching it, we
freeze its current behaviour for a representative set of deterministic
scenarios so any future refactor can be diffed against this baseline.

How it works
------------
- Synthetic, seeded OHLCV price data (tests/fixtures_price.py) gives fully
  reproducible technical indicators.
- Network-dependent helpers (`get_rs_score`, `get_rs_slope`,
  `get_auto_benchmark_info`) are monkeypatched to fixed values so the test
  runs offline and deterministically.
- The function's output dict is reduced to the fields that matter for the
  decision-tree decomposition (decision code/label/color/group/reasons,
  safety/macro state, sizing hint, grade, key scores) and compared against
  a committed JSON snapshot (tests/golden/decision_snapshots.json).

Updating the snapshot
----------------------
If a change is *intentional*, regenerate with:

    UPDATE_SNAPSHOTS=1 pytest tests/test_decision_golden_snapshot.py

then review the diff in tests/golden/decision_snapshots.json carefully —
every changed field should be explainable by the change you just made.
"""
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures_price import make_price_df


def _to_jsonable(value):
    """Recursively convert numpy/pandas scalars to plain JSON-safe types."""
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value

SNAPSHOT_PATH = Path(__file__).parent / "golden" / "decision_snapshots.json"

# Fields captured in the snapshot. Keep this list focused on what the
# guard/policy/signal/sizing decomposition must preserve.
SNAPSHOT_FIELDS = [
    "dec", "col", "decision_code", "decision_group", "decision_reasons",
    "grade", "t_score", "tech_total", "main_s", "adj",
    "safety_state", "macro_state",
    "dd", "rr_ratio", "sizing_hint",
    "buy_amt", "core_dca_rate", "core_dca_label",
    "structure_risk", "live_gap_shock", "is_52w_breakout",
    "profit_take_signal",
]


def _bench_info(sector_bench=""):
    return {
        "market_bench": "QQQM",
        "sector_bench": sector_bench,
        "sector_label": "-",
        "underlying_bench": "",
        "underlying_asset": "-",
        "sector_rs_label": "-",
    }


# Each scenario: (id, price_df kwargs, rs_score, rs_slope, calc kwargs)
SCENARIOS = [
    (
        "free_stock_uptrend_new_entry",
        dict(daily_drift=0.0015, daily_vol=0.012, seed=1),
        (2, "🚀강함"),
        (5.0, "📈RS상승중", 1),
        dict(
            name="테스트우상향주", ticker="TST1.KS", is_etf=False, asset_class="kr_stock",
            my_price=0.0, has_pos=False, fin_score=4, is_free=True,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=0.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "free_stock_downtrend_no_entry",
        dict(daily_drift=-0.0015, daily_vol=0.012, seed=2),
        (0, "🐢약함"),
        (-5.0, "📉RS하락중", -1),
        dict(
            name="테스트하락주", ticker="TST2.KS", is_etf=False, asset_class="kr_stock",
            my_price=0.0, has_pos=False, fin_score=2, is_free=True,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=0.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "portfolio_stock_financial_f_hard_block",
        dict(daily_drift=0.0002, daily_vol=0.01, seed=3),
        (1, "➖보통"),
        (0.0, "➡️RS횡보", 0),
        dict(
            name="재무F종목", ticker="TST3.KS", is_etf=False, asset_class="kr_stock",
            my_price=100.0, has_pos=True, fin_score=1, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "portfolio_stock_overweight_hard_block",
        dict(daily_drift=0.0005, daily_vol=0.01, seed=4),
        (1, "➖보통"),
        (0.0, "➡️RS횡보", 0),
        dict(
            name="비중초과종목", ticker="TST4.KS", is_etf=False, asset_class="kr_stock",
            my_price=100.0, has_pos=True, fin_score=4, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=15.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "core_us_etf_perfect_storm_dca",
        dict(daily_drift=0.0005, daily_vol=0.012, seed=5),
        (1, "➖보통"),
        (0.0, "➡️RS횡보", 0),
        dict(
            name="나스닥100", ticker="QQQM", is_etf=True, asset_class="us_etf_nasdaq",
            my_price=0.0, has_pos=True, fin_score=0, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=20.0,
            _macro_penalty=0.0, _final_macro_risk=5.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "core_kr_etf_crash_dca",
        dict(daily_drift=0.0005, daily_vol=0.012, seed=6, tail_shock=-0.40, tail_shock_days=15),
        (1, "➖보통"),
        (0.0, "➡️RS횡보", 0),
        dict(
            name="코덱스200", ticker="069500.KS", is_etf=True, asset_class="kr_etf",
            my_price=0.0, has_pos=True, fin_score=0, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=20.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "leveraged_etf_dca_blocked",
        dict(daily_drift=0.0005, daily_vol=0.02, seed=7, tail_shock=-0.40, tail_shock_days=15),
        (1, "➖보통"),
        (0.0, "➡️RS횡보", 0),
        dict(
            name="TQQQ", ticker="TQQQ", is_etf=True, asset_class="us_etf_nasdaq",
            my_price=0.0, has_pos=True, fin_score=0, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=20.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "position_profit_take_review",
        dict(daily_drift=0.004, daily_vol=0.015, seed=8),
        (2, "🚀강함"),
        (5.0, "📈RS상승중", 1),
        dict(
            name="과열보유종목", ticker="TST5.KS", is_etf=False, asset_class="kr_stock",
            my_price=70.0, has_pos=True, fin_score=4, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "position_structure_damage_check",
        dict(daily_drift=0.0008, daily_vol=0.012, seed=9, tail_shock=-0.25, tail_shock_days=10),
        (0, "🐢약함"),
        (-5.0, "📉RS하락중", -1),
        dict(
            name="구조훼손종목", ticker="TST6.KS", is_etf=False, asset_class="kr_stock",
            my_price=100.0, has_pos=True, fin_score=3, is_free=False,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=5.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "free_stock_new_entry_leader",
        dict(daily_drift=0.0020, daily_vol=0.012, seed=2),
        (2, "🚀강함"),
        (5.0, "📈RS상승중", 1),
        dict(
            name="대장주후보", ticker="TST8.KS", is_etf=False, asset_class="kr_stock",
            my_price=0.0, has_pos=False, fin_score=4, is_free=True,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=0.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        "free_stock_s_pullback_entry",
        dict(daily_drift=0.0013, daily_vol=0.012, seed=6),
        (2, "🚀강함"),
        (5.0, "📈RS상승중", 1),
        dict(
            name="S급눌림목", ticker="TST9.KS", is_etf=False, asset_class="kr_stock",
            my_price=0.0, has_pos=False, fin_score=4, is_free=True,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=0.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
    (
        # NB: with this seed the price path lands in a deep (~-54%) drawdown,
        # so this currently exercises CRISIS_PANIC_SELL_OFF rather than the
        # SAFETY_RED_NO_NEW_ENTRY override. Kept as-is (frozen baseline);
        # a dedicated SAFETY_RED scenario can be added separately once the
        # guard/signal stages are decomposed and easier to drive directly.
        "free_low_safety_score_downtrend",
        dict(daily_drift=-0.0005, daily_vol=0.012, seed=10),
        (0, "🐢약함"),
        (-3.0, "📉RS하락중", -1),
        dict(
            name="안전레드종목", ticker="TST7.KS", is_etf=False, asset_class="kr_stock",
            my_price=0.0, has_pos=False, fin_score=2, is_free=True,
            app_mode="자유모드", user_total_asset=10_000_000, user_curr_w=0.0, user_targ_w=10.0,
            _macro_penalty=0.0, _final_macro_risk=1.0, _total_eval=10_000_000,
            _cash_available=0.0, _reserve_available=0.0,
        ),
    ),
]


def _run_scenario(app_module, monkeypatch, price_kwargs, rs_score, rs_slope, calc_kwargs):
    df = make_price_df(**price_kwargs)

    monkeypatch.setattr(app_module, "get_rs_score", lambda ticker, asset_class: rs_score)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda ticker, asset_class: rs_slope)
    monkeypatch.setattr(
        app_module, "get_auto_benchmark_info",
        lambda ticker, name, asset_class, is_etf: _bench_info(),
    )

    result = app_module.calc_scores_and_decision(df=df, **calc_kwargs)
    return {field: _to_jsonable(result.get(field)) for field in SNAPSHOT_FIELDS}


def _load_snapshots():
    if not SNAPSHOT_PATH.exists():
        return {}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _save_snapshots(data):
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "scenario_id, price_kwargs, rs_score, rs_slope, calc_kwargs",
    SCENARIOS,
    ids=[s[0] for s in SCENARIOS],
)
def test_decision_golden_snapshot(
    app_module, monkeypatch, scenario_id, price_kwargs, rs_score, rs_slope, calc_kwargs,
):
    actual = _run_scenario(app_module, monkeypatch, price_kwargs, rs_score, rs_slope, calc_kwargs)
    snapshots = _load_snapshots()

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshots[scenario_id] = actual
        _save_snapshots(snapshots)
        pytest.skip(f"Snapshot updated for '{scenario_id}' (UPDATE_SNAPSHOTS=1)")

    assert scenario_id in snapshots, (
        f"No golden snapshot for '{scenario_id}'. "
        f"Run with UPDATE_SNAPSHOTS=1 to create it, then review the diff."
    )
    assert actual == snapshots[scenario_id]
