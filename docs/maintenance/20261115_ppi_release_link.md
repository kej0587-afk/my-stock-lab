# PPI release metadata recovery — 2026-11-15

Base3b8feabf; clean main and origin0/0. The user authorized continuing through
the remaining report defects, with separate bounded fixes and unchanged scores.

Cause: BLS observations contain October PPI values, but the BLS schedule returns
HTTP403. The existing FRED fallback supplies announcement dates without reference
months; assigning those dates to observations by month arithmetic would be a guess.
The existing period-exact verified metadata store covered CPI only.

Verified against the official BLS archive, not the user's example:
https://www.bls.gov/news.release/archives/ppi_11132026.htm
The header identifies October2026 and an embargo/publication time of
November13,2026,08:30 Eastern. Added only that metadata record, verified Nov15,
expiring Dec15 (next scheduled PPI release stated by BLS). Both MoM and YoY rows
link to the same publication. No actual, previous, forecast, period, unit, score
or cache TTL changed. A successful live date always takes precedence.

This is an explicitly labeled verified_snapshot fallback, not a claim that
automatic BLS calendar access has been restored. A local bounded probe observed
403 from BLS schedule, BLS current release and the DOL mirror listing. Do not
add repeated failing requests or infer future announcement dates. Period mismatch,
pre-verification runs and expiry refuse the fallback; stale values remain stale.

Verification:69 focused tests passed in3.19s (new PPI metadata, existing freshness,
release calendar and report reading contracts). Tests preserve actual/previous/
consensus fields and prove the recent-indicator table includes the exact-period
PPI row only after verified linkage, while still excluding stale observations.
Production regeneration is pending the report follow-up deployment; record actual
output and build state before claiming the production acceptance criterion.

Next bounded implementation: connect representative/registered individual-stock
close observations to the existing report-only breadth table; exclude ETF/fund
rows, retain date/source validation and avoid expanding live quote requests.
