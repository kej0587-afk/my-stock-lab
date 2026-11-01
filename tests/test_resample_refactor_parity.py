"""Exact, offline resampling parity against the fixed pre-refactor commit."""

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "9ced3c66"
FUNCTION = "resample_ohlcv_timeframe"
RULES = ("W-FRI", "W", "M", "m", "ME", "me", pd.offsets.MonthEnd(),
         pd.offsets.MonthEnd(2), pd.offsets.MonthEnd(0))


def compile_resampler(source, label):
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == FUNCTION)
    namespace = {"np": np, "pd": pd}
    exec(compile(ast.Module(body=[node], type_ignores=[]), label, "exec"), namespace)
    return namespace[FUNCTION]


@lru_cache(maxsize=1)
def implementations():
    baseline = subprocess.check_output(
        ["git", "show", f"{BASELINE}:app.py"], cwd=ROOT, encoding="utf-8")
    current = (ROOT / "app.py").read_text(encoding="utf-8-sig")
    return (compile_resampler(baseline, f"{BASELINE}:app.py"),
            compile_resampler(current, str(ROOT / "app.py")))


def make_frame(volume=None, *, index=None):
    if volume is None:
        volume = np.array([0., np.nan, 100., 200., np.nan, 0., -25., 400.])
    if index is None:
        index = pd.DatetimeIndex([
            "2024-02-02", "2024-01-02", "2024-01-02", "2024-03-31",
            "2024-02-29", "2024-01-05", "2024-01-31", "2024-03-01",
        ], name="Trading Date")
    close = np.arange(len(index), dtype=float) + 100
    frame = pd.DataFrame({"Close": close, "Volume": volume, "Low": close - 2,
                          "Open": close - 1, "High": close + 2, "Ignored": "extra"},
                         index=index)
    frame.columns.name = "Price Fields"
    frame.attrs = {"source": "synthetic", "metadata": {"markers": ["unchanged"]}}
    return frame


def assert_exact_frame(actual, expected):
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert actual.attrs == expected.attrs
    # assert_frame_equal treats -0.0 as equal to +0.0; retain bitwise coverage too.
    for position, dtype in enumerate(expected.dtypes):
        if isinstance(dtype, np.dtype) and dtype.kind in "fc":
            np.testing.assert_array_equal(
                actual.iloc[:, position].to_numpy().view(np.uint8),
                expected.iloc[:, position].to_numpy().view(np.uint8))


def assert_parity(frame, rule):
    before = deepcopy(frame)
    old, new = implementations()
    outcomes = []
    for function in (old, new):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            try:
                outcomes.append((function(frame, rule), None))
            except Exception as exc:
                outcomes.append((None, exc))
        if isinstance(frame, pd.DataFrame):
            assert_exact_frame(frame, before)
    expected, error = outcomes[0]
    actual, actual_error = outcomes[1]
    if error is not None:
        assert type(actual_error) is type(error)
        assert str(actual_error) == str(error)
    else:
        assert actual_error is None, repr(actual_error)
        assert_exact_frame(actual, expected)
    return actual


# These AST-only tests do not use the provider caches in tests/conftest.py.
@pytest.fixture(autouse=True)
def isolate_yahoo_metadata_cache():
    yield


@pytest.fixture(autouse=True)
def isolate_public_economic_disk_cache():
    yield


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("zone", (None, "Asia/Seoul", "America/New_York"))
def test_aliases_offsets_timezones_duplicates_and_metadata(rule, zone):
    frame = make_frame()
    if zone:
        frame.index = frame.index.tz_localize(zone)
    assert_parity(frame, rule)


VOLUME_CASES = [
    ("zero", np.zeros(8, dtype="int64")),
    ("all_nan", np.full(8, np.nan)),
    ("missing_integral", np.array([np.nan, 0., 200., np.nan, 30., -10., np.nan, 0.])),
    ("signed_zero", np.array([-0., -0., 0., -0., 0., 0., -0., -0.])),
    ("exact_limit", np.array([2 ** 53, 0, 0, 0, 0, 0, 0, 0], dtype="int64")),
    ("small_integer_overflow", np.array([127, 127, 127, 127, 127, 127, 127, 127], dtype="int8")),
    ("fractions", np.array([0.1, 0.2, 0.3, 0.4, 1.25, 2.5, -0.5, np.nan])),
    ("float_roundoff", np.array([1e16, 1., -1e16, 0., np.nan, 0., 0., 0.])),
    ("int_overflow", np.array([np.iinfo("int64").max] * 8)),
    ("int_min", np.array([np.iinfo("int64").min] + [0] * 7)),
    ("uint_extreme", np.array([np.iinfo("uint64").max] + [1] * 7, dtype="uint64")),
    ("infinity", np.array([np.inf, 1., -np.inf, 2., np.nan, 0., 3., 4.])),
    ("bool", np.array([True, False, True, False, False, True, False, True])),
    ("nullable_int", pd.array([1, None, 2, 0, -1, None, 4, 5], dtype="Int64")),
    ("nullable_float", pd.array([1., None, 2., 0., -1., None, 4., 5.], dtype="Float64")),
    ("nullable_bool", pd.array([True, None, False, True, False, None, True, False], dtype="boolean")),
    ("object_strings", np.array(["1", "2", None, "3", "4", "5", "6", "7"], dtype=object)),
    ("object_numeric", np.array([1, 2, None, 3, 4, 5, 6, 7], dtype=object)),
    ("object_mixed", np.array([1, "2", None, 3, 4, 5, 6, 7], dtype=object)),
    ("string_extension", pd.array(["1", "2", None, "3", "4", "5", "6", "7"], dtype="string")),
    ("float32_precision", np.array([2 ** 24, 1, 1, 0, 0, 0, 0, 0], dtype="float32")),
    ("float16", np.arange(8, dtype="float16")),
    ("complex", np.arange(8, dtype="complex128") + 1j),
    ("non_native", np.arange(8, dtype=">i8")),
]
VOLUME_CASES += [(dtype, np.arange(8, dtype=dtype)) for dtype in (
    "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "float64")]


@pytest.mark.parametrize("rule", ("W-FRI", "M", "ME", pd.offsets.MonthEnd(2)))
@pytest.mark.parametrize("case,volume", VOLUME_CASES, ids=[case for case, _ in VOLUME_CASES])
def test_volume_dtype_value_and_exception_parity(case, volume, rule):
    assert_parity(make_frame(volume), rule)


@pytest.mark.parametrize("rule", ("W-FRI", "ME", pd.offsets.MonthEnd()))
def test_missing_ohlc_empty_groups_nat_and_column_order(rule):
    index = pd.DatetimeIndex(["2024-01-03", "2024-01-04", "2024-01-25",
                              "2024-03-04", "2024-03-05", None, "2024-03-25", "2024-03-25"],
                             name="Sessions")
    frame = make_frame(index=index)
    frame.loc[frame.index == "2024-01-25", ["Open", "High", "Low", "Close"]] = np.nan
    frame.iloc[0, frame.columns.get_loc("Open")] = np.nan
    frame.iloc[-1, frame.columns.get_loc("Close")] = np.nan
    out = assert_parity(frame.loc[frame.index.notna()], rule)
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert_parity(frame, rule)


@pytest.mark.parametrize("rule", RULES)
@pytest.mark.parametrize("case", ("none", "empty", "missing_volume", "missing_open", "all_nat",
                                  "invalid_date", "string_dates", "unnamed", "duplicate_volume"))
def test_empty_missing_and_unusual_input(case, rule):
    frame = make_frame()
    if case == "none":
        frame = None
    elif case == "empty":
        frame = frame.iloc[:0]
    elif case.startswith("missing_"):
        frame = frame.drop(columns=case.split("_", 1)[1].title())
    elif case == "all_nat":
        frame.index = pd.DatetimeIndex([pd.NaT] * len(frame), name="Missing Date")
    elif case == "invalid_date":
        frame.index = ["invalid"] * len(frame)
    elif case == "string_dates":
        frame.index = frame.index.strftime("%Y-%m-%d")
    elif case == "unnamed":
        frame.index.name = None
    else:
        frame = pd.concat([frame, frame[["Volume"]]], axis=1)
    assert_parity(frame, rule)


@pytest.mark.parametrize("rule", ("invalid", "", None, 1, "0D", "-1D", pd.offsets.Day(0)))
def test_bad_rules_preserve_errors(rule):
    assert_parity(make_frame(), rule)


@pytest.mark.parametrize("rule", ("W-FRI", "ME"))
def test_fast_path_removes_series_callbacks_and_fallback_keeps_them(rule):
    old, new = implementations()
    original_sum = pd.Series.sum
    for volume, fast in ((np.arange(8, dtype="int64"), True),
                         (np.array([0., np.nan, 1., 2., 3., 4., 5., 6.]), True),
                         (np.arange(8, dtype="int8"), False),
                         (np.arange(8, dtype="float32"), False),
                         (np.arange(8, dtype=float) / 10, False),
                         (np.array([2 ** 53] * 8), False),
                         (pd.array(range(8), dtype="Int64"), False),
                         (np.array(["1"] * 8, dtype=object), False)):
        counts = []
        for function in (old, new):
            calls = []

            def counted_sum(series, *args, **kwargs):
                calls.append(None)
                return original_sum(series, *args, **kwargs)

            with patch.object(pd.Series, "sum", counted_sum):
                function(make_frame(volume), rule)
            counts.append(len(calls))
        assert counts[0] > 0
        assert counts[1] == (0 if fast else counts[0])


@pytest.mark.parametrize("rule", ("W-FRI", "ME"))
def test_seeded_long_history_exact_parity(rule):
    rng = np.random.default_rng(102631)
    index = pd.bdate_range("2015-01-01", periods=2600, name="Date", tz="Asia/Seoul")
    for missing in (False, True):
        volume = rng.integers(0, 10_000_000, len(index))
        if missing:
            volume = volume.astype(float)
            volume[rng.random(len(index)) < .2] = np.nan
        frame = make_frame(volume, index=index)
        frame = frame.iloc[rng.permutation(len(frame))]
        assert_parity(frame, rule)
