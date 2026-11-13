# Article evidence to market explanation

Date: 2026-11-13. Baseline: da1f26c2. Scope: report prose only.

## Reproduced problems

- Diplomacy keyword matching turned a sentence denying the need for negotiations
  into mediation optimism. The topic bypassed the old negation filter.
- Leadership transitions had no event type; a company name in a recap could also
  route it through earnings-only extraction.
- The body fact limit and one-fact-per-article editorial loop hid independent
  events in an already fetched recap behind generic oil commentary.
- A generic wrap prevented a separate, verified same-session leadership article
  from reaching the upper market explanation.

## Bounded changes

- Extract short, complete, attributed diplomacy sentences. Keep negation and
  qualifications; do not predict agreement, easing risk premium or oil direction.
- Recognize generic leadership transitions; no issuer, date or actual news story
  is hardcoded. Reject denied, historical, conditional, planned or demanded changes.
- Isolate selection/extraction in `article_market_events.py`. Preserve the existing
  four-fact cap, earnings/adverse-context treatment, session boundaries, article
  identity checks, source allowlist and maximum four body requests.
- Keep explicit oil observations in named-company market recaps; do not turn an
  issuer's cash-flow discussion into market-wide earnings optimism.
- Retain distinct facts from one source in the existing three-row editorial table.
  Link each supplemental same-session event to its own source in the headline.
- Bump the interpreted-body cache revision, not TTL. Include the new module in
  loaded/disk source diagnostics.

The changes do not alter investment decisions, weights, returns, market guards,
valuation, order quantities, data timestamps, providers or request concurrency.
No claim is made that a CEO change proves a production cut or competitor gain.

## Verification

- New synthetic test file: 11 failures / 9 passes on original implementation.
- Final focused suite: 283 passed, one known editorial-order failure deselected.
  That failure was separately reproduced using HEAD's original editorial module.
- Report scope baseline: 207 passed / 1 existing whole-app AST assertion failure
  (`test_theme_selection::test_extraction_changes_no_other_statements_or_functions`).
  Evidence: `cache/refactor_checks/report_ikm8vb1t` (local only).
- First implementation decision scope: 1367 passed, zero failures/errors/skips.
  Evidence: `cache/refactor_checks/decision_s3w2sfu_` (local only).
- Final report scope: 207 passed / the identical pre-existing AST failure;
  evidence `cache/refactor_checks/report_i4b97ivo`. No new report-scope failure.
- Final decision rerun: 1367 passed, zero failures/errors/skips (123.457s);
  evidence `cache/refactor_checks/decision_hpskxp41`. Source hashes stayed stable.
- Synthetic collection -> parsing -> report_sections -> upper editorial section
  test verifies source citations, separated interpretation and unchanged inputs.
- Different companies, denied/planned changes, diplomacy rejection/reopening,
  trailing denials, unverified bodies, wrong market/date and next-session items
  are covered. Existing transport tests verify unchanged body request bounds.
- No new live financial observations, production account calculation, Cloud UI
  acceptance or speedup is claimed. No private exports are committed.

## Deployment / next task

Final verification completed; this change is authorized for commit/push. Existing saved reports are not rewritten;
generate a new report. If runtime source diagnostics show stale modules, reboot
before evaluating the new output. Then inspect this single path in the generated
report and its body-collection diagnostics; do not add more data integrations.
