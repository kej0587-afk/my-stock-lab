# Four-view integration checkpoint — 2026-11-07

## Scope

Started clean on `main == origin/main == ffa04ee9`; fetched upstream first.
Reviewed Today Check, money-flow radar, Precision Observatory and Portfolio
Analysis. No production code, thresholds, wording, accounts or cache policy were
changed. This is a bounded connection audit, not validation of investment returns
or every external provider value.

## Evidence

- The restored Today result initially warned that its input context was stale.
  Ran one full calculation with the existing account/filter settings and theme
  refresh enabled; preserved the resulting 15:49 review ZIP (95 unique rows,
  32 flow candidates). Screen processing completed in approximately 78.2s.
  This is a displayed elapsed value, not a controlled before/after benchmark.
- Compared one held Korean ETF and one registered US stock using the completed
  Today and precision exports. Both use the 2026-11-06 price/flow session.
  Ten fields match for each: price date, raw price, decision code, candidate
  quality/score, execution gate/reason, flow date/verdict/connection route.
  Numeric scores were compared after CSV scalar-type normalization.
- The ETF's own price/volume series is reused when it is not a radar-universe
  member. The stock uses radar raw data. Neither route invents a flow observation
  date or converts a flow recovery/watch label into execution permission.
- Radar's live screen reuses the 15:48 flow snapshot from Today; it explicitly
  says that flow rank/precision candidates are not permission to buy. The common
  cached-snapshot path was checked in source and connection contracts. No separate
  radar refresh was triggered during comparison.
- Precision's final readiness remains restricted for both samples. Portfolio
  Analysis, visited after precision, reports **10/10 holdings connected** and
  **10/10 with price dates**. The reviewed ETF retains its completed precision
  restriction; original Today storage time 15:48 and precision time 15:52 are
  displayed separately. A registered but unheld stock is correctly absent from
  the positive-quantity holding review.
- Completed precision ZIPs identify `base_commit=ffa04ee9`,
  `restart_required=false`, `stale_modules=[]`. This also supplies runtime
  deployment evidence for the preceding theme-selection extraction.

## Mode difference investigated

The first stock visit was in free ticker exploration. Its raw decision code
differed from the registered Today calculation, although price/date/quality and
the blocking gate agreed. Source explicitly routes `is_free=True` through
`select_free_mode_decision`, while Today uses the portfolio-aware path. Reopening
the **registered** entry made all ten comparison fields identical. Do not merge
these policies or loosen a gate to make different modes look identical.

## Verification and limitations

- Connection, portfolio handoff, flow, observatory and display tests: **199 pass**.
- Frozen execution-context and holding-entry tests: **55 pass**.
- Replayed all ten positive-quantity holdings from the new export through board
  display and portfolio selection/review helpers: zero gate/date/code/reason
  mismatches, source unchanged, unreviewed precision cannot grant execution.
  CSV lacks DataFrame attributes, so replay uses an isolated audit context; it
  does not reconstruct live identity or recalculate the original OHLCV decision.
- No demonstrated wiring defect in this bounded review; production code left
  untouched. Existing financial freshness warnings remain: saved financial
  scores are not proof of immediate earnings refresh. Analyst target date may
  remain unknown when absent from the source. Portfolio report evidence can be
  unconnected until report generation/explicit evidence refresh; missing data
  remains missing rather than granting execution permission.
- An automated attempt to download the portfolio grid CSV did not produce a
  file. Live text/screenshot and the private helper replay provide the portfolio
  evidence; do not claim a downloaded portfolio CSV comparison.
- Selected contracts are not a full-suite pass or proof of equality for every
  ticker, mode, intraday timestamp and external feed.

Private evidence (outside Git): Downloads review ZIP timestamped
`20261107_1549`, completed precision ZIPs from 15:52/15:53, screenshot
`stock_lab_four_view_verified_20261107.png`; ignored `cache/four_view_*` logs and
replay results. No private account data or screenshots are committed.

## Next task only

Final closure regression: run the existing `scripts/check_refactor.py --scope all`
gate without regenerating baselines, inspect any failures against the last
records, confirm Git/deployment state, and document remaining data/provider
limitations. No new features or further speculative refactoring.
