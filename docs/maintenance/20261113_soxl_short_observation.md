# SOXL short observation isolation

Date: 2026-11-13. Immutable base: ae466e4e.

## Boundary

- Existing medium-term decisions, market defense, thresholds, daily inputs,
  allocations and execution plans are unchanged.
- SOXL precision panel only, opt-in query. No extra network work in today queue.
- SOXX is the primary observation. SOX, SMH and QQQ are context, not score inputs.
- Three modules: `soxl_short_data`, `soxl_short_observation`, `soxl_short_view`.

## Data and hypothetical plan

- Yahoo adjusted 60m OHLC, regular session only, last 59 calendar days.
- Existing exchange calendar: 09:30-anchored completed full hours. The final
  30-minute regular bar, incomplete bars, pre/post/daymarket and shortened-session
  partial bars are excluded. DST and holidays use the exchange schedule.
- All four symbols compare the same expected completed bar. Stale reference data
  is labeled as past data, without a fabricated change. No forward filling.
- SOXX missing, stale, malformed or gapped recent data cannot yield a plan.
- Existing confirmed-pivot parallel channel reused, without geometry changes.
- Entry reference is explicitly hypothetical latest completed SOXX close. Stop
  and target reference the same frozen channel lower/upper; 1R uses that entry.
- Outside/boundary prices hold the plan. 1R beyond the channel target is disclosed.
- SOXX prices are not SOXL order prices. No 3x price conversion, buy permission,
  automated orders, or validated strategy claims. An actual trade needs its own
  execution price, maximum loss and sizing; this panel does not supply those.
- Success cache 5 minutes, failure cooldown 30 seconds. Shared Yahoo lock wait
  capped at 5 seconds; download timeout 6 seconds per provider request.

## Verification

- Before: decision gate 1369 passed, 126.285 seconds.
- Initial after: decision gate 1369 passed, 132.252 seconds.
- Final focused suite: 127 passed, 31.70 seconds (26 new tests).
- All 820 existing top-level app function ASTs exactly match base; compile passed.
- Test runtimes are not production performance benchmarks.
- Local actual renderer: existing defense remains visible; all four live hourly
  series align to Nov 12 15:30 ET; outside-channel plan held, no invented levels.
- Local synthetic renderer: entry 101, stop 95, 1R 107, target 110, R/R 1.50.
  Synthetic values are labeled and confined to an ignored local preview.
- Final decision gate: 1369 passed, zero failures/errors/skips, 131.712 seconds.
  Evidence: `cache/refactor_checks/decision_03v_d_34`.
- Cloud verification: pending deployment below.

Private screenshots, quote outputs and preview files remain in ignored cache.
No account holdings, target weights or secrets modified.
