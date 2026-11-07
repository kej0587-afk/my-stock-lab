# DART financial-evidence bridge — integration design

Date: 2026-11-07 KST. Base: `8cda6db8`. **Design only: no collector, table,
upload UI, schedule or runtime fallback has been deployed by this task.**

## Decision and evidence

Use **local DART collection → JSON file → authenticated app preview/import →
private Supabase evidence table → read-only precision review**.
The first version is a manual bridge, not automatic or real-time collection.

Cloud corporate-code requests timed out before an HTTP response; local official
requests succeeded. The corporate-ID snapshot resolves identity temporarily, but
Cloud statement requests also fail. This is not evidence of an IP ban or bad key.
See [measured connection record](20261107_dart_cloud_connection.md).

| Route | Credentials and operation | Decision |
| --- | --- | --- |
| Local file + existing authenticated app | DART key stays local; app already has storage credentials and verified owner | Smallest first integration |
| Local script directly writes Supabase | Adds privileged storage access and owner selection to the collector | Defer; unnecessary for file collection |
| New server / scheduled CI relay | New execution environment, credential placement and monitoring | Defer |
| Commit statement snapshots to Git | Publishes selected-company coverage; couples refresh to deployment | Reject for personal evidence |

Existing `report_history` is keyed by owner and market sessions and validates
report rows/dates. Account ledgers validate valuations/flows and revisions.
Neither is a generic evidence store. `fin_scores.notes_json` belongs to saved
score provenance; refreshing it would change the meaning of existing grades.
Do not reuse these fields. This conclusion is based on repository contracts,
not an inspection of the live database schema.

## Boundaries in the current code

| Existing entry point | Integration contract |
| --- | --- |
| `app.py:get_supabase_client_cached`, `require_login` | Existing server storage client and verified owner; never owner supplied by the uploaded file |
| `app.py:inspect_financial_inputs` | Separate imported-evidence review beside explicit live refresh; no forced slow network retry to view a file |
| `app.py:extract_dart_metrics` | Reuse account selection and cumulative amount rules when displaying imported statements |
| `app.py:make_dart_single_quarter_record` | Reuse only with adjacent cumulative reports from the same year, currency and CFS/OFS basis |
| `stock_lab_core/financial_review.py:build_financial_review` | Compare stored score period with evidence period; no score calculation or persistence |
| `load_fin_score_meta_fast`, `get_final_fin_score`, Today Check | No imported-data dependency in this version |

The standalone collector must not import `app.py` or initialize Streamlit/auth.
It collects raw account rows, not scores or derived quarters. A later UI adapter
can receive existing parser functions as dependencies rather than duplicating
their logic or doing a broad extraction. Missing adjacent reports remain missing;
do not label a cumulative half-year/nine-month amount as a single quarter.

## Package contract (version 1)

One ticker per file, saved under ignored local `cache/financial_evidence/`.

| Field | Meaning / validation |
| --- | --- |
| `schema_version`, `collector_version` | Explicit format and producing code version; reject unsupported formats |
| `source`, `endpoint` | `dart`; fixed official statement endpoint without query parameters |
| `ticker`, `corp_code` | Normalized Korean ticker and 8-digit corporate ID; validate mapping independently of uploaded claims |
| `collected_at` | Timezone-aware UTC collection completion, not publication or import time |
| `requested_reports` | Explicit year/report-code scope; no silent omission of failed requests |
| `reports` | Successful raw rows with year, report code, CFS/OFS, receipt IDs and per-response retrieval time |
| `attempts` | Allowlisted status per request: success / no data / failed; HTTP/API status and duration, never request URL or exception text containing a key |

Keep original amount strings and cumulative fields, currency, statement/account
IDs and names, ordering and reporting identity. Final allowlist must cover every
column consumed by the existing parser and provenance; test with fixtures before
freezing it. Do not include credentials, account balances, owner email, saved
scores, analyst estimates or private holdings. No zero-fill for missing amounts.

Use official `fnlttSinglAcntAll.json`: business report `11011`, Q1 `11013`,
half-year `11012`, Q3 `11014`; CFS and OFS are distinct bases. Preserve `rcept_no`
for the official filing viewer. These fields are documented in the
[DART API guide](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020).

Start with an explicitly requested, bounded year/report scope. Do not crawl all
companies or replicate the UI's entire historical search by default. Fetch
sequentially; OFS fallback only for CFS no-data, not for transport/auth failure.
Stop on access/key/quota errors. Use finite connect/read timeouts and record
actual requests separately from report count. Never extend snapshot dates without
an official refresh. A failed collection must not replace a successful file.

Proposed validation caps: 8 MiB/file, 25 reports, 25,000 total rows and bounded
individual strings. These are defensive design limits, not measured performance
claims; check against real one-company packages before choosing final constants.
Reject oversized input before JSON parsing, duplicate JSON keys, nonfinite numbers,
unknown credential-bearing fields, conflicting report identities and duplicate
report keys. Do not fetch URLs supplied in a file. Build filing links from validated
14-digit receipt IDs. Use ordinary JSON only, never executable serialization.

Compute canonical SHA-256 on the server after validation; exclude any client hash.
The checksum proves content identity, **not issuer authenticity**. With the Cloud
route unavailable, imported content cannot be independently refetched there.
Display `로컬 수집·업로드 / 원문 서명 미검증`; source labels alone are not proof.
Reject ticker/corporate-ID disagreement with the usable official mapping. If that
mapping has expired/unavailable, allow inspection only and defer trusted import.

## Storage and isolation (proposed, not executed)

Add a dedicated `financial_evidence_bundles` table in the existing shared project:

| Column | Proposed type / rule |
| --- | --- |
| `owner_email` | Normalized verified server identity, nonempty |
| `ticker`, `corp_code` | Validated identifiers matching payload |
| `bundle_sha256` | Server-computed content digest |
| `schema_version`, `source` | 1 and `dart`, matching payload |
| `collected_at` | Timezone-aware source collection time |
| `imported_at` | Database insertion time; never used to refresh evidence age |
| `payload` | Validated JSON object; no credentials or grades |

Primary key `(owner_email, ticker, bundle_sha256)`; lookup index
`(owner_email, ticker, collected_at DESC)`. Immutable inserts: repeating the same
file is idempotent; a changed filing produces a new bundle. Do not replace the last
good bundle with empty/error data. No retention deletion in the first version.

Use the existing server-only access pattern, RLS and revoked direct client
permissions; give the server only SELECT/INSERT for this table. The app's Google
login is not a Supabase user JWT. Service credentials bypass RLS, so every read
must filter verified owner + ticker, and returned identity must match. Every
insert obtains owner exclusively from the server. Never cache personal evidence
under ticker alone. See the existing [history DDL](../20261020_report_history.sql)
and [Supabase RLS documentation](https://supabase.com/docs/guides/database/postgres/row-level-security).

DDL is a later deliverable: one new table affects the shared project, without
altering existing tables or scores. Do not claim it exists or run a migration as
part of this design task. No secret is copied to a new service.

## Freshness, selection and UI

Proposed evidence-display policy, independent of investment thresholds:

| Age since original collection | Display / default selection |
| --- | --- |
| Up to 24 hours | Recent collection; not a claim that the latest earnings announcement is included |
| Over 24 hours through 7 days | Stale read-only evidence, age shown explicitly |
| Over 7 days | Archive inspection only; excluded from default fallback |
| More than 5 minutes in the future / invalid clock | Reject |

Keep fiscal period, receipt ID, collection time and import time separate. Use
timezone-aware clocks; render KST to the user. Importing an old file does not
renew it. Corporate-ID snapshot freshness is a separate check. A recent request
can still return only older regular filings; earnings releases may precede them.

Select only a bundle with matching requested scope and complete request accounting.
Explicit provider no-data is distinguishable from failed/missing requests. Partial
collections remain inspectable with missing coverage, but cannot silently replace
a complete bundle. Never combine different owners, currencies or CFS/OFS bases.
On storage failure show the cause; retain existing saved score and evidence.

Preview table: company, source, fiscal periods, receipt IDs, collection age,
missing reports/metrics and existing saved-score period. Persist only after an
explicit import action. Show saved score unchanged beside read-only evidence.
This path supplies no consensus and makes no latest-results guarantee.

## Verification and implementation order

This task verifies design against existing functions/storage contracts and official
documentation. Only Markdown changes; no runtime tests, production refresh,
database changes or speedup claims are appropriate for this design-only commit.

**Next bounded task:** implement the local raw-evidence collector and strict
version-1 validator with synthetic fixtures/offline tests. Produce a local dry-run
package when the existing local key is available, without displaying keys or
committing the package. No Cloud/UI/storage changes in that task.

Later, separately: storage adapter and migration with owner-isolation/idempotency
tests; then preview/import/read-only review with one-company production roundtrip.
Acceptance must include no writes to `fin_scores`, exact saved-grade/decision
parity, stale/future/partial rejection, CFS/OFS and currency separation, no key
leakage, corrected filing handling and unchanged original files on failure.
SEC foreign-issuer support, scheduling and score refresh remain separate work.
