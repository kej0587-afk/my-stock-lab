"""Bounded ETF holdings snapshots, independent of Streamlit and price fetching.

Integration::

    snapshot = load_etf_holdings(ticker, kr_catalog=catalog, force_refresh=False)
    candidates = [r for r in snapshot["rows"] if r["reviewable"] and r["ticker"]]

``fetch(url, *, timeout=seconds)`` may supply bytes, text, or decoded JSON for
offline use. Injected transports must honor their timeout; they use no shared
cache unless an explicit ``ETFHoldingsCache`` is passed. ``now`` is an optional
datetime (naive means UTC). Network collection has an eight second budget,
bounded response sizes, no redirects, and no retries. No request runs at import.

Weights are the provider's percentage points, without rounding, normalization,
or conversion into daily economic exposure. Derivatives can exceed 100%.
``as_of`` is ONLY a holdings date; unknown dates are None. ``observed_at`` is
the UTC retrieval time, retained when an older snapshot is served from cache.
Scopes are all_reported, partial, top10, top5, or none. Naver reports a creation
basket, which need not describe the fund's entire economic exposure.

KR symbols keep a .KS/.KQ suffix only when the source RIC confirms it; bare
codes have exchange_unknown=True so the UI can request a market selection.
A reviewable row identifies a quoted security, not a recommendation or
a claim that its weight explains ETF flows. Yahoo's untyped top ten are a
partial, unverified fallback; they are not promoted to actual shares. The
SOXL route never substitutes an underlying ETF or Yahoo's top ten.
"""

from collections import OrderedDict
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
from io import StringIO
import json
import math
import re
import threading
import time
from urllib.parse import urlsplit

from lxml import html
import requests


SOXX_URL = ("https://www.ishares.com/us/products/239705/"
            "ishares-semiconductor-etf/latest-holdings.csv")
QQQ_URL = ("https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/"
           "QQQ/holdings/fund?productType=ETF&interval=monthly&idType=ticker")
CIBR_URL = "https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=CIBR"
SOXL_URL = "https://www.direxion.com/holdings/SOXL.csv"
NAVER_URL = "https://stock.naver.com/api/domestic/detail/{code}/ETFComponent"
MAX_BYTES = 2_000_000
MAX_ROWS = 2500
_MONTHS = {s: i for i, s in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


class _Unavailable(ValueError):
    pass


class ETFHoldingsCache:
    """Bounded per-symbol cache; failed refreshes never replace a good snapshot.

    Times are monotonic seconds. Success TTL defaults to 1h, failure TTL to
    30s, and maximum age of a retained success to 24h since retrieval. A stale
    response never extends that age. Returned dictionaries are independent.
    """

    def __init__(self, *, max_entries=128, success_ttl=3600, failure_ttl=30,
                 stale_ttl=86400, clock=None):
        self.max_entries = max(1, min(int(max_entries), 512))
        self.success_ttl = max(0, min(float(success_ttl), 86400))
        self.failure_ttl = max(0, min(float(failure_ttl), 60))
        self.stale_ttl = max(self.success_ttl, min(float(stale_ttl), 604800))
        self.clock = clock or time.monotonic
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def clear(self):
        with self.lock:
            self.entries.clear()

    def _read(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is not None:
                self.entries.move_to_end(key)
            return deepcopy(entry)

    def _write(self, key, snapshot):
        with self.lock:
            entry = self.entries.setdefault(key, {})
            if snapshot["status"] == "ok":
                entry.clear()
                entry.update(good=deepcopy(snapshot), good_at=self.clock())
            else:
                entry.update(failure=deepcopy(snapshot), failed_at=self.clock())
            self.entries.move_to_end(key)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)


_CACHE = ETFHoldingsCache()


def clear_etf_holdings_cache():
    """Clear this module's default cache only."""
    _CACHE.clear()


def _text(value):
    if value is None or isinstance(value, bool):
        return ""
    result = str(value).strip()
    return "" if result.lower() in {"nan", "none", "<na>", "nat", "null"} else result


def _number(value):
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool):
        return None
    try:
        result = float(_text(value).replace(",", "").rstrip("%"))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _identity(ticker):
    symbol = _text(ticker).upper()
    suffix = symbol.endswith((".KS", ".KQ"))
    code = symbol[:-3] if suffix else symbol
    if re.fullmatch(r"\d{1,6}", code):
        return code.zfill(6), "KR"
    if re.fullmatch(r"[A-Z0-9]{6}", code) and (suffix or any(c.isdigit() for c in code)):
        return code, "KR"
    if not suffix and re.fullmatch(r"[A-Z][A-Z0-9]{0,9}(?:[.-][A-Z0-9]{1,3})?", symbol):
        return symbol, "US"
    raise _Unavailable("invalid_ticker")


def _day(value):
    text = _text(value)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", text):
            return date.fromisoformat(text[:10]).isoformat()
        if re.fullmatch(r"\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})(?: 12:00:00 AM)?", text)
        if match:
            return date(int(match[3]), int(match[1]), int(match[2])).isoformat()
        match = re.fullmatch(r"([A-Za-z]+)\.? (\d{1,2}), (\d{4})", text)
        if match and match[1][:3].lower() in _MONTHS:
            return date(int(match[3]), _MONTHS[match[1][:3].lower()], int(match[2])).isoformat()
    except ValueError:
        pass
    return None


def _kind(name, asset_type=""):
    text = (name + " " + asset_type).upper()
    if re.search(r"\b(?:SWAP|TRS)\b|스왑", text):
        return "swap"
    if "FUTURE" in text or "선물" in text:
        return "futures"
    if "OPTION" in text or "옵션" in text:
        return "option"
    if (any(word in text for word in ("CASH", "MONEY MARKET", "COLLATERAL", "현금", "예금", "증거금"))
            or name.startswith(("US Dollar", "Canadian Dollar"))):
        return "cash"
    if any(word in text for word in ("COMMON STOCK", "EQUITY", "PREFERRED STOCK", "ADR")):
        return "equity"
    if any(word in text for word in (" ETF", " FUND", "TIGER ", "KODEX ", "TREASURY INST", "TRSRY INST", "TRSY CAPITAL")):
        return "fund"
    if any(word in text for word in ("BOND", "TREASURY NOTE", "TREASURY BILL", "채권")):
        return "bond"
    return "unknown"


def _row(name, symbol, weight, kind, *, verified=False, source_symbol=None):
    name, symbol = _text(name), _text(symbol).upper()
    valid = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,19}", symbol))
    reviewable = verified and valid and kind in {"equity", "security", "fund"}
    # Retain raw derivative identifiers separately; they are not quote targets.
    return dict(name=name, ticker=symbol if reviewable else None,
                weight_pct=_number(weight), kind=kind, reviewable=bool(reviewable),
                source_ticker=_text(source_symbol if source_symbol is not None else symbol) or None)


def _snapshot(symbol, market, now, *, rows=None, source=None, source_url=None,
              as_of=None, scope="none", reason="", holdings_basis="reported"):
    rows = rows or []
    issues = [reason] if reason else []
    status = "ok" if rows else "unavailable"
    if rows and not as_of:
        status = "partial"
        issues.append("holdings_as_of_unavailable")
    if rows and scope in {"partial", "top10", "top5"}:
        status = "partial"
        issues.append("partial_holdings_scope")
    if any(r["weight_pct"] is None for r in rows):
        status = "partial"
        issues.append("some_weights_unavailable")
    return dict(ticker=symbol, market=market, rows=rows, source=source,
                source_url=source_url, as_of=as_of, observed_at=now.isoformat(),
                status=status, scope=scope, reason="; ".join(issues),
                holdings_basis=holdings_basis, from_cache=False)


def _http_fetch(url, *, timeout):
    deadline = time.monotonic() + timeout
    headers = {"User-Agent": "Mozilla/5.0 StockLab/1.0"}
    host = (urlsplit(url).hostname or "").lower()
    if host == "naver.com" or host.endswith(".naver.com"):
        headers["Referer"] = "https://stock.naver.com/"
    response = requests.get(url, stream=True, allow_redirects=False,
                            timeout=(min(2.0, timeout / 2), min(3.0, timeout / 2)),
                            headers=headers)
    try:
        if response.status_code != 200:
            raise _Unavailable("http_" + str(response.status_code))
        if int(response.headers.get("Content-Length", "0")) > MAX_BYTES:
            raise _Unavailable("response_too_large")
        parts, size = [], 0
        for chunk in response.iter_content(chunk_size=16384):
            if time.monotonic() >= deadline:
                raise _Unavailable("collection_deadline")
            size += len(chunk)
            if size > MAX_BYTES:
                raise _Unavailable("response_too_large")
            parts.append(chunk)
        return b"".join(parts)
    finally:
        response.close()


def _body(data):
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise _Unavailable("response_too_large")
        return data.decode("utf-8-sig")
    if isinstance(data, str) and len(data.encode("utf-8")) <= MAX_BYTES:
        return data.lstrip("\ufeff")
    raise _Unavailable("invalid_response")


def _json(data):
    if isinstance(data, (dict, list)):
        if len(json.dumps(data).encode("utf-8")) > MAX_BYTES:
            raise _Unavailable("response_too_large")
        return data
    return json.loads(_body(data))


def _bounded_rows(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise _Unavailable("invalid_holdings_rows")
    if any(not isinstance(r, dict) for r in rows):
        raise _Unavailable("invalid_holdings_rows")
    return rows


def _csv(data, required):
    records = list(csv.reader(StringIO(_body(data), newline=None)))
    if len(records) > MAX_ROWS + 200:
        raise _Unavailable("too_many_rows")
    for i, cells in enumerate(records[:40]):
        if required.issubset(cells):
            rows = []
            for cells_row in records[i + 1:]:
                if not any(c.strip() for c in cells_row):
                    continue
                if len(cells_row) != len(cells):
                    break  # Issuer CSVs can end with a free-text disclaimer.
                rows.append(dict(zip(cells, cells_row)))
            return records[:i], _bounded_rows(rows)
    raise _Unavailable("holdings_csv_header_unrecognized")


def _ishares(data):
    preamble, records = _csv(data, {"Ticker", "Name", "Asset Class", "Weight (%)"})
    dates = [_day(r[1]) for r in preamble if len(r) > 1 and r[0] == "Fund Holdings as of"]
    rows = [_row(r["Name"], r["Ticker"], r["Weight (%)"],
                 _kind(r["Name"], r["Asset Class"]), verified=True) for r in records]
    return rows, dates[0] if len(dates) == 1 else None, "all_reported", "", "reported"


def _direxion(data):
    _, records = _csv(data, {"TradeDate", "AccountTicker", "StockTicker", "SecurityDescription", "HoldingsPercent"})
    if any(r["AccountTicker"] != "SOXL" for r in records):
        raise _Unavailable("fund_identity_mismatch")
    dates = {_day(r["TradeDate"]) for r in records}
    if len(dates) > 1:
        raise _Unavailable("mixed_holdings_dates")
    rows = []
    for r in records:
        kind = _kind(r["SecurityDescription"])
        if kind == "unknown" and r["StockTicker"]:
            kind = "security"
        rows.append(_row(r["SecurityDescription"], r["StockTicker"], r["HoldingsPercent"], kind, verified=True))
    return rows, next(iter(dates)), "all_reported", "derivative_weights_are_not_daily_exposure", "provider_reported_mixed"


def _invesco(data):
    doc = _json(data)
    if not isinstance(doc, dict) or doc.get("cusip") != "QQQ":
        raise _Unavailable("fund_identity_mismatch")
    records = _bounded_rows(doc.get("holdings"))
    rows = [_row(r.get("issuerName"), r.get("ticker"), r.get("percentageOfTotalNetAssets"),
                 _kind(_text(r.get("issuerName")), _text(r.get("securityTypeName"))), verified=True)
            for r in records]
    count = _number(doc.get("totalNumberOfHoldings"))
    scope = "all_reported" if count == len(records) else "partial"
    return rows, _day(doc.get("effectiveDate")), scope, "", "reported"


def _first_trust(data):
    root = html.fromstring(_body(data))
    titles = root.xpath('//*[contains(@id,"HoldingsListing_lblHoldingsTitle")]')
    if len(titles) != 1:
        raise _Unavailable("holdings_title_unrecognized")
    title = " ".join(titles[0].text_content().split())
    match = re.fullmatch(r"Holdings of the Fund as of (.+)", title)
    if not match or "CIBR" not in " ".join(root.xpath("//title/text()")):
        raise _Unavailable("fund_identity_mismatch")
    for table in root.xpath('//table[contains(@class,"fundSilverGrid")]'):
        trs = table.xpath("./tr | ./tbody/tr")
        if not trs:
            continue
        headers = [" ".join(c.text_content().split()) for c in trs[0].xpath("./td | ./th")]
        if not {"Security Name", "Identifier", "Weighting"}.issubset(headers):
            continue
        if len(trs) > MAX_ROWS + 1:
            raise _Unavailable("too_many_rows")
        rows = []
        for tr in trs[1:]:
            cells = [" ".join(c.text_content().split()) for c in tr.xpath("./td | ./th")]
            if len(cells) != len(headers):
                raise _Unavailable("invalid_holdings_table_row")
            r = dict(zip(headers, cells))
            kind = _kind(r["Security Name"])
            if kind == "unknown":
                kind = "security"
            symbol = r["Identifier"]
            # First Trust foreign identifiers (.JP/.FP/.CN) are not Yahoo codes.
            valid = bool(re.fullmatch(r"[A-Z]{1,6}(?:-[A-Z])?", symbol))
            rows.append(_row(r["Security Name"], symbol, r["Weighting"], kind, verified=valid))
        _bounded_rows(rows)
        return rows, _day(match[1]), "all_reported", "foreign_identifiers_retained_without_guessed_mapping", "reported"
    raise _Unavailable("holdings_table_unrecognized")


def _naver(data, symbol, fund_codes):
    records = _bounded_rows(_json(data))
    if any(_text(r.get("itemCode")) != symbol for r in records):
        raise _Unavailable("fund_identity_mismatch")
    dates = {_day(r.get("referenceDate")) for r in records}
    if len(dates) > 1:
        raise _Unavailable("mixed_holdings_dates")
    rows = []
    for r in records:
        name, code = _text(r.get("componentName")), _text(r.get("componentItemCode")).upper()
        isin, ric = _text(r.get("componentIsinCode")).upper(), _text(r.get("componentReutersCode")).upper()
        kind, verified, target, exchange_unknown = _kind(name), False, None, False
        if kind not in {"swap", "cash", "futures", "option", "bond"}:
            if (re.fullmatch(r"[A-Z0-9]{6}", code) and re.fullmatch(r"KR7[A-Z0-9]{6}\d{3}", isin)
                    and isin[3:9] == code):
                target, verified = code, True
                if ric in {code + ".KS", code + ".KQ"}:
                    target = ric
                else:
                    exchange_unknown = True
            elif isin.startswith("US") and re.fullmatch(r"[A-Z]{1,6}\.(?:O|N|OQ)", ric):
                target, verified = ric.rsplit(".", 1)[0], True
            if target and target.split(".", 1)[0] in fund_codes:
                kind = "fund"
            elif kind == "unknown" and verified:
                kind = "security"
        row = _row(name, target, r.get("weight"), kind, verified=verified,
                   source_symbol=ric or code)
        row["exchange_unknown"] = exchange_unknown
        rows.append(row)
    counts = {_number(r.get("componentCount")) for r in records}
    scope = "all_reported" if counts == {float(len(records))} else "partial"
    return rows, next(iter(dates)), scope, "creation_basket_not_full_economic_exposure", "creation_basket"


def _yahoo(data, symbol):
    doc = _json(data)
    records = doc.get("quoteSummary", {}).get("result")
    if not isinstance(records, list) or len(records) != 1:
        raise _Unavailable("yahoo_holdings_unavailable")
    quote = records[0].get("quoteType", {})
    if quote.get("quoteType") != "ETF" or quote.get("symbol") != symbol:
        raise _Unavailable("fund_identity_mismatch")
    holdings = _bounded_rows(records[0].get("topHoldings", {}).get("holdings"))
    if len(holdings) > 10:
        raise _Unavailable("unexpected_yahoo_scope")
    rows = []
    for r in holdings:
        weight = _number(r.get("holdingPercent"))
        kind = _kind(_text(r.get("holdingName")))
        rows.append(_row(r.get("holdingName"), r.get("symbol"),
                         weight * 100 if weight is not None else None, kind))
    return rows, None, "top10", "yahoo_asset_types_and_holdings_date_unverified", "provider_reported_unverified"


def _catalog(kr_catalog, symbol):
    if kr_catalog is None:
        return None, frozenset(), ""
    records = kr_catalog.to_dict("records") if hasattr(kr_catalog, "to_dict") else kr_catalog
    if not isinstance(records, list) or len(records) > MAX_ROWS:
        raise _Unavailable("invalid_kr_catalog")
    matched, codes = None, set()
    for row in records:
        if not isinstance(row, dict):
            continue
        try:
            code, market = _identity(row.get("ticker") or row.get("code"))
        except _Unavailable:
            continue
        if market == "KR":
            codes.add(code)
            if code == symbol:
                matched = row
    fields = [(matched or {}).get(f"top_{i}{suffix}") for i in range(1, 6)
              for suffix in ("", "_weight_pct")]
    fingerprint = hashlib.sha256(repr((fields, sorted(codes))).encode("utf-8")).hexdigest()
    return matched, frozenset(codes), fingerprint


def _aged(snapshot, now, max_age_days):
    snapshot = deepcopy(snapshot)
    if snapshot["as_of"]:
        age = (now.date() - date.fromisoformat(snapshot["as_of"])).days
        if age < -1:
            snapshot.update(rows=[], status="unavailable", scope="none", reason="future_holdings_date")
        elif age > max_age_days:
            snapshot.update(status="stale", reason="; ".join(filter(None, [snapshot["reason"], "holdings_date_is_old"])))
    return snapshot


def _cached_result(entry, cache, now, max_age_days, *, failed=None):
    if entry and entry.get("good") and cache.clock() - entry["good_at"] <= cache.stale_ttl:
        result = _aged(entry["good"], now, max_age_days)
        result.update(from_cache=True)
        if failed:
            result.update(status="stale", reason="; ".join(filter(None, [result["reason"], "refresh_failed: " + failed["reason"]])),
                          last_attempt_at=failed["observed_at"])
        return result
    if failed:
        return deepcopy(failed)
    return None


def load_etf_holdings(ticker, *, kr_catalog=None, force_refresh=False, fetch=None,
                      now=None, cache=None, timeout=8.0, max_age_days=7):
    """Return a JSON-compatible snapshot; failures are data, not UI exceptions.

    Primary statuses: ok, partial, stale, unavailable. Only rows with
    reviewable=True and a ticker should be offered as precision targets.
    ``force_refresh`` bypasses both cache TTLs, retaining stale-on-error support.
    A supplied KR catalog is never mutated or used to resolve names into codes.
    Its names-only top five fallback has as_of=None and reviewable=False.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    try:
        symbol, market = _identity(ticker)
    except _Unavailable as exc:
        return _snapshot(_text(ticker), None, now, reason=str(exc))
    timeout = max(0.05, min(float(timeout), 15.0))
    max_age_days = max(0, min(int(max_age_days), 365))
    try:
        catalog_row, fund_codes, fingerprint = _catalog(kr_catalog, symbol) if market == "KR" else (None, frozenset(), "")
    except (ValueError, TypeError):
        return _snapshot(symbol, market, now, reason="invalid_kr_catalog")
    transport = fetch or _http_fetch
    cache = cache if cache is not None else (_CACHE if fetch is None else ETFHoldingsCache())
    key = (symbol, market, fingerprint, max_age_days, id(transport))
    entry = cache._read(key)
    if entry and not force_refresh:
        if entry.get("failure") and cache.clock() - entry["failed_at"] < cache.failure_ttl:
            result = _cached_result(entry, cache, now, max_age_days, failed=entry["failure"])
            result["from_cache"] = True
            return result
        if entry.get("good") and cache.clock() - entry["good_at"] < cache.success_ttl:
            return _cached_result(entry, cache, now, max_age_days)
    if market == "KR":
        source, url, parser = "Naver ETF components", NAVER_URL.format(code=symbol), lambda data: _naver(data, symbol, fund_codes)
    else:
        providers = {"SOXX": ("iShares", SOXX_URL, _ishares), "QQQ": ("Invesco", QQQ_URL, _invesco),
                     "CIBR": ("First Trust", CIBR_URL, _first_trust), "SOXL": ("Direxion", SOXL_URL, _direxion)}
        source, url, parser = providers.get(symbol, ("Yahoo Finance", "https://query1.finance.yahoo.com/v10/finance/quoteSummary/"
                                                   + symbol + "?modules=quoteType,topHoldings&formatted=false",
                                                   lambda data: _yahoo(data, symbol)))
    deadline = time.monotonic() + timeout
    try:
        data = transport(url, timeout=timeout)
        if time.monotonic() >= deadline:
            raise _Unavailable("collection_deadline")
        rows, as_of, scope, reason, basis = parser(data)
        if any(not r["name"] for r in rows):
            raise _Unavailable("holding_name_unavailable")
        result = _snapshot(symbol, market, now, rows=rows, source=source, source_url=url,
                           as_of=as_of, scope=scope, reason=reason, holdings_basis=basis)
        result = _aged(result, now, max_age_days)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, _Unavailable) else ("request_timeout" if isinstance(exc, (TimeoutError, requests.Timeout)) else "invalid_or_unavailable_response")
        result = _snapshot(symbol, market, now, source=source, source_url=url, reason=reason)
        if catalog_row is not None:
            rows = [_row(catalog_row.get(f"top_{i}"), None, catalog_row.get(f"top_{i}_weight_pct"),
                         _kind(_text(catalog_row.get(f"top_{i}")))) for i in range(1, 6)
                    if _text(catalog_row.get(f"top_{i}"))]
            if rows:
                result = _snapshot(symbol, market, now, rows=rows, source="KR catalog", scope="top5",
                                   reason=reason + "; catalog_has_no_verified_symbols_or_holdings_date", holdings_basis="unverified_reference")
    cache._write(key, result)
    if result["status"] != "ok":
        return _cached_result(entry, cache, now, max_age_days, failed=result)
    return deepcopy(result)
