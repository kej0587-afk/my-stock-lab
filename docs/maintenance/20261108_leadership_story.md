# Market-wide leadership reading

2026-11-08 KST; base5f145fa3. Report-only interpretation over existing inputs.
No app.py, calculation/grade/gate, raw price/RS builder, provider, TTL or DB changes.

## Scope and interpretation

`report_leadership.leadership_lines` now explains the coexistence of weakness in
semiconductor/technology exposures and strength elsewhere, independently for US/KR.
It separates actual uptrends, relative defense and short-term rebounds. The existing
five-positive-return/RS display condition is unchanged. These are observations,
not evidence of actual fund transfers, previous historical leadership or buy signals.
Sample breadth limits remain visible. Future breadth/order/earnings checks are
questions, not claimed measurements. Prices, RS and duplicate-sector selection stay
unchanged for valid production input; mismatched row dates are excluded from prose.

At most two representative sectors per market get existing, same-session news.
Verified body interpretation stays an article claim; title-only evidence stays
explicitly unverified. Common-market stories are separated from direct sector
evidence so they cannot steal another sector's source through URL deduplication.
After-close publication is labeled subsequent information, not retroactive cause.
Financials, biotech, shipbuilding, suppliers and software have distinct next checks;
cash burden is not a universal sector ranking. The source's one-day news cannot
explain a whole20/63-day trend by itself.

Existing exact-date price/volume proxy scores and at most two dated macro components
are supplementary observations, not a new risk score or inferred capital flow.
Old/missing macro or proxy dates are not promoted to current data. No new HTTP;
the existing rotation builder still runs once. Price/RS audit tables remain intact
in Markdown/downloads and are collapsed in the UI behind a dedicated detail control.

Framework reference: [Fidelity sector rotation](https://www.fidelity.com/learning-center/trading-investing/markets-sectors/intro-sector-rotation-strats)
considers monetary policy, rates, commodity/input prices and the business cycle.
This reference does not validate a forecast or today's price cause.

## Verification

- Before report gate:207passed/1pre-existing theme whole-app AST failure,42.660s
  (`cache/refactor_checks/report_lyj60x6b`). After:207/same failure47.210s
  (`report_a0dsnsmq`), stable source hashes. No golden changes.
- Focused213passed/1deselected12.62s. The deselected editorial ordering test also
  fails on the base leadership+observation modules: it expects holdings before
  index/macro, while unchanged reading_order does the reverse. Captured separately
  in private `cache/leadership_preexisting_editorial_test.txt`; not patched here.
- Independent review found three concrete issues (common story stealing a direct
  source, after-close label loss, body text pipe breaking a table). All fixed;
  counterexamples and31focused tests passed on re-review.
- App entrypoint, rotation calculation and existing report evidence logic unchanged.
  Decision1367passed138.179s (`decision_wv3kkdj8`), stable source hashes.
  Application commits and Cloud acceptance are recorded below.

## Deployment / limits

Before-change authenticated Cloud report saved privately as cache/leadership_before.md.
It has US19unique sectors/20ETFs and KR10sectors/10ETFs,11/06completed close.
Its US staples satisfy the existing uptrend condition; KR has no qualifying
nontechnology alternative. This is report input evidence, not independent market
price verification. No Today full calculation/portfolio rows in that fresh session.
No generation speedup is claimed; input collection is unchanged.

Live QA: a910fcc3 generated correctly but Markdown joined fact/interpretation/check
into one paragraph. 9a2c1d5c separates those paragraphs (38focused tests passed).
Its actual10price/RS display rows matched the saved before report exactly and all
three loaded/disk/local module hashes matched; no reboot was required. The actual
related-news selector also chose an incidental chip-component listing notice and
an evergreen housing column. 0a4c980b excludes listing notices/evergreen opinion
titles from this evidence panel only; no wider news collection/filter changes.
40focused tests passed3.33s.

**Final Cloud acceptance:0a4c980b**, no user reboot. Newly generated report has
separate readable observations/interpretation/next-check paragraphs and collapsed
price/RS audit. US staples are an actual-uptrend candidate while memory/chips are
weak; KR has relative defense but no qualifying nontechnology uptrend. All10prior
displayed price/RS rows remain identical. The listing/evergreen articles no longer
appear in this evidence panel. Four selected sectors still lack direct original
article evidence; common US/KR session stories are separate and are not upgraded
to industry causes or20/63-day explanations. This source-coverage limit remains.

Downloaded report and completed render diagnostic verify all three modified module
loaded/disk/local normalized hashes agree; restart_required=false/stale_modules[].
The diagnostic is render_only and cannot measure full report generation or imply a
speedup. No full Today/portfolio recalculation in this fresh session: score parity
rests on unchanged app.py and1367fixed-input tests, not a live account comparison.
Private artifacts: cache/leadership_before.md, leadership_after.md,
leadership_before_rows.json, leadership_diagnostic.json, leadership_acceptance.json
and visually inspected leadership_cloud.png. Final publication is docs only.

## Next task

Measure one full automatic-news generation by actual phases: price history,
macro/official sources, news/body collection and report rendering. Count remote
requests separately from function calls, record cache state, and identify the
largest measured bottleneck before proposing a single safe optimization.
