# MSFT official business evidence, 2026-11-08 KST

## Bounded scope

Base `9390e4ce`, clean main and upstream checked. User asked to continue the
handoff's single next task: distinguish official MSFT segment/cloud results and
investment guidance, linked to the eight-quarter SEC review. No score, trade
policy, DB, existing provider, report generation or LLM changes.

The new MSFT precision expander performs one explicit query: official IR homepage,
latest linked earnings release, then its linked conference call (at most3 pages).
Fiscal-year/quarter paths are discovered rather than incremented or guessed.
Issuer HTTPS paths, redirects, publication date, actual fiscal quarter end,
transcript date/period, prepared-remarks boundary and guidance currency are checked.
No Q&A analyst estimate is promoted to company guidance. Failure is visible;
old transcripts/manual values are never substituted. Rerenders use session results.

The evidence separates company-wide revenue, current reported segments, the
overlapping Microsoft Cloud indicator and Azure growth. The current release
recasts segments to Agents and Infra / Devices and Consumer; previous Intelligent
Cloud definitions are not spliced into those series. Cloud/segment/product
indicators are not added together or labelled AI-only revenue.

Company CAPEX includes lease principal under its stated convention; cash PP&E,
finance leases, OCF and company-defined FCF remain separate. The next-quarter
CAPEX statement retains its strict lower-bound operator and forecast period;
it is neither an actual cash payment nor analyst consensus. Unknown attached
conditions or currency leave guidance unverified. Interpretation and next checks
are labelled, source-linked, and make no share-price causality/valuation claim.

An existing owner/ticker-scoped SEC review snapshot is reused without new SEC
requests. Comparison requires MSFT CIK, USD, exact start/end and single-quarter
scope. Company-wide revenue, cash PP&E, OCF and FCF are checked within the source's
rounding precision; company CAPEX is excluded from cash PP&E comparison. Matching
FCF numbers do not establish identical definitions. Original source hashes and
short numerical evidence fragments are included in a JSON download.

## Verification

- New parser/source/UI plus existing quarter-review tests:54 pass (7.83s).
  Wrong/future periods, lookalike hosts, redirects, conflicts, company-vs-cloud
  revenue, reported-vs-constant-currency growth, Q&A isolation, forecast conditions,
  rounding, scope, session identity, failure clearing and unchanged app function
  AST are covered. Review found/fixed a provenance bug that had associated cloud
  growth with the preceding revenue amount; source excerpt now cites its own rate.
- Stable decision regression gate:1334 pass,101.466s, zero failures/errors/skips
  and no source files changed during the run (`decision_2pqgvn_j`). No golden
  snapshots were regenerated.
- Actual official3-page query succeeded in1.953s locally: FY2027Q1 ended2026-09-30,
  published2026-10-28,13 verified metrics, no missing required metrics. This is
  query timing, not an app-render/Today benchmark. Current raw values and guidance
  are extracted at runtime, not hardcoded in a manual data profile.
- Four same-period comparisons against the existing SEC result fall inside the
  release/call rounding ranges. Private raw HTML/results remain ignored in cache.
- Production UI/download/decision acceptance will be recorded after deployment.

## Official sources and limits

- [Microsoft IR discovery](https://www.microsoft.com/en-us/investor/default)
- [FY2027Q1 release](https://www.microsoft.com/en-us/investor/earnings/fy-2027-q1/press-release-webcast)
- [FY2027Q1 official call](https://www.microsoft.com/en-us/investor/events/fy-2027/earnings-fy-2027-q1)

Coverage is one issuer, recognized source wording and prepared remarks. Changed
wording or missing sections are withheld; this is not an all-issuer semantic
parser. Guidance remains the company's dated expectation. No consensus provider,
segment historical time series, debt-maturity model, DCF or LLM integration has
been added. The market report does not yet consume this packet. Prior editorial
report production acceptance remains deferred and explicitly unresolved.
