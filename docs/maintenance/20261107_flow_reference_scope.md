# Flow-reference scope diagnosis and display clarification

2026-11-07 KST; base `3ec0137c`, clean and equal to origin before work.

## Finding

The four saved Cloud before/after cases do not show a changed common price-metric
formula. For all four,1D/1M/3M return, volume growth, flow score, price/volume dates
and timing are exactly equal. All20 exported OHLCV files (five per company) are
byte-identical before/after. The preceding acceptance already proved all28 core
score/decision comparisons identical. Full radar source frames were not exported,
so equality of every intermediate radar series/adjustment is not claimed.

The changed reference label is explained by candidate scope:

| Case | Standalone group/label | Radar group/label |
| --- | --- | --- |
|121600|종목 자체 흐름 / 관찰|스윙후보 / 스윙 후보|
|006280|종목 자체 흐름 / 관찰|회복추적 / 회복확인|
|092730|종목 자체 흐름 / 관찰|테마 주도주 · 회복추적 / 회복확인|
|003490|종목 자체 흐름 / 관찰|회복추적 / 회복확인|

`build_price_flow_row` calculates common metrics but deliberately does not perform
radar-universe ranking/selection. `build_source_flow_context` keeps the standalone
group. `build_today_flow_shortlist_df` assigns swing/recovery/theme groups and uses
the same `_flow_short_verdict` helper. That helper reads group and timing, not just
the common numerical flow score. Same-session radar context takes precedence in
`select_flow_fields`. This precedence and its veto handling are not changed.

Offline replay of the six actual verdict helper functions reproduced all eight
observed labels. Changing **only** the candidate-group field on the four standalone
rows exactly reproduced their radar labels. Thus a different price calculation or
missing earnings is not necessary to explain the observed discrepancy.

The seemingly disappearing6M return, acceleration, price level, current price and
state are omitted by `build_today_flow_context_df`'s explicit compact column list.
They are absent from the incoming snapshot rather than measured as zero/changed.
This task does not splice them back from another source or invent unavailable facts.

## Change and tests

Only `flow_connection_rows` display output adds `평가 범위` and `후보군`.
Standalone rows explain that radar candidate selection is not included; radar rows
identify classification/candidate/timing context. Unknown routes stay unconfirmed.
Existing verdict strings, numbers, scores, selection precedence, gates, thresholds,
DB/cache paths and the raw execution-workflow payload are unchanged. No added I/O.
The table is reused by precision/demo and exported through the existing serializer.

Focused contracts:156 passed before (22.52s),163 after (19.65s). Seven added cases
cover scope display, unknown/missing groups, unchanged input/gate, and identical
numeric context with different candidate groups. This is not a speed benchmark.
Final decision gate:1,334 passed, zero failures/errors/skips/source changes,
101.453s (`cache/refactor_checks/decision_sf6xc782`). No goldens regenerated.

Ignored diagnostic files: `cache/kr_flow_route_diagnosis.json`,
`cache/kr_flow_history_parity.json`, and the existing eight `cache/kr_rs_*` ZIPs.
Private account/export data are not committed. Public code/tests use representative
fixtures, not copied account records.

## Remaining boundary

The source distinction is useful evidence, not a new buy/sell judgement. A radar
wait label can still affect existing execution-gate behavior in other inputs;
the prior28/28 unchanged result applies only to the four observed cases.
Production display of the two new columns needs acceptance after deployment.
No broad refactor, automatic20-F scoring or Cloud DART transport recovery is claimed.
