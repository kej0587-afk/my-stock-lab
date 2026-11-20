# Queue / Precision Price Plan Alignment

Base: a53885a1. Scope: shared reference-price construction and precision readability.

## Findings and Changes

- Ordinary precision plans said to wait when current R/R < 1 but still selected
  current price as the first entry. Queue selected the highest valid pullback.
  Precision now uses the same support selection for that ordinary branch. The
  first 1R reference follows the selected entry, not current price.
- Precision rounded R/R before comparing with 1 and 1.5. It now compares the
  unrounded ratio and uses the existing boundary-safe formatter. In particular,
  0.996 is not treated as 1.00, and 1.496 does not open the 1.5 allocation branch.
  These are intentional bug corrections, not new thresholds.
- Extracted support filtering/deduplication, three reference entries, and exits
  into `entry_prices.py`. Both views use it. No I/O, TTL, source-date, score,
  market-defense, final-check or allocation-policy changes.
- Dedicated leverage timing retains its existing rule (including allow-current
  with its own R/R conditions). Queue is a screening summary; it does not collect
  that extra context. Blocked queue rows intentionally hide entry references,
  whereas precision can show a clearly blocked conditional plan. These distinct
  roles are not advertised as identical execution permission.
- Precision no longer repeats all three tranche R/R values above the table.
  The allocation explanation remains available in a collapsed disclosure.
- A/B/C opens the scenario named in the summary first. Evidence is collapsed
  initially; its observations and limitations remain accessible. Removed a
  verbatim duplicate of channel-location text in the interpretation column.

## Verification

- Before changes: 225 focused tests passed (10.94s).
- Final focused run including review export: 340 passed (18.76s), including missing/nonfinite triplets,
  support spacing, current/pullback/1R coherence, R/R boundaries, preserved
  leverage timing, input immutability, and focus-first A/B/C presentation.
- Fixed-input historical comparison against a53885a1: 192 synthetic cases;
  full precision return payload and full queue return payload equal, inputs
  unchanged. Cases span scaling, held/unheld, pullback/current, projected/ordinary
  exits, available/missing supports, normal/scout R/R and leverage wait. The
  deliberate low-R/R/boundary fixes are verified separately, not hidden in parity.
  Local ignored harness: `cache/entry_price_parity.py` (no account information).
- An initial extended run found one isolated-AST test missing the existing
  `format_rr_ratio` dependency. The application already imports it. Added the
  real formatter to that test's namespace; expected values were not weakened.
- Final frozen preservation gate: 1,836 passed, 0 failed/error/skipped, 195.338s;
  source hashes unchanged (`cache/refactor_checks/all_wnf54wvy`). Selected
  correctness contracts, not the entire test suite. Final historical comparison
  rerun also passed all 192 cases. Operating verification: completed below.
- No overall latency improvement or validated trading edge is claimed.

## Direct Screen Audit

Pre-change authenticated SOXL had B focus but A selected, and its expanded
four-axis evidence pushed all scenario responses below the narrow viewport.
The same R/R and allocation explanations appeared in both header and table.

Commit 47935154 was pushed, then verified in authenticated production after an
authorized reboot. SOXL still shows market-defense / new-buy stop. B is initially
selected; switching to A shows the same first-entry and target references as the
original blocked plan. The allocation disclosure opens successfully. Proof is
local and ignored: `cache/operating_20261120/entry_price_alignment.jpg`.

Additional observed backlog, not changed in this task:

- Personal analysis, independent long-term assessment and hold-vs-cut panels
  repeat leverage recovery explanations. Their unique risk/valuation fields
  need an ownership audit before removing any section.
- Daily channel freshness was explicitly unconfirmed while an intraday quote
  was used. Keep the channel withheld until dates and completed-bar semantics
  are reconciled; do not draw a new support merely to fill the display.
- Stock Traders Daily and a Moomoo opinion were labelled earnings/IR in the
  precision news panel. This is not proof of actual earnings; generic news
  classification needs a separate regression, not an issuer-specific blacklist.

## Exactly One Next Task

Compare current quote, completed daily bar and channel/plan source timestamps
on the same saved inputs in Today and precision. Identify genuine stale/mixed
inputs versus intentionally separate sessions; fix proven errors without changing
investment thresholds. Keep the remaining panel/news backlog recorded above.
