# Stock Lab Work Handoff

Updated: 2026-11-06 KST. Read this before continuing in a new chat or on another
computer. The current task is bounded performance work, not new market features
or investment-rule changes. Check Git for newer work before relying on this state.

## Resume Safely

1. Locate the `my-stock-lab` repository; a chat's working directory may be elsewhere.
2. Run `git status --short`, `git branch --show-current`, `git log -6 --oneline`
   and `git remote -v`. Preserve all local changes. Do not reset or overwrite work.
3. Fetch and inspect upstream. On clean `main`, use `git pull --ff-only` if needed.
   For dirty or diverged work, inspect and reconcile it first; do not force-pull.
4. Read this file and the two linked records below. Do not start by dumping all
   of `app.py` or by replaying the entire conversation.
5. Use the repository's installed Python environment. The last Windows checkout
   used `.\venv\Scripts\python.exe`; verify availability on the new computer.

Repository: `https://github.com/kej0587-afk/my-stock-lab.git`, branch `main`.
Production app: `https://3insky.streamlit.app/`.
Before this documentation-only handoff, HEAD was `26d005dc`; the deployed code
change was `91154660`. Use `git log` for the newer handoff commit itself.

## Completed Work

| Commit | Scope | Outcome |
| --- | --- | --- |
| `3329229e` | Cache/provider diagnostics | Distinguishes cache execution and actual requests; invocation counts alone are not HTTP counts. |
| `2834ff49`, `9e923a17` | History prefetch overlap and parity tests | Existing bounded KR workers overlap the overseas batch; inputs, periods, fallback order and calculation outputs preserved in tests. |
| `91154660` | Yahoo chart connection reuse | Calculation-local, worker-private Sessions; no new response cache, TTL change or extra concurrency. |
| `26d005dc` | Verification record | Records measured benefits and limits without claiming an overall speedup. |

Latest code changes are in `stock_lab_core/yahoo_chart_connections.py`,
`stock_lab_core/prices.py` and the connection scope in `app.py:get_all_summary`.
Older hot-loaded price modules can skip the optional scope until restart.
Tests cover exact request/return parity, errors, cleanup, worker isolation,
real HTTP connection reuse and the unchanged quote-selection body.

### Verification and Deployment

- `python scripts/check_refactor.py --scope all`: **1,379 selected regression
  tests passed**, zero failures/errors/skips/source mutations. This is not every
  repository test, not a live performance test and not proof of all live inputs.
- Code was pushed, Cloud rebooted, and `91154660` verified in downloaded build
  metadata. Authenticated live Today Check calculation completed without recorded
  errors. The final screen showed 96 rows, 0 execution candidates and 4 hard blocks,
  matching the pre-change screen for the then-current holdings.
- The last subsequent push, `26d005dc`, changed documentation only. This handoff
  also changes documentation only; no new runtime or UI validation is claimed.
- No orders, holdings edits, investment thresholds or data-basis changes were made.

### Measured Performance

Same account selection, 96 calculated rows, flow refresh and flow detail enabled.
These are two standard-refresh runs per version with provider caches warm:

| Metric | Before | After |
| --- | --- | --- |
| Full calculation, individual runs | 65.868s / 63.690s | 66.202s / 66.470s |
| Full calculation, mean | **64.779s** | **66.336s** |
| Yahoo chart active-wall time, mean | 14.710s | 9.341s |
| Actual Yahoo chart requests, each run | 52 | 52 |
| Actual KR history requests, each run | 0 | 0 |

**The quote segment became cheaper, but full calculation did not become faster.**
Do not claim a sub-minute result or subtract overlapping request durations from
the full runtime. The after runs used 6 Sessions and 46 Session reuses each;
Session reuse is not response caching or proof that every TCP socket stayed open.

First-load runs were 81.739s before and 106.462s after reboot. Their financial and
provider cache conditions differed; they are not a controlled cold-run comparison.
Network/CPU variation is material. Use fixed inputs for output parity, not equality
of live prices fetched at different times.

## Next Task Only

**Find and reduce one stage that determines full Today Check elapsed time.**
Do not assume price loading remains the limiting stage, or increase concurrency
without evidence. Inspect critical-path phases, sequential work and waits first.

1. Obtain a new complete timing JSON with the current code, holdings and options.
   Separate full calculations from render-only runs and Streamlit rerun exits.
2. Separate function invocations, actual HTTP requests, cache misses/hits, summed
   concurrent work and active-wall time. Include entry time separately.
3. Record 2-3 baseline runs with matching input/session/refresh/cache conditions.
   Keep first-load and warm-provider runs separate. Mark any provider failures.
4. Select just one measured bottleneck. Reuse existing helpers and tests; freeze
   affected outputs before extracting or optimizing. Preserve provider, adjustment
   basis, period, interval, session, observation time, TTL and failure fallback.
5. Run the relevant regression scope before/after, then the selected `all` gate.
   Do not edit sources during the gate or regenerate golden files to make it pass.
6. Repeat comparable full runs, inspect the actual authenticated screen and loaded
   build, and report all results, including no improvement or regression. Local
   synthetic timings cannot stand in for Cloud whole-calculation measurements.
7. Commit/push verified changes, verify deployment and update this handoff. If a
   measurement or UI check is blocked, name the blocker instead of claiming done.

Do not broaden this task to new news sources, features, financial guidance or
investment-rule changes. Do not repeat the completed connection optimization.
User authorization covers verified code commits/pushes; it does not authorize trades.

## Work Order After That

1. Compare held instruments across Today Check, the board, Precision Observatory
   and Portfolio Analysis using the same input snapshot. Check reference dates,
   decisions, execution plans and final checks. Separate legitimate differences
   in purpose/timeframe from actual contradictions; fix only verified errors.
2. Extract one large function in the inspected area after freezing its full
   outputs. Preserve scores, labels, amounts, share quantities, ordering and gates.
   Number of extracted files is not a meaningful completion percentage.
3. Review investment criteria separately once data and cross-view consistency are
   established. Propose score-overlap, leverage, cash and allocation-rule changes
   with evidence and tradeoffs; obtain approval before changing thresholds.

At each stage: one bounded change, regression evidence, actual UI verification,
commit/push, updated handoff and one clearly identified next task.

## Evidence and Privacy

- [Latest connection and timing record](docs/maintenance/20261106_yahoo_chart_connection_review.md)
- [Earlier review and bounded verification workflow](docs/maintenance/20261106_bounded_refactor_review.md)
- Latest local test evidence: `cache/refactor_checks/all_2c87fzjg/summary.json`.
  This ignored directory may not exist on the home computer; rerun verification.
- Full local timing IDs before: `2b036eef222a40bd8e97f8eb19c188e2`,
  `50b75684da7d4270942c7efc8ad23598`; after:
  `8b40667f507246959740cce0f7c0cfd2`, `dce97ff5993e46e78ef826b060026222`.
  Files were downloaded as `today_queue_<id>.json` in Downloads on this computer.
  Screenshot: `stock_lab_chart_connections_verified_20261106.png` in Downloads.
- Personal diagnostic files/screenshots are intentionally not committed. Do not
  assume they or browser login sessions are available elsewhere. Request fresh
  exports/login when needed; never ask for passwords or commit secrets/holdings.
- Use current holdings, not quantities or weights remembered from earlier chats.

## Keep This Handoff Current

Replace the current state after each completed step: actual commit, affected
files, preserved behavior, tests, comparable timing conditions/results, loaded
Cloud build/UI status, remaining issues and one next task. Keep older detail in
dated maintenance records rather than growing this entrypoint indefinitely.
