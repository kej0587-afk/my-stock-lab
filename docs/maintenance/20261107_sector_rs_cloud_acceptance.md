# Four KR sector-RS mappings: production acceptance

2026-11-07 KST; deployed base `b06916f8`.

## Actual workflow and results

Opened a fresh tab in the existing in-app browser after old-tab binding failed.
Authenticated production loaded normally; no reboot/login/security change needed.
Used the precision free-ticker mode with explicit Korean listing suffixes. Waited
for each **completed** result before downloading; partial renders/exports were not
treated as acceptance evidence. Saved four before ZIPs, ran the existing
`돈흐름 요약 새로고침`, then downloaded four completed after ZIPs in the same mode.
The refresh displayed `마지막 계산: 2026-11-07 21:57`.

The existing refresh function explicitly clears `get_auto_benchmark_info` and
benchmark-holdings caches. It also updates the flow snapshot; it is not an isolated
sector-only refresh and does not clear every price cache. No cold-cache performance
or external-request-count claim is made.

| Stock | Comparison ETF | Sector RS | Ratio-return change | RS date |
| --- | --- | --- | ---: | --- |
| 나노신소재121600.KQ | TIGER2차전지테마305540.KS | 강함 | +33.567044% | 2026-11-06 |
| 녹십자006280.KS | TIGER헬스케어143860.KS | 강함 | +11.670106% | 2026-11-06 |
| 네오팜092730.KQ | TIGER화장품228790.KS | 강함 | +22.822404% | 2026-11-06 |
| 대한항공003490.KS | KODEX운송140710.KS | 보통 | -1.176051% | 2026-11-06 |

These are20-session relative price-ratio changes, not standalone returns, cash
flow or percentage-point return subtraction. Production displays the first
benchmark as `2차전지` and the other three as ETF tickers. Dated provenance/proxy
limitations and source links are present in all four results (verification date
2026-11-07); the first source note identifies305540 explicitly.

All four RS values exactly match the preserved local production-loader calculation
within1e-10, and all sector labels/benchmarks/dates/values/provenance are unchanged
across the refresh. Local evidence previously verified both series end2026-11-06,
61 common sessions and20-session Close/Close comparison starting2026-10-08.
Cloud exports independently expose RS as-of and stock bar dates, not the full ETF
price frame; do not overstate this as independent exchange-level certification.

## Existing decisions preserved

For each ticker, seven before/after CSV sections are byte-identical:
`financial_inputs`, `candidate_grade`, `main_decision`, `final_check`,
`execution_readiness`, `entry_plan`, `workflow_display` — **28/28 comparisons pass**.
No automatic-financial-score, score-edit, holdings/account-save control was used.
No code, mapping, scoring threshold, label, TTL or golden file changed in this task.

All after exports identify build `b06916f8f1ddb981b372671591237a472cbf887e`,
`restart_required=False`, monitored `stale_modules=[]`.
This verifies one authenticated owner and same-mode precision sessions. It does
not compare registered mode against free mode or constitute a new95-row Today run.
No tests were repeated for the docs-only task; runtime evidence is the verification.

## Separate finding: flow-reference route changes

The entire `execution_workflow` export is **not** identical. After the flow-summary
refresh, its reference source changes from `종목 원자료 재사용` to `레이더 원자료`.
The reference flow label changes from `관찰` to `스윙 후보` for121600 and to
`회복확인` for the other three. Some flow metrics/metadata, names and calculation
timestamps also differ. The seven core sections and all sector RS fields above
remain unchanged. The cause of the flow-label difference is not established by
this task; period/price-basis/formula differences must be investigated before
calling it either correct or a bug. No values were forced to agree.

Next bounded task: trace only this four-case flow-source discrepancy using the
preserved snapshots, comparing input histories, periods, field semantics and
classification paths without changing scoring policy.

## Evidence

Ignored files: `cache/kr_rs_{code}_{before,after}.zip` (eight completed exports),
`cache/kr_rs_cloud_acceptance.json`, `cache/kr_rs_cloud_verified.png` and the earlier
`cache/sector_gaps_live_20261107.json`. Private exports/account context stay out of
Git. The verified tab is retained for the user. Publication is documentation only;
no app restart is required.
