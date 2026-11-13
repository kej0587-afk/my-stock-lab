"""Read a quote object's own symbol, price and timestamp, never nearby cards."""

import html
from html.parser import HTMLParser
import json
import math
from types import MappingProxyType

from stock_lab_core import report_build

report_build.register_loaded_source(__name__, __file__)
IMPORTED_SOURCE = MappingProxyType(dict(report_build._LOADED[__name__]))


class _JsonScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower() == "application/json"
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)
        elif data.lstrip().startswith(("{", "[")):
            self.documents.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.documents.append("".join(self.parts))
            self.active = False


def _objects(value, depth=0):
    if depth > 16:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child, depth + 1)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return
        yield from _objects(decoded, depth + 1)


def extract_overnight_quote(text, ticker, is_recent):
    """Keep overnight/day priority and freshness; reject ambiguous attribution."""
    if not text or not ticker:
        return 0.0
    parser = _JsonScripts()
    parser.feed(str(text))
    documents = parser.documents
    if not documents:
        # Historical callers also supply a standalone escaped JSON object.
        documents = [str(text)]
    quotes = []
    for document in documents:
        if "MarketPrice" not in document:
            continue
        try:
            payload = json.loads(document)
        except (ValueError, TypeError):
            try:
                payload = json.loads(html.unescape(document).replace('\\"', '"').replace("\\/", "/"))
            except (ValueError, TypeError):
                continue
        quotes.extend(obj for obj in _objects(payload)
                      if str(obj.get("symbol", "")).upper() == ticker.upper())
    for prefix in ("overnight", "day"):
        candidates = []
        for quote in quotes:
            try:
                price = quote.get(prefix + "MarketPrice")
                stamp = quote.get(prefix + "MarketTime")
                price = float(price.get("raw") if isinstance(price, dict) else price)
                stamp = int(stamp.get("raw") if isinstance(stamp, dict) else stamp)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(price) and price > 0 and is_recent(stamp):
                candidates.append((stamp, price))
        if candidates:
            return max(candidates)[1]
    return 0.0
