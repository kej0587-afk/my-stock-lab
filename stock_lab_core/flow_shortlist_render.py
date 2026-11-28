"""Reuse a shortlist only within one render and an unchanged cached input.

This is not a time/session cache. The original builder still owns snapshot
validity, candidate selection and registration semantics.
"""
from copy import deepcopy

import pandas as pd

from stock_lab_core.performance import count_event, timed_call


class FlowShortlistRenderReuse:
    def __init__(self, build, version):
        self.build = build
        self.version = version
        self.saved = None

    @staticmethod
    def _frame_copy(frame):
        # No nested snapshot attrs are used by the original cached branch.
        result = pd.DataFrame(frame).copy(deep=True)
        result.attrs = {}
        return result

    @staticmethod
    def _registration(holdings, watchlist):
        # Preserve raw values: matching/sanitizing stays in the original builder.
        columns = ["티커", "자산명", "종목명", "보유량", "원화환산"]
        frame = (holdings.loc[:, [c for c in columns if c in holdings.columns]]
                 if isinstance(holdings, pd.DataFrame) else pd.DataFrame())
        return FlowShortlistRenderReuse._frame_copy(frame), deepcopy(watchlist)

    @timed_call("display", "flow_shortlist_render_read")
    def get(self, snapshot, *, holdings, watchlist):
        source = snapshot.get("_flow_shortlist_df") if isinstance(snapshot, dict) else None
        valid = (isinstance(source, pd.DataFrame) and not source.attrs
                 and snapshot.get("_flow_shortlist_version") == self.version)
        registration = self._registration(holdings, watchlist)
        if valid and self.saved is not None:
            old_snapshot, old_source, old_registration, result = self.saved
            try:
                same = (snapshot is old_snapshot and source.equals(old_source)
                        and registration[0].equals(old_registration[0])
                        and registration[1] == old_registration[1])
            except (TypeError, ValueError):
                same = False
            if same:
                count_event("flow_shortlist_render.reuse")
                return result.copy(deep=True)
        count_event("flow_shortlist_render.build")
        self.saved = None
        result = self.build(snapshot)
        # The builder may have populated/replaced the snapshot cache.
        source = snapshot.get("_flow_shortlist_df") if isinstance(snapshot, dict) else None
        if (isinstance(result, pd.DataFrame) and isinstance(source, pd.DataFrame) and not source.attrs
                and snapshot.get("_flow_shortlist_version") == self.version):
            self.saved = (snapshot, self._frame_copy(source), registration, result.copy(deep=True))
        return result


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
