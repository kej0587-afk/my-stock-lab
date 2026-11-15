# Article-body coverage follow-up

Base: d54a8f73, 2026-11-16 KST. The user selected this bounded source-coverage
task ahead of the earlier download-rerun optimization. Clean main/upstream0/0;
the interrupted Customs stash was preserved.

## Findings and changes

- The prior operating report's one unconfirmed check meant partial coverage of
  many top-theme headlines, not one HTTP failure. Its eight selected articles
  yielded seven supported interpretations and one `no_supported_context`.
- Repeated issuer themes could exhaust eight slots before monetary/geopolitical
  topics. Keep primary top-three stories and explicit market-close coverage,
  then read one public candidate per uncovered named theme before repeats.
  Source ranking, materiality, caps, preview deduplication and fallback fill stay.
- Direct public publisher checks succeeded for the shareholder-request article
  and the Iran/Bahrain report. On identical saved paragraphs the previous
  extractor returned no event; the new extractor retains a leadership request
  or attributed conflict report. A request is not an appointment, a military
  claim is not independently confirmed damage, and neither implies a stock move.
- Detailed weekly sources now state each body's coverage category: connected,
  read but interpretation withheld, outside the selection budget, unsupported
  source, or access/identity/date failure. The connection check reports these
  separately instead of making omissions look like network failures.

No score, grade, gate, price, threshold, TTL, HTTP limit (eight articles/four
workers), provider whitelist, login or database changes. No paywall bypass,
Google redirect decoding, extra retry crawl or headline-to-body promotion.
Existing publication/modification, title identity and session guards remain.
Full public paragraphs used for the local comparison remain in ignored cache;
committed tests contain synthetic sentences only.

## Validation

- Before:286 related tests passed/8.26s.
- After:408 report/article/sector tests passed/10.82s, including selection
  diversity, no ninth fetch, requests versus decisions, denied/historical/
  conditional events, cyber versus military attacks and distinct coverage states.
- Decision gate:1369passed/136.983s (`decision_itsdpjfs`); no golden updates.
- Fresh pre-change operating baseline08:43KST: run
  `a43db6e261d04385bad83e8c5399bb7b`, normal77.706s, bodies1.964s.
  Eight/eight connected after new morning headlines replaced the old petition
  slot, but top-theme breadth remained limited. This is distinct from the00:17
  baseline; coverage must be compared by source/theme rather than success ratio.
- Post-deployment verification pending; do not treat local tests as live proof.

Private evidence directory: `cache/body_coverage_20261116`.

## Remaining limits

Eight selected articles cannot cover every collected headline. Unsupported
publishers and restricted/failed bodies remain explicit, never replaced with
invented causes. Body verification establishes source identity and the quoted
claim; it does not independently establish the truth of that claim.

Next bounded task after this verification: the previously observed read-only
report/review-ZIP download rerun, without changing calculated outputs.
