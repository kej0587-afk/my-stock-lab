# Completed-Bar Evidence and Priced A/B/C Observations

Base: 6721c62b. User requested continued framework work and useful numeric A/B/C
plans rather than repeated unknowns. No new data provider or investment threshold.

## Scope

- Precision A/B/C gets its own auditable completed-daily-bar observation set.
  It uses the existing exchange-calendar cutoff, original daily source, explicit
  quote-only exclusion and OHLC validation. Vendor partial bars after the last
  completed session are excluded. Missing calendar and stale source remain visible;
  stale source can supply dated history but not current conditional price rows.
- Fixed an observation metadata omission: chart expected-close metadata was set
  only when events existed and event overlays were enabled. It is now supplied
  independently of presentation toggles. No signal scoring changes.
- New pure `scenario_evidence.py` separates source validation, causal reference
  levels, time/volume measurements and presentation from the existing scenario
  builder. It does not fetch data, mutate frames or change decision/plan payloads.
- Confirmed pivots reuse the existing three-right-bar helper, with pivot and
  confirmation dates. Last six highs/lows in 140 observations and the prior
  20-observation high/low are explicit candidate levels. Current-close relative
  ordering determines support versus recovery barrier; broken lows above price
  are never claimed to remain support. No channel extrapolation or invented floor.
- A: observed recovery barrier, next higher observed price, lower invalidation
  reference and geometric ratio. B: lower structure breach and next lower observed
  level when present. C: between the observed boundaries, awaiting A/B. These are
  conditional observation prices, NOT approved entries, targets guaranteed to be
  reached, order prices, sizing, a short strategy or a validated win rate.
- The old execution-plan prices remain separately available. Source-close price
  conditions do not replace the original current-quote-derived plan/stop. This
  distinction is intentional, not a claim that those two plans are equivalent.
- Four axes now show actual source-close price structure, 20-observation range,
  5-observation mean true range / previous 20, volume contraction on that same
  non-overlapping window, consecutive observed closes below MA20, latest completed
  volume / previous 20 and source MFI. Zero volume is not missing. Missing volume
  does not erase available price structure. Contraction is not proof of accumulation.
- Reuse the existing selected-product quote evidence return value, no second
  request. Quote price, timestamp and session remain a separate reference. Even
  an observed outside-range quote is not labelled a confirmed daily breakout.
- Matched-date source-volume profile is computed from the same filtered frame.
  It is a range-allocation estimate, not actual market depth or net buying.
- Four-axis evidence is visible and A/B/C price conditions are compact tables.
  The full model is included in the private precision review export for later
  reproduction. No private account captures are committed.

## Replay

The user's completed SOXL export (11/19 source close 45.30) yields lower reference
40.59, recovery barrier 69.73 and next observed level 80.22. A's geometric ratio
is about 0.36R. This is deliberately NOT the earlier added-position R/R: its
reference trigger and structural failure level differ. This does not recommend
entering at 69.73 or holding until 40.59.

Latest completed volume / preceding 20 is 1.60047x, unlike the earlier inclusive
20-day denominator's 1.54620x. Both definitions are explicitly different. Mean
5-bar true range / prior 20 is 0.72966x while volume is 1.34908x: not simultaneous
price-range and volume contraction. Prior MFI is 32.5653; these are NOT live volume.

## Verification

- Baseline existing focused coverage: 132 passed, 4.54s.
- First expanded focused run: 195 passed / 1 failed, new test incorrectly expected
  the word KRW rather than the existing won symbol. Production currency code was
  unchanged. Corrected test: 196 passed, 5.25s. Additional integration tests added
  afterward cover quote position and production context/export wiring.
- No-network tests cover US/KR ticker formatting, missing and zero volume, short
  histories, malformed OHLC/indexes, missing calendar, stale source, vendor partial
  bars, same-date placeholders, future pivots, profile date mismatch, gate/plan
  immutability and separate quote evidence. Existing golden snapshots unchanged.
- Source-only evidence CPU check, 3 x 100 same-input calls: 6.360 / 6.689 / 6.318ms
  per call, mean 6.456ms. This excludes UI/profile rendering and is NOT a full-app
  speedup claim. No new external requests or TTL changes.
- Selected frozen gate: 2,025 passed, zero failures/errors/skips, 204.403s;
  source hashes unchanged (`cache/refactor_checks/all_whstmuow`). This includes
  the final quote-position/export-wiring tests and unchanged decision goldens.
  Selected contracts are not a full-repository, performance or strategy backtest.
- Quote normalization hardening: numeric strings are converted once before
  range comparison. Focused 161 passed; frozen selected gate then 2,028 passed,
  zero failures/errors/skips, 210.422s (`cache/refactor_checks/all_cjd4_y5l`).
- Export integration follow-up: the operating ZIP exposed a missing context
  allowlist entry, despite the production caller passing the new model. Added
  `scenario_analysis` to that list and an actual ZIP round-trip test (not merely
  an AST presence check), preserving source levels, axes and price rows without
  exposing private context keys. Focused scenario/export coverage: 209 passed,
  13.35s. Final frozen selected gate: 2,029 passed, zero failures/errors/skips,
  202.192s, unchanged source hashes (`cache/refactor_checks/all_0l8n78_0`).

## Operating Verification

- Code 883b4da6 and quote normalization d0569e9a pushed. Authorized Cloud reboot
  recovered from transient hot-reload import KeyErrors; this is not a claim that
  the deployment reload race is fixed. The next complete SOXL capture (16:36 KST)
  identified d0569e9a, no stale modules or restart requirement, and matching local,
  loaded and disk hashes for scenario evidence, scenario rendering and quote view.
- Actual A/B/C tabs and four axes checked at the existing narrow viewport. Prices
  and labels wrap, dollar signs are literal, and the original market defense and
  DCA block remain. A shows 69.73 / 80.22 / 40.59 / 0.36R; B shows 40.59 and no
  invented lower target; C shows 40.59-69.73 and A/B transition conditions.
- Source-close 45.30 and dated completed volume remain separate from the existing
  untimestamped scalar decision input and a separately timestamped day-market
  reference. The latter does not confirm a daily break or change the plan.
- The initial operating ZIP omitted the scenario model; fixed in 11ef6ecf. Do
  not describe the initial capture as containing this new context section.
- Final complete operating ZIP after the export fix identifies 11ef6ecf, no
  stale modules/restart requirement, and matching exporter loaded/disk hash
  (also matches the local source after Windows CRLF normalization). Its context
  and flattened CSV contain the full A/B/C observations, source date, four axes
  and measured numbers. Rebuilding evidence/prices from its captured daily OHLC
  reproduces them exactly with `read_csv(float_precision="round_trip")`, excluding
  the separately captured profile input. Default CSV float parsing had machine-
  epsilon differences, not changed displayed prices or plan logic.
- A second display run changed the live scalar/reference prices, as expected,
  while 11/19 source-close observations stayed 45.30 / 40.59 / 69.73 / 80.22.
  Ordinary GOOGL also rendered the same generic observation pathway; no SOXL
  numbers are hardcoded. Missing lower references remain missing, not invented.
- Hot deployment temporarily left the old assets body under a precision sidebar
  selection. Browser reload and selection restored the correct final screen.
  This does not demonstrate ordinary navigation-state persistence or fix the
  wider deployment reset issue; it is recorded, not folded into this change.
- Ignored local proof: `cache/operating_20261120/completed_scenario_axes.jpg`,
  `completed_scenario_A.jpg`, `completed_scenario_C.jpg`, and final B tab in
  `completed_scenario_axes_final.jpg`. No private ZIP committed.

## Limits and One Next Task

This completes the precision scenario input boundary, not the entire price-engine
audit. The original momentum/decision path can still use an un-timestamped scalar
quote; it was not silently replaced by the separate quote-evidence feed. Existing
A/B/C focus, market defense, final-check gate, position sizing and original plan
are preserved. Conditional price references require independent strategy testing.

Next: reconcile actual quote timestamp/completed-session identity in the shared
Today/board/precision decision input contract on identical captures, without
retuning thresholds or treating the local calendar date as a trade timestamp.
