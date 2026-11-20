"""Collect report earnings once; discovery and rendering never perform I/O."""

from copy import deepcopy

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import first, records
from stock_lab_core.performance import measure

register_loaded_source(__name__, __file__)


def _merge_discovered(events, results, discovered):
    """New results replace old results, not a later confirmed conference call."""
    events, results = list(events), list(results)
    for event in discovered["events"]:
        event = dict(event)
        ticker, period = event["ticker"], event["fiscal_period"]
        if event.get("source_kind") == "sec_discovered_release":
            older = [row for row in events if row.get("ticker") == ticker and row.get("event_status") == "released"]
            if any(str(row.get("fiscal_period", "")).removeprefix("FY") > period.removeprefix("FY") for row in older):
                continue
            for prior in events:
                if (prior.get("ticker") == ticker
                        and str(prior.get("fiscal_period", "")).removeprefix("FY") == period.removeprefix("FY")
                        and prior.get("conference_call_at")):
                    event["conference_call_at"] = prior["conference_call_at"]
                    event["conference_call_source_url"] = prior.get("source_url", "")
            events = [row for row in events if not (row.get("ticker") == ticker and
                      (str(row.get("fiscal_period", "")).removeprefix("FY") == period.removeprefix("FY")
                       or row.get("event_status") == "released"))]
            prior_results = [row for row in results if row.get("ticker") == ticker]
            results = [row for row in results if row.get("ticker") != ticker]
            for row in discovered["results"]:
                if row.get("ticker") != ticker:
                    continue
                row = deepcopy(row)
                for prior in prior_results:
                    if (prior.get("status") != "official_result" or prior.get("stale")
                            or str(prior.get("fiscal_period", "")).removeprefix("FY") != period.removeprefix("FY")
                            or prior.get("release_date") != row.get("release_date")):
                        continue
                    for key, metric in prior.get("metrics", {}).items():
                        if metric.get("status") == "reported" and row["metrics"].get(key, {}).get("status") == "missing":
                            row["metrics"][key] = {**deepcopy(metric), "enrichment_checked_at": prior.get("checked_at")}
                results.append(row)
        events.append(event)
    return events, results


def collect_report_earnings(summary_rows, calendar, now):
    from stock_lab_core.earnings_sources import load_official_earnings
    from stock_lab_core.earnings_result_sources import load_earnings_results
    from stock_lab_core.earnings_discovery import canonical_ticker, issuer_catalog
    from stock_lab_core.earnings_filing_sources import collect_filing_earnings

    requested = list(dict.fromkeys(canonical_ticker(first(row, "티커", "ticker"))
                                   for row in records(summary_rows)))
    catalog = issuer_catalog(summary_rows)
    eligible = [t for t in requested if t in catalog and catalog[t]["registered"]]
    tickers = sorted(eligible, key=lambda ticker: not catalog[ticker]["held"])
    with measure("external_data", "earnings_filing_discovery"):
        discovered = collect_filing_earnings(tickers[:96], now)
    fresh = {row["ticker"] for row in discovered["results"]}
    # The old verified IR sources remain a fallback, not the discovery universe.
    earnings = load_official_earnings([t for t in tickers if t not in fresh], now)
    updated = {row.get("ticker") for row in earnings["events"]}
    events = [r for r in calendar["events"] if r.get("ticker") not in updated] + earnings["events"]
    with measure("external_data", "earnings_result_reconciliation"):
        results = load_earnings_results(earnings["events"], now)
        if fresh:
            cached = load_earnings_results([row for row in discovered["events"] if row["ticker"] in fresh], now, refresh=False)
            results["results"].extend(cached["results"])
    events, actuals = _merge_discovered(events, results["results"], discovered)
    connected = {row["ticker"] for row in actuals if row.get("collection_reason") == "sec_exhibit_99_1"}
    return dict(calendar_events=events, earnings_sources=[*discovered["sources"],
                    *(row for row in earnings["sources"] if row.get("ticker") not in connected)],
                earnings_results=actuals, earnings_result_sources=[row for row in results["sources"] if row.get("ticker") not in connected],
                earnings_collection_scope={"requested": tickers, "submitted": tickers[:96],
                    "not_submitted": tickers[96:], "excluded_non_issuers": [t for t in requested if t not in eligible]})
