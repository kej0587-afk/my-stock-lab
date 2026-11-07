# SEC annual evidence: production acceptance

2026-11-07 KST. Deployed base: `ed5539b3`.

## Actual workflow

Recovered browser control by creating a fresh tab in the already selected in-app
browser. Binding the old user tab still returned `browser.user is unavailable`;
that did not prevent a fresh tab from loading the authenticated production app.
No app reboot, credential entry or security/permission change was needed.
For future recovery, use the documented fresh-tab route before claiming all
browser access is unavailable. Do not reset the user's existing tabs.

In `https://3insky.streamlit.app/`, selected NBIS in precision and downloaded the
completed review ZIP before the new evidence query. Opened the financial evidence
expander and clicked only `SEC 연간 근거 조회·새로고침 (점수 유지)`.
The actual Cloud response displayed NBIS, CIK0001513845, annual2023–2025 USD tables,
separate continuing/discontinued operating cash flow, provenance and warnings.
Displayed evidence query time:2026-11-07T12:46:46.261046+00:00.

Downloaded the SEC evidence JSON and a second completed precision ZIP. No automatic
score button, score edit, financial/account save, DB operation or cache-wide refresh
was invoked. Source HTTP status is not exposed by the UI; acceptance is based on
the actual displayed result and downloaded evidence, not an inferred status code.

## Verification

- Production JSON ticker/CIK match the selected company.
- All parsed annual records exactly match the earlier local official-source
  result, including the latest2023/2024/2025 periods and per-field provenance.
- `review_only=True`, `eligible_for_scoring=False`, `latest_release_verified=False`;
  quarterly/latest interim earnings are not claimed.
- Seven before/after CSVs are byte-identical: `financial_inputs`, `candidate_grade`,
  `main_decision`, `final_check`, `execution_readiness`, `entry_plan`, `workflow_display`.
- Export build is `ed5539b32fc0a36a448b376a09fdacfafcfd119a`;
  `restart_required=False`, monitored `stale_modules=[]`. The new SEC helper is
  not in the existing source-monitor list; its actual UI/data behavior was verified.
- Screenshot confirms table layout and review-only/continuing-business warnings.
  No new code was needed; previously passed99 focused tests and1,327 decision tests
  were not repeated for this docs-only verification.

## Private evidence and limits

Ignored local files: `cache/nbis_cloud_before.zip`, `cache/nbis_cloud_after.zip`,
`cache/nbis_cloud_annual.json`, `cache/nbis_cloud_acceptance.json`,
`cache/nbis_cloud_verified.png`. Private review exports/account data are not committed.
The verified tab is retained as a result for the user.

Acceptance covers one authenticated owner/company and this Cloud session.
It does not certify every foreign issuer, IFRS,6-K, newest quarterly release or
automatic20-F scoring. Existing scorer coverage remains intentionally unchanged.
Next bounded task is the four pending KR sector-RS production checks.
