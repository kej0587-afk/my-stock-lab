"""Select exact-symbol Yahoo histories without rescanning batch columns."""

import logging

import pandas as pd


class DownloadFrameSelector:
    """A batch-local column index; never cache prices or change their basis.

    The caller must not replace/mutate source columns during selection. Returned
    frames remain independent copies, including provenance attributes.
    """

    def __init__(self, frame):
        self.frame = frame
        self.matches = {}
        if isinstance(frame, pd.DataFrame) and isinstance(frame.columns, pd.MultiIndex):
            for level in range(frame.columns.nlevels):
                for value in frame.columns.get_level_values(level).unique():
                    # Keep the legacy first-level/first-raw-value precedence.
                    key = str(value).strip().upper()
                    self.matches.setdefault(key, (level, value))

    def select(self, ticker):
        frame = self.frame
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return pd.DataFrame()
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame.copy(deep=True)
        match = self.matches.get(str(ticker).strip().upper())
        if match is None:
            logging.warning("Yahoo OHLCV rejected: requested symbol absent (%s)", ticker)
            return pd.DataFrame()
        level, value = match
        out = frame.xs(value, axis=1, level=level).copy(deep=True)
        if isinstance(out.columns, pd.MultiIndex):
            return pd.DataFrame()
        return out
