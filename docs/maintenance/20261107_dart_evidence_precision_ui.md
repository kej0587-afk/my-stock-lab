# Precision DART file preview/import integration

Date: 2026-11-07 KST. Base `5cadb203`.

## User path

Precision observatory → **재무점수 계산 근거** →
**로컬 DART 근거 · 미리보기/가져오기** (Korean individual stocks only).

1. Upload the local collector's JSON. Preview validates format, size, timestamps
   and the full selected ticker, including KS/KQ. Upload alone never writes to DB.
2. Read collection time/age, saved-score period, per-request coverage and financial
   amounts. Reports retain cumulative/annual labels; missing values stay missing.
3. Click **기업·상장시장 확인**. The existing DART corporate-code loader resolves
   identity; Naver's basic metadata independently checks listing suffix. Failed or
   expired identity checks leave preview available but disable persistence.
4. Click **개인 근거로 가져오기 (점수 유지)** to insert an eligible file into the
   authenticated owner's private evidence table. Identical imports report already
   saved; no merge or score update occurs.
5. Select the exact report-year scope and click **같은 범위의 저장 근거 조회**.
   Upload supplies scope defaults; without a file the scope can be selected manually.

If the dedicated table is missing, the panel shows setup instructions and a
download of [the prepared SQL](../20261107_dart_evidence.sql). It does not run SQL.
The SQL adds one private table in the shared project and leaves existing tables
unchanged. Its execution has not been confirmed; live storage verification remains
outstanding. Local tests simulate both successful storage and missing schema.

## Changes and boundaries

- `app.py`: three imports and one guarded renderer call, under the existing
  non-ETF Korean-stock financial-evidence area. No existing function body changes.
- `dart_evidence_preview.py`: selected-ticker preview, coverage tables, existing
  metric parser reuse and explicit corporate/listing identity verification.
- `dart_evidence_view.py`: upload, explicit buttons and owner/ticker-scoped state.
- Public demo supports preview only; it cannot verify or write personal evidence.

Identity is checked for at most10minutes and never beyond the corporate snapshot's
expiry. Only the selected corporate ID is retained in this panel's state. Upload
bytes do not supply a trusted identity or arbitrary URL. Listing metadata is fetched
from the same fixed Naver basic endpoint already used by the app's quote provider;
local endpoint inspection confirmed `itemCode` and `stockExchangeType.code=KS` for
the public Samsung example. No API key is sent to that endpoint.

On owner/ticker/file/scope changes, the relevant state/widget keys separate previews
and results. Stored-result eligibility is checked again on render; identity expiry
disables actions. Opening the panel or a regular rerun makes no new external or DB
request. Corporate metadata and saved evidence are read only on their buttons.
No full Today Check recalculation, new timer or schedule is introduced.

Metric display calls the existing `extract_dart_metrics` on raw rows. It does not
calculate/save a financial grade, overwrite `fin_meta`, run a final decision or
replace cached automatic financial inputs. The existing automatic-score button
still uses its original provider path and does not consume the uploaded evidence.
Annual and cumulative interim figures are shown explicitly; no single-quarter
value is inferred from an isolated half-year report. The source-verification
limitation and missing latest-release coverage remain visible.

The upload filter is only a convenience; strict JSON validation remains mandatory.
The UI caps upload size at8MiB and reads at most the validator limit plus one byte.
See [Streamlit uploader documentation](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader).

## Verification

- Streamlit AppTest panel lifecycle: **14 passed** (15.73s standalone). Tests drive
  real buttons/tables/session state with synthetic in-memory file and storage
  providers. A separate smoke test renders the actual file-uploader widget.
- Covered: zero background calls, preview-only demo, identity/import/load sequence,
  duplicate import, schema-download state, wrong company/listing, invalid/expired/
  partial files, account switch, identity expiry and saved-score preservation.
- Existing parser reproduces cumulative revenue from uploaded rows. AST comparison
  against `5cadb203:app.py` verifies every existing top-level function unchanged.
- Combined UI/store/collector/financial tests: **145 passed**, 17.47s.
- Fixed-source decision gate: **1,327 passed**, 100.663s; no skips/source changes.
  Evidence `cache/refactor_checks/decision_w6u3nx3x`. No golden updates or
  investment-threshold/wording changes. This is selected regression coverage,
  not a full-suite or live-provider performance test.

Tests do not constitute live Cloud upload/storage verification. No production
account rows were read or written by this task and no schema was executed.
The mocked uploader supplies bytes directly; the actual widget smoke test does
not exercise browser multipart transfer. Production setup and one real roundtrip
are the remaining acceptance step.

## Next bounded task

Once the prepared table setup is confirmed, verify a single-company upload,
preview, explicit import, duplicate import and stored reload in the authenticated
production UI. Compare saved score/decision before and after and confirm matching
owner/ticker/report scope. Use the current collector output; do not renew old file
timestamps. If the table is missing, request the one-time setup using the prepared
SQL instead of running a migration automatically. No new features in that task.
