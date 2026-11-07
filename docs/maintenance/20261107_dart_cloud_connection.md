# DART Cloud corporate-code recovery — 2026-11-07

Base `ee6a789e`, clean and equal to upstream after fetch. Scope: corporate-code
lookup, preserving stored grades and decisions. No account/credential changes.

## Proven cause

Diagnostic deployment `2f79bc3c` reproduced production failure on explicit
read-only refresh: `stage=request`, `cause=connect_timeout`, elapsed **8.021s**,
HTTP/API status null, zero response bytes. Thus the immediate failure is connection
establishment, before ZIP/XML parsing or a DART application-level error response.
This does not prove an IP ban, bad API key, or a specific Cloud routing cause.
Key validity cannot be established without a response.

Same local official endpoint returned HTTP 200, **3,635,856 bytes / 4,013 mappings
in 2.638s** (another refresh 2.311s). Local configuration/network success is not
evidence that Cloud has identical access. No alternate proxy, TLS bypass,
credential replication, credential printing or new infrastructure was used.

The [official corporate-code guide](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018)
defines the ZIP containing corporate and stock IDs, and distinguishes key/IP/API
errors. Only the fixed source endpoint, not its credential-bearing URL, is saved.

## Changes

- `dart_corporate_codes.py` returns a dictionary-compatible mapping with safe
  diagnostics. Only stage/cause, bounded status codes, allowlisted content type,
  byte/count totals and elapsed time survive. Never retain raw error message,
  response body, exception text, request URL, headers or API key. XML/JSON error
  payloads are distinguished from ZIP failures. Mapping semantics are unchanged.
- `dart_corporate_snapshot.py` permits a dated official public-ID snapshot only
  after a transient transport failure. Successful live maps always win. Missing
  key, explicit HTTP/access/API errors, malformed payloads and empty live maps do
  not silently fall back. Expired (>7 days), future, invalid-source or malformed
  snapshots fail closed. Unknown tickers remain unmapped. Corporate IDs are not
  financial statements or investment signals.
- The bundled snapshot contains all 4,013 listed-code mappings returned by the
  official API, not a private portfolio subset. Public alphanumeric stock codes
  are retained. Metadata is limited to version/source/retrieval time/codes.
- Precision read-only review shows source/as-of/valid-until and an expandable
  safe connection diagnostic. DART connection failure remains visible even when
  corporate-code resolution is recovered from the snapshot. No claim that the
  snapshot supplies current earnings or fixes network connectivity.
- Existing 30-minute usable-map cache and 60-second failure cooldown remain.
  Snapshot expiry is checked at load; a cached usable map can persist until its
  ordinary 30-minute cache expires. No speedup based on TTL changes is claimed.

## Snapshot maintenance

From an environment that can reach official DART, run:

```powershell
.venv311/Scripts/python.exe -X utf8 scripts/refresh_dart_corporate_snapshot.py --secrets-file .streamlit/secrets.toml
```

The script also accepts `DART_API_KEY` from the environment. It never prints the
key or puts it in generated JSON. Review the public-data diff before committing.
No scheduled job was installed. A deployed snapshot does not refresh itself;
after expiry, a fresh official retrieval/deployment is needed if Cloud still
cannot connect. Do not extend the date without a successful official fetch.

## Verification

- Before: financial review/freshness tests **27 passed** (13.34s).
- Diagnostic stage: **37 passed** (13.73s); selected decision gate **1,327 passed**
  (102.113s), `cache/refactor_checks/decision_44uouu21`.
- Final focused coverage: **66 passed** (15.43s), including timeout redaction,
  ZIP/XML/JSON/error distinctions, cache serialization, fallback nonmutation,
  alphanumeric IDs, expiry/future/source rejection, auth/access nonfallback,
  actuals contracts and no financial-score/DB writes during review.
- Final decision gate: **1,327 passed** (101.628s), zero failures/errors/skips,
  `cache/refactor_checks/decision_k9w2y2li`. No thresholds, judgement labels,
  scoring functions or golden files changed.
- Production code `1b612377`: read-only review now resolves corporate identity
  through `official_snapshot` (4,013 mappings) and displays its timestamp/expiry.
  The subsequent statement API fails transport; the review correctly shows
  `DART 통신 실패` instead of corporate-code mapping failure. This is **temporary
  identity-lookup recovery, not restored live financial connectivity**.
- Completed production precision ZIP confirms matching selected/result ticker
  and unchanged saved financial score/source. No stale modules in the monitored
  list or restart requirement; new DART helpers are verified by actual behavior,
  not claimed as present in the legacy monitored-module hash list.
- Snapshot expiry: 2026-11-14 17:07:49 KST, plus any ordinary mapping cache
  lifetime already in flight. No financial-score or account writes performed.

Private evidence stays ignored: `cache/dart_corp_local_diagnostic.json`,
`cache/dart_cloud_connect_timeout.jpg` and `cache/dart_corp_*` test logs.
Production account scores remain untouched. The public ID snapshot alone is
committed; no private account export or secrets are included.
Final private evidence: `cache/dart_cloud_snapshot_recovery.jpg` and Downloads
`precision_review_329180.KS (2).zip`.

## One next task

Design a minimal read-only financial-evidence path using the existing local
environment that can reach DART and existing authenticated storage. Preserve
statement provenance/expiry and separate evidence from saved grades. Do not
provision a new service, copy credentials elsewhere, or auto-write new scores.
The immediate network connection failure is proven; its upstream routing/access
cause cannot be determined from the app response and is not fixed by this patch.
