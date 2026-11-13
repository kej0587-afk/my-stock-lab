# CPI Metadata and Korean Export Freshness

Base: f56454dc. Scope: economic report inputs/display only. No prices,
investment scores, market gates, position sizes or channel rules changed.

## Findings

- October CPI YoY is genuinely unavailable: the BLS release explicitly says
  October 2025 comparison indexes were not collected. Numeric October 2026
  index levels exist; dividing by a guessed prior index is prohibited.
  https://www.bls.gov/news.release/archives/cpi_11102026.htm
- The BLS API returns '-' for that comparison month. Preserve this marker as
  metadata and do not replace the current missing rate with September's cached
  success. Other transport failures still use explicitly stale prior success.
- BLS calendar/release HTML returns HTTP 403 from the application environment.
  November 10 08:30 ET / 22:30 KST was verified from the official release.
  A period-exact, expiring metadata fallback fills only this release date,
  labeled as verified fallback, not a repaired automatic schedule connection.
  Automatic calendar matches retain priority. No CPI value is hardcoded.
- Customs monthly final releases lag the ministry's preliminary monthly release.
  A bounded two-request ministry collector discovers the whole-month release,
  validates title, publication date and total-export sentence, and excludes ICT,
  imports and YTD figures. It upgrades only to a newer month; final values win
  in the same month. Forecast/reaction/previous values are not carried across.
  https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/172360/view
- Live public retrieval: October exports +93.7%, 1152.8 hundred-million USD,
  November 1 publication, preliminary. These numbers are responses, not constants.
  Separate cache key prevents the ministry and Customs from erasing each other's
  last successful observations. No private account data is stored in this commit.

## Verification

- 232 focused economic/calendar tests passed, including 15 new tests for missing
  comparisons, fallback expiry/month matching, total-export parsing, cache failure,
  final-over-preliminary priority and production report wording.
- Production report builder/renderer inspected in local Streamlit with live
  public BLS/ministry responses and no account inputs. CPI YoY remains missing
  with a reason, publication time is KST, exports are labeled preliminary.
- Report selected regression: 207 pass, one pre-existing whole-app AST failure
  (`test_theme_selection::test_extraction_changes_no_other_statements_or_functions`).
  No golden files were regenerated. This is not a full-suite pass.
- Final immutable-source decision run: 1367 passed, 127.564s, evidence
  `cache/refactor_checks/decision_ydgxil_m`. Earlier interrupted-source run is
  not used as acceptance evidence. Final focused run: 232 passed, 7.29s.
- Cloud acceptance remains separate from local renderer verification.

## Next Bounded Task

Audit current market-gate inputs, timestamps, score components and release
conditions without lowering thresholds. After that, evaluate SOXL timing with
its daily-reset product structure, matching timeframes, split-adjusted data,
fixed channel anchors and out-of-sample tests. The supplied quarter-channel
post is a hypothesis, not an established strategy or a promised 20% return.
Official SOXL/SOXX benchmark is NYSE Semiconductor Index; SOX is a separate
index. SOXX is a useful proxy, not SOXL's legal benchmark ETF.
https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs
https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf
