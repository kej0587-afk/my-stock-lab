"""Pure selection precedence for the precision observatory."""


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
