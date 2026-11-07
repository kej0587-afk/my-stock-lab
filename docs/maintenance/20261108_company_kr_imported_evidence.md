# Korean selected-company imported evidence

Base: e3c75cc2, clean main/origin before work. Date: 2026-11-08 KST.

## Change

Company review previously stopped at the live DART provider's failure. Explicit
selected-company queries now attempt owner-scoped existing imported evidence only
after that failure/exception. Live success makes no identity/database request.
Independent corporate/listing identity is required; one recent collected bundle
is selected and fully validated. Latest collected does not mean latest filing;
the original requested scope and missing reports are displayed. Seven-day import
eligibility and one-day stale label are unchanged; display also checks expiry on
rerun. Current source, failure, collection time/age, periods, CFS/OFS, cumulative
basis, currency, missing metrics and original filing links remain explicit.

Reuses the existing parser and immutable store decoder. New read-only load_recent
does not change precision's exact-scope load_latest or insert/dedup behavior. No
DB writes/migration, provider TTL, score/decision/raw records or parser changes.
US/default market paths unchanged. New modules join loaded/disk build monitoring.

## Verification

- Before decision gate: 1,334 pass, 103.346s, decision_a7e6iz0g.
- After decision gate: 1,334 pass, 105.735s, decision_0fxkwlvr; stable sources.
- Focused DART/store/preview/company/financial tests: 133 pass, one historical
  whole-app AST assertion failure, 19.51s. That assertion compares to 5cadb203;
  before this task HEAD already differs in render_today_market_memo_panel and
  _generate_today_briefing_market_memo. This task changes only the former's
  company callback wiring. Baselines were not regenerated.
- New tests cover owner/ticker/corp/scope/time validation, no-data, live success,
  failed live exceptions, sanitized failures, no writes, on-demand UI, reuse,
  switch hiding, owner isolation and expiry while displayed.
- Independent bounded reviewer: no concrete actionable findings.
- Local saved 005930.KS bundle: eligible; original requested two periods with
  one collected report. Expected parsed rows/coverage/hash saved privately under
  cache/company_kr_expected.json; no extra collection or new database import.
- Application commit `07b34e61` pushed. Authenticated Cloud diagnostic
  fcb7703e37eb4a1a8a55985b4c741b13 matches commit, restart_required false and
  stale_modules empty. Loaded/disk hashes for company_deep_dive,
  company_kr_evidence and dart_evidence_store all match; no reboot requested.
- Cloud's Samsung live provider now succeeds: seven annual/quarter rows through
  FY2025/FY2026Q2. Do not claim a real Cloud failure/fallback in this session.
  Local forced-failure replay uses the real previously imported Samsung JSON
  with injected identity/store (not a real Supabase read): hash, all metrics and
  requested-period coverage exactly match independent existing-parser output.
  The bundle has 2026 half-year data; Q3 is source no-data, never synthesized.
- Cloud manual Samsung query and JSON download succeeded with the new modules.
  Seven annual/quarter rows and every packet field other than query timestamp
  exactly match the pre-deployment packet; live-success path was preserved.
  Before08:38/after08:49 ZIPs contain the same95tickers. All14 core score/grade/
  verdict/gate fields match (1,330 comparisons). No whole-ZIP identity claim.
  Screenshot and diagnostic/packet/ZIP acceptance evidence are ignored under
  cache/company_kr_*. No new saved financial rows or scores were written.
  No full Today performance claim; initial startup/rerenders remain slow.

## Next bounded task

Build source-bound Korean company why/next-check explanations from these validated
rows, preserving annual/cumulative/CFS/OFS/currency boundaries and explicitly
holding missing comparisons. No extra fetches, CAPEX imputation or score changes.
