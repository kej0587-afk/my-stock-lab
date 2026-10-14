# 2026-10-14 Startup And Provider Recovery

## Scope

- Checked the updated working tree before making changes.
- Preserved trading labels, thresholds, candidate grades and scoring rules.
- No authentication, credentials, database writes or deployment changes.
- Reused one audit agent for an independent review; no broad refactor.

## 1-A: Startup

Local Windows Python 3.11.9 / Streamlit 1.56.0. Cloud is a different environment.
Three isolated servers reached HTTP 200 on both health endpoints in 7.021,
4.001 and 3.359 seconds. Connection refusal occurred before readiness.
Neither supplied log establishes a fatal crash, OOM or persistent port error.
Do not move DB initialization as a speculative health-check fix.

## 1-B: Yahoo Metadata

- Share `info` successes across display names, news and analyst views.
- Serialize metadata probes and share 429 cooldown with earnings calendars.
- Backoff starts at 180 seconds, doubles on repeated throttling, capped at 1800.
- Manual cache clearing cannot bypass the active provider cooldown.
- Retain bounded last-success snapshots with their original fetch time.
- Analyst freshness is six hours even if display-name metadata lasts a day.
- Stale targets are audit-only; they cannot populate executable upside maps.
- Propagate rate limits and lookup errors rather than claiming no coverage.
- Stop swallowing direct HTTP 429, refresh the actual crumb timestamp after
  HTTP 401, and avoid retrying the same empty response on the same host.

Quote/history price fallbacks retain their existing provider selection. The new
metadata circuit is not a claim that every Yahoo endpoint shares one limiter.

## 1-C: Existing And Remaining Bugs

Keltner keyword arguments, filled FVGs, exhausted order blocks and the prior-bar
52-week high were already fixed. Existing synthetic tests confirm them.
Fixed remaining long-lived failure caches: empty price history (formerly 300s)
and missing FX (formerly 3600s) now have separate 15s retry suppression.
Current-price failures have separate 5s suppression, without an immediate
second traversal of the full provider chain. Successful TTLs are unchanged.

## Loading Measurements

Same-input synthetic throttling probe, ten symbols / ten price reads:

| Provider attempts | Before | After |
| --- | ---: | ---: |
| Info + calendar | 11 | 1 |
| Current price | 11 | 1 |

Local public-demo AppTest wall time, fresh test process:

| Rendering | Before | After |
| --- | ---: | ---: |
| First | 11.457s | 8.723s |
| Rerun | 2.749s | 2.636s |

These include variable external response times, not a guaranteed Cloud saving.
A separate instrumented first render found three display-name lookups totaling
2.201s. Full chart identity now precedes heavy info only for display names;
short/truncated names still fall back to full info. Sector/analyst data does not
use identity-only fields. A successful name is cached for one day.

The instrumented top ten inclusive entries were sanitize_watchlist_item (12,
2.301s), load_watchlist_persistent (1, 2.259s), get_public_demo_watchlist (1,
2.259s), its list comprehension (1, 2.254s), sanitize_asset_name (12, 2.243s),
resolve_display_name_for_ticker (3, 2.207s), lookup_yfinance_display_name (3,
2.201s), cache wrapper (3, 2.191s), failure wrapper (3, 2.189s), success wrapper
(3, 2.187s). Nested inclusive timings overlap and must not be added together.
The profiled render took 21.712s and is not comparable to unprofiled wall time.

## Verification And Limits

Regression tests cover cross-view/cross-symbol throttling, increasing backoff,
concurrent fetch deduplication, stale expiry, original target timestamps,
snapshot expiry without renewal, status propagation and price-cache recovery.
Public-demo first render and rerun have zero AppTest exceptions.
Final full suite: 816 passed in 37.04s; one existing pykrx deprecation warning.
`git diff --check` reports no whitespace errors.
No Cloud deployment or authenticated private-portfolio performance test.

Primary references consulted:
- https://github.com/ranaroussi/yfinance/blob/0.2.66/yfinance/scrapers/quote.py
- https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
