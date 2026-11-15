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

Main-path materiality/session labeling changes are under independent review.
Production regeneration, representative coverage, timing and unchanged-decision
comparison will be recorded here after the deployed modules are verified.

Additional representative histories may add genuine cache misses. Do not claim
a speedup from a warm-cache sample or change cache lifetimes to hide that cost.
