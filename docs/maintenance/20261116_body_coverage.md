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
- Cross-review caught country-named cyber attacks, future attack plans, and
  employee requests mislabeled as shareholder requests. Narrowed to completed
  military-action claims, excluded cyber/planned actions, and retained a neutral
  request actor. Final related414passed/10.62s. Identical public paragraphs still
  produce the two intended attributed events. Commits6a48ec49/9103daeb pushed.
- Decision gate:1369passed/136.983s (`decision_itsdpjfs`); no golden updates.
  This gate preceded the last narration-only guard patch; final414tests cover it.
- Fresh pre-change operating baseline08:43KST: run
  `a43db6e261d04385bad83e8c5399bb7b`, normal77.706s, bodies1.964s.
  Eight/eight connected after new morning headlines replaced the old petition
  slot, but top-theme breadth remained limited. This is distinct from the00:17
  baseline; coverage must be compared by source/theme rather than success ratio.
- First operating check08:51KST (9103daeb):normal66.728s/bodies1.136s,
  eight/eight connected,112source hashes match, no restart required, report SHA
  matches. All95rows/23decision columns equal before/after generation and the
  original export. Rates gained a body, but geopolitics was still displaced by
  a fresh lower-volume single-company category. This was an observed limitation,
  not accepted as complete coverage.
- Follow-up72929b50 reserves candidates from the actual displayed top-five
  weekly themes before other categories. Reuses the existing dated/source-
  validated grouping with no new HTTP. Final related415passed/10.73s, including
  a crowded fresh-company versus high-volume-theme regression.
- Second operating check08:57KST (72929b50):the geopolitical theme was selected,
  but its newly published KEPCO analyst article read successfully without a
  supported interpretation. The other14geopolitical headlines were unsupported
  Google redirect links; the previous Iran direct-feed item was no longer in
  the displayed snapshot. Do not describe this as a new network failure.
- Original KEPCO public body identified the narrow omission: completed earnings
  falling below a "market estimate" was not recognized by the existing expected/
  consensus wording. Added only completed comparison forms, with forecast,
  denial and historical regressions. Public parser now returns attributed
  negative earnings evidence; no analyst forecast becomes official actual data.
  Extractor cache revision v12 invalidates old interpretation results while
  keeping6h/30s TTLs and eight-read budget. eb43939f pushed;420tests pass/10.94s.
- Final operating report09:06KST (eb43939f), run
  `c334506f23134575967d05a282e8e7f9`:normal, no degraded reasons,
  **76.469s generation /2.179s article phase**. Before77.706s/1.964s;
  news/caches changed between runs, so this is not a controlled speedup claim.
  Macro18.830s, prices23.603s, calculations1.061s, news2.087s,
  persistence8.918s and assembly19.790s.
- **112loaded/disk/Git hashes match**, `restart_required=false`; the downloaded
  summary+evidence reconstruct a report whose SHA matches its timing diagnostic.
  Both report tabs/downloads checked; screenshot evidence saved privately.
- **All95rows/23decision columns unchanged** from the original export and the
  immediately pre-generation export. No added/removed decision inputs.
- Eight selected articles:seven connected, one read but interpretation withheld.
  Rates and the KEPCO energy/earnings article now have body evidence. Top-five
  themes contain51headlines:4supported body rows,9not selected,37unsupported
  source links and1read/interpretation withheld; no access/identity/date failures
  in this displayed set. Selected-body totals differ because market wrap/other
  selected topics need not be among the displayed top-five themes.
- The remaining read/withheld item is a newly collected SK Securities KOSDAQ
  policy outlook. Direct public-body review confirmed conditional effects,
  unspecified timing and proposals, not an implemented policy/current price
  cause. It remains withheld; no attempt to turn opinions into completed events.
- Footer remains5passed/0failed/1unconfirmed, correctly disclosing partial
  headline coverage. News changed during the runs; no claim that all articles
  or all publishers are connected, or that seven reads verify every headline.

Private evidence directory: `cache/body_coverage_20261116`.
Final files use `after_` plus verification.json/operating_summary.png and
operating_evidence.png. `first_after_`/`second_after_` are earlier iterations.
Private originals and account exports are not in Git. Existing stash untouched.

## Remaining limits

Eight selected articles cannot cover every collected headline. Unsupported
publishers and restricted/failed bodies remain explicit, never replaced with
invented causes. Body verification establishes source identity and the quoted
claim; it does not independently establish the truth of that claim.

Next bounded task after this verification: the previously observed read-only
report/review-ZIP download rerun, without changing calculated outputs.
