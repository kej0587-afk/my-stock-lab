# SEC 20-F annual evidence in the observatory

2026-11-07 KST; base `5c83e217`, clean and equal to origin before work.
User authorized moving forward with code/test work despite browser-control failure.

## Delivered behavior

For non-Korean, non-ETF selections, the precision page now exposes:
`재무점수 계산 근거 > SEC 20-F 연간 근거 · 점수 유지`.
The explicit `SEC 연간 근거 조회·새로고침 (점수 유지)` button resolves the ticker
through the existing official SEC company list, verifies ticker/CIK identity,
and requests companyfacts once. The annual evidence parser validates the response
CIK and uses the KST date as its filing cutoff. Currency is explicitly USD.

The new panel shows up to three annual periods in income/cash-flow and balance
tables, separating total, continuing and discontinued operating cash flow.
Period dates, currency, missing fields, mixed accessions, per-field filing dates,
accessions and XBRL concepts remain visible. A JSON download carries the full
parsed review evidence, not private account data or a score.

This is review-only. The existing automatic scorer still does not accept20-F;
its stored failure/score is not silently replaced. Quarterly/latest earnings are
not inferred. No threshold, grade, judgement wording, DB path, existing provider
cache or TTL changed. The panel does not call the FMP/scoring workflow.

## Request/state boundaries

- No request merely from rendering, expanding, downloading or rerunning this panel.
- Explicit refresh fetches a fresh companyfacts response without replacing any
  existing scorer cache; ticker identity uses the existing company-list cache.
- Panel state is scoped to owner and ticker. Switching either hides previous data.
- Refresh discards its prior display first; failure never leaves it labelled as
  the newly successful result. Errors omit raw response text/contact details.
- Missing configuration, no owner and demo mode cannot issue panel requests.
- Operating Cloud needs its own root `sec_user_agent`; local configuration does
  not prove that Cloud is configured. No secrets were copied or committed.

## Verification

- Focused parser/review tests before wiring:46 passed (18.99s).
- UI/parser/review after wiring:57 passed (17.78s).
- Final UI, annual parser, existing10-K/10-Q parser and financial review:99 passed
  (16.97s). Eleven new tests include actual Streamlit AppTest lifecycle coverage,
  response/identity mismatch, unsupported data, sanitized refresh failure,
  account/ticker isolation, demo/config controls and unchanged saved score/decision.
- AST comparison against base proves every existing top-level app function is
  unchanged. App changes are11 additive lines in the precision UI only.
- A live local run used the actual existing ticker resolver functions (AST-isolated
  without importing the full app), the configured contact and the new panel loader.
  Official company list HTTP200; NBIS companyfacts HTTP200; CIK0001513845;
  latest annual periods2023/2024/2025; `eligible_for_scoring=False`.
  Private local evidence: `cache/nbis_live_ui_verification.json` and
  `cache/nbis_live_ui_evidence.json`. No identity spoofing or retries.
- Decision regression gate:1,327 passed, zero failures/errors/skips/source changes,
  105.532s; ignored evidence `cache/refactor_checks/decision_wl3rgaq6`.

## Deployment boundary and remaining work

Commit/push adds the UI and helper. Cloud runtime behavior has not been observed:
browser tab control previously returned `browser.user is unavailable`; Windows
control stopped because it could not establish the browser URL. This is a control
connection limitation, not evidence of app failure or a reason to request reboot.
Standalone AppTest is not a full authenticated Cloud integration test.

Next bounded task: production acceptance of this NBIS panel, with before/after
score/decision evidence and no automatic score button. Four sector-RS mapping
checks remain pending separately; do not claim they were completed.
