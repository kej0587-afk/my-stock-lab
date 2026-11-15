# Report summary, sector evidence and connection checks

Base: `4f657800`, clean main aligned with origin. The preserved Customs stash is
untouched. This follows the user's expanded report-finish request, beyond the
previous handoff's sector-only task. No score, grade, gate, price definition,
cache TTL, authentication or storage schema changes.

## Changes

- Sector explanations reuse verified body facts with issuer/sector, source,
  publication/body version and same-session gates. Common financing/rate context
  remains separate from sector-specific explanations of excess returns. Each
  supported channel carries a conditional implication and next check.
- Top five weekly themes use collected, source-checked, dated headlines over the
  latest seven calendar days (KST). Distinct URLs/titles count once across news buckets. Five is a
  maximum, not a quota filled with unsupported stories. Theme labels describe
  subjects, not assertions that the user's example events occurred. Holdings
  links describe exposure, not realised price contributions. Detailed headline
  lists move to the evidence document to avoid repeating the reading path.
- Unverified buy/hold/exit-advice headlines are excluded from the reading path;
  factual earnings/policy news is retained. Existing source material is preserved
  in the evidence appendix.
- Summary/evidence tabs and UTF-8 downloads split the same immutable report at
  its existing audit boundary. Joining the files restores the full report.
  The existing full-report download and diagnostic SHA remain unchanged.
  New downloads use `on_click='ignore'`; no new calculation or remote request.
  `app.py` is unchanged, avoiding a new mixed-module import failure.
- Summary footer checks only explicit connection/structure contracts: two market
  reference dates, account input, theme-body coverage, individual-investor history,
  and BOK schedule display. Missing data is `미확인`, not a pass; date disagreement
  is a failure. These checks do not certify article claims or investment outcomes.
- Npay daily history now includes individual investor code `8000` directly.
  Missing/invalid individual values are not inferred as a residual or filled with
  zero. Existing foreign/institution sums, 2 GETs, TTL600/failure60 and timeout
  `(3,6)` are preserved.

## Official schedule / provider review

BOK MPC was already connected for **2026-11-26**, date precision only, with no
inferred release time or policy outcome. Added integration tests rather than a
second collector. Verified against the
[BOK annual calendar](https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A&syear=2026)
and [November events](https://www.bok.or.kr/portal/singl/mainEvent/listCldr.do?date=2026-11&menuNo=200035).
Existing verified annual notice covers 2026 only; 2027 and current policy-rate
results are not implied by this schedule connection.

Individual mapping `8000 -> individual -> 개인` was checked against the provider's
[public page bundle](https://ssl.pstatic.net/imgstock/fn/real/pc/_next/static/chunks/app/market/stock/kr/trend/trader/page-bccb80eaf9b8df56.js)
and daily feed buy-minus-sell reconciliation for both markets. This JS URL is
verification evidence, not a runtime dependency.

## Verification / deployment

- Focused report/article/flow/calendar contracts: **411 passed /16.94s**.
- Final view/digest plus historical app-function contracts: **189 passed /59.80s**.
- Compile and whitespace checks passed. No golden files regenerated.
- First decision gate identified only two historical app-AST failures from the
  proposed download wiring. That app edit was removed. Final decision gate:
  **1,369 passed /137.938s**, `cache/refactor_checks/decision_f1lu3eob`.
- Read-only final review found global-only themes incorrectly showing no related
  holdings. The same exposure matcher now handles global/other-market articles
  with a cross-market label; final focused view/digest/classification checks:
  **51 passed /4.19s**. No decision code changed after the passing gate.
- Final production verification is recorded below. Private exports and screenshots:
  `cache/report_finish_20261115/`; never commit account data.

## Operating review corrections

First complete production report (23:56KST, fa304fca) ran normally in78.301s;
112 loaded/disk/Git hashes agreed, report SHA and split-file rejoin matched.
All95rows/23decision columns matched before/after generation and the prior run.
Footer:5passed/0failed/1unconfirmed (partial article-body coverage).
Review then found two presentation defects requiring a final regeneration:
- Broad market-wrap categories crowded out specific themes. Exclude those
  categories as themes; refine governance/crypto subjects, use an explicit
  seven-day window so a Monday pre-open report retains recent trading material.
- AI infrastructure body facts overmatched XHB/XLI/PAVE through broad words.
  Body linkage now requires actual housing/industrial machinery/public-infra
  evidence; AI financing remains common AI-sector background only.
No price or decision values changed. First artifacts retain `first_` prefixes.

Final operating-review corrections: related **440 passed /16.44s**.

## Final production verification — 2026-11-16 00:17 KST

Final code `817105f3` (earlier `dcddfd46`, `fa304fca`, `7c898e73`). Cloud owner
Reboot was performed during verification; the final small deployment reset the
session, so Today input was reconnected and recalculated (67.8s; an earlier cold
Today run was83.5s, not a controlled speed comparison). No login/input changes.

- Final report run `ba57ecaba1d04867850dbd9bb86d4dd1`: normal, no degraded reasons,
  **69.442s generation /91.515s script-to-report**. Macro22.133s, prices16.848s,
  calculations0.981s, news2.277s, bodies0.335s, persistence8.234s, assembly18.634s.
  Prior69.474s and first78.301s are different cache/session runs; no speedup claim.
- **112** loaded/disk/Git source hashes match; `restart_required=false`.
  Downloaded full-report SHA matches the diagnostic. Summary+evidence bytes
  rejoin exactly to the full original. Both tabs and all downloads were exercised.
- **95 rows x23 decision columns unchanged** across final report generation,
  and all95match the initial pre-change export; no added/removed input tickers.
- Five concrete themes appear (general market-wrap categories excluded), with
  headline counts, existing exposure and checks. Named leadership articles now
  retain the issuer's related holdings even without the company name in title.
- Verified sector-body rows: KRsemiconductors, USsoftware/cybersecurity/technology/
  memory/semiconductors. XHB/XLI/PAVE no longer receive the unrelated AI body.
- Individual rows appear for both KOSPI/KOSDAQ with independently collected
  five/twenty-session sums. BOK2026-11-26 appears once in the reading schedule,
  date-only precision, no invented result or release time.
- Footer **5passed /0failed /1unconfirmed**: theme article bodies are only partly
  connected. This is an explicit evidence-coverage limitation, not a failed
  arithmetic check, and does not certify all article claims.
- Final report/sector contracts440pass/16.44s. Final decision gate1369pass/135.995s
  in `cache/refactor_checks/decision_7347f0r5`; later issuer-alias-only change:
  focused digest/view/sector72pass/3.75s, no decision code changes.

Private final artifacts: report.md, summary.md, evidence.md, report_timing.json,
verification.json, before_generation_review.zip, after_review.zip,
operating_summary.png, operating_evidence.png in cache/report_finish_20261115.
Earlier first_/second_ files are retained for diagnosis, not final deliverables.
No account data, credentials or private snapshots were committed.

The summary is still a comprehensive market reading path, not a one-page digest.
On a narrow phone viewport, wide tables scroll horizontally. New split downloads
avoid a rerun; pre-existing full-report/review-ZIP buttons still rerun Today and
incur about20s of screen processing. This observed export overhead is the sole
next bounded task; no new sources, LLM, thresholds or broad refactoring.
