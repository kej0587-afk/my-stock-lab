from copy import deepcopy

import pandas as pd

from stock_lab_core.portfolio_commentary import holding_commentary, portfolio_commentary


def detail(ticker="RAM"):
    return {
        "holding": {"티커": ticker, "자산명": ticker},
        "signal": {"가격자료기준일": "2026-11-03", "게이트상태": "방어우선",
                   "시장실행상태": "시장방어", "게이트근거": "비중 초과",
                   "돈흐름_후보군": "메모리", "돈흐름_판정": "회복 관찰"},
        "precision": {},
    }


def test_ram_commentary_distinguishes_business_and_product_with_original_conditions():
    d = detail()
    management = {"판정": "축소/교체 검토", "근거": "현재/목표 12%/6%", "재개/해제 조건": "기존 조건"}
    before = deepcopy((d, management))
    result = holding_commentary(d, management)
    assert "DRAM의 일간 2배" in result["interpretation"]
    assert "12%/6%" in result["facts"]
    assert "회복 관찰" in result["facts"]
    assert "비중 초과" in result["next_step"]
    assert "기존 조건" in result["next_step"]
    assert (d, management) == before


def test_other_holdings_receive_commentary_without_memory_company_promotion():
    result = holding_commentary(detail("CIBR"), {"판정": "보유 유지"})
    assert "CIBR" in result["facts"]
    assert "보유와 비중 관리" in result["interpretation"]
    assert "삼성" not in result["interpretation"]
    assert "매도 시점은 이 게이트만으로 결정하지 않습니다" in result["next_step"]


def test_missing_inputs_are_not_safe_market_or_buy_permission():
    result = holding_commentary({"holding": {"티커": "MSFT"}}, {})
    assert "보류" in result["facts"]
    assert "단정할 수 없습니다" in result["interpretation"]
    assert "시점을 제시하지 않습니다" in result["next_step"]
    summary = " ".join(portfolio_commentary({}, {}, pd.DataFrame()))
    assert "단정하지 않습니다" in summary
    assert "0.0%" not in summary


def test_executable_queue_never_overrides_precision_block_or_date_mismatch():
    d = detail()
    d["signal"]["게이트상태"] = "실행가능"
    d["precision"] = {"basis": {"가격자료기준일": "2026-11-02"}, "final": {"final_label": "매수 금지"}}
    result = holding_commentary(d, {"판정": "조건부 적립"})
    assert "후보 확인 단계" in result["next_step"]
    assert "매수 금지" in result["next_step"]
    assert "하나의 최신 판정으로 합치지 않습니다" in result["next_step"]


def test_concentration_is_existing_flow_mapping_not_lookthrough_or_reclassification():
    details = {"RAM": detail(), "CIBR": detail("CIBR")}
    details["CIBR"]["signal"]["돈흐름_후보군"] = "보안"
    metrics = {"top3_weight": 70, "leverage_summary": {"leveraged_principal_pct": 15, "effective_exposure_pct": 30},
               "strategy_df": pd.DataFrame([
                   {"티커": "RAM", "현재비중": 12}, {"티커": "CIBR", "현재비중": 4},
                   {"티커": "MU", "현재비중": 50},
               ])}
    management = pd.DataFrame([{"티커": "MU", "우선": 1, "판정": "unheld"},
                               {"티커": "RAM", "자산": "RAM", "우선": 10, "판정": "축소/교체 검토", "근거": "기존 비중"}])
    result = " ".join(portfolio_commentary(metrics, details, management))
    assert "70.0%" in result and "15.0%" in result and "30.0%" in result
    assert "메모리'으로 묶인 보유자산 12.0%" in result
    assert "실효 업종비중은 아닙니다" in result
    assert "unheld" not in result and "62.0%" not in result


def test_nan_values_do_not_leak_into_commentary():
    d = detail("AAPL")
    d["signal"] = {"가격자료기준일": float("nan"), "돈흐름_시장맥락": pd.NA}
    result = holding_commentary(d, {"판정": pd.NA, "근거": float("nan")})
    assert "nan" not in str(result) and "<NA>" not in str(result)
    assert "기준일" in result["next_step"]


def test_optional_company_evidence_hidden_by_default_in_streamlit():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string('''
import streamlit as st
import pandas as pd
from stock_lab_core.portfolio_holding_review import render_portfolio_holding_review
h = pd.DataFrame([{"티커":"RAM", "자산명":"RAM", "보유량":1},
                  {"티커":"CIBR", "자산명":"CIBR", "보유량":1}])
render_portfolio_holding_review(st, h, context="test", metrics={"top3_weight":70})
''').run(timeout=30)
    assert not at.exception
    assert not at.button
    assert "내 보유를 어떻게 볼까" in " ".join(m.value for m in at.markdown)
    at.checkbox[0].check().run(timeout=30)
    assert not at.exception
    assert len(at.button) == 1
    at.selectbox[0].select("CIBR").run(timeout=30)
    assert not at.exception
    assert not at.button
    assert "CIBR의 기존 보유관리" in " ".join(m.value for m in at.markdown)


def test_legacy_panel_reuses_decisions_without_recalculating(app_module, monkeypatch):
    class UI:
        def markdown(self, *a, **k): pass
        def caption(self, *a, **k): pass
        def info(self, *a, **k): pass
        def metric(self, *a, **k): pass
        def columns(self, n): return [self] * n
        def dataframe(self, *a, **k): pass
    prepared = pd.DataFrame([{"자산": "RAM", "티커": "RAM", "구분": "leverage", "손익": "-20%",
                              "평가손익": "-100", "판정": "축소/교체 검토", "실행": "기존 실행",
                              "근거": "기존 근거", "재개/해제 조건": "기존 조건"}])
    before = prepared.copy(deep=True)
    def forbidden(*args):
        raise AssertionError("duplicate calculation")
    monkeypatch.setattr(app_module, "st", UI())
    monkeypatch.setattr(app_module, "build_portfolio_action_decision_df", forbidden)
    result = app_module.render_portfolio_action_decision_panel({}, prepared_decisions=prepared)
    assert result is prepared
    pd.testing.assert_frame_equal(before, prepared)
