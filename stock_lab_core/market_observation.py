"""Pure, report-only observations. No fetching, persistence, LLM, or trade signals.

Integration: pass context['price_frames'], context['closed_flow_rows'], and
context['sessions'] to build_sector_rotation with an explicit aware as_of.
Returns/RS changes are fractions; acceleration is a difference of returns.
Money-flow scores are existing price/volume proxies, NOT measured fund inflows.

Event studies additionally require caller-supplied exchange session schedules
(date index, aware market_open/market_close columns). Never invent a calendar or
announcement time from a headline. Supplied conventional times with a verified
date are kept in a separate assumption bucket, never confirmed observations.
All mappings can be replaced by the caller;
the defaults below are editable display classifications, not official metadata.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

import pandas as pd

from stock_lab_core.asset_classifier import is_leveraged_or_inverse_product
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_close_basis import pending_close_mask

register_loaded_source(__name__, __file__)


DEFAULT_BENCHMARKS = {"US": "^GSPC", "KR": "^KS11"}
DEFAULT_SECTOR_MAP = {
    ticker: {"market": market, "sector": sector, "kind": "sector_etf"}
    for market, pairs in (
        ("US", (("XLK", "Technology"), ("XLC", "Communication"), ("XLF", "Financials"),
                ("XLV", "Health care"), ("XLE", "Energy"), ("XLI", "Industrials"),
                ("XLB", "Materials"), ("XLY", "Consumer discretionary"),
                ("XLP", "Consumer staples"), ("XLU", "Utilities"), ("VNQ", "Real estate"),
                ("SMH", "Semiconductors"), ("SOXX", "Semiconductors"),
                ("DRAM", "Memory"), ("IGV", "Software"),
                ("IBB", "Biotech"), ("PAVE", "Infrastructure"),
                ("ITA", "Aerospace and defense"), ("CIBR", "Cybersecurity"),
                ("XHB", "Homebuilders"))),
        ("KR", (("396500.KS", "Semiconductors"), ("305540.KS", "Batteries"),
                ("139250.KS", "Energy"), ("139270.KS", "Financials"),
                ("244580.KS", "Biotech"), ("139260.KS", "Technology"),
                ("487240.KS", "Power infrastructure"), ("494670.KS", "Shipbuilding"),
                ("449450.KS", "Defense"), ("329200.KS", "Real estate"))),
    ) for ticker, sector in pairs
}
# Fixed subset already present in money_flow.MONEY_FLOW_UNIVERSE, not a new scan.
ROTATION_UNIVERSE = tuple(DEFAULT_SECTOR_MAP)
DEFAULT_NEWS_TAGS = {
    "ipo": ("ipo", "initial public offering", "listing application", "기업공개", "상장예비심사", "공모주", "상장 추진", "신규상장"),
    "earnings": ("earnings", "quarterly results", "실적", "잠정실적"),
    "policy": ("tariff", "regulation", "policy", "fomc", "federal open market committee",
               "관세", "규제", "정책", "금통위", "금융통화위원회"),
}
DEFAULT_LISTING_STATUS = {}  # Caller-maintained: listed / ipo_candidate / unknown.
_MARKET_HOURS = {"US": ("America/New_York", "16:00"), "KR": ("Asia/Seoul", "15:30")}
_NON_SECTORS = {"SPY", "VOO", "IVV", "QQQ", "QQQM", "DIA", "IWM", "069500.KS", "229200.KS",
                "GLD", "SLV", "TLT", "IEF", "SHY", "UUP", "USO", "UNG", "HYG", "LQD", "IBIT"}
_NON_SECTORS.update({"SH", "PSQ", "DOG", "SDOW", "RWM", "SDS", "QID", "SSO", "ROM", "USD", "UWM",
                     "TECL", "TECS", "LABU", "LABD", "TNA", "TZA", "FNGU", "FNGD", "BULZ"})
_NON_SECTORS.update({"BIL", "SGOV", "SHV", "USFR", "TFLO", "ICSH", "JPST", "BOXX",
                     "459580.KS", "214980.KS", "488770.KS"})


def _records(rows):
    if isinstance(rows, pd.DataFrame):
        return rows.to_dict("records")
    return list(rows) if rows is not None else []


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _first(row, *keys):
    return next((row[k] for k in keys if k in row and _text(row[k])), None)


def _symbol(row):
    return _text(_first(row, "Ticker", "ticker", "티커")).upper()


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _timestamp(value):
    if value is None or isinstance(value, (int, float)):
        return None
    try:
        stamp = pd.Timestamp(value)
        return stamp.tz_convert("UTC") if not pd.isna(stamp) and stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _clock(value):
    stamp = _timestamp(value)
    if stamp is None:
        raise ValueError("as_of must be a timezone-aware timestamp")
    return stamp


def _day(value):
    try:
        return pd.Timestamp(value).date().isoformat() if value is not None and not pd.isna(value) else ""
    except (TypeError, ValueError):
        return ""


def _closes(frame, column):
    if not isinstance(frame, pd.DataFrame) or column not in frame or not isinstance(frame.index, pd.DatetimeIndex):
        return pd.Series(dtype=float)
    prices = pd.to_numeric(frame[column], errors="coerce").copy()
    prices.iloc[pending_close_mask(frame)] = float("nan")
    prices.index = frame.index.tz_localize(None).normalize()
    prices = prices.loc[prices.index.notna()]
    # Conflicting/repeated daily bars are missing evidence, not extra sessions.
    prices.loc[prices.index.duplicated(keep=False)] = float("nan")
    prices = prices.loc[~prices.index.duplicated()]
    return prices.where(prices.gt(0) & prices.map(lambda x: _number(x) is not None)).sort_index()


def _change(prices, sessions, offset=0):
    end = len(prices) - 1 - offset
    start = end - sessions
    if start < 0 or prices.iloc[start:end + 1].isna().any():
        return None
    return float(prices.iloc[end] / prices.iloc[start] - 1)


def _excluded_product(ticker, meta, rows):
    description = " ".join(_text(row.get(key)) for row in [meta, *rows]
                           for key in ("name", "sector", "kind", "asset_class", "종목명", "섹터", "ETF 이름", "구분"))
    if ticker.startswith("^") or ticker.endswith(("=X", "=F", "-USD")) or ticker in _NON_SECTORS:
        return True
    if is_leveraged_or_inverse_product(description, ticker, _text(meta.get("kind"))):
        return True
    return any(row.get(key) is True for row in [meta, *rows] for key in ("leveraged", "inverse", "macro")) or bool(
        re.search(r"\b(macro|inverse|leveraged|bond|treasury|currency|commodity|cash|money.market)\b|거시|국채|채권|인버스|레버리지|현금|머니마켓|금리형|CD금리|KOFR", description, re.I))


def build_sector_rotation(price_frames, flow_rows=None, *, sessions, as_of,
                          sector_map=None, benchmarks=None):
    """Rank each market separately on its exact supplied completed benchmark date.

    rs_5d_change/rs_20d_change = (ETF/benchmark)_t / (ETF/benchmark)_(t-N) - 1,
    NOT an RS level. No inner-join compression or forward filling is allowed.
    3M = 63 benchmark sessions; accel_3m = last 63 return - preceding 63 return.
    Top/bottom three use 20D RS change; improving laggards have 20D < 0, 5D > 0.
    Missing short history excludes ranking; missing 3M/flow remains explicit.
    Flow scores require an exact matching date; undated rows never become zero.
    """
    now = _clock(as_of)
    mapping = DEFAULT_SECTOR_MAP if sector_map is None else sector_map
    benchmark_map = DEFAULT_BENCHMARKS if benchmarks is None else benchmarks
    flows = defaultdict(list)
    for row in _records(flow_rows):
        flows[_symbol(row)].append(row)
    output = {"kind": "observation_hypothesis", "not_trade_signal": True, "as_of": now.isoformat(),
              "markets": {}, "excluded": [], "units": "fractional_returns",
              "money_flow_note": "Price/volume proxy, not observed capital inflows."}
    for ticker, meta in sorted(mapping.items()):
        ticker = ticker.upper()
        market = meta.get("market")
        benchmark = benchmark_map.get(market)
        reason = ""
        day = _day(sessions.get(market))
        if meta.get("kind") != "sector_etf" or _excluded_product(ticker, meta, flows[ticker]) or ticker == benchmark:
            reason = "not_unlevered_sector_etf"
        elif market not in _MARKET_HOURS or not benchmark or not day:
            reason = "missing_market_basis"
        else:
            zone, close_time = _MARKET_HOURS[market]
            if pd.Timestamp(f"{day} {close_time}", tz=zone) > now:
                reason = "unfinished_market_session"
        if reason:
            output["excluded"].append({"ticker": ticker, "reason": reason})
            continue
        asset_frame, base_frame = price_frames.get(ticker), price_frames.get(benchmark)
        column = next((col for col in ("Adj Close", "Close")
                       if not _closes(asset_frame, col).loc[:day].dropna().empty
                       and not _closes(base_frame, col).loc[:day].dropna().empty), "")
        asset, base = _closes(asset_frame, column), _closes(base_frame, column).loc[:day]
        if base.empty or base.index[-1].date().isoformat() != day or base.iloc[-1:].isna().any():
            reason = "missing_benchmark_close"
        else:
            asset = asset.reindex(base.index)
            relative = asset / base
            rs5, rs20 = _change(relative, 5), _change(relative, 20)
            if rs5 is None or rs20 is None:
                reason = "missing_aligned_21_session_history"
        if reason:
            output["excluded"].append({"ticker": ticker, "reason": reason})
            continue
        ret3m, prev3m = _change(asset, 63), _change(asset, 63, 63)
        matching = [r for r in flows[ticker] if _day(_first(r, "기준일", "asof", "date")) == day]
        scores = {_number(_first(r, "돈흐름점수", "money_flow_score")) for r in matching}
        score = next(iter(scores)) if len(scores) == 1 else None
        row = {"ticker": ticker, "sector": meta.get("sector", ticker), "market": market,
               "benchmark": benchmark, "date": day, "price_basis": column,
               "rs_5d_start": base.index[-6].date().isoformat(),
               "rs_20d_start": base.index[-21].date().isoformat(),
               "rs_5d_change": rs5, "rs_20d_change": rs20, "return_3m": ret3m,
               "accel_3m": ret3m - prev3m if ret3m is not None and prev3m is not None else None,
               "money_flow_score": score, "money_flow_date": day if score is not None else None}
        row["missing"] = [key for key in ("return_3m", "accel_3m", "money_flow_score") if row[key] is None]
        output["markets"].setdefault(market, {"benchmark": benchmark, "date": day, "rows": []})["rows"].append(row)
    for market in output["markets"].values():
        rows = market["rows"]
        market["sample_count"] = len(rows)
        market["top3"] = sorted(rows, key=lambda r: (-r["rs_20d_change"], r["ticker"]))[:3]
        market["bottom3"] = sorted(rows, key=lambda r: (r["rs_20d_change"], r["ticker"]))[:3]
        market["improving_laggards3"] = sorted(
            (r for r in rows if r["rs_20d_change"] < 0 < r["rs_5d_change"]),
            key=lambda r: (-r["rs_5d_change"], r["ticker"]))[:3]
    return output


def _schedule(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not {"market_open", "market_close"}.issubset(frame.columns):
        return None
    schedule = frame.copy()
    days = [_day(day) for day in schedule.index]
    if not all(days) or len(set(days)) != len(days):
        return None
    schedule.index = pd.DatetimeIndex(days)
    for key in ("market_open", "market_close"):
        values = [_timestamp(value) for value in schedule[key]]
        if any(value is None for value in values):
            return None
        schedule[key] = pd.DatetimeIndex(values)
    schedule = schedule.sort_index()
    if (schedule.market_open >= schedule.market_close).any():
        return None
    if (schedule.market_open.iloc[1:].reset_index(drop=True) <= schedule.market_close.iloc[:-1].reset_index(drop=True)).any():
        return None
    return schedule


def _distribution(values):
    series = pd.Series(values, dtype=float)
    return {"sample_count": len(values), **{name: float(value) if len(values) else None for name, value in {
        "mean": series.mean(), "median": series.median(), "min": series.min(), "max": series.max(),
        "p25": series.quantile(.25), "p75": series.quantile(.75),
        "positive_fraction": (series > 0).mean() if len(values) else None,
    }.items()}}


def _event_time_basis(row):
    return "schedule_rule" if row.get("release_precision") == "schedule_rule" else "confirmed"


def _assumption_problem(row, at):
    """Validate an explicit date/clock supplied by the caller; never choose one."""
    day = _text(_first(row, "release_date", "date"))
    if (row.get("release_date_confirmed") is not True or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
            or _day(day) != day):
        return "missing_confirmed_release_date"
    if not _text(row.get("schedule_rule")) or not _first(row, "schedule_rule_source_url", "schedule_rule_source"):
        return "missing_time_assumption_or_source"
    if at is None:
        return "missing_assumed_timestamp"
    zone = _text(row.get("timezone")) or _MARKET_HOURS.get(row.get("market"), ("", ""))[0]
    try:
        local_day = at.tz_convert(zone).date().isoformat() if zone else ""
    except (KeyError, TypeError, ValueError):
        return "invalid_assumption_timezone"
    if local_day != day:
        return "assumed_timestamp_date_mismatch"
    return ""


def historical_earnings_events(context, *, as_of, session_schedules=None, allow_conventional=False):
    """Map already-connected official results into study inputs without I/O.

    Official result pages take precedence over the same ticker/fiscal-period
    calendar entry. An elapsed schedule, conference call or news story is not
    publication evidence. URLs reuse the collector's exact issuer-bound checks.
    Date-only results need explicit opt-in and a caller-supplied exchange
    schedule: the actual session close becomes a LABELED timing assumption,
    never an announced_at fact. No missing publication date/calendar is filled.
    build_event_study still enforces complete pre/post windows for these inputs.
    """
    from stock_lab_core.earnings_result_sources import is_official_result_url

    now = _clock(as_of)
    schedules = {market: _schedule(frame) for market, frame in (session_schedules or {}).items()}
    output = {"events": [], "skipped": []}
    results = [dict(row, _result=True) for row in _records(context.get("earnings_results"))]
    calendar = [dict(row, _result=False) for row in _records(context.get("calendar_events")) if row.get("ticker")]
    seen = set()
    for row in results + calendar:
        ticker, period = _symbol(row), _text(row.get("fiscal_period"))
        identity = (ticker, period)
        if identity in seen:
            continue
        market = "KR" if ticker.endswith((".KS", ".KQ")) else "US"
        zone = _MARKET_HOURS[market][0]
        day = _text(row.get("release_date") if row["_result"] else row.get("date"))
        checked = _timestamp(row.get("checked_at") if row["_result"] else row.get("source_verified_at"))
        source = _text(row.get("source_url"))
        reason = ""
        published = (row.get("status") == "official_result" if row["_result"] else
                     row.get("event_status") == "released" and row.get("release_date_confirmed") is True
                     and row.get("event_kind") != "conference_call")
        if not published:
            reason = "unconfirmed_publication"
        elif not ticker or not period or not is_official_result_url(ticker, source):
            reason = "missing_event_identity_or_official_source"
        elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or _day(day) != day:
            reason = "missing_confirmed_release_date"
        elif checked is None or checked > now:
            reason = "confirmation_not_available_as_of"
        elif day > now.tz_convert(zone).date().isoformat():
            reason = "future_event"
        event = {"event_id": f"earnings:{ticker}:{period}", "ticker": ticker, "market": market,
                 "event_type": "earnings", "confirmed": True, "release_date_confirmed": True,
                 "date": day, "timezone": zone, "source_url": source,
                 "known_at": checked.isoformat() if checked is not None else None}
        if not reason and row.get("release_precision") == "datetime":
            at = _timestamp(row.get("release_at"))
            if at is None or row.get("release_time_confirmed") is False:
                reason = "missing_confirmed_timestamp"
            elif at > now or at > checked:
                reason = "confirmation_not_available_as_of"
            elif at.tz_convert(zone).date().isoformat() != day:
                reason = "release_timestamp_date_mismatch"
            else:
                event.update(announced_at=at.isoformat(), release_precision="datetime", release_time_confirmed=True)
        elif not reason:
            schedule = schedules.get(market)
            if not allow_conventional:
                reason = "missing_confirmed_timestamp"
            elif row.get("release_precision") != "date":
                reason = "unconfirmed_event"
            elif schedule is None or pd.Timestamp(day) not in schedule.index:
                reason = "missing_or_invalid_session_schedule"
            else:
                event.update(release_at=schedule.loc[day, "market_close"].isoformat(),
                    release_precision="schedule_rule", release_time_confirmed=False,
                    schedule_rule="Exchange-close timing assumption; actual publication minute unconfirmed",
                    schedule_rule_source="Caller-supplied exchange schedule; modeling assumption, not release evidence")
        if reason:
            output["skipped"].append({"event_id": event["event_id"], "ticker": ticker, "reason": reason})
        else:
            seen.add(identity)
            output["events"].append(event)
    return output


def build_event_study(events, price_frames, *, as_of, window=5, session_schedules=None):
    """Completed N-session pre/post close returns, grouped by ticker/event type.

    Each event needs event_id, ticker, market, event_type, confirmed=True,
    aware announced_at (or release_at), and source/source_url. Schedules must be
    complete exchange calendars for the window, including special closes.
    Before-open announcements map to that open; at/after-close announcements
    map to the next supplied open. Intraday announcements cannot be isolated
    with daily bars and are excluded. No date-only/estimated/news dates accepted.
    An explicit release_precision='schedule_rule' also needs confirmed=True,
    release_date_confirmed=True, date/release_date, aware release_at/announced_at,
    schedule_rule and schedule_rule_source(_url). Its supplied clock is an
    assumption, not a verified announcement: separate assumption_observations,
    assumption_groups and assumption_sample_count never enter confirmed counts
    or hypotheses. The local date must match the verified date. No default
    time or date is generated, and all existing price/calendar checks apply.
    Pre = C[i-1]/C[i-N-1]-1; post = C[i+N-1]/C[i-1]-1 (includes reaction gap).
    Missing bars never shorten N. Duplicate IDs and same-time/type aliases do
    not multiply samples; conflicting timestamps for one ID are all excluded.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("window must be a positive integer number of sessions")
    now = _clock(as_of)
    rows = _records(events)
    schedules = {key: _schedule(value) for key, value in (session_schedules or {}).items()}
    output = {"kind": "historical_observation", "not_trade_signal": True, "as_of": now.isoformat(),
              "window": window, "observations": [], "groups": [], "skipped": [], "sample_count": 0,
              "assumption_observations": [], "assumption_groups": [], "assumption_sample_count": 0,
              "limitations": "Descriptive, not causal or a forecast. Overlapping distinct-event windows are not independent."}
    times_by_id = defaultdict(set)
    confirmed_ids, confirmed_occurrences = set(), set()
    for row in rows:
        at = _timestamp(_first(row, "announced_at", "release_at"))
        basis = _event_time_basis(row)
        identity = (_symbol(row), _text(row.get("event_id")))
        if row.get("confirmed") is True and at is not None:
            times_by_id[(identity, basis)].add(at)
            if (basis == "confirmed" and row.get("release_time_confirmed") is not False
                    and row.get("release_precision") in (None, "", "datetime")):
                confirmed_ids.add(identity)
                zone = _MARKET_HOURS.get(row.get("market"), ("UTC", ""))[0]
                confirmed_occurrences.add((_symbol(row), _text(_first(row, "event_type", "indicator")).casefold(),
                                           at.tz_convert(zone).date().isoformat()))
    seen_ids, seen_occurrences = set(), set()
    for row in rows:
        ticker, event_id = _symbol(row), _text(row.get("event_id"))
        kind = _text(_first(row, "event_type", "indicator"))
        at = _timestamp(_first(row, "announced_at", "release_at"))
        basis = _event_time_basis(row)
        assumed = basis == "schedule_rule"
        identity = (ticker, event_id)
        occurrence = (ticker, kind.casefold(), _text(_first(row, "release_date", "date")) if assumed else at, basis)
        reason = ""
        if row.get("confirmed") is not True or (not assumed and (
                row.get("release_time_confirmed") is False or row.get("release_precision") not in (None, "", "datetime"))):
            reason = "unconfirmed_event"
        elif not event_id or not ticker or not kind or not _first(row, "source_url", "source"):
            reason = "missing_event_identity_or_source"
        elif assumed and _assumption_problem(row, at):
            reason = _assumption_problem(row, at)
        elif at is None:
            reason = "missing_confirmed_timestamp"
        elif at > now:
            reason = "future_event"
        elif any(row.get(key) is not None and (_timestamp(row[key]) is None or _timestamp(row[key]) > now)
                 for key in ("confirmed_at", "known_at")):
            reason = "confirmation_not_available_as_of"
        elif assumed and (identity in confirmed_ids or
                (ticker, kind.casefold(), _text(_first(row, "release_date", "date"))) in confirmed_occurrences):
            reason = "superseded_by_confirmed_timestamp"
        elif len(times_by_id[(identity, basis)]) > 1:
            reason = "conflicting_event_timestamp"
        elif (identity, basis) in seen_ids or occurrence in seen_occurrences:
            reason = "duplicate_event"
        schedule = schedules.get(row.get("market"))
        if not reason and schedule is None:
            reason = "missing_or_invalid_session_schedule"
        if not reason:
            seen_ids.add((identity, basis))
            seen_occurrences.add(occurrence)
            intraday = (schedule.market_open < at) & (at < schedule.market_close)
            positions = [i for i, opening in enumerate(schedule.market_open) if opening >= at]
            if intraday.any():
                reason = "intraday_requires_intraday_prices"
            elif not positions:
                reason = "no_next_trade_in_schedule"
            else:
                i = positions[0]
                if i < window + 1:
                    reason = "insufficient_pre_history"
                elif i + window > len(schedule) or schedule.market_close.iloc[i + window - 1] > now:
                    reason = "unfinished_post_window"
        if not reason:
            dates = schedule.index[i - window - 1:i + window]
            frame = price_frames.get(ticker)
            column = next((col for col in ("Adj Close", "Close") if not _closes(frame, col).loc[:dates[-1]].dropna().empty), "")
            prices = _closes(frame, column).reindex(dates)
            if prices.isna().any():
                reason = "missing_price_in_event_window"
        if reason:
            output["skipped"].append({"event_id": event_id, "ticker": ticker, "reason": reason, "time_basis": basis})
            continue
        observation = {"event_id": event_id, "ticker": ticker, "event_type": kind,
            "announced_at": None if assumed else at.isoformat(), "reaction_date": schedule.index[i].date().isoformat(),
            "reaction_open": schedule.market_open.iloc[i].isoformat(),
            "pre_start_date": dates[0].date().isoformat(), "baseline_date": dates[window].date().isoformat(),
            "post_end_date": dates[-1].date().isoformat(), "completed_at": schedule.market_close.iloc[i + window - 1].isoformat(),
            "pre_return": float(prices.iloc[window] / prices.iloc[0] - 1),
            "post_return": float(prices.iloc[-1] / prices.iloc[window] - 1), "price_basis": column,
            "source": _text(_first(row, "source_url", "source")), "time_basis": basis}
        if assumed:
            observation.update(assumed_release_at=at.isoformat(), release_time_confirmed=False,
                release_date=_text(_first(row, "release_date", "date")),
                time_assumption=_text(row["schedule_rule"]),
                time_assumption_source=_text(_first(row, "schedule_rule_source_url", "schedule_rule_source")))
        output["assumption_observations" if assumed else "observations"].append(observation)
    for prefix in ("", "assumption_"):
        groups = defaultdict(list)
        for row in output[prefix + "observations"]:
            groups[(row["ticker"], row["event_type"], row["price_basis"], row.get("time_assumption", ""))].append(row)
        for (ticker, kind, basis, assumption), samples in sorted(groups.items()):
            group = {"ticker": ticker, "event_type": kind, "price_basis": basis,
                "sample_count": len(samples), "event_ids": [r["event_id"] for r in samples],
                "pre": _distribution([r["pre_return"] for r in samples]),
                "post": _distribution([r["post_return"] for r in samples])}
            if prefix:
                group.update(time_basis="schedule_rule", time_assumption=assumption, release_time_confirmed=False)
            output[prefix + "groups"].append(group)
    output["sample_count"] = len(output["observations"])
    output["assumption_sample_count"] = len(output["assumption_observations"])
    return output


def tag_candidate_news(news_rows, *, tag_keywords=None, entity_keywords=None, listing_status_map=None):
    """Editable keyword/entity mappings; candidates never become official dates.

    entity_keywords maps a ticker to a sequence of company/sector phrases.
    listing_status_map maps matched tickers to listed/ipo_candidate/unknown;
    it is manual, unverified context, never inferred from an IPO headline.
    published_at is retained ONLY as news_published_at, not announcement time.
    Caller-supplied event dates/confirmation flags are deliberately not promoted.
    """
    keywords = DEFAULT_NEWS_TAGS if tag_keywords is None else tag_keywords
    listing_status = DEFAULT_LISTING_STATUS if listing_status_map is None else listing_status_map
    output, seen = [], set()
    for row in _records(news_rows):
        title = _text(_first(row, "title", "제목"))
        body = title + " " + _text(_first(row, "summary", "description", "요약"))
        tags = [tag for tag, words in sorted(keywords.items()) if any(_keyword(word, body) for word in words)]
        if not tags:
            continue
        url = _text(_first(row, "url", "link", "source_url"))
        published = _text(_first(row, "published_at", "published", "시간"))
        identity = url or (title.casefold(), published)
        if identity in seen:
            continue
        seen.add(identity)
        tickers = sorted(ticker for ticker, words in (entity_keywords or {}).items()
                         if any(_keyword(word, body) for word in words))
        output.append({"title": title, "source_url": url, "news_published_at": published,
            "candidate_tags": tags, "candidate_tickers": tickers,
            "candidate_listing_status": {ticker: listing_status[ticker] if listing_status.get(ticker) in
                ("listed", "ipo_candidate", "unknown") else "unknown" for ticker in tickers},
            "listing_status_basis": "manual_unverified", "status": "unconfirmed",
            "confirmed": False, "official_date": None, "release_at": None,
            "basis": "Editable keyword mapping; verify against an original official announcement."})
    return output


def _keyword(word, body):
    word = _text(word)
    if not word:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])" if word.isascii() else re.escape(word)
    return bool(re.search(pattern, body, re.I))


def build_observation_hypotheses(rotation=None, event_study=None, candidate_news=None):
    """Exactly three falsifiable rule-based slots; never fabricate missing evidence.

    Inputs are outputs of the helpers above. No call_llm_analysis call is made:
    the app's current hook is a prompt-returning stub, not a live LLM.
    """
    markets = (rotation or {}).get("markets", {})
    rows = [row for market in markets.values() for row in market["rows"]]
    hypotheses = []

    def add(key, statement, evidence, falsifier, schedule, missing=()):
        hypotheses.append({"id": key, "kind": "observation_hypothesis", "not_trade_signal": True,
            "generator": "rule_based_no_llm", "status": "supported_observation" if evidence else "insufficient_data",
            "hypothesis": statement, "evidence": evidence, "falsifier": falsifier,
            "check_schedule": schedule, "missing": list(missing)})

    leaders = sorted((r for r in rows if r["rs_20d_change"] > 0 and r["rs_5d_change"] > 0),
                     key=lambda r: (-r["rs_20d_change"], r["ticker"]))
    leader = leaders[:1]
    add("relative_leadership", f"{leader[0]['ticker']} shows positive aligned 5D and 20D RS changes versus {leader[0]['benchmark']}; this describes observed leadership, not its continuation." if leader else
        "Relative leadership is unestablished; positive aligned 5D and 20D RS evidence is required.",
        leader, "Rechecking the same ETF's aligned dates and prices yields non-positive 5D or 20D RS change.",
        "Recheck after the next completed session of the same market, using matching benchmark dates.",
        () if leader else ("positive_aligned_5d_and_20d_rs",))
    laggards = sorted((r for r in rows if r["rs_20d_change"] < 0 < r["rs_5d_change"]),
                      key=lambda r: (-r["rs_5d_change"], r["ticker"]))
    recovery = laggards[:1]
    add("laggard_recovery", f"{recovery[0]['ticker']} shows positive 5D but negative 20D RS change; a recovery interpretation is hypothetical, not a reversal forecast." if recovery else
        "Laggard recovery is unestablished; negative 20D and positive 5D RS evidence is required.",
        recovery, "Rechecking the same ETF's aligned prices does not reproduce negative 20D and positive 5D RS changes.",
        "Recheck each completed session and after five additional observed benchmark sessions.",
        () if recovery else ("negative_20d_positive_5d_rs",))
    groups = sorted((g for g in (event_study or {}).get("groups", []) if g["sample_count"] >= 3 and g["post"]["median"] != 0),
                    key=lambda g: (-g["sample_count"], g["ticker"], g["event_type"]))
    group = groups[:1]
    candidate_count = len(_records(candidate_news))
    if group:
        g = group[0]
        direction = "positive" if g["post"]["median"] > 0 else "negative"
        statement = f"{g['ticker']}'s observed post-event return distribution for {g['event_type']} has a {direction} median across {g['sample_count']} completed observations; any event association is hypothetical, not causal or a next-event prediction."
    else:
        statement = "A historical event association is unestablished; at least three completed comparable observations are required."
        if candidate_count:
            statement += f" {candidate_count} unconfirmed news candidates are verification leads, not event samples."
    add("event_response", statement, group,
        "Rechecking announcement timestamps, duplicates, or comparable non-event windows removes support for the proposed association.",
        "Verify the original announcement first, then recheck only after all N post-event sessions close; no date is inferred.",
        () if group else ("three_completed_confirmed_comparable_events",))
    # Detach nested evidence so a consumer cannot mutate upstream calculations.
    from copy import deepcopy
    return deepcopy(hypotheses)
