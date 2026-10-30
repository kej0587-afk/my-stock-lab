"""Collect report-only context on explicit generation, never on each rerender."""

from datetime import datetime
import json
import logging
from pathlib import Path
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

from stock_lab_core.report_evidence import KST, first, is_held, price_observation, intraday_observation, records, text, stamp
from stock_lab_core.report_holdings import UNDERLYINGS
from stock_lab_core.report_prices import MACRO_SYMBOLS, SECTORS, align_us_report_frames, aligned_macro, btc_at_us_close, load_btc_close_frame, release_day_reaction
from stock_lab_core.report_session import kst_now, market_session_states
from stock_lab_core.performance import measure, timed_call


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


@timed_call("external_data", "report_context")
def collect_report_context(summary_rows=None, event_rows=None, *, now=None, price_frames=None,
                           economic_releases=None, calendar=None, btc_frame=None, live_frames=None, scenario_frames=None, flow_snapshot=None, include_news=False,
                           quote_data=None):
    from stock_lab_core.economic_releases import _api_key, load_economic_releases
    from stock_lab_core.prices import load_price_df, load_price_frames_batch
    from stock_lab_core.release_calendar import load_release_calendar

    now = kst_now(now or datetime.now(KST))
    tickers = {"^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI", "QQQ", "XLF", "XLI", "XLP", "XLV", "IWM", "SMH", *MACRO_SYMBOLS.values(), *SECTORS}
    for key in ("us_top5", "kr_top5", "global_top", "theme_top5"):
        for row in records((flow_snapshot or {}).get(key))[:5]:
            ticker = text(first(row, "Ticker", "티커", "ticker"))
            if ticker:
                tickers.add(ticker)
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
        from stock_lab_core.report_live import supplement_kr_indices
        frames = supplement_kr_indices(frames)
    from stock_lab_core.report_quotes import load_report_quotes, repair_held_us_closes, repair_kr_report_closes, extended_quote_observation, extended_quote_status, kr_index_observations
    held_us = tuple(sorted({text(first(row, "티커", "ticker")) for row in records(summary_rows)
                            if is_held(row) and text(first(row, "티커", "ticker"))
                            and not text(first(row, "티커", "ticker")).endswith((".KS", ".KQ"))}))
    held_kr = tuple(sorted({text(first(row, "티커", "ticker")).upper() for row in records(summary_rows)
                            if is_held(row) and text(first(row, "티커", "ticker")).upper().endswith((".KS", ".KQ"))}))
    kr_quote_tickers = tuple(sorted(set(held_kr) | {t for t in tickers if t.endswith((".KS", ".KQ"))} | {"0167A0.KS"}))
    # Quote only the fixed report sectors and holdings, never the full watchlist.
    us_quote_tickers = tuple(sorted(set(held_us) | {t for t in SECTORS if not t.endswith((".KS", ".KQ"))}))
    if quote_data is None:
        quote_data = (load_report_quotes(us_quote_tickers, include_kr=market_session_states(now)["KR"]["phase"] in {"intraday", "closed"}, kr_tickers=kr_quote_tickers)
                      if price_frames is None else {})
    us_quotes = quote_data.get("US", {})
    # A response fetched after collection starts is not a future quote.
    quote_now = max(now, stamp(quote_data.get("retrieved_at")) or now)
    if price_frames is None or quote_data.get("KR"):
        frames = repair_kr_report_closes(frames, quote_data.get("KR", {}), quote_now, tickers=kr_quote_tickers)
    pending_closes = [f"{ticker}: {frame.attrs['report_close_pending_date']} 한국 당일 종가 확인 대기 · "
                      + frame.attrs.get("report_close_pending_reason", "장중 캐시 제외")
                      for ticker, frame in frames.items() if frame is not None and frame.attrs.get("report_close_pending_date")]
    close_basis_notes = [f"{ticker}: {frame.attrs['report_close_basis_note']}"
                         for ticker, frame in frames.items() if frame is not None and frame.attrs.get("report_close_basis_note")]
    frames = repair_held_us_closes(frames, us_quotes, quote_now)
    frames, price_alignment = align_us_report_frames(
        frames, tickers, now, reload_batch=load_price_frames_batch if price_frames is None else None)
    observations = {ticker: price_observation(frames.get(ticker), ticker, now) for ticker in tickers}
    for ticker in price_alignment["unaligned"]:
        # A missing preceding session makes a multi-day change, not a daily one.
        if observations[ticker]["date"] == price_alignment["expected_date"]:
            observations[ticker]["return"] = None
        observations[ticker]["stale"] = True
    sessions, news_sessions = {}, {}
    for region, indices in (("KR", ("^KS11", "^KQ11")), ("US", ("^GSPC", "^IXIC", "^DJI"))):
        dates = {observations[ticker]["date"] for ticker in indices if observations[ticker]["date"]}
        # Do not advertise a common close when constituent dates disagree.
        if len(dates) == 1:
            sessions[region] = dates.pop()
            obs = max((observations[ticker] for ticker in indices if observations[ticker]["date"]),
                      key=lambda row: row.get("previous_date", ""))
            news_sessions[region] = {"date": obs["date"], "previous_date": obs.get("previous_date", "")}
    states = market_session_states(now, sessions)
    current_news_sessions = {}
    if states["KR"]["phase"] == "intraday" and sessions.get("KR"):
        current_news_sessions["KR"] = {"date": states["KR"]["active_date"], "previous_date": sessions["KR"], "is_active": True}
    intraday = {ticker: intraday_observation(frames.get(ticker), ticker, now) for ticker in tickers}
    if states["KR"]["phase"] == "intraday":
        # An untimed daily bar must not overrule a timestamped current index quote.
        kr_live = kr_index_observations(quote_data.get("KR", {}), quote_now, tickers=kr_quote_tickers)
        for ticker in ("^KS11", "^KQ11", *kr_quote_tickers):
            intraday[ticker] = kr_live.get(ticker, {})
    extended = {ticker: obs for ticker in us_quote_tickers
                if (obs := extended_quote_observation(us_quotes.get(ticker, {}), ticker, quote_now))}
    extended_reference = {ticker: obs for ticker in us_quote_tickers if ticker not in extended
                          if (obs := extended_quote_observation(us_quotes.get(ticker, {}), ticker, quote_now, allow_delayed=True))}
    quote_status = {ticker: extended_quote_status(us_quotes.get(ticker, {}), ticker, quote_now)
                    for ticker in held_us if ticker not in extended}
    if price_frames is None:
        for ticker, reason in quote_status.items():
            logging.info("Report extended quote %s: %s", ticker, reason)
    if states["US"]["phase"] == "intraday":
        from stock_lab_core.report_live import load_us_live_frames, us_live_observation
        us_tickers = tuple(sorted(t for t in tickers if not t.endswith((".KS", ".KQ", "=X", "=F"))
                                  and t not in {"^KS11", "^KQ11", "^TNX", "^MOVE", "^VIX"}))
        if live_frames is None:
            live_frames = load_us_live_frames(us_tickers) if price_frames is None else {}
        for ticker in us_tickers:
            # A daily bar has no auditable quote timestamp; do not backdate it as a live quote.
            intraday[ticker] = (us_live_observation(live_frames.get(ticker), ticker, observations[ticker], now)
                               if observations[ticker].get("date") == sessions.get("US") else {})
        current_news_sessions["US"] = {"date": states["US"]["active_date"], "previous_date": sessions.get("US", ""), "is_active": True}
    if any(text(first(row, "티커", "ticker")) in {"BITX", "BITU"} for row in records(summary_rows) if is_held(row)) and "US" in news_sessions:
        window = {"date": sessions["US"], "previous_date": observations.get("^GSPC", {}).get("previous_date", "")}
        observations["BTC-US-CLOSE"] = btc_at_us_close(load_btc_close_frame() if btc_frame is None else btc_frame,
                                                      window["date"], window["previous_date"])
    if economic_releases is None and calendar is None:
        # The release collector already fetched the calendar, including failure status.
        releases, calendar = load_economic_releases(event_rows=event_rows, now=now, include_calendar=True)
    else:
        releases = load_economic_releases(event_rows=event_rows, now=now) if economic_releases is None else records(economic_releases)
    if economic_releases is None:
        from stock_lab_core.economic_bulletins import apply_official_bulletins
        releases = apply_official_bulletins(releases, now)
    apply_verified_release_dates(releases, now)
    consensus_diagnostics = {}
    if economic_releases is None:
        from stock_lab_core.report_consensus import attach_economic_consensus
        releases, consensus_diagnostics = attach_economic_consensus(releases, now,
            api_key=_api_key("TRADING_ECONOMICS_API_KEY"))
    for row in releases:
        row.update(reaction=release_day_reaction(row, frames, now), reaction_source="Yahoo daily, release calendar")
    calendar = load_release_calendar(now=now, fred_api_key=_api_key("FRED_API_KEY")) if calendar is None else calendar
    earnings_sources = []
    earnings_results = {"results": [], "sources": []}
    official_outlooks = None
    if economic_releases is None and price_frames is None:
        from stock_lab_core.earnings_sources import load_official_earnings
        # Explicitly requested issuers first; no broad market scan on a rerender.
        requested_tickers = [text(first(row, "티커", "ticker")).upper() for row in records(summary_rows)]
        from stock_lab_core.earnings_sources import _ISSUERS as connected_issuers
        earnings_tickers = list(dict.fromkeys(["000660.KS", "005930.KS", "NVDA", "GOOGL", "META", "MSFT", "TSLA",
            *(ticker for ticker in requested_tickers if ticker in connected_issuers), *requested_tickers]))
        earnings = load_official_earnings(earnings_tickers, now)
        updated = {row.get("ticker") for row in earnings["events"]}
        calendar = dict(calendar, events=[r for r in calendar["events"] if r.get("ticker") not in updated] + earnings["events"])
        earnings_sources = earnings["sources"]
        from stock_lab_core.earnings_result_sources import load_earnings_results
        with measure("external_data", "earnings_result_reconciliation"):
            earnings_results = load_earnings_results(earnings["events"], now)
        from stock_lab_core.outlook_sources import load_official_outlooks
        with measure("external_data", "official_outlook"):
            official_outlooks = load_official_outlooks(now)
    closed_rows = []
    from stock_lab_core.money_flow import _compute_ticker_metrics, MONEY_FLOW_UNIVERSE
    from stock_lab_core.report_evidence import closed_daily_frame
    metadata = {}
    for item in MONEY_FLOW_UNIVERSE:
        metadata.setdefault(text(item.get("ticker")), item)
    for key in ("flow_df", "us_top5", "kr_top5", "global_top"):
        for item in records((flow_snapshot or {}).get(key)):
            symbol = text(first(item, "Ticker", "티커", "ticker"))
            if symbol:
                metadata[symbol] = dict(metadata.get(symbol, {}), **item)
    for ticker in sorted(tickers - set(MACRO_SYMBOLS.values())):
        if ticker in price_alignment["unaligned"]:
            continue
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if len(frame) < 20 or not {"Close", "High", "Low"}.issubset(frame.columns):
            continue
        region = "KR" if ticker.endswith((".KS", ".KQ")) or ticker in {"^KS11", "^KQ11"} else "US"
        if str(frame.index[-1].date()) != sessions.get(region):
            continue
        metrics = _compute_ticker_metrics(frame)
        meta = metadata.get(ticker, {})
        closed_rows.append(dict(metrics, Ticker=ticker, 섹터=text(meta.get("섹터")) or SECTORS.get(ticker, ticker),
                                구분=text(meta.get("구분")) or ("한국 섹터" if ticker.endswith((".KS", ".KQ")) else "미국 섹터"),
                                기준일=str(frame.index[-1].date()), 수치종류="확정 종가"))
    metrics_by_ticker = {row["Ticker"]: row for row in closed_rows}
    sectors = [dict(metrics_by_ticker.get(ticker, {}), **{"Ticker": ticker, "섹터": name, "구분": "한국 섹터" if ticker.endswith((".KS", ".KQ")) else "미국 섹터", "기준일": obs["date"],
                "1일수익률": obs["return"], "수치종류": "확정 종가"}) for ticker, name in SECTORS.items()
               if (obs := observations[ticker])["date"] == sessions.get("KR" if ticker.endswith((".KS", ".KQ")) else "US") and obs["return"] is not None]
    from stock_lab_core.portfolio import infer_scenario_shock_multiplier
    rotation_rows = [row for row in closed_rows if abs(infer_scenario_shock_multiplier({"티커": row["Ticker"]})) <= 1 and row["Ticker"] != "SMH"]
    result = {"prices": observations, "price_frames": frames, "sessions": sessions, "news_sessions": news_sessions, "current_news_sessions": current_news_sessions,
              "price_alignment": price_alignment,
              "quote_checked_at": quote_now.isoformat(), "extended_quote_status": quote_status,
              "market_states": states, "intraday_prices": intraday, "extended_prices": extended,
              "extended_reference_prices": extended_reference, "closed_flow_rows": closed_rows,
              "rotation_rows": [{**row, "1D": row["1일수익률"], "5D": row["5일수익률"], "2W": row["2주수익률"], "1M": row["1개월수익률"]} for row in rotation_rows],
              "sector_rows": sectors,
              "economic_releases": releases, "consensus_diagnostics": consensus_diagnostics,
              "calendar_events": calendar["events"], "calendar_sources": calendar["sources"], "earnings_sources": earnings_sources,
              "earnings_results": earnings_results["results"], "earnings_result_sources": earnings_results["sources"]}
    if official_outlooks is not None:
        result["official_outlooks"] = official_outlooks
    from stock_lab_core.report_scenario import SYMBOLS, build_scenario_context
    if scenario_frames is None:
        if price_frames is None:
            from stock_lab_core.report_live import load_us_live_frames
            comparison_tickers = tuple(t for t in held_kr if t.split('.')[0] in {"379800", "379810", "418660"})
            scenario_frames = load_us_live_frames(tuple(sorted({*SYMBOLS, *comparison_tickers, "CL=F"})))
        else:
            scenario_frames = {}
    result["scenario_observations"] = build_scenario_context(scenario_frames, sessions, now)
    result["scenario_frames"] = scenario_frames
    result["source_provenance"] = {"collected_at": quote_now.isoformat(),
        "indices": {ticker: {key: observations[ticker].get(key) for key in ("date", "previous_date", "source")}
                    for ticker in ("^KS11", "^KQ11", "^GSPC", "^IXIC", "^DJI")}}
    from stock_lab_core.report_reference import load_macro_reference_frame
    result["macro_data"] = aligned_macro(frames, sessions.get("US"), now, scenario_frames=scenario_frames,
                                         reference_loader=load_macro_reference_frame if price_frames is None else None)
    reference_missing = [f"{name}: 뉴욕 16:00 고정 기준값 미연결(변동 중 일봉 대체 금지)"
                         for name in ("유가", "환율") if name not in result["macro_data"]]
    if include_news:
        from stock_lab_core.today_news import fetch_session_market_news
        held_exposures = []
        for row in records(summary_rows):
            if is_held(row):
                held_exposures.append(row)
                ticker = text(first(row, "티커", "ticker"))
                held_exposures.extend({"Ticker": base, "섹터": SECTORS.get(base, "")}
                                      for base in UNDERLYINGS.get(ticker.split(".")[0], ())
                                      if base != "BTC-US-CLOSE")
        with measure("external_data", "report_news"):
            result.update(fetch_session_market_news(news_sessions, now=now, current_sessions=current_news_sessions,
                                                   sector_rows=sectors + closed_rows, held_exposures=held_exposures,
                                                   watched_exposures=records(summary_rows),
                                                   per_category=5, use_cache=True, include_article_bodies=True))
    result["price_basis_notes"] = close_basis_notes
    result["missing"] = list(dict.fromkeys(result.get("missing", []) + price_alignment["missing"] + reference_missing + pending_closes))
    return result
