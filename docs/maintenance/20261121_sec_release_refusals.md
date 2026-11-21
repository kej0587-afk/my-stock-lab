# SEC release validation audit — 2026-11-21

Started clean at `a791d693`; one bounded evidence/parser task.
Prior operating diagnostics counted 9/15 and 21/31 release-parser refusals,
but did not retain a reason histogram. Those historical counts cannot be
reconstructed exactly from function timings or the rendered coverage table.

## Fixed official evidence

Captured the same three submissions / primary 8-K / exhibit byte streams locally;
all nine requests returned HTTP200. Replayed before/after parsers offline with
fixed `2026-11-21T18:30:00+09:00`. Headers/contact details are not persisted.
Raw public bodies, hashes and results remain under ignored
`cache/sec_refusals_20261121/` rather than committing full releases.

| Case | Before | After / conclusion |
| --- | --- | --- |
| [MSFT exhibit](https://www.sec.gov/Archives/edgar/data/789019/000119312526436122/msft-ex99_1.htm) | `explicit_fiscal_quarter_unavailable` | Recovered FY2027Q1, released2026-10-28. The title has Q1 without year; a realized shareholder-return statement explicitly states FY2027Q1. Revenue/profit connect; CAPEX/FCF remain missing; guidance is deferred to the call. |
| [AAPL exhibit](https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/a8-kex991q4202609262026.htm) | `explicit_fiscal_quarter_unavailable` | Still withheld, now `release_dateline_unavailable`. The body identifies the fiscal quarter, but its initial announcement lacks a date. Filing, quarter-end, dividend and conference-call dates do not substitute for publication date. |
| [AMAT exhibit](https://www.sec.gov/Archives/edgar/data/6951/000162828026073360/exhibit991q42026earningsre.htm) | `release_issuer_mismatch` | Still withheld. Captured submissions name is `APPLIED MATERIALS INC /DE`, with `stateOfIncorporation=DC`; the headline uses Applied Materials. No guessed alias or blanket suffix stripping. Combined Q4/full-year headline is an additional unsupported shape, not fixed in this task. |

## Change and boundaries

- Existing accepted title-period path is unchanged. Only a year-less title with
  exactly one explicit ordinal quarter can consult short, non-table, realized
  body statements containing an explicit fiscal year. Require one unique FY/Q
  matching the title; reject forecast, comparison and outlook contexts.
- No quarter-end calendar inference, changed issuer validation, substituted
  publication date, carried-forward quarter, or invented metric. Ambiguous
  dated titles stay rejected. Existing score/decision inputs are not edited.
- Actual release-parser calls now export a fixed-vocabulary aggregate reason
  histogram. Cached failures are not counted as new parsing. Unknown exception
  text maps to `other_validation_error`; no URLs, bodies, contacts or issuer IDs
  enter those counters. Cache/TTL/deadline/request-rate/concurrency unchanged.

## Local verification

- 231 relevant earnings/discovery/reconciliation tests passed (18.03s).
- Selected report gate: 208 passed before47.936s (`report_o4ri9g_z`),
  after47.736s (`report_7_4lk6r9`). This is selected coverage, not all-suite/live QA.
- Existing cold/warm/failure/TTL-boundary collector fixtures: 9 complete outputs
  identical; exact request-argument multisets identical; zero network calls.
- Same three official input captures: only MSFT newly accepted; two remain
  withheld as above. New synthetic cases guard forecast/comparison/table-only,
  contradictory title/quarter, missing publication date and issuer suffix cases.
- `git diff --check` passed. Private inputs/results are ignored.

## Operating verification

Pending source push, owner reboot and completed report verification. Need a
fresh parser histogram and matching loaded/disk source hashes; do not infer
source freshness from the UI build label alone.
