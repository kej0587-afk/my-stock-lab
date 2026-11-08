# Official-bulletin retrieval overlap

2026-11-08 KST; baseline `44e5ba9f`, clean main synchronized before editing.

## Change and preserved contracts

The accepted Cloud generation `22bf0c2dc45b47538e96953665062f70` spent
7.456865s in apply_official_bulletins, within 21.098s macro/official and
56.778s total generation. Independent public CPI and Customs requests were serial.

Prefetch Customs in one worker while CPI remains on the owner thread, only when
exactly one row of each requires retrieval. Apply and persist CPI, then exports,
then dated manual fallbacks on the owner. Duplicate/ineligible rows keep the old
serial path. Providers, request parameters, retries, timeouts, TTLs, failure
cooldowns, latest-period/pending guards, source/vintage metadata, scores and gates
are unchanged. Network completion order can differ; shared caches retain locks.

Added fixed-label request/cache/collector/wait timing. bulletin_http overlaps the
existing economic_api counter for CPI/listing: do NOT sum both as unique HTTP.
Customs detail retries are now separately counted. Worker context propagates the
trace; worker totals can overlap owner wall time. No URLs/credentials are recorded.

## Verification

- Before: focused provider/regression tests 135 passed (2.84s).
- After: focused plus frozen-baseline parity/thread tests 158 passed (3.60s).
- Original `44e5ba9f` implementation compared against final full outputs, request
  multisets, persisted last-success bytes and unmodified inputs in 18 modes:
  cold/warm, pending/unflagged/supplied/wrong basis, complete/duplicate/single
  providers, newer/same period/source date, failures/rejection/cooldown, expired
  manual data and restored success. Tests also verify owner apply order, overlap,
  trace propagation, warm zero HTTP and unchanged cache bound.
- Decision gate: 1,367 passed, 140.489s; stable source hashes, no golden changes.
- Report gate: 207 passed, existing whole-app theme AST failure (46.23s pytest).
- Additional scope: 98 passed, two existing calendar Mock tests fail because the
  prior component timer requires __name__. Both reproduced with the baseline
  bulletin implementation (2.60s). Not a bulletin regression; left out of scope.
- Independent bounded review: no actionable findings.

Local live serial probe (not a Cloud benchmark): 4.682s total, CPI3.294s plus
exports1.388s; five actual HTTP attempts, both cache misses. Public endpoints and
existing parsers worked; local timing must not be presented as a Cloud speedup.

## Deployment and production comparison

Pending runtime commit/push and matched production run. Preserve the accepted
baseline and compare 95 Today rows, 11 news categories, 2/category, market RSS on,
stock RSS off, partly warm prices without clearing TTLs. Verify runtime hashes,
full dedicated generation JSON and matching Markdown, plus same-session score
parity. Separate total wall time from overlapping CPI/export collection and wait.

Private evidence is ignored under cache/: bulletin_* and refactor_checks/.
