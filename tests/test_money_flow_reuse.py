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


@pytest.mark.parametrize("empty", [False, True])
def test_download_cache_keys_exact_provider_input_and_preserves_output_and_clear(monkeypatch, empty):
    from stock_lab_core.performance import PerformanceTrace

    frame = pd.DataFrame() if empty else make_price_df()
    frame.attrs["source"] = "deterministic provider"
    calls = []

    def download(tickers, **kwargs):
        calls.append((tickers, kwargs))
        return frame.copy(deep=True)

    monkeypatch.setattr(money_flow.yf, "download", download)
    monkeypatch.setattr(money_flow, "yahoo_session_kwargs", lambda: {})
    money_flow.download_money_flow_prices.clear()
    try:
        with PerformanceTrace() as trace:
            results = [money_flow.download_money_flow_prices(tickers) for tickers in (
                ("NVDA", "AMD"), ("AMD", "NVDA"), ("NVDA", "AMD", "NVDA"),
            )]
        assert len(calls) == 1
        assert calls[0] == (["AMD", "NVDA"], {
            "period": "1y", "interval": "1d", "progress": False, "group_by": "ticker",
            "threads": 2, "auto_adjust": False, "timeout": 8,
        })
        assert trace.report()["functions"][0]["calls"] == 3
        for result in results:
            pd.testing.assert_frame_equal(result, frame, check_exact=True)
            assert result.attrs == frame.attrs
        money_flow.download_money_flow_prices.clear(("NVDA", "AMD", "NVDA"))
        pd.testing.assert_frame_equal(money_flow.download_money_flow_prices(("AMD", "NVDA")), frame)
        assert len(calls) == 2
        money_flow.download_money_flow_prices(("MSFT",))
        assert len(calls) == 3  # Distinct provider requests must not share results.
        assert money_flow.download_money_flow_prices(("005930.KS",)).empty
        assert money_flow.download_money_flow_prices(()).empty
        assert len(calls) == 3
    finally:
        money_flow.download_money_flow_prices.clear()


def test_repeated_ohlc_wrappers_are_not_repeated_provider_requests(monkeypatch):
    from stock_lab_core import kr_flow_history
    from stock_lab_core.performance import PerformanceTrace

    provider_calls = []
    frame = make_price_df()

    def provider(ticker, **kwargs):
        provider_calls.append(ticker)
        return frame.copy()

    monkeypatch.setattr(kr_flow_history._reader, "read", provider)
    kr_flow_history.load_kr_flow_history.clear()
    try:
        universe = [{"ticker": ticker} for ticker in ("005930.KS", "000660.KS", "005930.KS")]
        with PerformanceTrace() as trace:
            first = money_flow._load_universe_metrics(pd.DataFrame(), universe)
            second = money_flow._load_universe_metrics(pd.DataFrame(), universe)
        pd.testing.assert_frame_equal(pd.DataFrame(first), pd.DataFrame(second), check_exact=True)
        wrapper = next(row for row in trace.report()["functions"] if row["name"] == "get_money_flow_ohlc")
        assert wrapper["calls"] == 4
        assert sorted(provider_calls) == ["000660.KS", "005930.KS"]
    finally:
        kr_flow_history.load_kr_flow_history.clear()
