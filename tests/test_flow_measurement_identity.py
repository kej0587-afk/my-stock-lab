"""Run the actual merge path without account initialization or network access."""

import ast
from pathlib import Path

import pandas as pd

from stock_lab_core.performance import PerformanceTrace, bind_summary_measurement, measure, summary_measurement_reference


def attach_function(flow):
    tree = ast.parse((Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "attach_today_flow_context")
    function.decorator_list = []
    namespace = {"pd": pd, "_today_review_ticker_key": lambda v: str(v).lower(),
                 "build_today_flow_context_df": lambda **kwargs: flow.copy()}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
    return namespace[function.name]


def test_actual_flow_merge_preserves_bound_calculation_and_snapshot_metadata():
    with PerformanceTrace() as trace:
        with measure("phase", "summary"):
            summary = pd.DataFrame({"티커": ["MSFT"], "현재가": [531.25]})
        bind_summary_measurement(summary)
    summary.attrs["today_analyst_snapshots"] = {"MSFT": {"target": 599.28}}
    flow = pd.DataFrame({"_검토키": ["msft"], "판정": ["추격금지"]})
    result = attach_function(flow)(summary)
    assert summary_measurement_reference(result)["measurement_id"] == trace.measurement_id
    assert result.attrs == summary.attrs
    assert result["돈흐름_판정"].tolist() == ["추격금지"]
    assert "돈흐름_판정" not in summary


def test_unbound_old_summary_does_not_receive_unrelated_measurement():
    flow = pd.DataFrame({"_검토키": ["msft"], "판정": ["추격금지"]})
    with PerformanceTrace():
        with measure("phase", "summary"):
            pass
        result = attach_function(flow)(pd.DataFrame({"티커": ["MSFT"]}))
    assert not summary_measurement_reference(result)


def test_existing_radar_name_repairs_only_missing_or_ticker_labels():
    summary = pd.DataFrame({"티커": ["003160.KS", "MSFT", "AAPL", "AMD"],
                            "종목명": ["003160.KS", "내 Microsoft", "", "AMD"]})
    flow = pd.DataFrame({"_검토키": ["003160.ks", "msft", "aapl", "amd"],
                         "종목명": ["디아이", "Microsoft", "Apple", "AMD"]})
    result = attach_function(flow)(summary)
    assert result["종목명"].tolist() == ["디아이", "내 Microsoft", "Apple", "AMD"]
    assert summary["종목명"].iloc[0] == "003160.KS"
