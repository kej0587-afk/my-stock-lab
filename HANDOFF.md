# Stock Lab Work Handoff

Updated: 2026-11-21 KST. Read before large source files or edits.
This is the current work order. Historical next-task instructions are superseded.

## Resume Safely

1. Inspect `git status --short`, branch, recent commits and upstream after fetch.
   Preserve home/company edits; never reset or force-pull. Fast-forward only when compatible.
2. Read AGENTS.md, this file and the latest bounded record. Installed home Python:
   `.venv311/Scripts/python.exe`; another computer may use `venv/Scripts/python.exe`.
3. Private exports/captures are ignored under cache or Downloads and may be absent
   elsewhere. Never commit credentials, account quantities or private reports.
4. Commit/push and necessary owner reboot are already authorized. Do not request
   permission again. Ask for direct authentication only when an actual UI requires it.
5. Finish one bounded task, verify, then update this file with exactly one next task.
   Keep output compact; do not start another broad task when unable to finish it safely.

Repository: https://github.com/kej0587-afk/my-stock-lab.git, branch `main`.
Production: https://3insky.streamlit.app/.

## Big Picture

[ROADMAP](docs/maintenance/ROADMAP.md) defines the sequence and exit criteria:
**data identity/period/session → cross-view consistency → market/company/account
explanation → measured performance → bounded large-function extraction**.

Quality, timing and account/execution limits answer different questions. The report
explains their evidence; it must not implement another scoring/permission engine.
Many shared helpers already exist. This is continuation, not a rewrite. Missing
supplier fields are explicit limitations, not a reason to block all later stages.
No score thresholds, decision labels, TTLs or trading permissions may be changed
under a behavior-preserving task. Investment performance validation is separate.

## Latest Completed Task

[2026-11-21 Naver route comparison](docs/maintenance/20261121_naver_source_comparison.md),
based on `f915d5ee`. New standalone probe and offline contracts; no application edits.

- Two local closed-session rounds: 005930.KS, 000660.KS, 379810.KS; eight HTTP calls.
- Polling: one batch, 0.104416 / 0.084633 seconds. Basic: three individual calls,
  sequential 0.284028 / 0.268339 seconds. This is not a Cloud speed comparison.
- Root prices matched in both rounds, but 000660's nested NXT price differed.
  Matching numbers do not prove the same session. Do not graft nested time onto nv.
- Basic has its own supplier timestamp but costs one request per symbol. This
  comparison does not support an equivalent, no-extra-request replacement.
- Retain current route. Live regular/NXT equivalence remains unmeasured.
- New diagnostic tests: 15 passed; combined Naver/observation/prefetch tests:
  **259 passed, 15.49s**. No production/core edits or live score recalculation.
- Delivery scope: standalone probe, tests and documentation only; no Cloud reboot
  required. The application source remains unchanged; check Git for the delivery hash.

The former 1,787-line handoff is preserved, unabridged, at
[HANDOFF_HISTORY_20261121.md](HANDOFF_HISTORY_20261121.md). It was copied before this
rewrite; its links retain their repository-root meaning. Read specific historical
records only as needed. Do not resume an older next task from that archive.

## Last Direct Production Verification

[Selected-quote observation record](docs/maintenance/20261121_naver_quote_observation.md):
production source `eb0af4a2`, documentation `f915d5ee`, owner Cloud reboot completed.

- Existing Naver basic evidence retains its own aware time/session; polling records
  source identity with unknown per-item time. Existing batch reuse preserves the carrier.
- Previous final selected-all gate: **2,466 passed**, zero failures/errors/skips,
  234.228s, `cache/refactor_checks/all_t0oang_2`. Not rerun for documentation/probe work.
- Operating Today: 95 rows, **106.065s**, completed measurement
  `c4cd1b65cb224e08ae4aefaee052ed76`; no stale tracked report modules.
- 45 domestic rows used untimed polling; 50 Yahoo rows retained chart timestamps.
  These 45 missing provider timestamps are not pending transport fixes.
- 379810 precision before/after: price 23,180, input ID `bf23c77900eefde6`, financial
  and technical scores, grade, decision code and gate matched. No global live guarantee.
- This was a normal refresh with potentially warm caches, not a fully cold run or
  proof of speed improvement. No new production calculation in the comparison task.

Private evidence: `cache/operating_20261121/`; Downloads
`stock_lab_review_export_20261121_0107.zip`, `precision_review_379810.KS (3).zip` /
`(4).zip`, `today_queue_c4cd1b65cb224e08ae4aefaee052ed76.json`.
The GOOGL precision `(34).zip` captured a regular-session partial daily bar,
input `e4f3a675caffbd4d`. Inspect availability before assuming a fixed replay exists.

## Next Task Only

**Audit final daily-bar treatment with fixed 379810.KS and GOOGL inputs.**

Trace actual included rows, session/price kind and calculation timestamps through
`calc_scores_and_decision`, the observation axes A/B/C and report presentation.
Reuse preserved captures and shared input contracts. Compare RSI/ATR/RR only where
needed to explain a discrepancy. Distinguish intentional purposes from inconsistent
input selection; do not assume one latest bar is correct for every consumer.

Deliver one compact per-consumer table and a reproducible fixed-input comparison.
If captures lack required data, collect only the missing input without overwriting
old evidence and state the limitation. This audit does NOT change partial-bar
exclusion policy, score weights, thresholds, labels or provider routing. Any
behavior-changing fix requires its own explicit scope/evidence. Do not broaden into
new report features or another speculative provider replacement in this task.

## Verification Discipline

- Use relevant existing contracts before/after edits:
  `.venv311/Scripts/python.exe -X utf8 scripts/check_refactor.py --scope decision`
  (or `report`, `prices`, `all`). Freeze sources while the gate runs.
- No golden regeneration to pass; old Nov-7 private baselines stay archived in
  `cache/historical_baselines_20261107/`, not restored over current caches.
- Compare remote requests/cache misses separately from calls; distinguish elapsed
  critical path from overlapping worker totals. Do not change TTLs to claim speedups.
- New diagnostic command and exact limits: latest comparison record above.
- Source architecture: [map](docs/20261104_architecture_refactor_map.md).
  Refactor procedure: [review](docs/maintenance/20261106_bounded_refactor_review.md).
