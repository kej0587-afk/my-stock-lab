# Upcoming events and what to watch — 2026-11-15

Base: 27e039e9. The user's new event-watch request supersedes the previously
queued article-story task. No account records, scores, thresholds, grades,
gates, price inputs, consensus values or existing cache TTLs are changed.

## Behavior

The main report's existing final calendar now shows sourced local/Korean dates,
scheduled/result-pending/result-confirmed state, concrete checks, conditional
interpretations and existing holding/sector exposure links. A report generation
rebuilds this view using the providers' normal caches. Saved reports remain
timestamped snapshots: no background scheduler or unsolicited messages added.

Official Census ADVANCE retail schedules are distinguished from the adjacent
monthly retail table. APEC's institutional meeting dates do not confirm a
bilateral summit or policy agreement. Cboe November/December 2026 dates were
visually verified against its official color-coded PDF: last trading day and
expiration are separate. The finite mapping requires an unchanged live PDF
SHA256 and expires at 2027-01-01; a changed PDF cannot silently use old dates.
These are bounded additions using release_calendar's existing timeout and
success cache, with parallel requests. No recurring weekday/date inference.
When the Census table omits its time zone, one optional current MARTS PDF fetch
reads the exact next-release sentence on page 2. Only matching target month and
date receive that time; the preceding release's clock is never copied. Live
verification linked October's November 17 08:30 EST /22:30 KST release. Failed
clock proof retains the date and reports the missing source. At most four new
bounded requests, not an assumed zero-cost feature.

The NVIDIA October 28 IR announcement supersedes the older call-only evidence
for reports as of November 15 onward. November 17 is the after-close result date;
the 17:00 EST call is November 18 07:00 KST. The approximate result time is not
promoted to an exact time. The original historical and expiry guards remain.

Elapsed time is not proof of a released result. Economic completion requires
matching indicator, period and local release date, an observed value and no
stale/future flag. News-only results remain separate from official results.
IPO/summit articles remain watch material unless the event source confirms a
date. Unsupported numeric probabilities and 25/50bp policy conclusions are not
generated. Conditional interpretation combines consumption, wages, prices and
Fed evidence. AI adoption checks include paid users, revenue, cost/margin and
durable sector relative strength alongside cash generation and investment.

Original detailed report evidence is preserved in the existing collapsed audit
appendix. Offline injected inputs keep the original renderer unless the explicit
market_watch_sources marker is supplied. The new modules participate in the
loaded/disk source fingerprint guard.

## Verification and deployment

Integrated calendar, reading, earnings-pipeline, event-study and source tests:
171 passed (final related run). Calendar collector live probe connected all four sources;
the private sample was generated at21:51KST. First decision gate:1369passed,
but correctly blocked because concurrent calendar edits changed source hashes.
Stable-source decision gate:1369passed, no failures/errors/skips,136.985s.
Subsequent display-only follow-up retains next-month macro schedules, explicitly
labels standard-rule times and preserves existing policy/debt deadlines. New
tables separate the coming week/recent outcomes from later90-day events. Focused
calendar/rendering tests cover that follow-up. Operating results are recorded below.
Independent boundary review then found status-string stale values, future
released events, a shortened legacy90-day next-release horizon and malformed
URLs. All now have regressions. First operating sample additionally exposed
period-less FRED calendars incorrectly calling already dated CPI/PPI results
unconfirmed: connect only exact indicator/local publication date and an actual
release period; do not infer a period from a date. Known period mismatches still
fail closed. Preserve FOMC's labelled14:00ET convention, group identical option
interpretations, and group Anthropic IPO tracking while retaining source links.
Final related tests:182passed/10.29s, including malformed FOMC date fallback.
Private artifacts belong in ignored cache/event_watch_20261115; do not commit
portfolio exports.

## Limits

Not all issuer/IPO/diplomatic events have connected official sources. Unknown
dates are shown as unconnected or news-only, not guessed. Cboe coverage is a
verified finite mapping, not an all-year PDF calendar parser. Conditional prose
is a transparent event-specific rule set, not a new LLM integration or a change
to investment decisions. Current-session article-story synthesis remains the
one next bounded task after this event-watch work.

## Final operating result

Code7492cde0 pushed. Cloud owner-menu reboot completed for the new collection
modules. Subsequent report-only fixes hot-reloaded successfully: the final
22:12KST report (46f4f243959846dcb053085150a174a2) has111 matching loaded/disk/Git
source fingerprints, restart_required=false, no stale modules, normal generation
and no degraded reasons. Downloaded Markdown hash equals the timing diagnostic.
Do not infer a reboot requirement from earlier deployment behavior.

The operating calendar shows November17 22:30KST retail; NVIDIA November17 US
after-close results with November18 07:00KST call; APEC November18–19; distinct
VIX last trade/expiry and standard options expiry; later BOK/FOMC/CPI/employment
dates. FOMC standard time remains explicitly unconfirmed for exceptions. CPI/PPI
recent values now appear as matching official results, not unknown results or
current consensus. Duplicate option interpretations and Anthropic IPO tracking
are grouped. IPO news does not supply an assumed listing date. AI adoption
checks include paid customers, usage/revenue and cost/margin alongside cash/capex.

| Exclusive stage | Seconds |
| --- | ---: |
| Prices | 9.620 |
| Macro / official evidence | 16.258 |
| Calculations | 1.445 |
| News | 0.424 |
| Article bodies | 0.173 |
| Persistence | 8.972 |
| Assembly | 17.822 |
| Total report generation | 54.714 |

Script entry-to-report78.942s; full Today104.4s. Prior baseline report68.846s;
first new-feature operating sample74.9s (UI record,6bb85da6...), final54.714s.
Cache/network state differs: final calendar component reused cache in0.001s.
This validates operation, not a causal performance improvement. The first
diagnostic download was interrupted when new code cleared the old report;
do not invent its per-stage breakdown. Final report/timing download succeeded.

Before/after final generation:95rows,23score/decision/gate columns identical.
Across deployment:94common rows identical, with one input added/removed by the
live candidate scope. Fixed-input decision gate1369passed; no baseline/golden
regeneration. Private exports, verification.json and operating_calendar.png
are under ignored cache/event_watch_20261115. No account data committed.
