"""Rotation display follows existing Today stop precedence without rescoring."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from stock_lab_core.decision_workflow import attach_market_execution_context


def source():
    return pd.DataFrame([
        {"Ticker": ticker, "섹터": label, "구분": group, "RS(3M)": .15,
         "RS모멘텀": .04, "3M수익률": .25, "1개월수익률": .06,
         "2주수익률": .03, "1주수익률": .01, "가격수준": .5,
         "업종내부": "확산 우세", "상태": "주도 유지", "사분면": "주도", "돈흐름점수": 42.}
        for ticker, label, group in (("005930.KS", "한국 테스트", "한국 섹터"),
                                      ("AAPL", "미국 테스트", "미국 섹터"))
    ])


def guard(mode="정상", action="", **updates):
    return {"mode": mode, "action": action, "kr_stats": {"mode": "정상"},
            "us_stats": {"mode": "정상"}, **updates}


@pytest.mark.parametrize("mode,action", [
    ("위험", ""), ("비상", ""), ("전시장 비상", "국장·미장 신규/추매 중단"),
    ("방어", "신규매수 중단 · 현금/리스크 점검"), ("정상", "신규매수 중단"),
])
def test_rotation_global_stop_overrides_normal_region(app_module, mode, action):
    frame, market = source(), guard(mode, action)
    before, guard_before = frame.copy(deep=True), deepcopy(market)
    result = app_module._apply_rotation_execution_framework(frame, market_guard=market, label_col="섹터")
    today = attach_market_execution_context(frame.rename(columns={"Ticker": "티커"}), market)
    assert today["시장실행상태"].eq("시장방어: 신규매수 중단").all()
    assert result["실행분류"].eq(app_module.ROTATION_DEFENSE_ACTION).all()
    assert result["진입검토"].eq(app_module.ROTATION_DEFENSE_ACTION).all()
    assert not app_module._rotation_candidate_mask(result).any()
    pd.testing.assert_frame_equal(frame, before)
    pd.testing.assert_frame_equal(result[frame.columns], before)
    assert market == guard_before


@pytest.mark.parametrize("mode,blocked,other", [("국장 비상", 0, "us_stats"), ("미장 비상", 1, "kr_stats")])
@pytest.mark.parametrize("other_missing", [False, True])
def test_rotation_regional_emergency_does_not_block_other_region(app_module, mode, blocked, other, other_missing):
    market = guard(mode)
    if other_missing:
        market.pop(other)
    frame = source()
    result = app_module._apply_rotation_execution_framework(frame, market_guard=market)
    today = attach_market_execution_context(frame.rename(columns={"Ticker": "티커"}), market)
    assert today.iloc[blocked]["시장실행상태"] == "시장방어: 신규매수 중단"
    assert result.iloc[blocked]["실행분류"] == app_module.ROTATION_DEFENSE_ACTION
    assert result.iloc[1-blocked]["실행분류"] == "✅ 정밀후보"
    # Missing regional data is not an inferred global stop or execution approval.
    assert "시장방어" not in today.iloc[1-blocked]["시장실행상태"]


@pytest.mark.parametrize("market", [None, guard(), guard("방어"),
    guard("방어", kr_stats={"mode": "방어"}), guard("위험장 반등")])
def test_rotation_non_global_stop_keeps_existing_regional_display(app_module, market):
    result = app_module._apply_rotation_execution_framework(source(), market_guard=market)
    expected = ["✅ 정밀후보", "✅ 정밀후보"]
    if market and market["kr_stats"]["mode"] == "방어":
        expected[0] = app_module.ROTATION_DEFENSE_ACTION
    assert result["실행분류"].tolist() == expected


def test_rotation_global_stop_does_not_relax_existing_risk_avoidance(app_module):
    frame = source()
    frame["RS(3M)"], frame["RS모멘텀"], frame["3M수익률"] = -.2, -.1, -.3
    frame["1개월수익률"], frame["2주수익률"] = -.2, -.1
    before = frame.copy(deep=True)
    result = app_module._apply_rotation_execution_framework(frame, market_guard=guard("위험"))
    assert result["실행분류"].eq("🚫 위험회피").all()
    assert result["진입검토"].eq("🚫 제외").all()
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("mode", ["위험", "정상"])
def test_rotation_chart_hover_table_candidates_share_defense_state(app_module, monkeypatch, mode):
    app, figures, tables, messages = app_module, [], [], []
    frame = source()
    before = frame.copy(deep=True)
    frame.attrs["provenance"] = {"original": [1, 2]}
    attrs_before = deepcopy(frame.attrs)
    monkeypatch.setattr(app, "st", SimpleNamespace(
        caption=messages.append, markdown=messages.append, info=messages.append,
        warning=messages.append, expander=lambda *a, **kw: nullcontext(),
        plotly_chart=lambda fig, **kw: figures.append(fig),
        dataframe=lambda table, **kw: tables.append(table.copy(deep=True)),
    ))
    # Freeze provider enrichment only; execute real framework, figure and table builders.
    monkeypatch.setattr(app, "_attach_kr_internal_context_to_rotation_df", lambda df, **kw: df.copy(deep=True))
    monkeypatch.setattr(app, "_build_internal_representative_table", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(app, "ETF_TO_THEME", {})
    app._render_rotation_chart_and_table(frame, "섹터", market_guard=guard(mode))
    expected = app.ROTATION_DEFENSE_ACTION if mode == "위험" else "✅ 진입검토"
    points = [row for trace in figures[0].data for row in trace.customdata]
    assert len(points) == len(frame)
    assert {row[4] for row in points} == {expected}
    assert all(trace.marker.color == ("#a78bfa" if mode == "위험" else "#22c55e") for trace in figures[0].data)
    assert all(table["진입검토"].eq(expected).all() for table in tables if "진입검토" in table)
    assert ("**✅ 우선 확인 후보**" in messages) is (mode == "정상")
    assert any("매수 허가가 아닙니다" in text for text in messages)
    np.testing.assert_allclose(sorted(x for trace in figures[0].data for x in trace.x), sorted(frame["RS(3M)"] * 100))
    np.testing.assert_allclose(sorted(y for trace in figures[0].data for y in trace.y), sorted(frame["RS모멘텀"] * 100))
    pd.testing.assert_frame_equal(frame, before)
    assert frame.attrs == attrs_before
