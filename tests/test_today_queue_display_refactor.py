"""Exact display-policy parity with the pre-extraction Today Queue."""

import ast
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product
from stock_lab_core.decision_engine import classify_decision_signal
from stock_lab_core.decision_workflow import attach_market_execution_context, partition_today_queue
from stock_lab_core.execution_gate import apply_execution_gate_columns
from stock_lab_core.formatters import is_kr_listed, sanitize_ticker_value
from stock_lab_core.today_queue import (
    leveraged_market_defense_mask as _leveraged_market_defense_mask,
    leveraged_recovery_tracking_mask as _leveraged_recovery_tracking_mask,
    leveraged_scout_execution_mask as _leveraged_scout_execution_mask,
    today_queue_reason_bucket as _today_queue_reason_bucket,
)
from stock_lab_core import today_queue_display
from tests.test_today_queue_view_refactor import freeze


ROOT = Path(__file__).resolve().parents[1]
BASE = "57ba39a96d45197bd3a04a6a6dd14fb001feab9b"
MAIN = "_render_today_queue_tab"


@pytest.fixture(scope="module")
def sources():
    return (subprocess.check_output(["git", "show", BASE + ":app.py"], cwd=ROOT, encoding="utf8"),
            (ROOT / "app.py").read_text(encoding="utf-8-sig"))


def assigns(node, name):
    return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)


@lru_cache(maxsize=2)
def display_body(source):
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == MAIN)
    start = next(i for i, n in enumerate(fn.body) if assigns(n, "portfolio_signal_attrs"))
    end = next(i for i, n in enumerate(fn.body) if assigns(n, "risk_df"))
    return fn.body[start:end]


@lru_cache(maxsize=2)
def compiled_display(source):
    return compile(ast.Module(body=display_body(source), type_ignores=[]), "<queue-display>", "exec")


def sample():
    cases = [
        ("RAM", "LEVERAGED_RECOVERY_DCA_CONDITIONAL", "레버리지 시장위험: DCA 대기"),
        ("SOXL", "LEVERAGED_DCA_CONDITIONAL", "레버리지 DCA 조건부"),
        ("BITX", "WAIT", "레버리지 회복추적: 눌림대기"),
        ("418660.KS", "WAIT", "레버리지 시장위험: 신규/DCA 대기"),
        ("MSFT", "HARD_BLOCK_OVERWEIGHT", "하드차단: 비중 초과"),
        ("AAPL", "HARD_BLOCK_BOLLINGER_UPPER", "하드차단: 볼린상단 이탈"),
        ("NVDA", "HARD_BLOCK_MFI_OVERHEAT", "MFI 과열"),
        ("005930.KS", "PRICE_DRAWDOWN_NO_ENTRY", "고점대비 -20%"),
        ("267260.KS", "SINGLE_DAY_BREAKDOWN", "단기급락"),
        ("TSM", "REVERSE_TREND", "추세방어"),
        ("379810.KS", "MACRO_STORM", "코어 ETF 방어: 거치 적립"),
        ("379800.KS", "CORE_PANIC", "패닉: 현금 최종 투입"),
        ("MAGS", "CORE", "코어 눌림 100% 적립"),
        ("0227L0.KS", "NEW_ETF_MIN_DATA_WATCH", "최소 데이터 관찰"),
        ("EMPTY", "DATA_ERROR", "데이터확인"),
        ("AMD", "HARD_BLOCK", "하드차단"),
    ]
    rows = []
    for i, (ticker, code, label) in enumerate(cases):
        rows.append({"티커": ticker, "종목명": ticker, "유형": "ETF" if i < 4 or i >= 10 else "개별주",
            "asset_class": "kr_stock" if ".KS" in ticker else "us_stock", "판정코드": code,
            "🔥기술적 타점": label, "최종읽기": "관망" if i != 12 else "방어우선",
            "📌후보등급": "위기/패닉" if i == 11 else "A급", "판정분류": "buyish",
            "실행메모": "R/R 회복 대기", "매크로상태": "CAUTION", "데이터상태": "OK",
            "핵심근거": "회복 4/6(부분 회복) · 기초축 1W +6.0%" if i < 3 else "",
            "R/R": 1.15, "Adj점수": 4.2, "현재비중": 0.5, "목표비중": 2.,
            "RSI": 64., "MFI": 72., "볼린저 %B": .82})
    rows[13]["데이터상태"] = rows[14]["데이터상태"] = "MISSING"
    frame = pd.DataFrame(rows)
    frame.attrs = {"portfolio_signal_context": {"scope": "fixture"}, "queue_measurement": {"id": "retained"}}
    return frame


def guard(mode="정상", kr="정상", us="정상", risk=0.):
    return {"mode": mode, "kr_stats": {"mode": kr}, "us_stats": {"mode": us}, "macro_risk": risk}


GUARDS = [None, {}, guard(), guard("주의"), guard("방어"), guard("위험", risk=4.5),
          guard("위험장 반등"), guard("전시장 비상"), guard("국장 비상"), guard("미장 비상"),
          guard(kr="비상"), guard(us="비상"), guard(risk=4.49), guard(risk=4.5)]


def run(source, frame, market):
    before, guard_before = deepcopy(frame), deepcopy(market)
    calls = []

    def market_guard(snapshot, summary):
        calls.append((snapshot, summary.copy(), deepcopy(summary.attrs)))
        return market

    env = dict(globals(), summary_df=frame, get_cached_today_market_flow_snapshot=lambda: {"fixture": True},
               build_today_market_guard=market_guard)
    exec(compiled_display(source), env)
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    assert frame.attrs == before.attrs and market == guard_before
    result = env["summary_df"]
    output = {key: env[key] for key in ("reason_bucket", "hard_block_mask", "buyish_mask", "caution_mask")}
    gated = apply_execution_gate_columns(attach_market_execution_context(result, market))
    output.update(summary=result, attrs=result.attrs, calls=calls, gates=gated,
                  partition=partition_today_queue(gated, env["reason_bucket"]))
    return output


def assert_parity(before, after):
    for key in ("summary", "gates"):
        pd.testing.assert_frame_equal(before[key], after[key], check_exact=True)
    for key in ("reason_bucket", "hard_block_mask", "buyish_mask", "caution_mask"):
        pd.testing.assert_series_equal(before[key], after[key], check_exact=True)
    assert freeze(before) == freeze(after)


@pytest.mark.parametrize("market", GUARDS)
def test_regional_modes_preserve_labels_masks_gates_and_execution_partition(sources, market):
    assert_parity(run(sources[0], sample(), market), run(sources[1], sample(), market))


@pytest.mark.parametrize("kind", ["no_group", "minimal", "missing_grade", "none_text", "noncontiguous",
                                  "duplicate_index", "string_index", "storm", "panic", "zero_weights"])
def test_missing_values_indices_and_fallback_classification_are_unchanged(sources, kind):
    frame = sample()
    if kind == "no_group":
        frame = frame.drop(columns="판정분류")
    elif kind == "minimal":
        frame = frame[["종목명", "티커", "🔥기술적 타점"]]
    elif kind == "missing_grade":
        frame = frame.drop(columns="📌후보등급")
    elif kind == "none_text":
        frame.loc[:3, ["최종읽기", "실행메모", "판정분류"]] = None
    elif kind == "noncontiguous":
        frame.index = np.arange(len(frame)) * 7 + 10
    elif kind == "duplicate_index":
        frame.index = np.arange(len(frame)) // 2
    elif kind == "string_index":
        frame.index = [f"r{i}" for i in range(len(frame))]
    elif kind == "storm":
        frame["매크로상태"] = "STORM"
    elif kind == "panic":
        frame["최종읽기"] = "방어우선"
    else:
        frame[["현재비중", "목표비중"]] = 0.
    assert_parity(run(sources[0], frame, guard("방어")), run(sources[1], frame, guard("방어")))


@pytest.mark.parametrize("seed", range(36))
def test_numeric_edges_randomized_rows_and_gate_results_remain_exact(sources, seed):
    rng = np.random.default_rng(seed)
    frame = pd.concat([sample(), sample()], ignore_index=True)
    for column, choices in {
        "R/R": [.99, 1., 1.19, 1.2, 2., np.nan], "Adj점수": [3.99, 4., np.nan],
        "현재비중": [0., 1.94, 1.95, 2., 2.05, 2.06, np.nan], "목표비중": [0., 2., np.nan],
        "RSI": [71.99, 72., 77.99, 78., np.nan], "MFI": [81.99, 82., 87.99, 88., np.nan],
        "볼린저 %B": [.8999, .9, 1.0499, 1.05, np.nan],
    }.items():
        frame[column] = rng.choice(choices, len(frame))
    frame["최종읽기"] = rng.choice(["관망", "정밀확인", "방어우선", "DCA조건부", "돌파대기"], len(frame))
    frame["매크로상태"] = rng.choice(["NORMAL", "CAUTION", "STORM", ""], len(frame))
    frame["판정분류"] = rng.choice(["buyish", "caution", "neutral"], len(frame))
    market = GUARDS[seed % len(GUARDS)]
    assert_parity(run(sources[0], frame, market), run(sources[1], frame, market))


def test_extracted_conditions_and_refresh_order_are_syntax_identical(sources):
    old = display_body(sources[0])
    start = next(i for i, n in enumerate(old) if assigns(n, "ticker_series"))
    tree = ast.parse((ROOT / "stock_lab_core/today_queue_display.py").read_text(encoding="utf8"))
    functions = {n.name: n.body for n in tree.body if isinstance(n, ast.FunctionDef)}
    prefix = functions["prepare_today_queue_display"]
    first = next(i for i, n in enumerate(prefix) if assigns(n, "type_series"))
    end = next(i for i, n in enumerate(prefix) if assigns(n, "text"))
    leverage = functions["_apply_leverage_labels"]
    scout = next(n.value for n in leverage if assigns(n, "scout_candidates"))
    assembled = [leverage[0]] + prefix[first:end] + [
        n for n in leverage[1:] if not assigns(n, "scout_candidates")
    ] + functions["_apply_defense_labels"][:-1] + functions["_build_display_masks"][:-1]

    class RestoreOriginalNames(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == "text":
                names = {"label": "label_series", "final_read": "final_read_series",
                         "grade": "grade_series", "action": "action_series"}
                return ast.Name(id=names[node.attr], ctx=node.ctx)
            return self.generic_visit(node)

        def visit_Name(self, node):
            return deepcopy(scout) if node.id == "scout_candidates" else node

    rebuilt = RestoreOriginalNames().visit(ast.Module(body=deepcopy(assembled), type_ignores=[]))
    assert ast.dump(rebuilt) == ast.dump(ast.Module(body=old[start:], type_ignores=[]))


@pytest.mark.parametrize("market", [guard(), guard("방어"), guard(us="비상")])
def test_scout_scan_is_reused_only_within_one_preparation(sources, monkeypatch, market):
    original = _leveraged_scout_execution_mask
    calls = []

    def counted(frame, mask):
        calls.append(frame.copy())
        return original(frame, mask)

    monkeypatch.setitem(globals(), "_leveraged_scout_execution_mask", counted)
    monkeypatch.setattr(today_queue_display, "_leveraged_scout_execution_mask", counted)
    frame = sample()
    before = run(sources[0], frame, market)
    assert len(calls) == 2
    pd.testing.assert_frame_equal(calls[0], calls[1], check_exact=True)
    calls.clear()
    assert_parity(before, run(sources[1], frame, market))
    assert len(calls) == 1
    frame["현재비중"] = 20.
    calls.clear()
    changed = run(sources[1], frame, guard("위험"))
    assert len(calls) == 1 and calls[0]["현재비중"].eq(20.).all()
    assert_parity(run(sources[0], frame, guard("위험")), changed)


def test_public_helper_preserves_caller_frame_groups_and_attributes():
    frame = sample()
    groups = frame["판정분류"].astype(str)
    before, before_groups = deepcopy(frame), groups.copy()
    result, _, _ = today_queue_display.prepare_today_queue_display(frame, guard("방어"), groups)
    assert result is not frame
    pd.testing.assert_frame_equal(frame, before, check_exact=True)
    pd.testing.assert_series_equal(groups, before_groups, check_exact=True)
    assert result.attrs == before.attrs == frame.attrs
