"""Pure selection precedence for the precision observatory."""

from stock_lab_core.formatters import sanitize_ticker_value


def apply_precision_quick_target(state, split_ticker, queue_free_target, pending_key, kr_markets):
    """Apply before widgets render so the browser and body share one identity."""
    ticker = sanitize_ticker_value(state.get("precision_quick_free_ticker", ""))
    if not ticker:
        return
    base, market = split_ticker(ticker)
    selected_market = state.get("precision_quick_free_market")
    if selected_market in kr_markets and market in kr_markets and "." not in ticker.upper():
        market = selected_market
    target = base
    if market in kr_markets:
        target += ".KQ" if "KOSDAQ" in market else ".KS"
    state.pop(pending_key, None)
    queue_free_target(target)


def remember_precision_selection(state, widget_key, pending_key, option_map, preset_map):
    """Capture identity in the widget callback, before rerun rebuilds its options."""
    label = state.get(widget_key)
    meta = option_map.get(label) or {}
    if meta.get("type") == "free":
        state[pending_key] = {"free": True}
        return
    ticker = (meta.get("item") or {}).get("ticker")
    if not ticker and label in preset_map:
        ticker = preset_map[label][0]
    if ticker:
        state[pending_key] = {"ticker": str(ticker)}


def resolve_precision_selection(
    options, *, free_option, current_option=None, widget_option=None,
    pending_option="", force_free=False,
):
    """Return (selected label, reset widget), preserving explicit user input."""
    if pending_option in options:
        return pending_option, True
    if force_free and free_option:
        return free_option, True
    if widget_option in options:
        return widget_option, False
    if current_option in options:
        return current_option, widget_option is not None
    return free_option, True
