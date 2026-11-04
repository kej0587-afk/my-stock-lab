"""Roundhill's published holdings feed, not its static marketing top-exposures."""

from datetime import timedelta
import re
import time
from zoneinfo import ZoneInfo

from stock_lab_core.etf_holdings import _csv, _day, _kind, _row, _snapshot, _Unavailable


def parse_roundhill(data, symbol):
    _, rows = _csv(data, {"Date", "Account", "StockTicker", "SecurityName", "Weightings"})
    rows = [r for r in rows if r["Account"].strip().upper() == symbol]
    dates = {_day(r["Date"]) for r in rows}
    if not rows or len(dates) != 1 or None in dates:
        raise _Unavailable("roundhill_holdings_date_or_account_missing")
    # The issuer's app.js displays CSV Date minus one calendar day.
    from datetime import date
    as_of = (date.fromisoformat(dates.pop()) - timedelta(days=1)).isoformat()
    result = []
    for r in rows:
        raw, name = r["StockTicker"].strip(), r["SecurityName"].strip()
        kind = "cash" if r.get("MoneyMarketFlag") == "Y" else _kind(name, raw)
        ticker = None
        if kind == "unknown":
            if re.fullmatch(r"\d{6} KS", raw):
                ticker = raw[:6] + ".KS"
            elif re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", raw):
                ticker = raw
            kind = "security" if ticker else "unknown"
        result.append(_row(name, ticker, r["Weightings"], kind,
                           verified=bool(ticker), source_symbol=raw))
    return result, as_of


def collect_roundhill(symbol, *, now, fetch, timeout=8):
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    deadline, failures = time.monotonic() + timeout, []
    last_url = "https://www.roundhillinvestments.com/etf/" + symbol.lower() + "/"
    # At most four dated files; the same total deadline covers weekend fallback.
    for offset in range(4):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        candidate = day - timedelta(days=offset)
        path = (f"rex_data/rex_ram_holdings_{candidate:%Y%m%d}.csv" if symbol == "RAM"
                else f"filepointroundhill.40ru.ru_holdings_{candidate:%m%d%Y}.csv")
        last_url = "https://www.roundhillinvestments.com/assets/data/" + path
        try:
            data = fetch(last_url, timeout=remaining)
            rows, as_of = parse_roundhill(data, symbol)
            if time.monotonic() > deadline:
                raise _Unavailable("collection_deadline")
            return _snapshot(symbol, "US", now, rows=rows, as_of=as_of,
                             source="Roundhill official holdings", source_url=last_url,
                             scope="all_reported", holdings_basis="reported",
                             reason="issuer_csv_date_minus_one; derivative_weights_are_not_daily_exposure")
        except Exception as exc:
            failures.append(str(exc) if isinstance(exc, _Unavailable) else "request_timeout_or_invalid_response")
    return _snapshot(symbol, "US", now, source="Roundhill official holdings", source_url=last_url,
                     reason="; ".join(dict.fromkeys(failures)) or "collection_deadline")


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
