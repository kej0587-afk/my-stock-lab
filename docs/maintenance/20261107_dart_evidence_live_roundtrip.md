# Production DART evidence roundtrip

Verified 2026-11-07 KST on authenticated production, deployed `142e749a`.
Documentation-only follow-up; no runtime changes or automatic financial refresh.

## Actual checks

| Step | Observed result |
| --- | --- |
| Browser connection | A fresh in-app browser tab reused the authenticated session; existing-tab binding was unavailable. |
| Baseline | Completed precision ZIP before upload; selected and result ticker agree. |
| File transfer | Actual JSON file chooser upload, 101.4 KB; not an injected AppTest payload. |
| Preview | One half-year CFS report; 223 source rows in the validated file. Q3 is explicitly supplier no-data, not an estimate. |
| Identity | Corporate code and listing market verified; import button became enabled. |
| First import | `개인 근거 저장 완료 · 기존 점수 유지`. Confirms the prepared storage path is usable after user setup. |
| Same-file import | `이미 저장된 동일 자료입니다 · 기존 점수 유지`. Existing immutable row returned after uniqueness conflict; no update path. |
| Exact-scope reload | Explicit server lookup displayed the stored company, collection time, report coverage and cumulative figures. |
| Result preservation | Financial inputs, candidate grade, main decision and final check equal before/after. Execution workflow differs only at `계산시각`. |
| Runtime coherence | Completed exports report base `142e749a`, no monitored stale modules, restart not required. |

The upload, duplicate and reload actions used the same authenticated owner and
selected company. The adapter verifies returned owner/ticker/digest/scope before
showing success. No cross-owner DB enumeration or alternate-account access test
was performed. Duplicate proof is the production uniqueness-conflict/readback
path, not an independent database-wide row count.

The explicit reload button invokes the storage SELECT; this was not merely the
uploaded preview. A browser restart/session-loss test was not performed. The
private store retains evidence without changing saved financial metadata or
scoring inputs. Existing manual selection and automatic score were both preserved.

## Evidence and limits

Private local evidence (ignored, not published):

- `cache/dart_import_before.json`, `cache/dart_import_after.json`: completed review exports.
- `cache/dart_import_duplicate.png`: actual duplicate response.
- `cache/dart_import_reloaded.png`: stored coverage and financial figures.
- Original collector output remains under `cache/financial_evidence/`; no timestamp edits.

Before/after captures: 10:25:06 and 10:27:54 UTC. Only the relevant completed
export sections were compared; this is not a full-suite or performance benchmark.
The prior implementation's tests remain recorded separately. No tests were
regenerated or investment thresholds/labels changed for this verification.

Cloud live DART financial transport remains unresolved. A recent upload does not
prove the latest earnings release exists in the package; Q3 remains explicit
no-data. Existing saved score provenance remains its original source. One-owner
roundtrip does not prove all RLS denial paths or every issuer/report scope.

Commit/push this documentation after whitespace/link checks; no reboot is needed.
Next task is the single US financial-data failure diagnosis specified in HANDOFF.
