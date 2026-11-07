# Local DART evidence collector and validator

Date: 2026-11-07 KST. Base `db70567e`; implements only the local phase of the
[bridge design](20261107_dart_evidence_bridge_design.md).

## Delivered scope

- `scripts/collect_dart_evidence.py`: explicit single-company/report collection
  and offline file validation, using the existing local key configuration.
- `stock_lab_core/dart_evidence_collector.py`: sequential official requests;
  CFS -> OFS only after status 013. Transport, HTTP, API and malformed-response
  failures stop collection. No automatic retry, redirected statement request,
  inferred values, score calculation or app import.
- `stock_lab_core/dart_evidence.py`: strict versioned JSON validation, canonical
  SHA-256, report/attempt accounting, corporate identity matching, freshness,
  resource bounds and exclusive file creation.

No existing app/provider/score code was edited. No database schema, account data,
Cloud UI, storage integration, schedule or credentials were changed. The new
modules are not imported by the running app; no reboot is needed for this step.

## Usage (repository root, installed Python)

Collect explicit periods. `DART_API_KEY` from the environment wins; otherwise
`--secrets-file` reads existing `dart_api_key` / `DART_API_KEY` fields. There is
deliberately no CLI argument that contains the key itself.

```powershell
.venv311/Scripts/python.exe -X utf8 scripts/collect_dart_evidence.py collect --ticker 005930.KS --report 2026:11012 --report 2026:11014 --secrets-file .streamlit/secrets.toml
.venv311/Scripts/python.exe -X utf8 scripts/collect_dart_evidence.py validate cache/financial_evidence/FILE.json
```

Collection first resolves identity using a fresh official corporate-code fetch;
it does not extend the bundled identity snapshot's expiry. The user specifies the
KS/KQ listing suffix; the DART stock-code map proves corporate identity, not market
suffix. That suffix must be checked against app listing metadata on later import.

Output defaults to a unique UTC filename under ignored `cache/financial_evidence/`.
An explicit `--output` must remain inside that directory. Existing files are never
overwritten, including by failed or partial runs. Exit code 0 means complete request
accounting with at least one report; 2 means partial or no reports; 1 means invalid
input/identity/package/file error. A partial package at a new path retains successful
reports and records the stopping failure. Unattempted reports remain in scope.
Offline `validate` returns 0 for a structurally valid package, even if partial or
expired; inspect the summary before using it. It never connects to a provider.

## Meaning of validation

`complete` means all requested periods received a terminal success/no-data response,
not that all periods have financial statements. `eligible` additionally requires
some reports, age <=7 days and an independently supplied usable corporate map.
Offline CLI validation supplies no map: `identity_verified=false`, `eligible=false`
is intentional. A valid hash is content identity, not source authentication.
The future app must label this as local uploaded evidence and cannot claim issuer
signature verification or latest-earnings coverage.

Collection and request times are UTC; naive/future timestamps and nonchronological
request times are rejected. <=24h is recent, >24h through7d stale, >7d archive only.
Missing metrics remain absent/null/original strings. Reporting period, CFS/OFS,
currency and receipt ID are kept separate; no cumulative-to-quarter calculation is
performed here. Unknown uploaded fields, mixed report identity/receipts/currency,
duplicate JSON keys and nonfinite JSON numbers are rejected. Raw rows retain the
existing parser's official snake-case amount/account columns.

Limits: 8 MiB/file or statement response, 25 requested reports, 25,000 total rows,
4,096 characters per row value. Requests have connect/read timeouts (8/15s), no
statement redirects, and an elapsed-time check while consuming response chunks.
Diagnostics store only fixed cause/status fields, not request URLs or arbitrary
exception/provider-message text. Credentials reflected in retained row values are
rejected. The CLI suppresses local secret-file parsing details.

## Verification

- Focused bridge + corporate-code + financial review/refresh contracts:
  **129 passed**, 14.15s. Synthetic fixtures cover CFS/OFS, API/HTTP/transport
  failures, partial scope, invalid identities, age, size, duplicate keys, credential
  leakage, immutable output and parser parity. Existing cumulative revenue/OCF
  extraction produces identical results from original versus collected rows.
- The new collector can import without `app`, Streamlit, Supabase or scoring modules.
- Final fixed-source decision gate: **1,327 passed**, 100.825s, no skips/changes
  during the run; evidence `cache/refactor_checks/decision_jz5id7nk`.
  The first run's 1,327 tests
  all passed, but the wrapper correctly rejected it because new source files were
  still being edited. Final verification is run with source files held fixed.
- No golden files or thresholds were changed. This is not a full-suite, live UI,
  performance improvement or investment-results validation.

Local official dry run: Samsung Electronics, requested 2026 half-year and Q3.
Fresh identity lookup succeeded; statements: half-year CFS success, Q3 CFS/OFS
both status013. **1 report / 223 rows / 3 statement requests / 103,798 bytes**;
statement durations total **1.191s**, whole CLI process observed **4.469s**
(includes identity lookup/startup; not a Cloud benchmark).
No claim that the latest earnings release was incorporated: Q3 remains unavailable
on this endpoint at this fetch. Raw input is never fabricated to fill that gap.

Private evidence (not committed):
`cache/financial_evidence/20261107T084616348739Z.json`.
Canonical digest `98b2ed44a94dd5ff7771660949c01ee7e95a15228dde6c000b005432ced84791`.
The package also passes final offline validation; Git ignores its directory.

## Remaining boundary

Cloud DART statement transport is still unavailable. Users cannot yet import these
files into the app. Next bounded task: owner-scoped immutable Supabase evidence
adapter and a prepared (not executed) table migration, with synthetic isolation and
idempotency tests. UI preview/import and production roundtrip follow separately.
Do not route this evidence into saved grades or Today Check during that work.
