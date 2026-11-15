# Report quality follow-up — 2026-11-15

Base: 5b7d11cd (period-exact verified PPI publication metadata). User authorized
continuing the remaining report defects, commits/push and operating verification.
Other-computer changes and the interrupted Customs stash remain preserved.

## Representative prices

The operating report fetched portfolio ETFs and sectors, but not most companies
in the representative-stock table. The table therefore omitted US representatives;
an unclassified TDF was the only Korean company observation. This was a collection
scope defect, not evidence of absent market activity.

`report_company_prices` reuses the existing issuer catalog and cached one-year
histories. Only missing frames go through the existing batched US/bounded Korean
loader (four workers). It excludes fund/TDF aliases in report scope, validates
both latest and previous session against the market benchmark, and applies the
existing split/large-change guard. Future, unmatched and unavailable observations
remain missing. It does not request company info, analyst targets or live quotes.

The application explicitly opts into `company_prices`. This is separate from
the original `prices`, portfolio observations, rotation calculations and all
decision inputs. Supplied offline frames never trigger missing-data requests.
The module is registered in the loaded/disk fingerprint check. No TTL, score,
investment threshold, grade, gate or raw economic value was changed.

Focused collector tests: 10 passed (2.29s); reuse, provider failure, fund exclusion,
future rows, exact session pairs, stale benchmark, immutable input and unverified
large-move checks covered. Related report tests: 93 passed; one known whole-app AST
assertion against an older commit remains incompatible with later reviewed app
changes. It is not evidence that the decision suite failed; report separately.

## News and operating verification

Main-path review now excludes explicit promotional/history formats and unsupported
generic valuation filler. It keeps distinct material events and all original
appendix evidence without imposing a per-sector count cap. Central-bank speakers
precede issuer aliases; known Korean subjects no longer sit in the US-close table.
Prior-close, intraday and closing stories have separate labels/order. A news
collection window's end is never treated as the exchange's closing time; supplied
special-session close times take precedence. Shared representative price sources
are printed once below the table, with connected/expected company counts.

Independent related coverage: 370 tests passed. Integrated changed-area run:
103 passed/3.61s. Decision gate initially: 1,367 passed, two old-app AST comparisons
failed solely on the new report opt-in keyword. The exact True opt-in is now
normalized by the existing contract helper; both failing checks passed on rerun
(13 tests including collector/strict normalization checks, 15.33s). Original
Git baselines and all golden decision results are unchanged. The separate
pre-existing report whole-app AST mismatch remains recorded, not hidden.

Final selected report/article tests: 382 passed/7.32s. Final full decision gate:
1,369 passed, no failures/errors/skips, gate elapsed146.526s.
Production regeneration and unchanged-decision comparison completed below.

The prior body collector still spent its four slots on some items now excluded
from the main reading path. Applied the same materiality filter before body
selection, retained strategic scenario coverage, expanded the bounded budget to
eight public articles, and keyed diversity by market AND theme rather than only
market. This permits policy, chips, credit and other US catalysts to coexist.
Four workers, provider allowlist, byte/time/date guards and success/failure TTLs
are unchanged. Original evidence is retained; failed bodies never become verified
facts. Article/materiality regression: 100 passed/4.09s. Extra real requests must
be reported as a coverage cost, not described as an optimization.

Additional representative histories may add genuine cache misses. Do not claim
a speedup from a warm-cache sample or change cache lifetimes to hide that cost.

## Verified production result

Rebooted through the authenticated Cloud owner menu. Final application commit
90629496; report generated Nov15 21:17KST, run292ccf9f7ebb45d2a271a1fb4a14b1f5.
All109 loaded module hashes equal committed Git blobs and disk hashes;
restart_required=false, no stale modules, normal generation, no degraded reasons.
Downloaded Markdown SHA256 matches its diagnostic. The before/after ZIPs contain
the same95 tickers and identical23 score/decision/gate columns, both across this
deployment and before/after report generation. Full Today126.3s (prior113.5s).

| Exclusive report stage (seconds) | Prior report | New report |
| --- | ---: | ---: |
| Prices | 15.237 | 18.506 |
| Macro / official evidence | 20.128 | 23.456 |
| Calculations | 1.135 | 0.812 |
| News | 2.065 | 2.018 |
| Article bodies | 1.188 | 1.805 |
| Persistence | 9.686 | 8.121 |
| Assembly | 17.513 | 14.128 |
| Total report generation | 66.952 | 68.846 |

Company-price collection was4.559s inside the prices stage, not additional to the
total. Script entry-to-saved-report88.796s; browser painting is separate. Same
95-input/settings, including11categories/per-category2, but caches/network are
not controlled or emptied: this is an operating observation, not a speedup test.

- PPI MoM/YoY now visible in the main recent-release table with verified
  Nov13 08:30EST /22:30KST publication. Existing values/consensus stay unchanged;
  MoM consensus is still explicitly missing. Snapshot expiry remains Dec15.
- Company closes: KR59/59, US75/75 connected with matching benchmark pairs.
  TDF remains in its legitimate holding row but is excluded from company breadth.
- Public bodies:8attempted,7with verified facts,1read with insufficient supported
  interpretation. No bypass of publisher restrictions. Original source evidence
  and rejected/promotional items remain in the collapsed appendix.
- Main title-only mentions112->82 (mentions, not unique articles); body mentions
  8->16. Recycling promotion removed from main. Main347->357lines,61578->60422
  Markdown characters including links, despite adding134company observations.
  More coverage is verified; this is not a claim that narrative quality is finished.
- Narrow operating screenshot confirms the75/75 company table and three columns.
  Large sector rows still occupy substantial vertical space.

Private ignored evidence: cache/report_coverage_20261115/production/quality_*,
verification_quality.json. No holdings, account exports or screenshots in Git.

## Remaining defects / limits

The US closing interpretation still mostly repeats a generic PPI implication.
Important AI-credit/datacenter headlines remain title-only; the newly read
datacenter article produced no supported interpretation. Two weekly previews
consume two body slots. Repeated generic caution/check wording remains verbose.
Next work should improve verified-body event synthesis and deduplicate previews,
not inflate certainty or claim every headline explains that day's close.
One overnight S&P futures headline is accurately dated to the previous day but
the fallback label says previous-close observation; futures must remain distinct
from confirmed closes in that synthesis. Full 2Y/European-gas/option-gamma and
night-futures numerical coverage remains unavailable. The old whole-app report
AST assertion is still a separately documented compatibility issue; no claim of
an all-repository suite pass. No live LLM integration was added.
