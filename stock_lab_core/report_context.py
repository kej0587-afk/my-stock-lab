"""Collect report-only context on explicit generation, never on each rerender."""

from datetime import datetime
import json
from pathlib import Path
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

from stock_lab_core.report_evidence import KST, first, is_held, price_observation, intraday_observation, records, text
from stock_lab_core.report_holdings import UNDERLYINGS
from stock_lab_core.report_prices import MACRO_SYMBOLS, SECTORS, aligned_macro, btc_at_us_close, load_btc_close_frame, release_day_reaction


def apply_verified_release_dates(rows, now):
    """Historical publication facts checked against BLS archives, not a schedule guess."""
    path = Path(__file__).with_name("data") / "verified_release_facts_20261018.json"
    facts = json.loads(path.read_text(encoding="utf-8"))
    if now.date().isoformat() < facts["verified_at"]:
        return
    for row in rows:
        match = next((fact for fact in facts["events"] if fact["indicator"] == row.get("indicator") and fact["period"] == row.get("period")), None)
        if match and not row.get("release_at"):
            row.update(release_at=match["release_at"], release_precision="datetime", release_source="BLS archive (2026-10-18 verified)",
                       release_source_url=match["source_url"])
        if match and "verified_yoy" in match and row.get("basis") == "YoY" and row.get("actual") is not None:
            state = "일치" if row.get("actual") == match["verified_yoy"] else "불일치: 수정치/자료 경로 재확인 필요"
            row["verification"] = f"BLS 원문 재확인(2026-10-18) {state} [공식 발표문]({match['source_url']})"


def collect_report_context(summary_rows=None, event_rows=None, *, now=None, price_frames=None,
                           economic_releases=None, calendar=None, btc_frame=None, include_news=False):
    from stock_lab_core.economic_releases import _api_key, load_economic_releases
    from stock_lab_core.prices import load_price_df, load_price_frames_batch
    from stock_lab_core.release_calendar import load_release_calendar

    now = now or datetime.now(KST)
    tickers = {"^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI", "QQQ", *MACRO_SYMBOLS.values(), *SECTORS}
    for row in records(summary_rows):
        if is_held(row):
            ticker = text(first(row, "티커", "ticker"))
            if ticker:
                tickers.add(ticker)
                tickers.update(base for base in UNDERLYINGS.get(ticker.split(".")[0], ()) if base != "BTC-US-CLOSE")
    frames = price_frames
    if frames is None:
        # Reuse the app's cached one-year histories, not one info request per asset.
        frames = load_price_frames_batch(tuple(sorted(tickers)), "1y")
        for ticker in sorted(tickers):
            if ticker.endswith((".KS", ".KQ")):
                frames[ticker] = load_price_df(ticker, "1y")
    observations = {ticker: price_observation(frames.get(ticker), ticker, now) for ticker in tickers}
    sessions, news_sessions = {}, {}
    for region, indices in (("KR", ("^KS11", "^KQ11")), ("US", ("^GSPC", "^IXIC", "^DJI"))):
        dates = {observations[ticker]["date"] for ticker in indices if observations[ticker]["date"]}
        # Do not advertise a common close when constituent dates disagree.
        if len(dates) == 1:
            sessions[region] = dates.pop()
            obs = next(observations[ticker] for ticker in indices if observations[ticker]["date"])
            news_sessions[region] = {"date": obs["date"], "previous_date": obs.get("previous_date", "")}
    if any(text(first(row, "티커", "ticker")) in {"BITX", "BITU"} for row in records(summary_rows) if is_held(row)) and "US" in news_sessions:
        window = news_sessions["US"]
        observations["BTC-US-CLOSE"] = btc_at_us_close(load_btc_close_frame() if btc_frame is None else btc_frame,
                                                      window["date"], window["previous_date"])
    releases = load_economic_releases(event_rows=event_rows, now=now) if economic_releases is None else records(economic_releases)
    if economic_releases is None:
        from stock_lab_core.economic_bulletins import apply_official_bulletins
        releases = apply_official_bulletins(releases, now)
    apply_verified_release_dates(releases, now)
    for row in releases:
        row.update(reaction=release_day_reaction(row, frames, now), reaction_source="Yahoo daily, release calendar")
    calendar = load_release_calendar(now=now, fred_api_key=_api_key("FRED_API_KEY")) if calendar is None else calendar
    sectors = [{"Ticker": ticker, "섹터": name, "구분": "한국 섹터" if ticker.endswith((".KS", ".KQ")) else "미국 섹터", "기준일": obs["date"],
                "1일수익률": obs["return"]} for ticker, name in SECTORS.items()
               if (obs := observations[ticker])["date"] == sessions.get("KR" if ticker.endswith((".KS", ".KQ")) else "US") and obs["return"] is not None]
    result = {"prices": observations, "sessions": sessions, "news_sessions": news_sessions,
              "intraday_prices": {ticker: intraday_observation(frames.get(ticker), ticker, now) for ticker in tickers},
              "macro_data": aligned_macro(frames, sessions.get("US"), now), "sector_rows": sectors,
              "economic_releases": releases, "calendar_events": calendar["events"], "calendar_sources": calendar["sources"]}
    if include_news:
        from stock_lab_core.today_news import fetch_session_market_news
        result.update(fetch_session_market_news(news_sessions, now=now, categories=("반도체·AI", "매크로/중국"), per_category=5))
    return result
