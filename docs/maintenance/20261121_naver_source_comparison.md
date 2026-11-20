# Naver polling/basic comparison — 2026-11-21

Base: `f915d5ee`. This completes its HANDOFF comparison task. It does not change
production provider routing, caches, scores, labels, thresholds or daily-bar policy.

## Decision

Keep the current route. The two compared endpoints do not establish a replacement
that both preserves quote semantics and avoids one extra request per symbol.
This is not a claim that no other provider or bulk interface could ever work.
Unknown polling observation time remains unknown; further work can proceed with
that limitation recorded rather than repeatedly fabricating or repairing it.

## What was measured

Standalone `scripts/probe_kr_quote_sources.py` made **8 public HTTP requests**:
two rounds, each with one polling batch and three mobile basic calls. Phase order
was reversed on round two. Symbols: 005930.KS, 000660.KS, 379810.KS. All selected
responses said CLOSE; captures were collected locally on Saturday, 2026-11-21 KST,
for supplier records dated 2026-11-20. These were sequential requests, not an
atomic market snapshot, regular/NXT live validation or a Cloud timing benchmark.

| Round / order | Polling requests | Polling seconds | Basic requests | Basic sequential seconds |
| --- | ---: | ---: | ---: | ---: |
| 1 / polling then basic | 1 | 0.104416 | 3 | 0.284028 |
| 2 / basic then polling | 1 | 0.084633 | 3 | 0.268339 |

| Symbol | Polling nv = basic closePrice, both rounds | Basic session label | Basic supplier time (KST) | Separate polling NXT price/time |
| --- | ---: | --- | --- | --- |
| 005930.KS | 180,900 | afterMarket | 11-20 20:20:21 | 180,900 / 20:00 |
| 000660.KS | 1,100,000 | afterMarket | 11-20 20:20:23 | **1,099,000 / 20:00** |
| 379810.KS | 23,180 | regularMarket | 11-20 20:20:23 | absent |

Basic times are timezone-aware supplier fields, **not independently verified trade
execution times**. A regularMarket label next to 20:20 does not prove a regular
trade then. Polling has no own per-item observation time. Its response clock and
nested NXT quote cannot supply that missing time, especially when the values differ.
Equal root prices across these closed-session probes do not prove live equivalence.

Replacing one healthy polling batch covering 45 symbols with this basic endpoint
would structurally require 45 requests instead of one; that is a request-count
projection, not an actual 45-request speed measurement. Parallelism cannot remove
the request cost or prove price/session compatibility. No timeout was forced in
production and no failure cache or TTL was modified for this measurement.

## Supplier semantics reference

[Naver's official notice](https://help.pay.naver.com/faq/content.help?faqId=18245)
distinguishes regular closing price from the last price including the after-market
session, and identifies ETF/ETN exceptions. It is display/product documentation,
not a machine-readable contract for `nv`, `closePrice` or `localTradedAt`.
Do not infer these API fields' exact trading semantics solely from that notice.

## Verification and artifacts

- New offline diagnostic contracts: 15 passed. Equal/different prices, separate
  NXT values, missing/naive times, symbol mismatch, malformed states, input
  nonmutation, exact batch/basic costs, reversed order, single-attempt failures,
  explicit live opt-in and preservation of existing output are covered.
- Combined new + existing Naver/quote observation/prefetch contracts:
  **259 passed in 15.49s**. Synthetic fixtures perform no external requests.
- No app/core source edits. Same production scores and routing are preserved by
  leaving those sources untouched; no new all-stock live parity claim is made.
- Public raw captures and diagnostics remain ignored at
  `cache/operating_20261121/naver_source_comparison.json` and
  `naver_source_probe_stderr.log`; account exports and secrets were not used.
- Re-run with `.venv311/Scripts/python.exe -X utf8 scripts/probe_kr_quote_sources.py
  --live --rounds 2 --output cache/<new-capture>.json`. Existing output is refused.
- This commit contains a standalone diagnostic, tests and documentation only.
  No production UI change or reboot is required; the last direct operating
  verification is documented in [the prior record](20261121_naver_quote_observation.md).

See [the overall roadmap](ROADMAP.md). The one next task is a fixed-input audit
of final daily-bar usage, not an unproven provider switch.
