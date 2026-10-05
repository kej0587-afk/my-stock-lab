"""External research links used by the Stock Lab UI.

The helpers here only build URLs. They do not scrape or score external sites,
so they are safe to use from Streamlit render paths.
"""

from __future__ import annotations

from urllib.parse import quote, quote_plus

from stock_lab_core.formatters import is_kr_listed, sanitize_ticker_value


def _clean_symbol(ticker: str) -> str:
    text = sanitize_ticker_value(ticker).upper()
    for suffix in (".KS", ".KQ"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _tradingview_symbol(ticker: str) -> str:
    symbol = _clean_symbol(ticker)
    if not symbol:
        return ""
    if is_kr_listed(ticker):
        return f"KRX:{symbol}"
    return symbol


def _stockanalysis_path(ticker: str) -> str:
    symbol = _clean_symbol(ticker).lower().replace(".", "-")
    return quote(symbol, safe="")


def build_research_links_for_ticker(ticker: str, name: str = "", is_etf: bool = False) -> list[dict]:
    """Return grouped external research links for one ticker."""
    ticker_clean = sanitize_ticker_value(ticker)
    symbol = _clean_symbol(ticker_clean)
    if not symbol:
        return []

    query = quote_plus(" ".join(x for x in [name, ticker_clean] if str(x).strip()) or symbol)
    encoded_symbol = quote(symbol, safe="")
    tv_symbol = quote(_tradingview_symbol(ticker_clean), safe="")
    kr_asset = is_kr_listed(ticker_clean)
    groups: list[dict] = []

    chart_links = [
        {"label": "TradingView", "url": f"https://www.tradingview.com/chart/?symbol={tv_symbol}"},
    ]
    if not kr_asset:
        chart_links.extend(
            [
                {"label": "FINVIZ", "url": f"https://finviz.com/quote.ashx?t={encoded_symbol}"},
                {"label": "StockCharts", "url": f"https://stockcharts.com/h-sc/ui?s={encoded_symbol}"},
            ]
        )
    groups.append({"category": "차트/종목", "links": chart_links})

    if kr_asset:
        groups.append(
            {
                "category": "국내 공시/기업",
                "links": [
                    {"label": "네이버 증권", "url": f"https://finance.naver.com/item/main.naver?code={quote(symbol, safe='')}"},
                    {"label": "DART", "url": f"https://dart.fss.or.kr/dsab007/main.do?option=corp&textCrpNm={quote_plus(symbol)}"},
                    {"label": "KIND", "url": "https://kind.krx.co.kr/"},
                    {"label": "KRX", "url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"},
                ],
            }
        )
    else:
        groups.append(
            {
                "category": "미국 공시/기업",
                "links": [
                    {"label": "Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{encoded_symbol}"},
                    {"label": "SEC EDGAR", "url": f"https://www.sec.gov/edgar/search/#/q={encoded_symbol}"},
                    {"label": "Stock Analysis", "url": f"https://stockanalysis.com/stocks/{_stockanalysis_path(symbol)}/"},
                    {"label": "Seeking Alpha", "url": f"https://seekingalpha.com/symbol/{encoded_symbol}"},
                ],
            }
        )

    if is_etf or symbol in {"SPY", "QQQ", "SOXX", "SOXL", "QLD", "MAGS", "CIBR", "BITX", "BITU", "RAM", "SGOV"}:
        groups.append(
            {
                "category": "ETF 분석",
                "links": [
                    {"label": "ETF.com", "url": f"https://www.etf.com/{encoded_symbol}"},
                    {"label": "ETFdb", "url": f"https://etfdb.com/etf/{encoded_symbol}/"},
                    {"label": "ETF Research Center", "url": "https://www.etfrc.com/funds/overlap.php"},
                ],
            }
        )

    groups.append(
        {
            "category": "수급/기관",
            "links": (
                [
                    {"label": "KRX", "url": "https://data.krx.co.kr/contents/MDC/MAIN/main/index.cmd"},
                    {"label": "KIND", "url": "https://kind.krx.co.kr/"},
                ]
                if kr_asset
                else [
                    {"label": "DATAROMA", "url": "https://www.dataroma.com/m/home.php"},
                    {"label": "WhaleWisdom", "url": f"https://whalewisdom.com/stock/{encoded_symbol}"},
                ]
            ),
        }
    )

    return groups


def build_research_home_link_groups() -> list[dict]:
    """Return broad macro/calendar research links from the reference image."""
    return [
        {
            "category": "경제지표/금리",
            "links": [
                {"label": "FRED", "url": "https://fred.stlouisfed.org/"},
                {"label": "한국은행 ECOS", "url": "https://ecos.bok.or.kr/"},
                {"label": "CME FedWatch", "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"},
            ],
        },
        {
            "category": "경제/실적 일정",
            "links": [
                {"label": "Investing.com Calendar", "url": "https://www.investing.com/economic-calendar/"},
                {"label": "Trading Economics", "url": "https://tradingeconomics.com/calendar"},
                {"label": "Nasdaq Earnings", "url": "https://www.nasdaq.com/market-activity/earnings"},
            ],
        },
    ]
