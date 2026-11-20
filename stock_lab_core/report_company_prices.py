"""Report-only issuer observations; never feed portfolio or decision inputs."""

import re
from time import perf_counter

from stock_lab_core.earnings_discovery import issuer_catalog
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import price_observation
from stock_lab_core.report_price_quality import validate_report_prices

register_loaded_source(__name__, __file__)

_FUND = re.compile(r"\b(?:ETF|ETN|TDF|fund|target[ -]?date)\b|펀드|타깃데이트|타겟데이트", re.I)


def company_catalog(summary_rows=()):
    """Reuse the representative universe, excluding fund aliases in report scope."""
    return {ticker: row for ticker, row in issuer_catalog(summary_rows).items()
            if not any(_FUND.search(str(name)) for name in [row["name"], *row.get("aliases", ())])}


def collect_company_prices(summary_rows, frames, benchmark_prices, sessions, now, *,
                           allow_fetch=True, loader=None, regular_loader=None):
    """Reuse available histories and batch only missing ones using existing TTLs.

    Injected report fixtures set allow_fetch=False. Missing/stale histories stay
    missing rather than substituting an intraday quote or another session.
    """
    started = perf_counter()
    catalog = company_catalog(summary_rows)
    selected = {ticker: frames[ticker] for ticker in catalog
                if ticker in frames and frames[ticker] is not None and not frames[ticker].empty}
    missing = tuple(sorted(set(catalog) - set(selected)))
    reused = len(selected)
    error = ""
    regular_basis = loader is None or regular_loader is not None
    overseas_missing = tuple(t for t in missing if not regular_basis or not t.endswith((".KS", ".KQ")))
    if overseas_missing and allow_fetch:
        if loader is None:
            from stock_lab_core.prices import prefetch_price_data_parallel
            loader = prefetch_price_data_parallel
        try:
            fetched = loader(overseas_missing, period="1y", max_workers=4)
            selected.update({ticker: frame for ticker, frame in fetched.items() if ticker in missing})
        except Exception as exc:
            error = type(exc).__name__
    # Apply the existing split/large-change guard, not an inferred price repair.
    if allow_fetch and regular_basis:
        from stock_lab_core.kr_regular_history import align_regular_frames
        selected = align_regular_frames(selected, catalog, now, **({"loader": regular_loader} if regular_loader else {}))
    selected, notes, issues, _ = validate_report_prices(selected, {}, now, etf_tickers=tuple(catalog))
    result = {}
    for ticker, entry in catalog.items():
        observation = price_observation(selected.get(ticker), ticker, now)
        market = entry["market"]
        benchmark = benchmark_prices.get("^KS11" if market == "KR" else "^GSPC", {})
        expected = (sessions.get(market), benchmark.get("previous_date"))
        actual = (observation.get("date"), observation.get("previous_date"))
        if (not all(expected) or benchmark.get("date") != expected[0]
                or benchmark.get("return") is None or benchmark.get("stale") or actual != expected):
            observation = dict(observation)
            observation.update({"return": None, "stale": True,
                                "missing_reason": "시장지수와 종가 기준일·직전 거래일 불일치 또는 이력 미수집"})
        result[ticker] = observation
    coverage = {market: {"expected": sum(e["market"] == market for e in catalog.values()),
                         "connected": sum(catalog[t]["market"] == market and o.get("return") is not None
                                          for t, o in result.items())} for market in ("KR", "US")}
    return result, {"coverage": coverage, "reused_frames": reused,
                    "requested_symbols": len(missing) if allow_fetch else 0,
                    "elapsed_seconds": perf_counter() - started, "error": error,
                    "notes": notes, "issues": issues,
                    "scope": "대표주·보유·관심 기업 표본; 지수 전체 구성종목 아님"}
