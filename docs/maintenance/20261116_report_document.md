# Single Report and Decision Summary

## Scope

Base: d4dc17a3. User approved only duplicate-report removal and an existing
decision/reasons/reconsideration summary, with verification and push. No new
providers, scoring, thresholds, price calculations, trade advice or TTL changes.

## Findings

- `compose_reading_report` appended the entire old report after its new reader.
  `test_report_reading` and `test_report_event_watch` explicitly required this.
  The problem was an incorrect acceptance contract, not absence of all tests.
- The operating report put its decision status after long market tables. The
  current queue also displayed an input-change/recalculation warning; a fresh
  report does not mean fresh account decision inputs.
- Repeated stress 40 alone does not prove stale data. Current discrete components
  can produce the same total with different prices. VIX direction and level are
  distinct labels. A small position can exceed a zero target. Those reviewer
  claims are not grounds to change investment rules in this task.
- The export percentage/source, cross-article semantic duplication and broader
  narrative quality remain separate verification tasks. No unsupported value
  was clipped or replaced to make a review look better.

## Changes

- Extract `report_document.py`: promote the existing guard action, scope, score
  decomposition, next boundaries, basis warnings and current market/account rows.
  Report interpretation exposes the existing final inference sentence from
  `market_summary.headline`, without new inference. Operating inspection found
  that the full overview repeated too much evidence at the top, so it stays in
  detailed sections instead of the decision summary.
- Keep input-change/recalculation warnings at the top; missing inputs do not
  become zero or permission. Entry restrictions do not mean sell all holdings.
- Remove the second report title/preamble and copied tables/paragraphs from their
  explicitly mapped source sections. Keep full source tables if the reader omits
  fields; do not deduplicate identical tables across unrelated contexts.
- Keep the decision and current conditions visible. Reader data sections fold
  independently; downloads retain data and evidence, including dated caveats.
- Update only output-location contracts, replacing the two assertions that
  required the entire report to be appended. No golden files regenerated.

## Verification

- Targeted report/UI/source contracts: 187 passed, 8.04s (including summary).
- Compared old/new `market_summary` on populated and missing-input fixtures:
  all pre-existing returned fields are identical; only `interpretation` is new.
- Decision gate: 1369 passed, 145.586s; private record
  `cache/refactor_checks/decision_31nkzh9p/summary.json`.
- Pre-change selected report gate: 207 passed / 1 failed, 43.692s.
  `test_theme_selection::test_extraction_changes_no_other_statements_or_functions`
  compares the current large app against a historical extraction; unchanged here.
- Broad report suite baseline in an isolated d4dc17a3 worktree: 1414 passed /
  19 failed, 67.19s. Baseline XML remains in the local temporary worktree.
  Final post-change: 1422 passed / 18 failed, 56.40s; private record
  `cache/report_document_20261116_final_tests.xml`. XML comparison confirms no new
  failing test IDs. The candidate/order assertion was updated to the single
  canonical reader location. All 18 remaining failures also fail at baseline;
  these include historical layout contracts, incomplete test doubles and reader
  caveat/news-quality gaps. This is not a full-suite pass or speed benchmark.
- Frozen operating export replay (private 11:19 report, before adding the new
  intro): 2 titles to 1, 86 tables to 78, 183889 to 177345 characters. No source
  URL or original table cell lost. This is removal of literal copied evidence,
  not a claim to have removed all semantic repetition or halved report length.

## Deployment

First push e9483eef was operating-verified with the 11:34 KST report (loaded
source 57cb8499a7c67afc): one report title, decision/reasons/boundaries above
collapsed details, stale-input warning retained. The live check identified an
overlong overview; the final one-sentence polish still needs regeneration.
Raw reports and account screenshots stay outside Git.

## One Next Task

Restore the missing time/session caveats in the reader's projected holdings
table (`test_report_close_session` and `test_report_quote_regressions` baseline
failures). Keep underlying prices and decisions unchanged; compare the first
visible holding row with its full source row before adding further report features.
