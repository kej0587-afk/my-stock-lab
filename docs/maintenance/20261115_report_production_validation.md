# Production report coverage validation — 2026-11-15

Started on clean main at 9f95190f; fetch confirmed 0/0 divergence. No company
edits or preserved Customs stash were applied, discarded or overwritten.
This task validates coverage commit 50551641; it does not change scoring,
thresholds, investment labels, source precedence or cache lifetimes.

## Browser and deployment

Reconnected the supported in-app browser. Production was authenticated;
Cloud initially required GitHub sign-in. The existing Google account sign-in
completed GitHub authentication and exposed the owner's 3insky Reboot menu.
Clicked Reboot and confirmed its disruption dialog. Observed the temporary
startup page and subsequent authenticated app recovery with no calculated
Today result in the new session. No browser safety bypass or credential access.

Before reboot, a newly generated report already proved that all tracked loaded
modules matched disk: base 9f95190f, restart_required=false, stale_modules=[].
The matching downloaded Markdown hash equals diagnostic output_sha256.
Reboot was therefore performed as requested, not claimed as a missing-code fix.
The completed post-reboot report again has restart_required=false, no stale
modules, base9f95190f and matching output SHA256. The pre-reboot loaded source
hashes match all108 committed Git blobs; compare Git blobs rather than raw
Windows files because CRLF changes byte hashes without changing source code.

## Measured runs

| Run | Today full calculation | Report generation | Notes |
| --- | ---: | ---: | --- |
| Pre-50551641 baseline | 78.2 s | 58.269 s | 62070e9d8d4f45089f56ff86e6621ed4 |
| Coverage code, before requested reboot | 83.9 s | 64.038 s | 8ff86d8d9d034fea83da33a85209755e |
| Coverage code, after requested reboot | 113.5 s | 66.952 s | 159a4617664c43c4871a1b0ef6d74720 |

Same 95-item count and report settings: market RSS on, all eleven categories,
two/category setting, watch RSS off. No cache clearing or TTL change. Persistent
cache warmth, network latency, current source responses and account inputs are
not controlled; the elapsed difference is not evidence of an algorithmic
speedup or regression. Function cumulative time must not be added to wall time.

Exclusive report wall time before requested reboot:

| Stage | Baseline (s) | Coverage run (s) | After reboot (s) |
| --- | ---: | ---: | ---: |
| Macro / official / flow evidence | 22.608 | 19.371 | 20.128 |
| Price lookup / alignment | 14.910 | 14.522 | 15.237 |
| Close indicator calculations | 1.095 | 1.439 | 1.135 |
| News RSS / classification | 1.850 | 2.077 | 2.065 |
| Article bodies / interpretation | 0.044 | 0.762 | 1.188 |
| History persistence | 3.269 | 9.224 | 9.686 |
| Report assembly | 14.494 | 16.642 | 17.513 |

These stage names describe the existing instrumentation boundaries, not proof
that assembly is pure formatting or that every provider request is counted.
Post-reboot pre-generation script work was21.175s; script entry through saved
report was88.127s, excluding subsequent browser rendering. The last partial
screen-rerun26.4s is not the report generation time and must not overwrite it.
Both generated reports completed via normal path with no degraded reasons.

## Decision preservation

Downloaded Today master immediately before and after automatic report creation.
All 95 rows agree on 23 score/decision/gate/grade columns. Only quantity string
formatting (one row, numeric quantity identical) and analyst-query timestamps
(six rows) differ elsewhere. Thus report creation did not alter the observed
decisions. This is separate from a fixed-input historical regression gate.
No source/test edits this task; reuse the already recorded stable decision
1369-pass and focused report 281-pass evidence for 50551641 rather than rerunning
them to claim additional confidence. The pre-existing report whole-app AST
failure remains recorded, not hidden or repaired by changing goldens.
Repeated comparison after reboot also passed all95 rows/23 columns, both across
the reboot and before/after the final report. The final report and same-run
generation diagnostic were downloaded along with corresponding Today ZIPs.

## Coverage against the user's examples

| Check | Observed result |
| --- | --- |
| Reading order | Macro -> indices -> KR -> US -> portfolio/replacement -> sector rotation -> schedule |
| Broad sector comparisons | 9 -> 29 rows; now includes non-technology sectors, source dates and market-relative returns |
| Earnings catalysts | 5 -> 7 issuers; revenue/EPS/guidance are no longer displaced by cash-only details |
| Added observations | Russell2000, US natural gas (USD/MMBtu), DXY (points); 30Y/10Y daily changes in bp |
| KR flow | Investor and program flow separately tabulated; no program/institution aggregation |
| Main closing summary | Morning-only KR rally no longer asserted as the reason for the negative close |
| Appendix | One collapsed detailed-evidence expander; original full evidence retained in Markdown |
| Existing decisions | Same 95 rows and 23 score/decision columns before/after report generation |

**Coverage is not yet equivalent to the supplied examples. Do not mark report
quality complete simply because the new code loads and more rows appear.**

Concrete remaining defects observed in the real output:

1. PPI actual/previous values were collected in the economic appendix, but
   release_at was missing. The freshness filter correctly refuses to invent a
   release day, so PPI disappears from the main recent-release section. Repair
   official release metadata upstream; do not hardcode dates from the examples.
2. The US representative-stock return table is absent. KR has only a TDF ETF
   under an unconnected sector. The renderer cannot create prices it was not
   supplied; an ETF must not be treated as evidence of issuer breadth.
3. Main text expanded from 196 to 348 lines. Title-only article mentions grew
   from 10 to 113 (mentions, not unique events). Bank recycling/service promotion,
   historical profiles and generic valuation articles dilute the relevant news.
   Distinct important events must remain, but unconditional display-all is not
   a replacement for materiality selection and event deduplication.
4. A Fed Williams headline is labeled finance, and a Korean semiconductor issuer
   appears in the US brief. A Nov13 06:02 KST US closing headline is attached to
   the Nov13 US session, although that local timestamp precedes that session.
   A generic session label is insufficient; distinguish prior close, intraday,
   closing wrap and next-session material before synthesis.
5. The US closing wrap supplies only a short PPI-related body fact. NVIDIA
   succession/regulation, AI financing and Fed financial-stability material are
   partly present as titles, but the causal chain and follow-up checks remain
   generic. More headlines do not prove comprehensive event-body coverage.
6. 2Y Treasury, European gas, option positioning/gamma/0DTE and KOSPI night
   futures still lack complete numeric connections. No proxy or user-example
   value has been substituted. Missing consensus stays missing.

The final post-reboot report retains the same findings (347 main lines,
29 sector rows,7 catalyst issuers,112 title-only mentions). No PPI release day
was fabricated to make the acceptance check pass. On the narrow browser view,
the macro table still requires considerable vertical scrolling and its source
column extends horizontally; visual readability is not certified as complete.
Saved the fully rendered20:30KST report screenshot after the running overlay
cleared. The production report tab is retained; the authenticated Cloud tab is
retained for continuation.

## Private evidence

Ignored cache/report_coverage_20261115/production contains before/after Today
ZIPs, generated Markdown, matching generation JSON and machine-readable
verification. Do not commit account reports, position amounts, screenshots,
login state or credentials. Public-source facts above describe what the app
displayed; they are not an independent certification of all market statistics.
Final files: reboot_after.md, reboot_after_timing.json,
reboot_before_report_review.zip, reboot_after_report_review.zip,
verification_after_reboot.json and report_reboot_verified.png.

## Next bounded task

Repair PPI official release-date linkage so the already collected current
release reaches the main recent-indicator table with a verified publication
date and unchanged values/periods. Test missing/stale/future dates and verify
the main report in production. Other observed quality defects remain queued;
do not mix scoring redesign or broad optimization into that fix.
