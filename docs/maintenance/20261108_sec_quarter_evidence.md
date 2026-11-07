# Eight-quarter financial evidence, 2026-11-08 KST

## Scope and design

User explicitly approved the first financial-evidence phase of improving market
commentary, superseding the previous handoff's production report acceptance task.
Base: `68d617a4`, clean main/upstream at start. Existing score/decision functions,
providers, thresholds, database and automatic refresh paths are unchanged.

The new precision panel is under financial score calculation evidence, for US
individual stocks. It loads only on explicit request, up to four selected companies;
suggested comparison companies are MSFT, AMZN, GOOGL, META, NVDA and MU. Merely
opening the panel, switching tabs or rerendering does not request SEC data.
An owner/ticker/selection-specific session result is retained; failed refreshes
remove old evidence instead of presenting it as a new successful query.

`sec_quarter_review.py` wraps the existing period parser, preserving its scoring
consumers. It validates CIK identity, USD, filing cutoff, supported 10-K/10-Q forms,
accessions, actual economic periods and provenance. Eight observed quarters are
selected only after comparisons use the full available history. Missing quarters
and missing values stay explicit; no calendar-quarter or zero imputation.

Revenue, operating/net income, OCF, cash investment and cash are available. Derived
FCF is OCF minus cash investment, with compatible period/accession signatures.
Cash investment scope is explicit: PP&E alone, or productive assets including
software/intangibles. Restricted cash, total liabilities, leases and acquisition
cash flows are not substituted. The resulting FCF is not company-adjusted FCF.

Later-revised YTD is not subtracted from an earlier annual/current cumulative
filing. Older direct quarters contradicted by newer cumulative facts are withheld;
within the same filing, the disclosed direct quarter wins over cumulative
subtraction (rounding and revisions can cause differences). Cross-filing
differences remain flagged for review, with growth interpretation withheld.
Same-filing derived values are labelled cumulative subtraction, not direct facts.

YoY matches actual dates/durations and fiscal-quarter identity, requiring the same
concept and a positive prior denominator. It does not use four list rows earlier.
Business scope remains unverified; this is evidence for review, not a comparable
valuation ranking. Foreign 20-F/IFRS quarterly estimates are not fabricated.

Tables separate income and cash flow, with readable facts and next-check questions
above them. The download keeps original unrounded USD, actual start/end dates,
filing dates, concepts, operands, issues and source URLs. No LLM, consensus,
segment revenue, debt-maturity model or DCF is claimed implemented in this phase.

## Verification

- Focused SEC parser/annual/quarter/UI contracts: **105 passed** (8.01s final run).
  Tests cover cumulative Q4, gaps, currency, identity, cutoff, mixed sources,
  revisions, direct-vs-derived values, source labels, account/selection isolation,
  refresh failure, no implicit network and unchanged app function AST.
- Decision regression: initial run1334 passed but the gate correctly refused
  acceptance because new files were edited during the run. Stable rerun:
  **1334 passed**,104.908s, zero failures/errors/skips/changed files
  (`cache/refactor_checks/decision_7jsh6yyl`). No baseline regeneration.
- Actual SEC ticker identity + companyfacts requests succeeded for six companies.
  All six produce eight contiguous observed quarters; all six latest quarters have
  the six requested raw fields. FCF coverage44/48: MSFT8, AMZN7, GOOGL7, META7,
  NVDA7, MU8. Four historical values remain withheld for incompatible revisions.
  Latest ends: MSFT/AMZN/GOOGL/META2026-09-30, NVDA2026-07-26, MU2026-09-03.
  Different ends are shown, not treated as the same calendar reporting period.
  This does not verify every latest earnings release or custom XBRL extension.
- Real-source panel preview is isolated at127.0.0.1:8535; raw responses and preview
  artifacts remain ignored under `cache/quarter_*`. No personal data is published.
- Production acceptance/deployment will be recorded after verification.

## Sources and remaining work

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  provide companyfacts; actual dates and source scope must still be reconciled.
- [SEC non-GAAP guidance](https://www.sec.gov/rules-regulations/staff-guidance/corporation-finance-interpretations/non-gaap-financial-measures)
  explains why FCF definitions and adjustments need clear identification.

The next bounded research step is one company's official segment revenue and
investment guidance linked to this historical evidence, then business relations
and source-bound narration. The report itself does not yet consume this panel.
Previous report production acceptance remains a separate unresolved limitation.
