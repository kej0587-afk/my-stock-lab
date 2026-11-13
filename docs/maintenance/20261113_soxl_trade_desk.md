# SOXL connected short-term research desk

## Scope and rule fixed before measurement

Separate observation/research only. No changes to daily scores, existing hourly
SOXX channel calculations, allocation, market defense or orders. No optimized
thresholds, inferred missing prices or probability of success at a quoted price.

`soxl-linked-v1`: 140 completed regular SOXX hours, prefix-only confirmed channel.
The signal requires a lower-channel touch and close back inside, with room for
SOXX 1R below the frozen channel upper. SOXL must have valid OHLC at exactly the
same signal hour. Its signal-bar Low is the independent protective-stop reference.
Entry proxy is the next scheduled regular SOXL Open, never the signal Close.
SOXX must still be inside with 1R room at the entry Open. SOXL target is actual
entry + (entry - frozen SOXL Low). No conversion of SOXX returns by three.

Exit on SOXL protective stop / 1R target, or on a completed SOXX hour below its
frozen lower followed by the next regular SOXL Open. Same-bar stop/target order
is unknown: count stop first. Gap stops use the worse opening price; favorable
target gaps use the target, conservatively. These OHLC proxies are NOT proven
fills; spread, queue priority and outages are unavailable. Costs: 10bp each side,
with a 20bp sensitivity comparison. Two policies, without selecting a winner:
same-day final regular bar Close versus up to 18 full hours with overnight risk.
Final partial hour can execute, never create an hourly signal. One position and
one entry per channel formation; missing paths are excluded and counted.

Five-minute prices are paired SOXX/SOXL completed regular bars only. Existing
SOXX 5m breach observation remains advisory, NOT a newly backtested entry filter.
No 5m stop-improvement claim from the previous five-trade matched sample.

Current panel distinguishes data failure, unmet technical setup, closed market,
and unchanged execution gate. Even when no signal, display independently valid
SOXL price scenarios as hypothetical, not entry permission. Manual entry changes
recompute one risk basis and explicitly have no price-specific historical rate.
Account/cash inputs are local scenario inputs only, default unset; no portfolio
write. Sizing includes configured adverse gap/slippage allowance and costs.
It is a maximum under assumptions, not a guaranteed loss cap.

Historical wins are descriptive, with sample count, interval, expectancy, worst
trade, MAE, close-equity drawdown, chronological halves, missing counts and cost
sensitivity. Full historical market-defense snapshots do not exist: no claim of
gate-filtered win rate. No zero-trade win rate and no current price probability.

## Verification / deployment

Implemented in separate plan/replay/view modules and wired only into the existing
SOXL precision expander. Daily decision functions and app.py unchanged. Live data
uses one batch for SOXX/SOXL/SOX/SMH/QQQ hours and one paired 5m batch. History
fetch/replay is explicit, success cache 24h; no today-queue background work.

Frozen input hashes are recorded in ignored `cache/soxl_linked_research/summary.json`.
2024-11-14 through 2026-11-12; same-day 64 trades/24 wins (37.5%), net mean
-0.5808%, worst -5.7198%; overnight 63/26 (41.27%), mean -0.5669%, worst -6.9202%.
The new protective-stop variant has no positive after-cost expectancy in this
sample. This is NOT the older SOXX-stop-only 63-trade study; do not mix results.
95% Wilson ranges 26.67-49.75% / 29.96-53.58%, descriptive, not current-price odds.
Matched 63 entries: day better 4, worse 8, max saved 9.624pp / forgone 5.236pp.
One unpaired entry is excluded from paired comparison. Missing SOXX/SOXL bars
14/15 are retained; no interpolation. Replay twice: 11.684s/11.641s, identical
outcomes; these are replay timings, not a full-app performance claim.

118 focused/research tests passed. Baseline decision gate 1369 passed/129.065s;
final decision gate 1369 passed/133.58s (`decision_2t10sr52`).
Local browser verified actual saved prices outside the channel still have a
separately labeled price scenario; synthetic 60/58/62 arithmetic; zero cash
zero quantity and cash-capped integer sizing. Real historical win rates remain
separate from the synthetic UI scenario. Production validation pending.
