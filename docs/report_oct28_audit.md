# October 28 report audit

## Scope and unchanged behavior

Report presentation, public evidence collection and isolated observation modules
only. Existing signal scores, thresholds, market gates and order behavior are
unchanged. No order submission or brokerage execution was added.

## One account definition

`report_account.cumulative_account_metrics` weights each holding once. For US
holdings it compounds the latest completed regular-session return with a valid
subsequent regular/extended observation: `(1 + regular) * (1 + subsequent) - 1`.
For KR holdings it uses the latest observation relative to the preceding KR
close. Missing baseline dates or stale/mismatched legs are excluded, not zero.
The report displays dates, coverage and market groups under one cumulative
total. This asynchronous, current-weight estimate is not daily account P/L.

## Corrections

- Closed KR sessions no longer use the intraday headline label.
- Stress attribution identifies a monthly-change sign flip only when holding
  the current level and restoring the old monthly change reproduces the old
  contribution. Stress formulas remain unchanged.
- Quote-table news posts are excluded; trailing commas in candidate names are
  removed for display only.
- Official earnings releases and conference calls are distinguished, including
  recent results formerly hidden by future-only filtering. Coverage is seven
  explicit issuers, verified on 2026-10-28, with bounded public requests and
  expiring verified snapshots. It is not a complete future-quarter calendar.
- Korea Customs detail ConnectTimeout gets one bounded retry (2s connect / 4s
  read), then a 180s failure cooldown. HTTP/parse failures are not retried. Live
  public list/detail verification returned HTTP 200 and a parsed observation.

## Observation extensions and limits

- FRED BAMLH0A0HYM2 adds dated HY credit-spread evidence. Existing manually
  queried real Kiwoom sector flows can be shown if fresh; overlapping totals
  are not summed. Market-wide breadth, turnover, margin balance and leverage
  concentration remain unconnected and are explicitly labeled as such.
- Sector rotation reuses existing price frames. KR/US rankings are separate;
  exact completed dates, matching benchmarks and missing-data exclusion apply.
- News catalyst tags are unconfirmed candidates, not event dates or causes.
- Event-study calculations are implemented and tested, but production historical
  confirmed announcement timestamps and exchange schedules are not connected.
  Therefore the report currently shows zero samples, not fabricated distributions.
- Exactly three evidence/falsifier/schedule observations are rendered by rules.
  The existing LLM integration is not connected; no LLM generation is claimed.
- The optional event ledger is manual and separate from signal verification.
  Per-trade loss budget defaults to unset. Risk at a stop is not a guaranteed
  maximum loss. A saved trade keeps its ID across resubmissions; only explicit
  new-trade initiation changes the ID. CSV formula cells are escaped.
- `20261028_event_swing_ledger.sql` provides owner-scoped RLS schema. It has not
  been executed on the user's database. Save stays unavailable until the
  dedicated table/permissions are connected; no false save-success message.

## Performance measurement

Three controlled repetitions per version with identical 10ms transport latency:

| Case | Before median | After median | Network requests |
| --- | ---: | ---: | ---: |
| Cold raw news retrieval | 73.73ms | 74.97ms | 12 / 12 |
| Warm retrieval | 21.34ms | 21.03ms | 0 / 0 |

Output hashes match. There is no demonstrated meaningful speedup. A 60s
success-only raw-bundle cache and a separate `report_news` measurement were
added; classification still runs against current session windows. Partial and
empty results are not retained at bundle level; existing query cooldowns remain.
The Cloud report-context 27s was not reproduced by this controlled benchmark.

Current latest-price loading already uses six workers. Summed nested call time
is not elapsed time. No new price-batching source/fallback changes were shipped.

## Validation

Focused tests cover compound account returns, missing baselines, mode labels,
MOVE attribution, publisher table filtering, official earnings coverage,
customs retry/cooldown, observation/event-study leakage, missing sentiment data,
manual risk settings and unchanged input records. Full regression results and
deployment verification are reported in the task close-out.
