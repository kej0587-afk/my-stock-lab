# Leveraged Product / Channel Audit

Base: `21428d1b`; 2026-11-13 KST. Scope: SOXL, RAM, BITX, 418660.KS.
No investment thresholds, DCA multipliers, channel anchors, basket membership,
order logic, TTLs or request budgets changed. No automated trades.

## Findings and Changes

- Cloud precision views inspected for all four products before editing. Their
  charts are fitted to each ETF's own prices, not SOX-derived target levels.
  Daily/weekly/monthly SOXL and BITX exported channel rails have constant width
  and an exact midpoint (maximum floating error 7.1e-15 / 2.84e-14). This checks
  geometry only, not predictive validity or a one/four-hour trading strategy.
- Product/proxy explanation extracted from the large panel into
  `leveraged_product_view.py`. SOXL targets NYSE Semiconductor Index daily 3x;
  SOXX is a same-index comparison, SOX is a different index. RAM targets DRAM
  daily 2x. BITX is futures-centered daily Bitcoin 2x, not IBIT 2x; BTC trades
  through weekends while the ETF does not. 418660 is synthetic Nasdaq100 daily
  leverage with currency/counterparty/session risks.
- Existing recovery average is an unweighted proxy basket, not the underlying
  index return. The view now discloses included rows without changing membership.
  BTC spot remains outside the existing BITX average. Existing 1/5/21-bar
  comparisons are labeled as such, with short-history and mixed-session limits.
- **Live data defect found:** UUP displayed about USD79.68 and +171.5% 1D in
  the BITX proxy table, contaminating its recovery mean. Public Yahoo UUP HTML
  reproduced old-parser USD79.72 from a recommendation script whose symbols
  were FXE/FXY/TBT/TLT/UDN, not UUP. The old 1800-character window accepted even
  quotes with no matching symbol. `overnight_quote.py` now parses JSON objects:
  symbol, price and timestamp must belong to the same object. Missing exact
  quotes fall through to the existing providers; no inferred/clipped price.
  Subsequent live UUP fallback returned USD29.42. Public HTML varies by request;
  regression fixtures reproduce the cross-symbol failure deterministically.

## Verification

- Decision gate before display extraction: 1367 passed, 132.683s.
- Final decision gate after parser fix: 1367 passed, 129.127s,
  `cache/refactor_checks/decision_xro2vs3l` (not an app speed comparison).
- Product renderer, parser, price and gzip transport focused tests: 106 passed,
  21.56s, including Streamlit AppTest and immutable valid-quote parity.
- Additional channel/watch/build/quote diagnostics tests: 196 passed, 25.16s.
- Prices gate before parser: 265 passed / 1 failed (43.045s); after: same
  265 passed / 1 failed (41.918s). Existing failure is the broad historical
  `test_kr_history_request_scope::test_all_app_functions_except_scope_wrapper_unchanged`
  covering unrelated older app refactors. Not hidden, not a full-suite pass.
- Historical display AST contracts normalize only the two known view changes
  against immutable 21428d1b; a mutation test ensures numeric edits still fail.
- The previous parser AST identity contract intentionally became valid same-symbol
  baseline parity: wrong-symbol behavior is an explicit, tested bug correction.
- Source provenance includes both new helpers.

## Cloud Verification

Code `5ed16cf3` pushed. After reload, all four precision views were freshly
queried and checked on 2026-11-13 about 13:05-13:08 KST; no manual reboot needed.
The new product tables, proxy explanations and own-price channel captions were
visible. SOXL/RAM/418660 retained market-defense execution blocks. BITX retained
recovery-before-DCA hold; its proxy UUP now showed USD29.42, not USD79.68.
BITX recovery average changed from +57.6% to -0.5%, checks 1/6 to 0/6, consistent
with removing a false positive input. These live samples differ in capture time;
they are not an immutable numerical parity or performance benchmark. Numeric
parity for unchanged logic is covered separately by the decision regression.
Private visual proof: `Downloads/leveraged_BITX_product_verified.jpg` outside Git.
No account holdings, targets or order instructions were changed.

## Official Product References

- https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs
- https://www.ishares.com/us/literature/fact-sheet/soxx-ishares-semiconductor-etf-fund-fact-sheet-en-us.pdf
- https://indexes.nasdaq.com/Index/Overview/SOX
- https://roundhillinvestments.com/etf/ram/
- https://www.volatilityshares.com/bitx
- https://www.volatilityshares.com/uploads/fund/4-17-How-BITX-Works-07312024.pdf
- https://m.funetf.co.kr/upload/FOK/gongsi/R2_K55301DQ3577_20240409.pdf

The TIGER-hosted PDF returned 403 to the browsing tool; do not claim full access
to it. Product mandate/currency references were checked against the prospectus.

## Remaining Boundary

No claim that quarter-channel bounces guarantee returns, that a multi-day ETF
return equals a fixed multiple, or that a daily recovery panel validates intraday
trading. Corrected input prices can legitimately change outputs; criteria remain
unchanged. Existing proxy returns can mix live quote and historical-bar sessions.
Exactly one next bounded task: attach verified quote/history timestamps to the
leveraged proxy comparisons, and test matched-session return endpoints without
changing the recovery basket or investment thresholds.
