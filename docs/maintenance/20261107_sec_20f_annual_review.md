# NBIS official 20-F annual review evidence

Date: 2026-11-07 KST. Base: `febb067e`.

## Source access

After the user configured the local root `sec_user_agent`, one request to the
[official SEC companyfacts endpoint](https://data.sec.gov/api/xbrl/companyfacts/CIK0001513845.json)
returned HTTP 200, application/json, 1,568,737 bytes at
2026-11-07T11:45:48.522578+00:00. This verifies local access on this request, not
Cloud configuration or the cause of the earlier HTTP 403 from a different URL.
No identity rotation, credentials in logs, retries or DB writes were used.

Raw SHA-256: `7e21951ecf0fed0fb2a26b5e2464c7b15d69bcdd1928d8cda52a875a29ca04f7`.
Full payload and retrieval metadata are ignored under `cache/nbis_*`; the local
secret is ignored. The committed fixture contains only 83 unchanged public USD
facts for selected concepts and 2023/2024/2025 period ends, with source provenance.
It is explicitly a subset, not the complete SEC response or a synthetic fixture.

## Bounded implementation

`stock_lab_core/sec_annual_review.py` is a pure, offline, review-only annual reader.
It accepts US-GAAP 20-F/20-F/A monetary facts, requiring an explicit matching CIK,
currency and as-of date. Exact period dates determine identity, not filing fy/fp.
Annual duration windows follow the existing period parser (330–385 inclusive days).
Ambiguous periods/conflicting facts remain missing; failures never become zero.
52/53-week years are supported. IFRS, 6-K and quarterly inference are not included.

The reader reuses existing fact-selection/provenance helpers without changing
them. Preferred concept order is retained, then latest filing per exact period.
A later exhibit-only amendment cannot remove earlier valid financial facts.
Actual amended values retain their own accession/form; mixed accessions are flagged.
All records retain `business_scope_unverified`, and the result sets
`review_only=True`, `eligible_for_scoring=False`, `latest_release_verified=False`.

Continuing/discontinued cash flow and earnings are separate evidence fields.
For example, 2024 total operating cash flow is USD245.6m, while continuing operations
are USD-269.9m. Treating the total as current-business cash generation would be
misleading. See the [official annual filing, cash-flow table](https://www.sec.gov/Archives/edgar/data/1513845/000110465926052948/nbis-20251231x20f.htm).
Cross-year business scope is not certified; no growth ratios or grades are inferred.

## Verification

- Existing SEC/financial-review tests before changes: 57 passed (14.36s).
- New annual reader plus existing tests: 88 passed (13.66s), with network disabled
  in annual-reader tests. Covers actual public values/provenance, immutability,
  currency, cutoff, amendments, missing/conflicting/malformed/oversized facts,
  period ambiguity, annual duration and unsupported forms/taxonomies.
- Every fixture row was compared against the retrieved original; all83 match.
  Raw hash matches fixture provenance. Full payload yields15 annual periods;
  its latest3 equal the fixture's3 exactly.
- Existing 10-K/10-Q parser still returns no20-F records before/after the new
  review reader, and `app.py` / existing SEC parser are unchanged from the base.
- Decision regression gate:1,327 passed, zero failures/errors/skips/source changes,
  101.773s; ignored evidence `cache/refactor_checks/decision_ir07t9cm`.

## Deployment and remaining limits

No app import/provider routing/UI/storage was added. Publishing this module does
not resolve the displayed NBIS failure automatically and needs no app reboot.
Existing scores, saved decisions and thresholds are unchanged. This establishes
annual evidence only, not latest2026 interim earnings or real-time data freshness.
Cloud source access and a future read-only UI integration need separate validation.
The four restored sector-RS connections still need their previously planned
production verification; local benchmark evidence remains valid.
