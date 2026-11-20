# Naver selected-quote evidence — 2026-11-21

## What the actual responses contain

Read the existing polling and mobile basic endpoints for 005930 and 379810.
The polling object (`cd`, `nv`, `ms`) does **not** provide a per-instrument quote
timestamp in these captures. `result.time` is response time; the nested
`nxtOverMarketPriceInfo.localTradedAt` belongs to its separate `overPrice`.
Neither may be attached to the selected `nv`, even if the numbers happen to match.

The basic endpoint supplies `itemCode`, `closePrice`, aware `localTradedAt` and
`marketSessionType` in the same object. Captured 379810 price was 23,180 with
2026-11-20 20:20:23 KST / regularMarket; 005930 supplied 20:20:21 / afterMarket.
These are supplier-labeled quote times, not independently verified execution
times or evidence of a KRX regular trade at 20:20. No session is inferred from
the computer clock, `marketStatus=CLOSE`, or the exchange's nominal hours.

## Bounded implementation

`prices.py` attaches evidence; `quote_prefetch.py` preserves the selected carrier
in its existing batch scope. The helper is registered in precision build evidence. The existing float carrier keeps
same-symbol, same-object evidence for an unchanged selected numeric value.
Basic closePrice can carry the aware supplier timestamp and explicit session;
polling carries known provider identity with observation time/session unknown.
No response-level clock, neighboring symbol or nested NXT time is borrowed.

The legacy scalar regex still selects exactly the same number. If parsed JSON
cannot uniquely establish its identity/field, the number remains an ordinary
untimed float. Malformed metadata never discards a previously usable price.
Batch and dictionary paths retain their original numeric values/change fields.
No extra request, provider change, ordering change, cache TTL change, score/gate
change, private storage change or partial-daily-bar policy change is included.

## Verification

- Before changes: prices regression scope 533 passed, 53.746s;
  `cache/refactor_checks/prices_p6at1lmp`.
- Existing focused tests after initial wiring: 129 passed, 12.21s.
- Actual local basic and polling calls for 379810 both returned 23,180; basic
  retained its own 20:20:23 KST time, polling retained explicit unknown time.
- Focused combined tests after fixing batch carrier loss: **210 passed**, 15.12s.
- Final frozen selected-all gate: **2,466 passed**, zero failures/errors/skips,
  234.228s (`all_t0oang_2`); source/test hashes unchanged during the run.
  This is selected regression coverage, not a full-suite or speed benchmark.
  Non-string supplier session values retain valid time while session stays unknown.
- Production verification: pending.

Private raw captures and operating exports are ignored under
`cache/operating_20261121/` or Downloads. Do not commit them or replace regression
goldens with live prices. A live polling export remaining untimed is an honest
provider limitation, not a failed timestamp transport or a promise of 45 fixes.
