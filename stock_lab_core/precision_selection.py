"""Pure selection precedence for the precision observatory."""


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
