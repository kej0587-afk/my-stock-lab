import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_lab_core import money_flow as flow
from stock_lab_core.market_basis import positive_observation_fraction
from stock_lab_core.flow_snapshot import (
    can_reuse_theme_snapshot, flow_source_date_rows, flow_source_issue_rows, source_sessions,
)
from tests.fixtures_price import make_price_df


ROOT = Path(__file__).resolve().parents[1]


def test_old_block_symbol_resolves_once_and_ended_qorvo_is_not_downloaded():
    assert flow.normalize_money_flow_ticker("sq") == "XYZ"
    assert flow._money_flow_download_tickers(("SQ", "XYZ", "QRVO", "005930.KS")) == ("XYZ",)
    assert flow.normalize_money_flow_ticker("QRVO") == "QRVO"
    assert any(item["ticker"] == "XYZ" and item["name"] == "블록" for item in flow.IMAGE_THEME_UNIVERSE)
    assert not any(item["ticker"] == "SQ" for item in flow.IMAGE_THEME_UNIVERSE)


def test_direct_ended_listing_keeps_official_reason_and_never_uses_another_price(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("ended listings must not fetch or substitute a quote")

    monkeypatch.setattr(flow, "_fetch_fdr_ohlc", unexpected)
    monkeypatch.setattr(flow, "_fetch_alpha_vantage_ohlc", unexpected)
    frame = flow.get_money_flow_ohlc(pd.DataFrame({"Close": [999]}), "QRVO")
    assert frame.empty
    assert frame.attrs["listing_event"]["last_trading_date"] == "2026-10-02"
    assert frame.attrs["listing_event"]["source_url"].startswith("https://www.nasdaqtrader.com/")
    assert "transport_error" not in frame.attrs


def test_theme_retains_inactive_row_but_no_live_score_or_transport_failure(monkeypatch):
    universe = [{"ticker": t, "name": name, "테마": "A", "하위테마": "test"}
                for t, name in (("SQ", "블록"), ("QRVO", "Qorvo"), ("FAIL", "Unavailable"))]
    calls = []
    missing = pd.DataFrame()
    missing.attrs["transport_error"] = "ReadTimeout"
    monkeypatch.setattr(flow, "IMAGE_THEME_UNIVERSE", universe)
    monkeypatch.setattr(flow, "download_money_flow_prices", lambda _: pd.DataFrame())
    monkeypatch.setattr(flow, "get_money_flow_ohlc", lambda data, ticker: calls.append(ticker) or (
        missing if ticker == "FAIL" else make_price_df()))
    result = flow.calculate_image_theme_flow_df.__wrapped__("")
    assert calls == ["XYZ", "FAIL"]
    assert len(result) == 3
    assert result.attrs["history_failures"] == ["FAIL"]
    ended = result.set_index("Ticker").loc["QRVO"]
    assert pd.isna(ended["현재가"]) and pd.isna(ended["돈흐름점수"])
    assert ended["상태"] == "가격부족"  # Existing verdict vocabulary is unchanged.
    assert ended["상장상태"] == "거래종료"
    assert ended["마지막거래일"] == "2026-10-02"
    assert result.loc[result["Ticker"].eq("XYZ"), "돈흐름점수"].notna().all()


def frame(*rows):
    return pd.DataFrame(rows)


def test_old_symbol_or_unannotated_inactive_snapshot_cannot_be_reused():
    benchmark = frame({"Ticker": "XLF", "기준일": "2026-10-30"})
    valid = {"Ticker": "PYPL", "기준일": "2026-10-30", "돈흐름점수": 1}
    old_block = {"Ticker": "SQ", "기준일": None, "돈흐름점수": np.nan}
    ended = {"Ticker": "QRVO", "기준일": None, "돈흐름점수": np.nan}
    assert not can_reuse_theme_snapshot({"theme_flow_df": frame(valid, old_block)}, benchmark)
    assert not can_reuse_theme_snapshot({"theme_flow_df": frame(valid, ended)}, benchmark)
    ended["상장상태"] = "거래종료"
    assert can_reuse_theme_snapshot({"theme_flow_df": frame(valid, ended)}, benchmark)


def test_ended_listing_is_counted_separately_without_inventing_a_current_date():
    theme = frame({"Ticker": "XYZ", "기준일": "2026-10-30", "돈흐름점수": 2},
                  {"Ticker": "QRVO", "기준일": None, "상장상태": "거래종료", "돈흐름점수": None})
    dates = flow_source_date_rows({"theme_flow_df": theme})[0]
    assert dates["가격 기준일"] == "2026-10-30"
    assert dates["기준일 미확인"] == 0 and dates["거래종료"] == 1
    only_ended = theme.iloc[1:]
    assert source_sessions(only_ended) == {}
    assert flow_source_date_rows({"theme_flow_df": only_ended})[0]["가격 기준일"] == "미확인"


def test_missing_and_ended_evidence_rows_are_deduplicated_and_keep_source():
    theme = frame({"Ticker": "QRVO", "종목명": "Qorvo", "돈흐름점수": None,
                   "상장상태": "거래종료", "원자료사유": "합병", "공식출처": "https://www.nasdaqtrader.com/"},
                  {"Ticker": "QRVO", "종목명": "Qorvo", "돈흐름점수": None,
                   "상장상태": "거래종료", "원자료사유": "합병", "공식출처": "https://www.nasdaqtrader.com/"},
                  {"Ticker": "XYZ", "종목명": "Block", "돈흐름점수": 1},
                  {"Ticker": "MISSING", "돈흐름점수": None})
    rows = flow_source_issue_rows({"theme_flow_df": theme})
    assert [row["Ticker"] for row in rows] == ["QRVO", "MISSING"]
    assert rows[0]["자료상태"] == "거래종료"
    assert rows[0]["사유"] == "합병"
    assert rows[0]["공식출처"].startswith("https://www.nasdaqtrader.com/")
    assert flow_source_issue_rows({"theme_flow_df": pd.DataFrame()}) == []


@pytest.mark.parametrize("returns,expected", [([0.2, -0.1, 0.0, np.nan, np.inf], 1 / 3),
    ([np.nan, np.inf], np.nan), ([0.2, 0.1], 1.0), ([-0.1, 0.0], 0.0)])
def test_theme_positive_share_uses_only_finite_returns(returns, expected):
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "_th_pos_ratio"
                           for target in node.targets)]
    assert len(assignments) == 1
    scope = {"positive_observation_fraction": positive_observation_fraction,
             "theme_df": pd.DataFrame({"3개월수익률": returns})}
    exec(compile(ast.Module(body=assignments, type_ignores=[]), "<positive-share>", "exec"), scope)
    assert pd.isna(scope["_th_pos_ratio"]) if pd.isna(expected) else scope["_th_pos_ratio"] == pytest.approx(expected)
