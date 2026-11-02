"""Collect report earnings once; discovery and rendering never perform I/O."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, records, text
from stock_lab_core.performance import measure

register_loaded_source(__name__, __file__)


def collect_report_earnings(summary_rows, calendar, now):
    from stock_lab_core.earnings_sources import _ISSUERS, MAX_TICKERS, load_official_earnings
    from stock_lab_core.earnings_result_sources import load_earnings_results

    requested = list(dict.fromkeys(text(first(row, "티커", "ticker")).upper()
                                   for row in records(summary_rows)))
    # Preserve the existing bounded request order and provider behavior.
    tickers = list(dict.fromkeys(["000660.KS", "005930.KS", "NVDA", "GOOGL", "META", "MSFT", "TSLA",
                                *(t for t in requested if t in _ISSUERS), *requested]))
    earnings = load_official_earnings(tickers, now)
    updated = {row.get("ticker") for row in earnings["events"]}
    events = [r for r in calendar["events"] if r.get("ticker") not in updated] + earnings["events"]
    with measure("external_data", "earnings_result_reconciliation"):
        results = load_earnings_results(earnings["events"], now)
    return dict(calendar_events=events, earnings_sources=earnings["sources"],
                earnings_results=results["results"], earnings_result_sources=results["sources"],
                earnings_collection_scope={"requested": [t for t in tickers if t],
                    "submitted": [t for t in tickers[:MAX_TICKERS] if t],
                    "not_submitted": [t for t in tickers[MAX_TICKERS:] if t]})
