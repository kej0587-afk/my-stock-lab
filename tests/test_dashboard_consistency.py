import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import money_flow, prices


def test_legacy_prices_does_not_break_startup(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    guarded_import = next(node for node in tree.body if isinstance(node, ast.Try)
                          and any(isinstance(child, ast.ImportFrom) and child.module == "stock_lab_core.prices"
                                  and any(alias.name == "fetch_yahoo_display_metadata" for alias in child.names)
                                  for child in node.body))
    monkeypatch.delattr(prices, "fetch_yahoo_display_metadata")
    monkeypatch.setattr(prices, "_fetch_yahoo_chart", lambda *args: (1.0, {"symbol": "XLK", "longName": "Full ETF name"}))
    namespace = {}
    exec(compile(ast.Module(body=[guarded_import], type_ignores=[]), str(path), "exec"), namespace)
    assert namespace["fetch_yahoo_display_metadata"]("XLK")["longName"] == "Full ETF name"


def test_metrics_emit_daily_and_weekly_returns():
    close = np.linspace(100.0, 150.0, 160)
    frame = pd.DataFrame({"Close": close, "High": close + 1, "Low": close - 1, "Volume": 1000})
    result = money_flow._compute_ticker_metrics(frame)
    assert result["1일수익률"] == pytest.approx(close[-1] / close[-2] - 1)
    assert result["5일수익률"] == result["1주수익률"]


def _sector(**overrides):
    return {"구분": "미국 섹터", "섹터": "소프트웨어", "Ticker": "IGV", "돈흐름점수": 80.0,
            "1일수익률": -0.03, "5일수익률": -0.04, "2주수익률": 0.08,
            "1개월수익률": 0.12, "3개월수익률": 0.30, "가격수준": 0.5, "진입검토": "정밀관측", **overrides}


def test_positive_three_months_cannot_override_negative_week(app_module):
    cards = app_module._flow_sector_ability_cards(pd.DataFrame(), pd.DataFrame([_sector()]), pd.DataFrame())
    assert cards[0]["action"] == "관망/제외"
    assert cards[0]["short_basis"] == "5D"
    assert cards[0]["short"] == -0.04
    assert cards[0]["values"]["강도"] > cards[0]["values"]["타점"]


def test_sector_rank_is_deterministic_and_market_local(app_module):
    rows = [_sector(), _sector(Ticker="CIBR", 섹터="사이버보안", **{"5일수익률": 0.02}),
            _sector(Ticker="143860.KS", 섹터="바이오", 구분="한국 섹터", **{"5일수익률": 0.01})]
    def build(data):
        return app_module._flow_sector_ability_cards(pd.DataFrame(), pd.DataFrame(data), pd.DataFrame())
    left, right = build(rows), build(rows[::-1])
    assert [(x["market"], x["title"], x["rank"]) for x in left] == [(x["market"], x["title"], x["rank"]) for x in right]
    assert next(x for x in left if x["market"] == "한국")["rank"] == 1
    assert next(x for x in left if x["market"] == "미국")["rank"] == 1


def test_recent_periods_are_not_averaged_together(app_module):
    rows = [_sector(), _sector(Ticker="CIBR", 섹터="사이버보안", **{"5일수익률": np.nan, "2주수익률": 0.90})]
    cards = app_module._flow_sector_ability_cards(pd.DataFrame(), pd.DataFrame(rows), pd.DataFrame())
    assert cards[0]["short"] == -0.04
    assert cards[0]["short_basis"] == "5D"


def test_cluster_uses_snapshot_returns_without_new_lookup(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_load_index_rotation_recent_returns", lambda *args: pytest.fail("Snapshot already has returns"))
    monkeypatch.setattr(app_module, "_get_market_cluster_snapshot_cached", lambda *args, **kwargs: {})
    row = _sector(**{"RS(3M)": 0.30, "RS모멘텀": 0.10, "사분면": "주도", "단기가속도": 0.05})
    result = app_module._build_cluster_list(pd.DataFrame([row]), {"소프트웨어": ["IGV"]}, market_key="미국")
    assert result[0]["timing_state"] == "하락 중"
    assert result[0]["r5d"] == -0.04


def test_unified_radar_is_lazy_and_reuses_same_snapshot(app_module, monkeypatch):
    from streamlit.testing.v1 import AppTest

    snapshot = {"saved": True}
    calls = []
    monkeypatch.setattr(app_module, "get_cached_today_market_flow_snapshot", lambda: snapshot)
    monkeypatch.setattr(app_module, "render_today_market_flow_panel", lambda value, **kwargs: calls.append(value))
    monkeypatch.setattr(app_module, "render_money_flow_etf_section", lambda: pytest.fail("Hidden ETF view ran"))
    monkeypatch.setattr(app_module, "render_image_theme_flow_section", lambda: pytest.fail("Hidden theme view ran"))
    app = AppTest.from_string("import app\napp.render_money_flow_tab()").run()
    assert not app.exception
    assert calls == [snapshot]


def test_adjusting_theme_cannot_be_promoted_back_to_precision(app_module):
    action, _ = app_module._unified_flow_action(cluster_label="주도", theme_signal="주도 후 조정", cluster_timing="진입 가능", price_level=0.5)
    assert app_module.normalize_flow_action_label(action) != "정밀관측"
    assert app_module._adjust_flow_command_action({"통합판정": "정밀관측", "5D": -0.01}) == "관망/제외"
    action, _ = app_module._unified_flow_action(cluster_label="주도", theme_signal="주도 후 조정", theme_state="극단과열", cluster_timing="진입 가능", price_level=0.99)
    assert app_module.normalize_flow_action_label(action) == "추격금지"


def test_kiwoom_diagnostics_do_not_expose_keys_or_invalid_environment():
    from stock_lab_core.kiwoom_data import KiwoomConfig, KiwoomDataClient
    client = KiwoomDataClient(KiwoomConfig(enabled=True, appkey="PRIVATE", secretkey="SECRET", environment=[]))
    assert client.connection_info == {"status": "invalid_configuration", "environment": ""}
    assert "PRIVATE" not in str(client.connection_info)


def test_semiconductor_materials_etf_is_connected_to_domestic_cluster():
    assert any(row["ticker"] == "455850.KS" for row in money_flow.MONEY_FLOW_UNIVERSE)
    assert "455850.KS" in money_flow.SECTOR_CLUSTERS_KR["AI·반도체"]
    assert "456600.KS" not in money_flow.SECTOR_CLUSTERS_KR["AI·반도체"]


def test_guard_average_uses_same_representative_policy_as_memo(app_module):
    frame = pd.DataFrame({"티커": ["^KS11", "069500.KS", "^KQ11"], "1일": [-0.05, -0.064, -0.03]})
    result = app_module._today_benchmark_guard_stats(frame)
    assert result["avg_day"] == pytest.approx(-0.04)
    assert set(result["avg_day_tickers"]) == {"^KS11", "^KQ11"}


def test_demo_kiwoom_panel_does_not_blame_secret_settings(app_module, monkeypatch):
    messages = []
    monkeypatch.setattr(app_module, "IS_PUBLIC_DEMO", True)
    monkeypatch.setattr(app_module.st, "info", messages.append)
    monkeypatch.setattr(app_module, "get_kiwoom_data_client", lambda: pytest.fail("Demo must not read credentials"))
    app_module.render_kiwoom_market_evidence("test")
    assert len(messages) == 1 and "체험모드" in messages[0]
    assert "enabled" not in messages[0]
