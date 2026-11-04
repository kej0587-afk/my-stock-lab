# Report interpretation audit: 2026-11-04

## Scope

Report-only policy catalysts, conditional article evidence, oil/bond provenance,
and cumulative investor-flow history. Trading thresholds, gates, allocation,
price anchors and existing macro scoring are unchanged.

## Evidence paths

- `today_news` retains the existing query budget and admits US election news
  without requiring a stock-market keyword.
- `article_context` still retrieves at most four allowlisted articles. One
  strategy/scenario article may take priority. `article_events` extracts complete
  qualified sentences, event subjects and explicit conditional scenarios.
- `report_policy_catalysts` renders source claims, not forecast sector winners.
  The verified policy-calendar JSON is a checked snapshot, NOT an automatic
  official-calendar collector. It records verification and expiry dates.
  Stale future official deadlines remain visible with a recheck warning.
- `report_context` adds BZ=F and ^TYX to the existing daily batch only. They do
  not enter live quote requests, rotation, macro scoring or decision gates.
- `report_energy_basis` compares existing reference/daily/scenario observations.
  It does not fetch settlement prices or invent rollover metadata/probabilities.
- `report_history` stores validated post-close public investor-flow observations
  in the existing owner-scoped payload. No new table or network request is added.
  Historical backfill is NOT connected. Missing sessions prevent exact 5/20-day
  sums and sign streaks. Today's intraday observation is explicitly provisional.

## Observed oil discrepancy

The public Yahoo query fixture was collected at 2026-11-04 10:39 KST:

| Completed 5-minute bar | Nov 2 | Nov 3 | Change |
| --- | ---: | ---: | ---: |
| 14:30 ET | 96.56 | 96.16 | -0.41% |
| 16:00 ET | 95.87 | 96.54 | +0.70% |

These are different endpoints. Neither is the CME 14:28-14:30 VWAP settlement.
The response named the current contract December 2026, but historical contract
mapping/rollover evidence was unavailable. This does not establish the cause of
every news discrepancy, and no price is forced to match report31.
See `tests/fixtures/report_energy_yahoo_20261104.json` for request URLs and values.

## Validation

```powershell
py -3.11 -X utf8 -m pytest tests -q -k "report or earnings or article or news or golden or public_market"
git diff --check
```

Regressions cover future/expired evidence, US/non-US attribution, qualified
scenario extraction, unchanged request limits, US meeting-date conversion,
settlement-window completion, data gaps/revisions/units, owner isolation and
history restoration. Cloud execution and live Supabase persistence still need
confirmation after deployment; local tests use injected stores.
