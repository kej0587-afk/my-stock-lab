# NBIS financial failure: bounded diagnosis

2026-11-07 KST; baseline `8bdc407e`, clean and equal to upstream after fetch.
Scope: diagnose one US failure and propose a repair. No runtime edits, score
refresh, storage changes, subscription changes or production UI actions.

## Evidence

| Layer | Established finding | Limit |
| --- | --- | --- |
| Saved failure | NBIS FMP annual income request returned HTTP402 subscription/permission restriction; SEC resolved CIK0001513845 then reported fewer than2 annual records. | Saved account evidence, not a new live provider call. Private grades/records are not published. |
| Prior local reproduction | Same-day `financial_live_parsed.json` records NBIS FMP402. | No repeated paid-provider request was needed for this diagnosis. |
| Official filing | 2025 Form20-F contains US-GAAP statements, including2023–2025 operations/cash flows. | Filing existence does not prove every field is present in companyfacts. |
| Parser | Form allowlist rejects20-F; annual anchors separately require10-K. | Both restrictions must be addressed; widening just the list does not recover annuals. |
| Wrapper | Annual `report_code` is hard-coded to10-K. | An accepted20-F must not be relabelled10-K. |

Code locations at baseline: `stock_lab_core/sec_financial_periods.py:25,85,200`;
`app.py:4700,4727`. Current concepts are US-GAAP only, as configured at
`app.py:4539`. NBIS itself uses US-GAAP: an IFRS conversion is not the first repair
for this company. Its filing discusses discontinued operations/reclassification;
multi-year growth comparisons need compatible scopes, not merely matching years.

Sources: [NBIS official2025 Form20-F](https://www.sec.gov/Archives/edgar/data/1513845/000110465926052948/nbis-20251231x20f.htm)
(financial-statement index, auditor opinions, discontinued-operations note);
[SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
(standard taxonomy/entity-wide coverage and unit-specific facts).

## Verification

- Isolated synthetic US-GAAP revenue spans for2023–2025, with the app's actual
  concept preferences:20-F ->0 annual records; temporarily widening the module
  allowlist in memory ->still0; identical facts labelled10-K ->3 annual records.
  Input remained unchanged; original allowlist restored. No runtime file edited.
- This is a form-filter demonstration, **not downloaded NBIS financial facts**.
  Private diagnostic output: `cache/nbis_form_diagnosis.json`.
- Existing `tests/test_sec_financial_periods.py` and `tests/test_financial_review.py`:
  **57 passed in16.47s**. Includes read-only score preservation and period contracts.
- No full decision-gate rerun needed for documentation-only work. No saved score,
  decision threshold/text, golden baseline or account state was changed.

The research tool could read the official filing but could not open
`https://data.sec.gov/api/xbrl/companyfacts/CIK0001513845.json`. This is a tool
access failure, not evidence of a SEC HTTP403 or Cloud outage. The earlier local
audit reported no configured SEC User-Agent; production configuration is unknown.
No contact identity was invented. Exact current JSON concept availability, latest
interim dates and Cloud end-to-end retrieval remain unverified.

## One bounded improvement proposal

Add a separate, review-only US-GAAP20-F annual reader, preserving the existing
10-K/10-Q path and default outputs. First capture an official dated fixture and
check actual mapped tags, USD/other units, annual durations and entity scope.
Preserve20-F/20-F/A provenance and amendments; retain unavailable fields as missing.
Do not route newly recovered facts into stored grades or automatic scoring.

Required acceptance checks: official fixture annual values match the filing;
form/date/currency provenance preserved; amendments and conflicting facts handled;
existing10-K/10-Q fixtures unchanged; no inferred quarter from annual-only data;
missing/comparability flags and score-isolation tests pass. Keep6-K interim parsing,
IFRS support and other issuers outside this step.6-K is not automatically a
quarterly financial statement, and companyfacts excludes custom/entity-segment
concepts, so successful20-F support alone cannot promise complete latest earnings.

Documentation publication needs no app reboot. HANDOFF contains the single next
task; the proposed parser is not implemented in this diagnosis commit.
