"""The ability board is evidence, not a second, more permissive buy gate."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


def sector(**values):
    return dict({"구분": "미국 섹터", "섹터": "소프트웨어", "Ticker": "IGV", "돈흐름점수": 28.0,
        "1일수익률": 0.01, "5일수익률": 0.03, "2주수익률": 0.04, "1개월수익률": 0.08,
        "3M수익률": 0.20, "가격수준": 0.5, "진입검토": "정밀관측"}, **values)


def cards(app, *, command=None, sectors=None, themes=None):
    return app._flow_sector_ability_cards(pd.DataFrame(command or []), pd.DataFrame(sectors or []), pd.DataFrame(themes or []))


def test_duplicate_source_rows_cannot_manufacture_breadth_or_a_leading_verdict(app_module):
    row = sector()
    one = cards(app_module, sectors=[row])[0]
    three = cards(app_module, sectors=[row, row, row])[0]
    assert one["values"] == three["values"]
    assert one["total"] == three["total"]
    assert one["verdict"] == three["verdict"]
    assert one["item_count"] == three["item_count"] == 1


def test_finalized_command_action_wins_over_raw_etf_precision_signal(app_module):
    command = {"시장": "미국", "후보군": "소프트웨어", "Ticker": "IGV", "ETF/대표": "IGV",
        "대표주": "Datadog (DDOG)", "행동": "눌림대기", "_점수": 200.0,
        "1개월": 0.08, "5D": 0.03, "2주": 0.04, "가격수준": 0.5}
    card = cards(app_module, command=[command], sectors=[sector()])[0]
    assert card["action"] == "눌림대기"
    assert card["raw_action"] == "정밀관측"
    assert card["item_count"] == 1
    assert card["values"]["강도"] == pytest.approx(7.0)  # Raw 28, not derived command 200.
    assert "Datadog" in card["representatives"]
    assert "IGV" in card["etfs"]


def test_finalized_overheat_warning_keeps_safety_penalty_after_dedup(app_module):
    base = cards(app_module, sectors=[sector()])[0]
    command = {"시장": "미국", "후보군": "소프트웨어", "Ticker": "IGV", "ETF/대표": "IGV",
               "대표주": "Datadog (DDOG)", "행동": "추격금지"}
    blocked = cards(app_module, sectors=[sector()], command=[command])[0]
    assert blocked["action"] == "추격금지"
    assert blocked["values"]["안정도"] == pytest.approx(base["values"]["안정도"] - 1.2)


def test_etf_only_observation_does_not_authorize_its_static_stock_anchors(app_module):
    card = cards(app_module, sectors=[sector(섹터="방산", Ticker="SHLD")])[0]
    assert card["action"] != "정밀관측"
    assert card["raw_action"] == "정밀관측"
    assert card["representatives"] == "-"
    assert "록히드마틴" in card["anchor_representatives"]


def test_bare_etf_symbols_are_not_captured_individual_stocks(app_module):
    card = cards(app_module, command=[{"시장": "미국", "후보군": "반도체", "Ticker": "SOXX",
        "구분": "ETF", "ETF/대표": "SOXX", "대표주": "SOXX", "행동": "관심등록"}])[0]
    assert card["representatives"] == "-"
    assert card["etfs"] == "SOXX"


def test_explicit_sector_precedes_issuer_name_or_broad_connected_theme(app_module):
    result = cards(app_module, themes=[{"테마": "2차전지 밸류체인", "대표주": "롯데에너지머티리얼즈 (020150.KS)"}],
        command=[{"시장": "미국", "후보군": "산업재·원자재", "연결테마": "전력·인프라",
                  "세부축": "주택건설", "대표주": "DR호튼 (DHI)", "행동": "관심등록"}])
    assert {c["title"] for c in result} == {"2차전지·EV", "산업재·건설"}
    assert "DR호튼" in next(c for c in result if c["title"] == "산업재·건설")["representatives"]


def test_unquoted_cluster_reference_names_are_not_today_captured_stocks(app_module):
    card = cards(app_module, command=[{"시장": "미국", "후보군": "2차전지·EV", "핵심하위테마": "셀 메이커",
        "대표주": "테슬라 -, 토요타 모터스(ADR) -, 셔윈 윌리엄스 -", "행동": "관망/제외"}])[0]
    assert card["representatives"] == "-"
    assert card["anchor_representatives"] != "-"


def test_absolute_three_month_return_does_not_fall_back_to_relative_strength(app_module):
    row = sector(**{"돈흐름점수": np.nan, "1일수익률": np.nan, "5일수익률": np.nan,
        "2주수익률": np.nan, "1개월수익률": np.nan, "3M수익률": 0.20, "RS(3M)": -0.10})
    card = cards(app_module, sectors=[row])[0]
    assert card["values"]["강도"] > 5
    assert card["values"]["모멘텀"] > 5
    assert "단기유입" in card["missing_axes"]


def test_common_five_day_breadth_does_not_count_monthly_only_rows(app_module):
    rows = [sector(**{"5일수익률": -0.02}),
        sector(Ticker="CIBR", **{"5일수익률": np.nan, "1개월수익률": 0.10}),
        sector(Ticker="HACK", **{"5일수익률": np.nan, "1개월수익률": 0.10})]
    card = cards(app_module, sectors=rows)[0]
    assert card["short_basis"] == "5D"
    assert card["values"]["확산"] == 0
    assert card["action"] == "관망/제외"


def test_missing_measurements_are_not_normal_five_point_evidence(app_module):
    card = cards(app_module, command=[{"시장": "미국", "후보군": "사이버 보안", "행동": "정밀관측"}])[0]
    assert np.isnan(card["values"]["강도"])
    assert np.isnan(card["values"]["확산"])
    assert np.isnan(card["values"]["단기유입"])
    assert np.isnan(card["values"]["모멘텀"])
    assert np.isnan(card["total"])
    assert app_module._flow_stat_total_label(card) == "미산출"
    assert card["action"] != "정밀관측"


def test_market_summary_reuses_exact_sector_values_without_second_scoring(app_module):
    source = cards(app_module, sectors=[sector()])
    before = deepcopy(source)
    summary = app_module._flow_market_cards_from_sector_ability(source)
    assert summary[0]["values"] == source[0]["values"]
    assert summary[0]["action"] == source[0]["action"]
    assert source == before


def test_missing_benchmark_is_not_zero_return_or_entry_permission():
    from stock_lab_core.money_flow import calculate_sector_rotation_df
    frame = pd.DataFrame([{"구분": "미국 섹터", "섹터": "소프트웨어", "Ticker": "IGV",
        "3개월수익률": .20, "가속도": .10, "2주수익률": .05, "1주수익률": .03,
        "단기가속도": .05, "상태": "주도 유지", "기준일": "2026-10-30"}])
    result = calculate_sector_rotation_df(frame).iloc[0]
    assert np.isnan(result["RS(3M)"])
    assert result["3M수익률"] == .20
    assert result["사분면"] == "미확인"
    assert "관망" in result["진입검토"]
    assert result["기준일"] == "2026-10-30"


def test_sector_board_has_compact_first_table_without_removing_detailed_evidence(app_module):
    from streamlit.testing.v1 import AppTest
    source = cards(app_module, sectors=[sector()])
    app_module._test_flow_ability_cards = source
    try:
        ui = AppTest.from_string("import app\napp.render_sector_flow_ability_board(None,None,None,cards=app._test_flow_ability_cards)").run(timeout=20)
        assert not ui.exception
        frames = [element.value for element in ui.dataframe]
        assert len(frames) == 2
        assert list(frames[0]) == ["순위", "시장", "섹터", "최종읽기", "종합", "실행분류", "오늘 포착종목"]
        assert {"원천 관측신호", "미산출", "유효 능력치", "기준 대표축"}.issubset(frames[1])
        assert frames[0].iloc[0]["실행분류"] == source[0]["action"]
    finally:
        del app_module._test_flow_ability_cards


@pytest.mark.parametrize("day,rebuild", [("2026-10-30", False), ("2026-10-29", True)])
def test_actual_refresh_only_reuses_same_session_theme(app_module, monkeypatch, day, rebuild):
    app = app_module
    old = {"theme_flow_df": pd.DataFrame({"Ticker": ["NVDA"], "기준일": [day]}),
           "theme_rotation_df": pd.DataFrame({"test": [1]})}
    fresh = pd.DataFrame({"Ticker": ["NVDA"], "기준일": ["2026-10-30"]})
    built, cleared = [], []
    monkeypatch.setattr(app, "st", SimpleNamespace(session_state={}))
    monkeypatch.setattr(app, "IMAGE_THEME_FLOW_AVAILABLE", True)
    monkeypatch.setattr(app, "get_cached_today_market_flow_snapshot", lambda: old)
    monkeypatch.setattr(app, "calculate_money_flow_df", lambda: pd.DataFrame({"Ticker": ["SOXX"], "기준일": ["2026-10-30"]}))
    monkeypatch.setattr(app, "calculate_sector_rotation_df", lambda frame: pd.DataFrame())
    monkeypatch.setattr(app, "build_today_flow_rank_table", lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(app, "cache_clear", lambda fn: cleared.append(fn))
    monkeypatch.setattr(app, "_build_theme_flow_snapshot_payload", lambda: built.append(True) or {"theme_flow_df": fresh})
    result = app.refresh_today_market_flow_snapshot()
    assert bool(built) is rebuild
    assert (app.calculate_image_theme_flow_df in cleared) is rebuild
    assert result["theme_flow_df"].iloc[0]["기준일"] == "2026-10-30"
