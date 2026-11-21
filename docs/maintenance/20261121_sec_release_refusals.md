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
- Previously accepted parser cases: 14 complete outputs identical (7 title
  period forms /2 synthetic issuer names), zero network calls.
- Same three official input captures: only MSFT newly accepted; two remain
  withheld as above. New synthetic cases guard forecast/comparison/table-only,
  contradictory title/quarter, missing publication date and issuer suffix cases.
- `git diff --check` passed. Private inputs/results are ignored.

## Operating verification

Source **`2ac2d94b`** pushed; owner Cloud Reboot performed directly. Completed
report `3d4dd44113a04b259ac4d4c7bba38e0d`, **120.6717s**, normal generation path.
18 checks passed: report/diagnostic hash, loaded/disk/Git-blob hashes for four
modules, no stale modules, matching counter totals, expected issuer outcomes,
and unchanged Nov20 SOXL regular-close return -31.83%.

| Actual release-parser outcome | Calls |
| --- | ---: |
| accepted | 9 |
| release_issuer_mismatch | 6 |
| explicit_fiscal_quarter_unavailable | 3 |
| release_dateline_unavailable | 2 |
| result_heading_unavailable | 1 |

The21 actual calls /12 caught refusals reconcile exactly; cached failures are
excluded. MSFT official FY2027Q1 /Oct28 appears in the detailed evidence table;
AAPL remains withheld for publication date and AMAT for identity. This does
not prove all remaining rejections correct or all financial fields connected.

Discovery23.5768s; release parsing0.850s. SEC68 requests/68 unique identities;
DART2 requests/1 unique identity, reflecting the **existing bounded retry**.
SEC rate-wait active13.197s (worker-overlapping sum30.308s); DART setup10.047s.
Report exclusive macro44.572s /prices30.315s /calculations1.199s /news2.033s /
article bodies2.323s /persistence13.148s /assembly27.083s. These are not comparable
controlled before/after speed measurements; no performance improvement claim.

**New operating limitation:** DART corporate directory setup raised
`connect_timeout` after both existing attempts. Report explicitly withholds31
domestic issuer connections; a normal generation path does not mean every
provider succeeded. No zero/default financial values or extended TTL were used.
This was outside the SEC parser change and was not modified speculatively.

Private evidence: `cache/sec_refusals_20261121/` contains the three fixed-source
captures/manifests, before/after replay, accepted/collector parity, report(47),
matching auto_report JSON,18-check audit and `operating_msft.jpg`. UI left on
the expanded detailed company earnings table.

## Next bounded task

Audit the DART corporate-directory `connect_timeout` and existing last-success
fallback on fixed failure/reboot inputs. Determine whether a valid snapshot
existed and why it was/was not reused; preserve issuer validation, TTLs, request
rate/deadline and scores. Only repair a demonstrated availability defect, then
verify in production. Remaining SEC alias/combined-quarter shapes stay recorded.
