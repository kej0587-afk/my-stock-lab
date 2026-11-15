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
- Top five weekly themes use collected, source-checked, dated headlines since
  Monday KST. Distinct URLs/titles count once across news buckets. Five is a
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
- Production verification pending after push. Private exports and screenshots:
  `cache/report_finish_20261115/`; never commit account data.
