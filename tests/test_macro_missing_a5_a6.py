"""A-5/A-6 (2026-11-25): missing macro data is neither risk nor normal.

- Collection failure or any missing core input (10Y, VIX, USD/KRW, oil) -> macro risk NaN (UNKNOWN).
- MOVE missing adds nothing (no assumed 0.5) and is shown as "MOVE 미확인".
- The decision is computed without macro effect; the gate is DATA_CHECK · 매크로 미확인,
  except rows already in 방어우선, which stay 방어우선.
- Incomplete results are never cached, so a recovered collection is used at once.
"""
import math

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.execution_gate import GATE_DATA_CHECK, GATE_DEFENSE, build_execution_gate
from stock_lab_core.macro_status import (
    COMPLETE,
    FAILED,
    PARTIAL,
    macro_caption_text,
    macro_data_status,
    macro_unknown_reason,
)
from tests.fixtures_price import make_price_df
from tests.test_decision_golden_snapshot import SCENARIOS, _bench_info

FULL = {
    "10Y 금리": {"val": 4.3}, "유가": {"val": 70.0}, "환율": {"val": 1350.0}, "VIX": {"val": 15.0}, "MOVE": {"val": 95.0},
}


def test_macro_status_complete_partial_failed_and_move():
    assert macro_data_status(FULL)["macro_data_status"] == COMPLETE
    assert macro_data_status(FULL)["move_status"] == "ok"
    partial = {k: v for k, v in FULL.items() if k != "환율"}
    status = macro_data_status(partial)
    assert status["macro_data_status"] == PARTIAL
    assert status["macro_missing_components"] == ("USD/KRW",)
    assert macro_data_status({})["macro_data_status"] == FAILED
    no_move = {k: v for k, v in FULL.items() if k != "MOVE"}
    assert macro_data_status(no_move)["macro_data_status"] == COMPLETE
    assert macro_data_status(no_move)["move_status"] == "MOVE 미확인"
    for bad in (np.nan, 0.0, None, "x"):
        broken = dict(FULL, VIX={"val": bad})
        assert macro_data_status(broken)["macro_missing_components"] == ("VIX",)


def test_caption_never_prints_a_number_for_missing_macro():
    assert macro_caption_text(np.nan, macro_data_status({})) == "매크로 미확인 · 수집 실패"
    partial = macro_data_status({k: v for k, v in FULL.items() if k != "환율"})
    assert macro_caption_text(np.nan, partial) == "매크로 미확인 · USD/KRW 데이터 누락"
    no_move = macro_data_status({k: v for k, v in FULL.items() if k != "MOVE"})
    assert macro_caption_text(2.0, no_move) == "2.0pt · MOVE 미확인"
    assert macro_unknown_reason(()) == "매크로 미확인"


def _download(series):
    idx = pd.bdate_range("2026-10-01", periods=25)
    return pd.concat({tkr: pd.DataFrame({"Close": pd.Series([val] * 25, index=idx)}) for tkr, val in series.items()}, axis=1)


ALL_SERIES = {"^TNX": 4.3, "CL=F": 70.0, "USDKRW=X": 1350.0, "^VIX": 15.0, "^MOVE": 110.0}


@pytest.fixture
def macro_app(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "build_macro_event_risk_table", lambda *a, **k: (pd.DataFrame(), 1.0, 1))
    app_module.get_macro_analysis.clear()
    yield app_module
    app_module.get_macro_analysis.clear()


def test_normal_macro_keeps_existing_calculation(macro_app, monkeypatch):
    monkeypatch.setattr(macro_app.yf, "download", lambda *a, **k: _download(ALL_SERIES))
    results, risk, penalty, move = macro_app.get_macro_analysis()
    # storm 0 + trend 0 + MOVE 110 -> 0.5 + event 1.0
    assert risk == 1.5 and penalty == 0.5 and move == 110.0
    assert macro_app.classify_macro_state(risk) == "CAUTION"


def test_move_missing_adds_nothing(macro_app, monkeypatch):
    series = {k: v for k, v in ALL_SERIES.items() if k != "^MOVE"}
    monkeypatch.setattr(macro_app.yf, "download", lambda *a, **k: _download(series))
    results, risk, penalty, move = macro_app.get_macro_analysis()
    assert risk == 1.0 and penalty == 0  # no assumed +0.5 for MOVE
    assert math.isnan(move)
    assert macro_data_status(results)["move_status"] == "MOVE 미확인"


def test_one_core_missing_is_unknown_and_keeps_observed_values(macro_app, monkeypatch):
    series = {k: v for k, v in ALL_SERIES.items() if k != "USDKRW=X"}
    monkeypatch.setattr(macro_app.yf, "download", lambda *a, **k: _download(series))
    results, risk, penalty, move = macro_app.get_macro_analysis()
    assert math.isnan(risk) and math.isnan(penalty)
    assert macro_app.classify_macro_state(risk) == "UNKNOWN"
    assert macro_data_status(results)["macro_missing_components"] == ("USD/KRW",)
    assert results["VIX"]["val"] == 15.0
    assert "guard_macro_base" not in results["VIX"]


def test_incomplete_macro_is_not_cached_and_recovers_at_once(macro_app, monkeypatch):
    monkeypatch.setattr(macro_app.yf, "download", lambda *a, **k: pd.DataFrame())
    assert math.isnan(macro_app.get_macro_analysis()[1])
    monkeypatch.setattr(macro_app.yf, "download", lambda *a, **k: _download(ALL_SERIES))
    assert macro_app.get_macro_analysis()[1] == 1.5  # no clear() between the calls


def _run(app_module, monkeypatch, price_kwargs, rs_score, rs_slope, calc_kwargs, fmr, mp):
    df = make_price_df(**price_kwargs)
    monkeypatch.setattr(app_module, "get_rs_score", lambda ticker, asset_class: rs_score)
    monkeypatch.setattr(app_module, "get_rs_slope", lambda ticker, asset_class: rs_slope)
    monkeypatch.setattr(app_module, "get_auto_benchmark_info", lambda ticker, name, asset_class, is_etf: _bench_info())
    kwargs = dict(calc_kwargs, _final_macro_risk=fmr, _macro_penalty=mp)
    return app_module.calc_scores_and_decision(df=df, **kwargs)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_missing_macro_decision_is_macro_neutral(app_module, monkeypatch, scenario):
    _, price_kwargs, rs_score, rs_slope, calc_kwargs = scenario
    neutral = _run(app_module, monkeypatch, price_kwargs, rs_score, rs_slope, calc_kwargs, 0.0, 0.0)
    missing = _run(app_module, monkeypatch, price_kwargs, rs_score, rs_slope, calc_kwargs, np.nan, np.nan)
    for key in ("decision_code", "dec", "decision_group", "buy_amt", "core_dca_rate", "sizing_hint", "grade", "adj"):
        assert missing.get(key) == neutral.get(key), key
    assert missing["macro_state"] == "UNKNOWN"
    assert missing["macro_data_status"] == "missing"
    assert neutral["macro_data_status"] == "complete"
    assert not any("FMR 0.0" in str(r) for r in missing.get("decision_reasons") or ())


def test_gate_macro_unknown_is_data_check_with_missing_items():
    row = {"판정코드": "LEADER_MA5_PULLBACK_ENTRY", "판정분류": "buyish", "매크로상태": "UNKNOWN",
           "매크로누락": "USD/KRW", "최종읽기": "눌림대기", "데이터상태": "OK"}
    gate = build_execution_gate(row)
    assert gate["게이트상태"] == GATE_DATA_CHECK
    assert gate["게이트근거"] == "매크로 미확인 · USD/KRW 데이터 누락"
    assert "macro" in gate["게이트근거ID"]
    normal = build_execution_gate(dict(row, 매크로상태="NORMAL"))
    assert normal["게이트상태"] != GATE_DATA_CHECK or normal["게이트근거"] != gate["게이트근거"]


def test_gate_macro_unknown_keeps_existing_defense():
    for row in (
        {"판정코드": "STRUCTURE_DAMAGE_HOLDING_CHECK", "최종읽기": "구조훼손 점검", "매크로상태": "UNKNOWN"},
        {"판정코드": "HARD_BLOCK_FINANCIAL", "최종읽기": "", "매크로상태": "UNKNOWN"},
        {"판정코드": "QUALITY_RECOVERY_WATCH", "최종읽기": "", "매크로상태": "UNKNOWN", "상위시간대상태": "상위 시간대 경고"},
    ):
        assert build_execution_gate(row)["게이트상태"] == GATE_DEFENSE, row


def test_entry_header_and_panel_show_missing_items(app_module, monkeypatch):
    from types import SimpleNamespace
    shown = []

    class Col:
        def markdown(self, text, **_):
            shown.append(text)

    fake = SimpleNamespace(session_state={}, caption=shown.append, warning=shown.append, info=shown.append,
                           columns=lambda n: [Col() for _ in range(n)])
    monkeypatch.setattr(app_module, "st", fake)
    partial = {k: dict(v, icon="➖", storm=False) for k, v in FULL.items() if k != "환율"}
    app_module.render_macro_entry_header(partial, np.nan, np.nan, 0.0, "test")
    app_module.render_macro_entry_panel(partial)
    text = "\n".join(shown)
    assert "매크로 지수: 매크로 미확인 · USD/KRW 데이터 누락" in text
    assert "매크로 패널티: 미확인" in text and "nan" not in text
    assert "환율: <b>미확인</b>" in text
    assert fake.session_state["_app_macro_status"]["last_complete_macro_at"] == "미확인"
    assert app_module.current_macro_missing_components() == ("USD/KRW",)
    shown.clear()
    app_module.render_macro_entry_header(FULL, 0.5, 0.0, 0.0, "test")
    assert "매크로 지수: 0.5pt" in shown[0]
    assert fake.session_state["_app_last_complete_macro_at"] != "미확인"
    assert app_module.current_macro_missing_components() == ()
    monkeypatch.delitem(vars(app_module), "_APP_MACRO_STATUS", raising=False)
