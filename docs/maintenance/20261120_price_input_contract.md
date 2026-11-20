# Price Input Contract and Same-Date ATR

## Scope

Today Check, dashboard and precision keep the existing decision engine, market
defense, thresholds and position-size policy. This is a bounded input audit, not
a trading-rule change or a completed migration of every price provider.

- Capture the source last OHLCV row before a same-date scalar quote overwrites it.
  ATR restores that captured row, then excludes quote-only placeholders. Without
  a valid captured source row (old exports, malformed OHLC), exclusion remains.
- Add a pure shared helper for source-row recovery and a price-input ID. The ID
  covers ticker, scalar quote, source/chart OHLCV and provisional-row flags; it
  excludes processing time, macro, portfolio and financial inputs. Equal IDs do
  not establish equality of the entire investment decision.
- Expose the ID, source date, ATR date/count, quote provenance and provisional
  calendar-date meaning in the three views and review ZIP. Never label a local
  calendar date as the provider's trade time or a completed session.
- Public-demo precision now shares one prepared indicator context between its
  chart and decision, just as the account precision path already does.
- No new external requests, TTL changes or replacement quote source.

## Reproduction

Private SOXL export (8), source 2026-11-19, 251 rows. For a controlled same-date
overlay at 41.91, the old quote-only filter also dropped the original last source
bar: ATR14 was 12.855000359671456 instead of 11.373572213309151. Recovery restores
the latter, equal to the captured source calculation. Next-date overlays preserve
the source result too. This is a replay, not a claimed live price or entry signal.

ATR-derived references may legitimately change for this bug. Investment thresholds
are not changed to force previous, erroneous stop/target references to survive.

## Verification

- Baseline focused contracts: 178 passed, 13.41s.
- New focused input/engine/ATR/basis/refactor contracts: 200 passed, 16.57s.
- Initial combined selected gate: 2,040 passed / 23 failed, no errors/skips,
  218.250s (`cache/refactor_checks/all_io5m0mtz`). Failures classified: 20 old mock
  signatures, two AST contracts missing the two reviewed provenance arguments,
  one historical full-output adapter expecting last-source-bar removal.
- Keep committed golden JSON unchanged. AST normalization asserts the exact new
  call before removing only its reviewed metadata arguments. Historical output
  comparison independently derives ATR and six affected references from original
  OHLC and asserts captured provenance; all other fields remain compared.
- Focused classification/adapters and input coverage: 77 passed, 47.95s.
- Final frozen selected gate: 2,063 passed, zero failures/errors/skips, 198.701s,
  unchanged source hashes (`cache/refactor_checks/all_nnjtiqzz`). This is selected
  correctness coverage, not the full repository suite or a speed/strategy test.
- Code 5de4b3f5 pushed and Cloud rebooted. Today Check completed in 88.3s;
  this is a single live run, not a like-for-like performance comparison.
- Actual Today export and precision SOXL ZIP contain the new basis fields.
  Dashboard detail column controls also expose the ID, quote provenance, date
  meaning and ATR date/count; its CSV download did not complete, so no claim of
  dashboard-export replay. Identical-capture tests cover the shared projections.
- SOXL source/ATR date is 2026-11-19, provisional indicator date 2026-11-20;
  unknown provider time/session remains explicit. Market defense and
  LEVERAGED_RECOVERY_DCA_BLOCK remain. Numeric A/B/C observation tabs still render.
- Live replay exposed a second audit bug: pandas 2.3.3 on Cloud hashes date indices
  in nanoseconds, whereas pandas 3.0.2/CSV replay locally can use microseconds.
  Identical OHLCV therefore had different IDs. Normalize only the hash index to
  nanoseconds; no prices, scores or dates in the calculation change.
- After normalization, the private Today quote 43.06 reproduces its price ID
  b29e7b96a7875f10, and precision quote 42.93 reproduces f342d1cf00b79a47.
  Precision ATR is 11.373572213309151, equal to its captured source calculation.
  Different live runs are not expected to share IDs when their quote differs.
- Additional unit-resolution and real ZIP round-trip coverage: 108 focused tests
  passed, 13.15s. Final frozen selected gate: 2,068 passed, zero failures/errors/
  skips, 206.966s, unchanged source hashes (`cache/refactor_checks/all_qeqywtsr`).
  Timestamp identity fix 1d9116cc pushed and Cloud reboot verified.
- Final operating SOXL export at 17:26 KST reports base commit 1d9116cc,
  restart_required=false and no stale modules. The helper's loaded/disk/local
  normalized-text SHA256 matches (3a054896487bf98062207c046940178d5fb192d20c858e79cb828e389e3f1830).
  Quote 42.77 replays ID 98546325ebb6bb46 exactly and ATR 11.373572213309151.
  LEVERAGED_RECOVERY_DCA_BLOCK and market defense remain.
- Actual A/B/C tabs after restart: A recovery 69.73 / next observed level 80.22 /
  failure 40.59; C observed range 40.59-69.73; B breach 40.59, no observed lower
  target invented. These are source-daily observations, not orders or a win rate.
  Local proof (not committed): `cache/operating_20261120/price_input_basis.jpg`,
  `price_input_scenario_a.jpg`, `price_input_scenario_c.jpg`.
- Hot-deploy briefly produced module-import KeyErrors before reboot. Reboot
  restored operation; this task does not claim that hot-reload problem is fixed.

## Limits and Next Task

The existing scalar loader still discards provider timestamp/session metadata.
The UI explicitly marks that limitation; a separately timestamped reference quote
is NOT silently substituted into decisions. Source rows restored for ATR are
original observations, not newly certified completed sessions. Vendor partial
daily bars still need a session-aware contract.

Next: carry provider timestamp/session through the existing scalar quote loader
without adding providers, then use it to audit partial-daily-bar inclusion across
the three views. Do not retune thresholds or infer missing timestamps.
