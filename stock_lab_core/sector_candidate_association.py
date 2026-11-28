"""Identify a sector candidate's market without changing its flow metrics."""

import re

from stock_lab_core.report_build import register_loaded_source


_MARKETS = {
    "한국": "한국", "한국 섹터": "한국", "KR": "한국", "KOSPI": "한국", "KOSDAQ": "한국",
    "미국": "미국", "미국 섹터": "미국", "US": "미국", "USA": "미국", "NYSE": "미국", "NASDAQ": "미국",
}


def _text(value):
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"", "-", "nan", "none", "<na>"} else text


def _ticker_market(value):
    symbol = _text(value).upper()
    if re.fullmatch(r"[0-9][A-Z0-9]{5}(?:\.(?:KS|KQ))?", symbol):
        return "한국"
    if symbol in {"BRK.A", "BRK.B"}:
        return "미국"
    if re.fullmatch(r"[A-Z][A-Z0-9-]*", symbol) and not symbol.endswith("-USD"):
        return "미국"
    return ""


def sector_market_from_row(row):
    """Match explicit market labels and instrument identities, never ``BRK-B``'s K-.

    The app adapter can delegate `_flow_sector_market_from_row` here. This
    function only returns ownership; source rows and all numerical fields stay
    untouched. Unidentified markets remain mixed rather than defaulting to US.
    """
    for column in ("시장축", "시장", "구분"):
        market = _MARKETS.get(_text(row.get(column)).upper())
        if market:
            return market
    for column in ("Ticker", "티커"):
        ticker = _text(row.get(column))
        if ticker:
            return _ticker_market(ticker) or "혼합"
    for column in ("대표주", "대표주★", "업종대표주"):
        tickers = re.findall(r"\(([A-Za-z0-9.^-]+)\)", _text(row.get(column)))
        markets = {_ticker_market(ticker) for ticker in tickers}
        if markets:
            return next(iter(markets)) if len(markets) == 1 and "" not in markets else "혼합"
    # Theme/category words may supply ownership when no instrument is known.
    # Representative names and ticker fragments are never market keywords.
    context = " ".join(_text(row.get(column)) for column in ("후보군", "연결테마", "테마", "섹터"))
    kr = bool(re.search(r"한국|국내|(?<![A-Za-z0-9])K-", context))
    us = "미국" in context
    if kr != us:
        return "한국" if kr else "미국"
    return "혼합"


register_loaded_source(__name__, __file__)
