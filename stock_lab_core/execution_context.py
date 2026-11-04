"""Shared, display-time context pipeline; scoring and gate policy stay unchanged."""

from copy import deepcopy
from inspect import Parameter, signature

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def prepare_execution_context(frame, *, snapshot, flow_shortlist, market_guard,
                              attach_flow, attach_market, apply_gate,
                              upside_map=None, enrich_analyst=None, build_upside_map=None):
    """Keep one frozen snapshot and never retry an exception from a provider body.

    Today supplies an already enriched frame. Precision and the board enrich
    after market context, preserving their existing order and cache behavior.
    A lazy market guard preserves precision's flow-before-guard evaluation.
    """
    out = frame.copy(deep=True)
    out.attrs = deepcopy(frame.attrs)
    if out.empty:
        return out
    try:
        parameters = signature(attach_flow).parameters
        accepts_snapshot = "snapshot" in parameters or any(
            item.kind == Parameter.VAR_KEYWORD for item in parameters.values()
        )
    except (TypeError, ValueError):
        accepts_snapshot = False
    # Legacy adapters have two arguments; execution errors must propagate once.
    if accepts_snapshot:
        out = attach_flow(out, flow_shortlist, snapshot=snapshot)
    else:
        out = attach_flow(out, flow_shortlist)
    guard = market_guard() if callable(market_guard) else market_guard
    out = attach_market(out, guard)
    if enrich_analyst is not None:
        out = enrich_analyst(out)
        upside_map = build_upside_map(out)
    return apply_gate(out, upside_value_map=upside_map)
