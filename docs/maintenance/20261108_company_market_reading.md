# Selected company: market context and financial evidence

2026-11-08 KST; clean main base `9f4451ed`, equal to origin before work.

## Scope

The individual-company view now joins the existing account-scoped report
snapshot to validated financial readings. It shows dated market/sector closes,
sector minus market daily return in percentage points, conditional interpretation,
actual financial evidence and next checks. The existing static sector map is a
proxy, not proof of segment revenue or causal exposure. No additional prices,
news or metadata requests run on selection. SEC/DART remains explicit on-demand.

The bridge reuses `select_market_review` (account/input scope; 30-minute freshness),
and requires the latest completed session from the existing local exchange
calendar. A newly fetched old history is not current evidence. Session mismatch,
calendar failure, stale quote flags and missing data withhold current conclusions.
Related news reuses the report's sector/session filters, has publication-time
guards, and remains an article claim rather than a confirmed price cause.

The generic financial reader's provenance/period/definition checks remain intact.
Its facts and next checks are wrapped into one narrative rather than duplicated.
Alphabet/Amazon source-recovered cash panels remain distinct from raw automatic
fields. KR has market context plus its existing DART evidence; no invented KR
eight-quarter cash analysis. Download adds `market_review`; original packet is
unchanged. Scores, thresholds, verdicts, account data, caches and TTLs unchanged.

## Verification

- Pre-edit decision gate: 1,367 passed, 129.756s.
- Initial focused company/portfolio tests: 112 passed, 16.49s.
- Report gate: 207 passed, one existing whole-app AST failure in
  `test_theme_selection`. Reproduced on base HEAD: two DART helper functions
  (`inspect_financial_inputs`, `pick_dart_operating_cash_flow`) postdate its
  immutable reference. Not removed or regenerated.
- The previous MTF gate initially detected the intended company UI change.
  A strict AST adapter restores only the new display arguments/import and is
  independently compared against immutable `9f4451ed`; no score baseline changed.
- Independent review found fresh collection could carry an old session; fixed
  with `session_reference` and regression cases for old dates/calendar failure.
- Final focused tests: 147 passed, 57.74s. Final decision gate: 1,367 passed,
  139.702s; stable sources and no golden regeneration. Reviewer verified the
  freshness fix with 14 network-blocked focused cases; no remaining finding.
- Cloud verification: pending below.

## Operational acceptance

Before export preserved privately as `cache/company_market_before.zip`.
Deployment and authenticated selected-company checks pending.

## Limits / next scope

This is evidence-based conditional prose, not free-form LLM analysis or automatic
causal proof. Quarter facts are not today’s earnings or business-unit numbers.
Unmapped sectors and unsupported filings are explicit. Refresh market-wide report
if its snapshot is absent, scoped differently or older than 30 minutes.

Next: general same-period year-over-year earnings/cash comparison for supported
company packets, with matching definitions and provenance; no dated issuer-only
exception or investment score changes.
