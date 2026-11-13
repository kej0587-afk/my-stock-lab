# Report Input Status and Financing Ads

Date: 2026-11-13 KST. Base: 500c41e1.

## Scope

- Separate market-only reports from reports with calculated account rows.
- Missing input is not zero holdings, zero candidates or zero coverage.
- Separate skipped history comparison, failed/unconfirmed reads, successful
  remote persistence and an actual local fallback. No storage migration.
- Exclude financing promotions requiring both a financing product and explicit
  promotional wording. Retain reporting on credit balances, margin liquidation,
  interest-rate changes and company earnings. Filter the report's copied news
  buckets and strict curation; do not change investment scoring inputs.
- Extract display helpers; preserve account calculations, thresholds and prices.

## Verification

- 173 focused tests passed, including report full-output legacy contracts with
  only the intentionally changed history wording adapted (golden hashes unchanged).
- Decision scope: 1367 passed, no failures/errors/skips, 126.537 seconds.
  Local evidence: cache/refactor_checks/decision_su0sc6v6 (not committed).
- Local Streamlit uses the production report builder and renderer with explicitly
  synthetic empty/connected inputs. Both states render without exception, the
  market-only header says inputs are missing, and financing advertising is absent.
- No whole-app speedup or fresh account-data validation is claimed.
- Report regression scope: 207 passed; the same pre-existing whole-app AST
  failure in test_theme_selection remains (app.py is unchanged in this patch).
  Local evidence: cache/refactor_checks/report_hmqg52jg. This is not a full-suite pass.
- Cloud validation pending deployment; private reports/screenshots stay outside Git.

## Economic Freshness Follow-up (Read-only Audit)

The user also asked to check CPI and other releases. Report generated at
2026-11-13 10:39 KST was compared with official publications:

- US CPI October MoM 0.4% and core MoM 0.3% are already updated. Official release
  was November 10. YoY inputs and release dates are missing in the report; this
  is a partial data/metadata failure, not evidence the entire CPI row is old.
  https://www.bls.gov/news.release/cpi.nr0.htm
- US PPI October release is scheduled for November 13 08:30 ET / 22:30 KST.
  September is still the latest release at this morning's validation time.
  https://www.bls.gov/news.release/ppi.nr0.htm
- Census current retail bulletin is September, released October 15. The report
  matches the 0.8% value but explicitly uses last success after a fetch failure.
  https://www.census.gov/retail/marts/www/marts_current.pdf
- KR CPI October YoY 2.8% matches the November 3 official publication.
  https://m.korea.kr/briefing/policyBriefingView.do?newsId=156787698
- KR export report still uses September +83.7%; official October bulletin is
  available (November 1, +93.7%). Investigate bulletin discovery/ECOS freshness
  separately, without adding a permanent manual override.
  https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/172360/view

No missing economic value was estimated or substituted in this patch.
