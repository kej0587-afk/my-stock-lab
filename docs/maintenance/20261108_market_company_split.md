# Market-first report and selected-company review

Base `8d53b10f`, clean main/origin after fetch. User superseded the previous
MSFT-only precision task: default market-wide report plus selectable held/watch
companies, with scoring unchanged and production verification.

## Scope

- Market collection no longer implicitly fetches MSFT SEC cash/IR packets.
  Market interpretation, story, materials and index/macro overview precede
  holdings impact and calendar. Existing market evidence and report exports
  remain; explicitly supplied legacy MSFT attachments are retained at the end.
- The Today briefing's market memo has separate Market/Company views. Company
  choices come only from current holdings/watchlist, deduplicated; ETFs/exempt
  instruments are excluded via the existing asset classifier. No default MSFT
  selection or automatic requests on switching companies.
- Explicit button loads one US SEC company (existing identity-checked eight
  quarter parser) or Korean company's existing financial provider. Results are
  owner/selection scoped, cleared before a failed refresh, and displayed with
  retrieval and period dates. Six-hour display freshness guard, no provider TTL
  change or score/database write. Download contains selected public evidence only.
- US review explains confirmed results, cash creation/investment implications
  and next observations, with missing/revision/period guards. Original financial,
  quality and filing tables remain available. No fabricated consensus, guidance,
  AI revenue, price causality or universal cash-exhaustion prediction.
- MSFT original reviewed Q4 and IR/call feature remains under an optional
  selected-MSFT expander. Other companies never receive MSFT facts.
- Korean path exposes actual source/period/missing data. Its current annual/
  quarter provider does not provide the same eight-quarter PP&E/outlook review.
  Cloud DART access failures are explicit; no Naver proxy labelled official DART.
  20-F/6-K-only issuers remain unsupported by this SEC quarter parser.

## Verification

- Baseline decision gate1334 passed101.573s (`decision_jsrvcmpo`).
- Existing source-flow/MSFT/cash contracts183 passed22.09s. Approved UI routing
  statements alone normalized in historical AST adapter; no golden regeneration.
- Focused selection/reading/MSFT contracts151 passed5.98s. AppTest verifies no
  request on selection, explicit query, company switch hides prior output,
  failed refresh clears prior data, owner isolation, GOOGL routed US and KR failure.
- Final decision1334 passed108.758s, stable source (`decision_p96dp6_s`).
  Report207 passed/one unchanged pre-existing theme-selection whole-app function
  assertion48.736s (`report_ats0dt7m`). No new failure/golden regeneration.
- Independent UI/scope review: no concrete issue. Live SEC AMZN/NVDA each8quarters
  verified; AMZN cash reading connected, NVDA cross-filing cash comparison held.
- Application `5d243918` pushed and accepted in authenticated Cloud, no reboot
  or stale-code warning. New market report08:22KST/generation `008e550fc604`,
  loaded hash `d34e05e0828d1df3`, matching code. Downloaded Markdown headings:
  basis/current status/interpretation/market story/materials/index-macro/holdings/
  calendar; zero MSFT-specific sections. Default mode is Market.
- Company view: actual held/watch selection AMZN, manual SEC query and JSON
  download succeeded. Ticker/CIK/currency/status/gaps and complete8quarter records
  equal independent local SEC retrieval. Why/next-check explanations and source
  table visible. Switching to NVDA hides AMZN heading/evidence until explicitly
  queried; returning to AMZN uses the selection-scoped saved result.
- Pre/post95tickers match; all14 core score/grade/verdict/gate fields equal
  (1,330 comparisons). No whole-ZIP equality claim. Private acceptance JSONs,
  original report/ZIPs/issuer packets and screenshots under cache/company_*.
- Live Korean query and Cloud NVDA query were not performed. KR failure routing
  covered by AppTest; NVDA live SEC evidence checked locally and selection switch
  checked in Cloud. Startup/report rerender delays persist; no full Today timing
  or numerical total-speed improvement claim.

## Next bounded task

Connect Korean selected-company review to existing owner-scoped imported DART
evidence when Cloud live access fails. Preserve original source/period labels,
raw records, existing score and decision paths; never call missing data zero.
