# Market leadership reading and issuer research questions

Base: cf84af2d, clean main/origin. 2026-11-08 KST.

## User objective and bounded scope

User clarified that the report should assess weakening semiconductor/data-center
leadership, possible replacement trends and Big Tech investment/recovery, not
merely list numbers. This reprioritizes the pending KR prose-only extension.
Existing reports already calculated sector rotation, but buried it in an audit
table. This change promotes a concise interpretation and links it to company
research questions, preserving all trading grades/gates.

## Implementation

- Reuse build_sector_rotation exactly once inside the existing observation panel.
  Add actual5/20-session returns from its already-aligned price series. Existing
  rankings, RS formula,63-session return/acceleration and flow scores unchanged.
- New front section after core interpretation: dated US/KR summary, semiconductor/
  memory/software/technology focus, alternative trend candidates, relative defense
  and rebound observations. KR technology139260.KS belongs in focus, not an
  alternative outside technology. SOXX/SMH count as one sector (prefer SOXX).
- Rising candidate requires positive actual5/20/63 returns AND positive5/20 RS
  change. This is a report-only observation definition, not a calibrated prediction
  or trading threshold. Show at most two alternatives per market by20-session RS,
  plus one defense/rebound example. No candidate is manufactured when all fall.
  A positive relative return with a negative actual20-session return is defense.
  Missing3M data holds classification. Markets/dates are never combined.
- Investor questions distinguish Big Tech spenders from chip suppliers; META's
  question concerns advertising monetization. Only existing summary tickers are
  listed for selection. Company view displays the matching question before query.
  These are research directions, not collected segment metrics or causal claims.
- Old observation tables remain available in a collapsed detail section/export.
  No new provider calls, persistence, score/parser/TTL changes or LLM integration.

## Research basis (not current-market causal evidence)

- [Fidelity: sector rotation](https://www.fidelity.com/learning-center/trading-investing/markets-sectors/intro-sector-rotation-strats)
  treats rotation as an economic-cycle/sector allocation approach. This app's
  short-window sign conditions are our transparent observation rules, not Fidelity
  methodology, recommendations or a backtested next-leader forecast.
- [Microsoft FY27Q1 official call](https://www.microsoft.com/en-us/investor/events/fy-2027/earnings-fy-2027-q1)
  separately discusses demand, infrastructure investment, cash generation and
  outlook. This supports the review questions; no dated numbers from this page
  were hard-coded into reports or other companies' analysis.

## Verification

- Decision before:1334pass103.067s(decision_dmt1cphk).
- Final production-code decision:1334pass105.779s(decision_18vtba7x),stable sources.
- Targeted rotation/reading/company/UI contracts155pass8.07s.
- Reviewer found KR technology omitted from focus; fixed with regression test.
  Also added a negative5-day case: recent actual decline cannot be called rising
  solely because20/63-day returns and relative strength are positive.
- Initial report gate195pass/13fail:12 legacy digest failures include the explicitly
  added section; one historical theme-selection failure predates this task.
  Narrow adapter now excludes only leadership_lines in the historical digest test;
  original expected hashes retained, new section independently tested.
  Final report gate207pass/one same historical theme-selection failure41.830s
  (report_rs56kvb2), stable sources. No full-suite/speed claim.
- Application8eeed6db pushed. Authenticated Cloud diagnostic matches commit;
  restart_required false/stale_modules empty and loaded/disk hashes match for
  report_leadership, market_observation and company_deep_dive. No reboot.
  Fresh report accepted09:19KST, generationf922ba27b64f, loaded source639c2e2a02e0ac57.
  Downloaded Markdown has one new front section between core interpretation and
  market story, both markets dated2026-11-06. Six AI/technology focus rows,
  SOXX/SMH deduplicated, XLP's displayed five return/RS values positive. XLI/KR
  real-estate negative actual20-day returns remain defense, XHB's negative63-day
  return is recovery rather than rising candidate. This describes report inputs,
  not an independently verified next-leader forecast.
- Same95tickers and14 score/grade/verdict/gate fields unchanged(1,330 comparisons)
  before/after live generation. No whole-ZIP identity claim. Screenshot/Markdown/
  diagnostic/ZIP acceptance evidence ignored under cache/leadership_*.
  Actual market-to-company navigation verified: selected MSFT displays the
  investment/recovery question and conditional checks before requesting evidence.
  No additional SEC query or cross-company financial comparison claimed here.
  Initial page rerender was slow; reconnecting the agent-created browser session
  resolved verification. Full Today timing/performance was not measured.
- Private before ZIP:cache/leadership_before.zip(09:06KST). No private rows in Git.

## Next bounded task

Add on-demand Big Tech cash-generation/investment comparison for selected held/
watch companies using the existing SEC8-quarter loader. Align fiscal periods and
scope, distinguish cash PP&E from leases/commitments, hold missing comparisons.
No automatic default-report fetching, valuation/price prediction or score changes.
Pending KR detailed narrative remains deferred, not claimed complete.
