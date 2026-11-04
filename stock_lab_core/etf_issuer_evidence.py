"""Dated ETF membership and explicit one-issuer earnings collection, read only."""

from datetime import datetime, timedelta, timezone

from stock_lab_core.earnings_discovery import canonical_ticker
from stock_lab_core.report_evidence import records, safe_link, stamp

# Only RAM's documented underlying is used as look-through evidence. Other
# benchmark ETFs are comparisons, not proof of the held fund's composition.
UNDERLYING_FUNDS = {"RAM": "DRAM"}


def verified_members(snapshot, now):
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    observed, as_of = stamp(snapshot.get("observed_at")), stamp(snapshot.get("as_of"))
    url = safe_link(snapshot.get("source_url"))
    if (snapshot.get("status") not in {"ok", "partial"}
            or snapshot.get("holdings_basis") in {"unverified_reference", "provider_reported_unverified", "historical_reference"}
            or not observed or not as_of or not url
            or not timedelta(0) <= now - observed <= timedelta(hours=1)
            or not 0 <= (now.date() - as_of.date()).days <= 7):
        return []
    return [r for r in records(snapshot.get("rows"))
            if r.get("reviewable") and r.get("kind") in {"security", "equity", "stock"}
            and canonical_ticker(r.get("ticker"))]


def related_issuers(ticker, state, now):
    linked = {canonical_ticker(ticker): ("직접 기업", "")}
    for symbol in dict.fromkeys([ticker, UNDERLYING_FUNDS.get(ticker)]):
        if not symbol:
            continue
        snapshot = state.get("etf_constituents_" + symbol) or {}
        for row in verified_members(snapshot, now):
            label = "구성기업 간접" if symbol == ticker else f"기초 ETF {symbol} 구성기업 · 보유 ETF 직접비중 아님"
            linked[canonical_ticker(row["ticker"])] = (
                label + " · 구성 " + snapshot["as_of"], safe_link(snapshot.get("source_url")))
    return linked


def collect_issuer_earnings(ticker, name="", *, now=None):
    from stock_lab_core.earnings_sources import load_official_earnings
    from stock_lab_core.earnings_result_sources import load_earnings_results
    from stock_lab_core.earnings_pipeline import build_earnings_pipeline
    fixed_now = now is not None
    now = stamp(now or datetime.now(timezone.utc).isoformat())
    official = load_official_earnings([ticker], now)
    result = load_earnings_results(official["events"], now)
    if not fixed_now:
        now = stamp(datetime.now(timezone.utc).isoformat())
    context = dict(calendar_events=official["events"], earnings_sources=official["sources"],
                   earnings_results=result["results"], earnings_result_sources=result["sources"],
                   earnings_collection_scope={"requested": [ticker]})
    pipeline = build_earnings_pipeline(context, [{"티커": ticker, "종목명": name or ticker}], now=now)
    return dict(checked_at=now.isoformat(), earnings=pipeline["packets"],
                earnings_missing=pipeline["coverage"]["missing"])


def merge_issuer_evidence(data, linked, state, now):
    """Only fresh explicitly collected issuers; never stamp old market data anew."""
    merged = dict(data or {})
    merged["earnings"] = list(merged.get("earnings") or [])
    merged["earnings_missing"] = list(merged.get("earnings_missing") or [])
    for ticker in linked:
        extra = state.get("etf_issuer_earnings_" + ticker) or {}
        checked = stamp(extra.get("checked_at"))
        if checked is None or not timedelta(0) <= now - checked <= timedelta(minutes=30):
            continue
        for key in ("earnings", "earnings_missing"):
            merged[key] = [r for r in merged[key] if canonical_ticker(r.get("ticker")) != ticker]
            merged[key].extend(r for r in extra.get(key, []) if canonical_ticker(r.get("ticker")) == ticker)
    return merged


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
