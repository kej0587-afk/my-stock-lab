"""Supplier evidence attached to the exact selected scalar, without repricing it.

Only instrumented providers attach observations. Plain floats (including other
provider fallbacks) remain honestly unknown. Arithmetic/float conversion drops
the evidence intentionally: a derived price is no longer the supplier's quote.
"""

from datetime import datetime, timezone
import math

from stock_lab_core.report_build import register_loaded_source


_SESSIONS = frozenset({"regular", "pre", "post", "overnight", "day", "unknown"})
_TIMESTAMP_KINDS = frozenset({"trade", "bar_start", "unknown"})


def _symbol(value):
    return value.strip().upper() if isinstance(value, str) else ""


def _utc_timestamp(value):
    """Normalize supplier epoch seconds/aware timestamps; never fill missing time."""
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, datetime):
            stamp = value
        elif isinstance(value, str) and not value.replace(".", "", 1).isdigit():
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            epoch = float(value)
            if not math.isfinite(epoch) or epoch <= 0:
                return None
            stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class QuoteObservation(float):
    """A float whose immutable metadata tuple survives pickle/deepcopy caches.

Numeric equality, hash, representation and JSON serialization retain float's
semantics. Metadata does not participate in the numerical price-input identity.
"""

    def __new__(cls, price, source="", symbol="", observed_at=None,
                session="unknown", timestamp_kind="unknown"):
        value = super().__new__(cls, price)
        value._observation = (
            source.strip() if isinstance(source, str) else "",
            _symbol(symbol),
            _utc_timestamp(observed_at),
            session if isinstance(session, str) and session in _SESSIONS else "unknown",
            timestamp_kind if isinstance(timestamp_kind, str) and timestamp_kind in _TIMESTAMP_KINDS else "unknown",
        )
        return value

    def __reduce__(self):
        return type(self), (float(self), *self._observation)


def observed_price(value, *, ticker, source, observed_at,
                   session="unknown", timestamp_kind="trade"):
    """Attach supplied evidence to the unchanged scalar selected by a provider."""
    return QuoteObservation(value, source=source, symbol=ticker, observed_at=observed_at,
                            session=session, timestamp_kind=timestamp_kind)


def quote_provenance(value, ticker="") -> dict:
    """Return evidence only for a usable observed scalar of the requested symbol."""
    if not isinstance(value, QuoteObservation) or not math.isfinite(value) or value <= 0:
        return {}
    source, symbol, observed_at, session, timestamp_kind = value._observation
    if not source or not symbol or (ticker and _symbol(ticker) != symbol):
        return {}
    result = {
        "source": source,
        "symbol": symbol,
        "session": session,
        "timestamp_kind": timestamp_kind,
        "price": float(value),
    }
    if observed_at is not None:
        result["observed_at"] = observed_at
    return result


register_loaded_source(__name__, __file__)
