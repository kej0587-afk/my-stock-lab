"""Collect report-only context on explicit generation, never on each rerender."""

from datetime import datetime

from stock_lab_core.report_evidence import KST, LEVERAGE, first, is_held, price_observation, records, text


def collect_report_context(summary_rows=None, event_rows=None, *, now=None, price_frames=None):
    from stock_lab_core.economic_releases import load_economic_releases
    from stock_lab_core.prices import load_price_df, load_price_frames_batch

    now = now or datetime.now(KST)
    tickers = {"^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI"}
    for row in records(summary_rows):
        if is_held(row):
            ticker = text(first(row, "티커", "ticker"))
            if ticker:
                tickers.add(ticker)
                if ticker in LEVERAGE:
                    tickers.add(LEVERAGE[ticker][0])
    frames = price_frames
    if frames is None:
        # Reuse the app's cached one-year histories, not one info request per asset.
        frames = load_price_frames_batch(tuple(sorted(tickers)), "1y")
        for ticker in sorted(tickers):
            if ticker.endswith((".KS", ".KQ")):
                frames[ticker] = load_price_df(ticker, "1y")
    observations = {ticker: price_observation(frames.get(ticker), ticker, now) for ticker in tickers}
    sessions = {}
    for region, indices in (("KR", ("^KS11", "^KQ11")), ("US", ("^GSPC", "^IXIC", "^DJI"))):
        dates = {observations[ticker]["date"] for ticker in indices if observations[ticker]["date"]}
        # Do not advertise a common close when constituent dates disagree.
        if len(dates) == 1:
            sessions[region] = dates.pop()
    return {"prices": observations, "sessions": sessions,
            "economic_releases": load_economic_releases(event_rows=event_rows, now=now)}
