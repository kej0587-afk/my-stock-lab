# Market report reading path and earnings visibility

Base: company commit `746b92fb`, 2026-11-15 KST.

## Preservation

Fetched and fast-forwarded 28 company commits only after preserving seven local
interrupted Customs-work files. Copies/patch/manifest are in ignored
`cache/resume_20261115_pre_sync/`; Git stash is named
`codex: preserve interrupted Customs reuse work before 20261115 company sync`.
The stash is NOT applied: company changes overlap economic collection files.
No reset, force push, credentials or private account exports in this commit.

## Changes

- Existing collected report now has one main path: macro, indices, Korea, US,
  portfolio/replacement review, sector rotation, upcoming calendar. Full original
  dated evidence and diagnostics are retained in one closed appendix.
- Market-specific sourced narratives reuse the existing same-session summary.
  News already explained in the summary is not repeated in the brief table.
  Current/closed, provisional, missing and partial-coverage labels remain local
  to relevant numbers; generic methodology moves behind the reading path.
- Recent economic rows reuse the same freshness/selection checks and exact
  formatted values. Old releases remain in the appendix. No new collection.
- Earnings follow-up publication date no longer disappears behind an older
  official release date. Original release date/period stay intact; preview news,
  future articles and unlinked URLs cannot renew a result.
- Cash-flow/CAPEX facts no longer suppress company guidance. Compact market
  catalyst tables show up to four distinct issuers with facts, conditional
  economic meaning and concrete next checks. Fresh catalysts precede older
  holdings results; source/actual/forecast distinctions remain explicit.
- A Constellation Energy company-name match no longer counts as an oil-sector
  article. Explicit oil/WTI/sector evidence elsewhere in the title still matches.
- The Philadelphia semiconductor index remains in the index board; the SOXX
  sector row is not duplicated by another SOX row in the main sector table.

This is presentation/evidence-selection work. No investment thresholds, score,
gate, allocation, portfolio records, TTL, provider request or retry changes.
Replacement candidates retain their existing gate and release conditions.
No claims from the user's example report were embedded as live data.

## Verification

- Baseline production login, Today calculation, report generation and downloads
  completed. Report `471a62f3dd284613ba6ca29d685586a9`: 31.469s normal generation.
  Exclusive wall stages: macro/official12.837s, prices6.846s, calculations1.125s,
  news2.000s, article bodies0.050s (cache reuse), persistence2.158s, assembly6.452s.
  This is a mixed-cache observation, not a cold-cache benchmark.
- Stable decision gate: 1,369 passed, 144.032s (`decision_k6vf5mu8`). Earlier run
  also passed assertions but was marked blocked because files changed mid-run;
  that earlier run is not the final gate evidence.
- Legacy detailed report digests retain all 12 fixed session/holdings cases;
  no golden files regenerated. Main-path tests cover ordering, exact units and
  dates, gate/partial-account preservation, news date guards, title-only labels,
  recent-release filtering, and independent market/account narratives.
- Focused final coverage: 278 passed /13.99s; one known historical whole-app AST
  test explicitly deselected (see below). Final report gate207 passed/1 identical
  pre-existing failure,43.045s (`report_rezdg8_a`). Changed full-report tests keep
  the original detailed headings/numeric checks and add main-path independence;
  missing-input wording matches the company's Nov13 fix.
- Baseline report gate already failed the historical whole-app AST assertion
  in `test_theme_selection`; 207 other tests passed. Two extra historical tests
  also predate company changes: `test_report_editorial_nov08` expects a different
  legacy section order; report-generation timing's whole-app AST test compares
  all functions with `e56b95e0`. Those source areas/app.py were unchanged here.
  Do not regenerate their historical baselines merely to obtain green output.
- Private baseline report/ZIP/diagnostic and labeled offline sample are in
  ignored `cache/report_reading_20261115/`.

## Deployment and remaining limit

Code validation complete; commit/push authorized. Existing saved reports must be
regenerated to use this layout. `report_reading` participates in the loaded/disk
code check. Post-change production validation is NOT complete: user confirmed
management login, but the IAB management tab still showed GitHub sign-in. While
selecting the user's existing Edge management window, Computer Use stopped this
turn because it could not establish the Windows browser URL reliably. No further
browser operation, reboot or post-change screenshot was attempted. Production
baseline generation above was verified before this interruption. Do not claim
post-change timings or live score parity from it.

Collector coverage remains bounded. An expired static IR announcement can still
exclude its issuer from result collection; display improvements do not repair
that missing source. Do not extend expiry dates or claim whole-market coverage.
First resume the authorized production reboot and generated-report verification.
Only after that, result retrieval blocked by expired calendar notices remains a
separate documented improvement candidate.
