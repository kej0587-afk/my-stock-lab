import pandas as pd
import pytest

from stock_lab_core import money_flow
from tests.fixtures_price import make_price_df


@pytest.mark.parametrize("empty", [False, True])
def test_theme_reuses_metrics_without_removing_duplicate_theme_rows(monkeypatch, empty):
    universe = [
        {"ticker": "MSFT", "테마": "A", "하위테마": "A1", "name": "First"},
        {"ticker": "MSFT", "테마": "B", "하위테마": "B1", "name": "Second"},
        {"ticker": "NVDA", "테마": "A", "하위테마": "A2", "name": "Third"},
    ]
    frame = pd.DataFrame() if empty else make_price_df()
    fetches, calculations = [], []
    original = money_flow._compute_ticker_metrics
    def metrics(frame):
        calculations.append(True)
        return original(frame)
    monkeypatch.setattr(money_flow, "IMAGE_THEME_UNIVERSE", universe)
    monkeypatch.setattr(money_flow, "download_money_flow_prices", lambda *a: frame)
    monkeypatch.setattr(money_flow, "get_money_flow_ohlc", lambda data, ticker: fetches.append(ticker) or frame)
    monkeypatch.setattr(money_flow, "_compute_ticker_metrics", metrics)
    result = money_flow.calculate_image_theme_flow_df.__wrapped__("")
    assert fetches == ["MSFT", "NVDA"]
    assert len(calculations) == (0 if empty else 2)
    assert len(result) == 3
    assert set(result["종목명"]) == {"First", "Second", "Third"}
    if not empty:
        for _, row in result.iterrows():
            for key, value in original(frame).items():
                assert row[key] == pytest.approx(value) if isinstance(value, float) else row[key] == value
    else:
        assert set(result["상태"]) == {"가격부족"}


def test_flow_rank_bonus_does_not_mutate_reused_metrics(monkeypatch):
    universe = [
        {"ticker": "MSFT", "구분": "US", "섹터": "A", "name": "First", "랭킹보조점수": 1},
        {"ticker": "MSFT", "구분": "US", "섹터": "B", "name": "Second", "랭킹보조점수": 3},
    ]
    original_metrics = {"돈흐름점수": 5.0, "3개월수익률": 0.1}
    calls = []
    frame = pd.DataFrame({"Close": range(30)})
    monkeypatch.setattr(money_flow, "build_money_flow_universe_with_naver_rankings", lambda: universe)
    monkeypatch.setattr(money_flow, "download_money_flow_prices", lambda *a: frame)
    monkeypatch.setattr(money_flow, "get_money_flow_ohlc", lambda *a: calls.append(True) or frame)
    monkeypatch.setattr(money_flow, "_compute_ticker_metrics", lambda *a: original_metrics)
    result = money_flow.calculate_money_flow_df.__wrapped__()
    assert len(calls) == 1
    assert len(result) == 2
    assert result.set_index("섹터")["돈흐름점수"].to_dict() == {"A": 6, "B": 8}
    assert original_metrics == {"돈흐름점수": 5.0, "3개월수익률": 0.1}
