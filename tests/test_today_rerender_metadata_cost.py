"""Retained-input parity and bounded metadata copying; no provider/time assumptions."""
import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import today_queue_session as session
from stock_lab_core import today_result_observation as observation

BASE = "dffa5a4274f2cb316266a73634fb4d401a9a3f95"
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(None)
def retained(module_name, name):
    module = {"today_queue_session": session, "today_result_observation": observation}[module_name]
    source = subprocess.check_output(["git", "show", f"{BASE}:stock_lab_core/{module_name}.py"], cwd=ROOT)
    fn = next(n for n in ast.parse(source.decode("utf8")).body if isinstance(n, ast.FunctionDef) and n.name == name)
    env = dict(vars(module))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<retained-rerender>", "exec"), env)
    return env[name]


class CopyProbe:
    copies = 0

    def __deepcopy__(self, memo):
        type(self).copies += 1
        return CopyProbe()


def frame(rows=104):
    result = pd.DataFrame({"티커": [f"T{i}" for i in range(rows)], "has_pos": [False] * rows,
                           "qty": [np.nan] * rows, "금액": [12.3456789012345] * rows,
                           "판정코드": ["WAIT"] * rows, "가격입력ID": ["fixed"] * rows})
    result.attrs.update(portfolio_signal_context="scope", portfolio_signal_at="fixed",
                        today_observation_inputs={"T0": {"price_input_id": "fixed", "decision": {"rr": 0.4}}},
                        today_saved_display=pd.DataFrame({"proof": [1, 2]}),
                        probe=CopyProbe())
    return result


@pytest.mark.parametrize("rows", [1, 104])
@pytest.mark.parametrize("matched", [False, True])
def test_ownership_repair_parity_and_isolation(rows, matched):
    src = frame(rows)
    state = {session.SIGNATURE_KEY: "sig", "_app_holdings_table": pd.DataFrame({"티커": ["T0"], "보유량": [2.5]})}
    sig = "sig" if matched else "other"
    old = retained("today_queue_session", "_repair_cached_ownership")(state, src, sig)
    CopyProbe.copies = 0
    new = session._repair_cached_ownership(state, src, sig)
    assert CopyProbe.copies <= 1
    pd.testing.assert_frame_equal(pd.DataFrame(old), pd.DataFrame(new))
    assert set(new.attrs) == set(old.attrs)
    assert pd.isna(src.at[0, "qty"])
    if matched:
        assert new.at[0, "qty"] == 2.5
        assert new.at[0, "has_pos"]
        new.attrs["today_observation_inputs"]["T0"]["decision"]["rr"] = 99
        new.attrs["today_saved_display"].iloc[0, 0] = 99
        assert src.attrs["today_observation_inputs"]["T0"]["decision"]["rr"] == 0.4
        assert src.attrs["today_saved_display"].iloc[0, 0] == 1


@pytest.mark.parametrize("variant", ["missing", "zero", "held", "changed_value", "changed_envelope", "nullable"])
def test_observation_identity_matches_retained_without_storage_copies(variant):
    original = frame()
    if variant == "zero": original["qty"] = 0.
    if variant == "held": original.loc[0, ["has_pos", "qty"]] = [True, 2.5]
    if variant == "changed_value": original.loc[0, "금액"] = 12.5
    if variant == "changed_envelope": original.attrs[observation.INPUTS_KEY]["T0"]["decision"]["rr"] = 0.7
    if variant == "nullable": original["qty"] = pd.Series([pd.NA] * 104, dtype="Float64")
    displayed = pd.DataFrame(original, copy=True)
    kwargs = dict(signature="sig", context="scope", calculation_id="fixed")
    previous = retained("today_result_observation", "_observation_key")(original, displayed, **kwargs)
    expected_input = pd.DataFrame(original, copy=True)
    expected_evidence = deepcopy(original.attrs[observation.INPUTS_KEY])
    CopyProbe.copies = 0
    current = observation._observation_key(original, displayed, **kwargs)
    assert current == previous
    assert CopyProbe.copies == 0
    pd.testing.assert_frame_equal(pd.DataFrame(original), expected_input)
    assert original.attrs[observation.INPUTS_KEY] == expected_evidence
    original.loc[0, "금액"] = 123.
    assert observation._observation_key(original, displayed, **kwargs) != current
