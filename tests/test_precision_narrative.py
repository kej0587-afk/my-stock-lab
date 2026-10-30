"""Frozen pre-extraction HTML and AST parity without importing the app UI."""

import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from stock_lab_core.asset_classifier import is_fin_score_exempt_asset, is_leveraged_or_inverse_product
from stock_lab_core.decision_engine import build_sideways_quality_state
from stock_lab_core.formatters import clean_bool, clean_float, escape_html_value, finite_num, format_currency


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).with_name("golden") / "precision_narrative.json"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def function_node(path, name):
    return next(node for node in ast.parse(path.read_text(encoding="utf-8-sig")).body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def app_functions():
    names = {"_smc_zone_price_text", "describe_fvg_plain", "build_precision_narrative"}
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    namespace = {name: globals()[name] for name in (
        "np", "clean_bool", "clean_float", "escape_html_value", "finite_num", "format_currency",
        "is_fin_score_exempt_asset", "is_leveraged_or_inverse_product", "build_sideways_quality_state")}
    selected = ast.Module(body=[node for node in tree.body
                               if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    exec(compile(selected, "app.py", "exec"), namespace)
    return namespace


def cases():
    result = {}

    def add(key, changes=None, **kwargs):
        decision = {"dec": "관찰", "grade": "A", "t_score": 7, "tech_total": 5,
                    "rsi": 55.0, "mfi": 55.0, "pct_b": 0.5, "cur_p": 100.0,
                    "ma5": 98.0, "ma20": 95.0, "current_w": 1.0, "target_w": 5.0}
        decision.update(changes or {})
        result[key] = dict(name="Test <&>", tkr="MSFT", c=decision, fin_score=4,
                           has_p=False, my_p=95, **kwargs)

    add("default")
    result["minimal"] = dict(name="Test", tkr="MSFT", c={}, fin_score=0, has_p=False, my_p=0)
    for score in (0, 1, 2, 3, 4, 7):
        add(f"finance_{score}")
        result[f"finance_{score}"]["fin_score"] = score
    for index, decision in enumerate(("회복 매수", "홀드", "진입 보류", "차단", "방어", "역배열", "관찰")):
        for rr in (0.5, 2.0):
            add(f"conclusion_{index}_{rr}", {"dec": decision, "rr_ratio": rr, "rr_target": 120, "rr_stop": 90})
    for index, (rsi, mfi, pct_b) in enumerate(zip(
        (29, 30, 44.9, 45, 59.9, 60, 69.9, 70),
        (np.nan, 39, 40, 54.9, 55, 79.9, 80, 90),
        (np.nan, 0.34, 0.35, 0.74, 0.75, 1.0, 1.01, -0.1),
    )):
        add(f"indicator_boundary_{index}", {"rsi": rsi, "mfi": mfi, "pct_b": pct_b,
            "trend": ("🚀정배열(상승)", "🌊역배열(하락)", "➡️횡보/혼조", "🆕신규상장/자료부족")[index % 4],
            "rs_slope_label": ("📈RS상승중", "📉RS하락중", "")[index % 3]})
    codes = ("S_UPTREND_WAIT_PULLBACK", "A_UPTREND_WAIT_PULLBACK", "QUALITY_PULLBACK_ENTRY",
             "TREND_PULLBACK_EXPLORE", "CORE_ETF_DCA_BUY", "REVERSE_TREND_NO_ENTRY",
             "STRONG_REVERSE_NO_ENTRY", "PROFIT_TAKE_SIGNAL", "HOLD_QUALITY_UPTREND",
             "LEADER_MA5_PULLBACK_ENTRY", "LEADER_MA5_FAST_PULLBACK_ENTRY", "OVERHEAT_EXTENSION_WAIT_MA5")
    for code in codes:
        for position, weight in ((False, 0), (True, 1), (True, 6)):
            key = f"{code}_{position}_{weight}"
            add(key, {"decision_code": code, "current_w": weight, "rsi": 71, "mfi": 81, "pct_b": 1.1})
            result[key]["has_p"] = position
    for index, fvg in enumerate(("없음", "Bullish FVG", "Bearish FVG", "Other <&>")):
        for active in (False, True):
            add(f"fvg_{index}_{active}", {"fvg_type": fvg, "fvg_active": active, "fvg_bottom": 90,
                "fvg_top": 110, "ext_event": "BOS", "int_event": "CHoCH", "is_52w_breakout": active,
                "smc_action": "관망", "smc_insight": "기존 해석", "pd_zone": "Discount"})
    for index, live in enumerate((0, 0.003, 0.0031, -0.02, np.nan)):
        add(f"live_{index}", {"live_price_used": True, "regular_day_ret": -0.01, "live_ref_ret": live,
            "live_quote": {"volume_status": "missing_live_volume", "mfi_asof": "2026-10-29T10:00:00"}})
    for index, ratio in enumerate((np.nan, 0, 0.69, 0.7, 1.99, 2)):
        add(f"volume_{index}", {"vol_ratio": ratio, "vol_ma20": 1000, "last_volume": 2500,
            "vol_valid_count": 12, "day_ret": -0.02 if index % 2 else 0.01, "day_ret_label": "확인 등락"})
    add("projection", {"rr_ratio": 2.0, "rr_target": 120, "rr_stop": 90,
                       "rr_target_is_projection": True, "rr_target_source": "ATR <&>"})
    add("loss", {"cur_p": 80})
    result["loss"]["has_p"] = True
    for index, (ticker, metadata, explicit) in enumerate((
        ("379810.KS", {}, None), ("UNKNOWN", {"is_etf": True}, None),
        ("UNKNOWN", {"is_etf": "false"}, None), ("UNKNOWN", {"execution_workflow": {"유형": "ETF"}}, None),
        ("UNKNOWN", {"asset_class": "us_etf_nasdaq"}, None), ("UNKNOWN", {}, True),
        ("UNKNOWN", {"is_etf": True}, False), ("379810.KS", {"execution_workflow": {"유형": "개별주"}}, None),
        ("SOXL", {"is_leveraged_or_inverse": True}, None),
    )):
        key = f"product_{index}"
        add(key, metadata)
        result[key].update(tkr=ticker, is_etf=explicit)
    return result


@pytest.fixture(scope="module")
def original_goldens():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def app_namespace():
    return app_functions()


@pytest.mark.parametrize("case_id,case", cases().items(), ids=cases().keys())
def test_extracted_and_app_wrapper_match_original_html(case_id, case, app_namespace, original_goldens):
    from stock_lab_core.precision_narrative import build_precision_narrative

    payload = deepcopy(case)
    before = json.dumps(payload, sort_keys=True)
    actual = build_precision_narrative(**payload, describe_fvg_plain=app_namespace["describe_fvg_plain"])
    wrapped = app_namespace["build_precision_narrative"](**payload)
    assert actual == wrapped
    assert digest(actual) == original_goldens["outputs"][case_id]
    assert json.dumps(payload, sort_keys=True) == before


def test_only_gate_alignment_and_validated_rr_change_the_original_body(original_goldens):
    from stock_lab_core import precision_narrative

    core = function_node(Path(precision_narrative.__file__), "build_precision_narrative")
    wrapper = function_node(ROOT / "app.py", "build_precision_narrative")
    alignment = [node for node in core.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Call)
                 and ast.unparse(node.value.func) == "align_precision_narrative_display"]
    assert len(alignment) == 1 and core.body[-3] is alignment[0]
    assert ast.unparse(alignment[0].targets[0]) == "(lines, border_color)"
    original_body = [node for node in core.body if node is not alignment[0]]
    rr = next(node for node in original_body if isinstance(node, ast.Assign)
              and ast.unparse(node.targets[0]) == "rr_ratio")
    validated_rr = ast.parse('(c.get("execution_workflow") or {}).get("RR값", c.get("rr_ratio"))', mode="eval").body
    assert ast.dump(rr.value) == ast.dump(validated_rr)
    rr.value = ast.parse('c.get("rr_ratio")', mode="eval").body
    assert digest(ast.dump(ast.Module(body=original_body, type_ignores=[]))) == original_goldens["body_sha256"]
    assert ast.dump(wrapper.args) == original_goldens["signature_ast"]
    assert wrapper.end_lineno - wrapper.lineno < 15


def test_wrapper_passes_current_app_callbacks_without_changing_input(app_namespace, monkeypatch):
    calls = []

    def fvg(*args):
        calls.append(("fvg", args))
        return "Label <&>", "Note <&>"

    def sideways(*args, **kwargs):
        calls.append(("sideways", args, kwargs))
        return {"label": "Injected <&>", "note": "Note", "reason_text": "Reason"}

    monkeypatch.setitem(app_namespace, "describe_fvg_plain", fvg)
    monkeypatch.setitem(app_namespace, "build_sideways_quality_state", sideways)
    payload = deepcopy(cases()["fvg_1_True"])
    before = deepcopy(payload)
    html = app_namespace["build_precision_narrative"](**payload)
    assert "Label &lt;&amp;&gt;" in html and "Injected &lt;&amp;&gt;" in html
    assert [call[0] for call in calls] == ["fvg", "sideways"]
    assert calls[1][1][0] is payload["c"] and payload == before


def test_module_has_no_app_or_streamlit_dependency():
    from stock_lab_core import precision_narrative

    tree = ast.parse(inspect.getsource(precision_narrative))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any(name == "app" or name.startswith("streamlit") for name in imports)
