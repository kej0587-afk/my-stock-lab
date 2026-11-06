# Yahoo chart connection reuse

## Scope and safety

- Baseline: `9e923a17`. Implementation: `91154660`.
- Only `get_all_summary` workers reuse Yahoo chart connections, through a
  calculation-local context. Each worker owns its Session; workers join before
  Sessions close. Nested scopes reuse the parent, separate runs do not share.
- No response/failure cache added. Every existing chart request still runs.
  URLs, query periods, timeout, JSON parsing, session selection and provider
  fallback order are unchanged. No investment threshold or formula change.
- Cookies are cleared between requests; public queries do not use netrc auth.
  TLS verification and environment proxy settings remain enabled. Requests'
  default adapter has zero automatic retries. Outside the scope the original
  urllib opener remains in use. An older hot-loaded prices module safely skips
  the optional scope until reboot instead of breaking calculation.
- Counters distinguish created/reused Sessions from actual requests; a reused
  Session is not claimed to be a cache hit or a guaranteed reused TCP socket.
- Verification: 1,379 selected regression tests passed, zero errors, failures,
  skips or source mutations. Evidence: `cache/refactor_checks/all_2c87fzjg`.
  Tests cover unchanged source selection, exact chart return/request parity,
  success/empty/bad JSON/timeout/401/429/500, thread isolation, cleanup, hot
  reload compatibility and real local HTTP keep-alive with changing responses.

## Live comparison protocol

- Same account selection and 96 calculated rows; 81 registered and 12 automatic
  flow candidates. Refresh-flow and flow-detail enabled on both sides. No
  portfolio settings or trades performed during verification.
- Standard refresh clears latest quotes/history wrapper caches, not all
  provider/financial caches. Compare first-run history misses separately from
  subsequent warm-provider runs. Live prices may change; deterministic tests,
  not live numeric equality, establish preservation of calculations.
- Before: first calculation 81.739s (`6bf56e6c`, 405 KR HTTP requests).
  Subsequent calculations 65.868s (`2b036eef`) and 63.690s (`50b75684`), mean
  64.779s. Both made 52 Yahoo chart requests and no KR history HTTP requests.
  Yahoo chart summed request times 36.938s / 17.694s; active-wall times
  16.590s / 12.830s. This variation precludes treating one pair as causal proof.
- Personal diagnostic JSONs and screenshots remain local, not in Git.

## Post-deployment evidence

- Cloud rebooted and verified `91154660` in downloaded build metadata. First
  calculation 106.462s (`ff025550`), 405 KR history requests, 66 Yahoo chart
  requests. Not comparable to the earlier 81.739s as a fully cold pair: analyst
  active-wall time alone was 8.676s versus 1.810s, with other provider variation.
- Subsequent identical-settings full calculations:

| Metric | Before run 1 | Before run 2 | After run 1 | After run 2 |
| --- | ---: | ---: | ---: | ---: |
| Full today calculation (s) | 65.868 | 63.690 | 66.202 | 66.470 |
| Including app entry (s) | 70.439 | 67.977 | 70.428 | 70.834 |
| Yahoo chart summed work (s) | 36.938 | 17.694 | 12.018 | 12.159 |
| Yahoo chart active wall (s) | 16.590 | 12.830 | 9.349 | 9.333 |
| Latest price active wall (s) | 20.726 | 16.274 | 15.434 | 14.584 |
| Actual Yahoo chart requests | 52 | 52 | 52 | 52 |
| Actual KR history requests | 0 | 0 | 0 | 0 |

- After IDs: `8b40667f` and `dce97ff5`. Each uses 6 worker-local Sessions with
  46 reuses, 548 prefetched-history hits, and zero recorded errors. The 96-row
  input counts and refresh settings match the before runs.
- Mean Yahoo chart active-wall time: 14.710 -> 9.341s. Mean full calculation:
  64.779 -> 66.336s (1.557s slower). The request segment is cheaper, but no
  end-to-end speedup has been demonstrated; unrelated work and network/CPU
  variation remain. Do not claim completion under 60s or subtract overlapping
  request work from full elapsed time. More parallelism was not added.
- Actual authenticated UI still shows 96 caution rows, no execution candidates,
  4 hard blocks (same post-holdings-update before screen). No order or holdings
  edits were made. Final timing card matches `dce97ff5`: 66.5s + entry 4.2s.
  Local screenshot: `Downloads/stock_lab_chart_connections_verified_20261106.png`.
