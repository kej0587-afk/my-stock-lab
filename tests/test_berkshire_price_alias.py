import pandas as pd
import pytest

from stock_lab_core import prices


@pytest.fixture(autouse=True)
def isolate_batch_cache():
    prices.load_price_frames_batch.clear()
    yield
    prices.load_price_frames_batch.clear()


def history(symbols, ticker_first=False):
    frame = pd.DataFrame(
        [[500.0 + i for i in range(len(symbols))]],
        index=pd.to_datetime(["2026-11-25"]),
        columns=pd.MultiIndex.from_product([["Close"], symbols]),
    )
    if ticker_first:
        frame.columns = frame.columns.swaplevel()
    return frame


@pytest.mark.parametrize("symbol,provider", [("BRK.B", "BRK-B"), ("BRK.A", "BRK-A"), ("BRK-B", "BRK-B")])
def test_single_history_alias_only_at_provider_boundary(monkeypatch, symbol, provider):
    calls, alignments = [], []
    def download(ticker, **kwargs):
        calls.append(ticker)
        return history([provider]) if ticker == provider else pd.DataFrame()
    monkeypatch.setattr(prices.yf, "download", download)
    monkeypatch.setattr(prices, "_maybe_align_ohlcv_to_live_price", lambda ticker, frame: alignments.append(ticker) or frame)
    result = prices._fetch_yfinance_ohlcv(symbol)
    assert not result.empty
    assert calls == [provider]
    assert alignments == [symbol]
    assert prices.normalize_price_lookup_key(symbol) == symbol


@pytest.mark.parametrize("ticker_first", [False, True])
def test_batch_maps_provider_columns_to_requested_keys(monkeypatch, ticker_first):
    calls = []
    source = history(["BRK-B", "MSFT"], ticker_first)
    original = source.copy(deep=True)
    def download(tickers, **kwargs):
        calls.append(tickers)
        return source
    monkeypatch.setattr(prices.yf, "download", download)
    result = prices.load_price_frames_batch(("BRK.B", "MSFT"))
    assert calls == [["BRK-B", "MSFT"]]
    assert set(result) == {"BRK.B", "MSFT"}
    assert result["BRK.B"].Close.iloc[-1] == 500
    assert result["MSFT"].Close.iloc[-1] == 501
    pd.testing.assert_frame_equal(source, original)


def test_batch_deduplicates_alias_requests_without_losing_app_keys(monkeypatch):
    calls = []
    monkeypatch.setattr(prices.yf, "download", lambda tickers, **kwargs: calls.append(tickers) or history(["BRK-B"]))
    result = prices.load_price_frames_batch(("BRK.B", "BRK-B"))
    assert calls == [["BRK-B"]]
    assert set(result) == {"BRK.B", "BRK-B"}
    result["BRK.B"].iloc[0, 0] = 999
    assert result["BRK-B"].Close.iloc[-1] == 500


def test_missing_alias_never_borrows_another_symbol(monkeypatch):
    monkeypatch.setattr(prices.yf, "download", lambda *args, **kwargs: history(["MSFT"]))
    assert set(prices.load_price_frames_batch(("BRK.B", "MSFT"))) == {"MSFT"}
    assert prices._fetch_yfinance_ohlcv("BRK.B").empty


@pytest.mark.parametrize("symbol", ["005930.KS", "035720.KQ", "VOD.L", "BTC-USD", "^GSPC", "MSFT"])
def test_other_provider_symbols_unchanged(symbol):
    assert prices._yfinance_history_candidates(symbol) == [symbol]
