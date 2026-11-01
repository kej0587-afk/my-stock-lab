# Quote HTML Compression

## Scope

The completed production profile 999afd9de18d471bb3b1022c3d9f5067 showed
71 Yahoo overnight HTML requests, 56.20s work / 25.32s active wall, with
94.72s Today Queue / 112.63s total script elapsed across 95 calculated items.

Both existing quote-page callers now request Accept-Encoding: gzip and use
one small decoder in stock_lab_core/quote_html.py. The decoder undoes only
declared gzip/identity layers, then retains the existing UTF-8 errors=ignore
policy. Identity responses remain supported. No magic-byte guessing, body
truncation, new cache, cache TTL, concurrency or dependency changes.

URL, headers other than compression negotiation, 8s timeout, parser, price
freshness checks, provider ordering, stale-value rejection, grades and
decision wording are unchanged. Malformed/unsupported content does not
produce a quote: the existing outer error/fallback paths remain in use.
Authentication, account data and persistence are not changed.

## Public Transport Probe

Four local public requests, identity then gzip for each symbol:

| Symbol | Identity Wire Bytes | Gzip Wire Bytes | Gzip Decoded Bytes |
| --- | ---: | ---: | ---: |
| GOOGL | 836746 | 155987 | 837124 |
| SOXX | 800622 | 180572 | 856950 |

All returned HTTP 200. Gzip wire size was about 19-21% of its decoded size.
These were separate dynamic pages, not byte-identical server snapshots;
request latency is not a controlled Cloud speed benchmark. Tests replay the
same identity bytes and compressed bytes to assert identical parser input
and prices. The larger reduction in bytes is not an app-wide speedup claim.

## Diagnostics And Provenance

quote_html_body measures body read, decompression and UTF-8 decoding; the
existing caller timer also includes connection/header wait and parsing.
wire_bytes/decoded_bytes, gzip_response/identity_response counters contain
only sizes and fixed provider labels, never bodies, URLs or ticker names.
Wire bytes count successful reads even if decoding subsequently fails;
decoded bytes count only after successful content-encoding processing.

The new module keeps an immutable copy of its actual import-time source
record. A missing registry entry can be restored from that captured copy,
not by reading current disk code and calling it loaded. Existing registered
hashes are never overwritten. Direct and cached-name-list metadata paths
still flag changed disk files, including when the registry is missing.

## Verification

- Decoder tests: 68 passed (identity, gzip stacks/members, invalid UTF-8,
  errors, single reads, counters, timing, no cache and source immutability).
- Related decoder, wiring, provider, cache, summary and decision tests:
  234 passed, before the final missing-registry/changed-disk case was added.
- Import-snapshot restoration and changed-disk checks: 3 passed.
- Price parser AST is identical to b5e0c722. Provider-body comparison against
  5a859433 allows only the explicitly tested gzip transport and existing
  diagnostics additions; choice conditions and return paths remain fixed.
- Final full suite: 5309 passed, 1 skipped, 18 subtests passed in 266.78s.
  The first full run exposed one obsolete source-registry expectation;
  it now permits the new actual import snapshot while still asserting that
  every pre-existing account source entry and hash remains unchanged.

## Production Source Check

The completed GOOGL precision export captured at 2026-11-01 13:12:28 UTC
reported base commit 028eaf3d, restart_required=false and no stale modules.
The actual loaded hashes for app_entry, prices, quote_html and leveraged_watch
matched local LF-normalized source. This is a source-record check, not proof
that the new decoder was exercised by the subsequent calculation.

## Production Measurement Before Reboot

Completed calculation 8c3d30cf8b1e4d7fb6e8802c5be53d43, captured on
2026-11-01 at 13:16:53 UTC, calculated the same 95 items (81 registered,
12 auto-flow candidates, full-flow refresh enabled). Both profiles declare
standard_refresh_not_fully_cold with quote/frame resets and possibly warm
provider history, analyst and financial caches.

| Metric | Prior 999afd9d | New 8c3d30cf |
| --- | ---: | ---: |
| Today Queue elapsed (s) | 94.72 | 85.90 |
| Before Today Queue (s) | 17.77 | 0.67 |
| Full script elapsed (s) | 112.63 | 86.66 |
| Overnight requests / responses | 71 / 71 | 71 / 71 |
| Overnight summed work (s) | 56.20 | 39.35 |
| Overnight active wall (s) | 25.32 | 19.75 |
| Price frames active wall (s) | 17.89 | 20.41 |
| Analyst enrichment elapsed (s) | 9.93 | 3.00 |

The new profile has no quote_html_body timer or wire/decoded/gzip counters,
despite 71 actual overnight responses. Therefore this is NOT accepted as
production proof of gzip activation or a compression speed benchmark.
Source records alone are insufficient to explain the missing call evidence.
A Cloud reboot and fresh complete calculation were requested before making
that claim. The warmer entry and analyst paths also confound total elapsed.

No fresh price source has been removed and no TTL changed to improve timings.
The saved timing screenshot is quote-gzip-pre-reboot-timing.png; it shows a
completed run only, not verified transport activation.

## Production Verification After Reboot

After the user confirmed a Cloud reboot, calculation
c8bc9b90748d4b77b00d04651a3bd3e5 completed at 2026-11-01 13:26:00 UTC
on f1a5c50d. It retained 81 registered / 95 calculated / 12 auto-flow
candidates and full-flow refresh. Status was completed, calculation_completed
and is_full_today_queue_measurement were true. No stale sources were reported.

This run actually exercised the decoder: 73 overnight requests, 73 responses,
73 gzip responses and 73 quote_html_body calls. No measured decoder failures
or instrumented HTTP error/429/timeout events were recorded. This is transport
evidence; it does not certify the freshness/accuracy of every data provider.

- Encoded response body bytes: 14,966,673.
- Decoded body bytes: 69,996,193.
- Encoded body was 21.38% of decoded size, a 78.62% reduction. These counters
  exclude HTTP headers, TLS and connection overhead, so are not total traffic.
- Body read/decode: 23.29s summed work / 15.74s active wall.
- Full overnight caller: 49.51s summed work / 25.94s active wall.
- Today Queue: 103.41s; before Today Queue: 17.21s; full script: 120.75s.

This was the first calculation after reboot, not a verified fully cold
benchmark. It was slower overall than the pre-reboot 85.90s observation.
Neither that difference nor the byte reduction is claimed as an app-wide
latency improvement. The prior missing decoder evidence was resolved after
reboot, but the exact cause of the old in-memory call path was not proven.

Related decoder/wiring tests rerun after the reboot request: 91 passed in
15.92s. No runtime code changed during this verification. Saved screenshot:
quote-gzip-post-reboot-first.png.

### Repeated Full Refresh

Calculation 60d1fd4e717e4dbba37e347d8fbf796b completed at
2026-11-01 13:28:24 UTC on the same f1a5c50d code. Input counts, full-flow
refresh and declared cache-reset policy matched the first calculation.
Both completed calculation flags were true; no measured failures, stale
sources or instrumented transport error/429/timeout events were recorded.

| Metric | First After Reboot | Repeated Refresh |
| --- | ---: | ---: |
| Today Queue elapsed (s) | 103.41 | 60.51 |
| Before Today Queue (s) | 17.21 | 17.00 |
| Full script elapsed (s) | 120.75 | 77.63 |
| Overnight requests / gzip responses / body calls | 73 / 73 / 73 | 56 / 56 / 56 |
| Encoded body bytes | 14966673 | 11625442 |
| Decoded body bytes | 69996193 | 54216568 |
| Body size reduction (%) | 78.62 | 78.56 |
| Overnight active wall (s) | 25.94 | 18.80 |
| Body read/decode active wall (s) | 15.74 | 12.83 |
| Flow refresh elapsed (s) | 19.86 | 7.70 |
| Analyst enrichment elapsed (s) | 9.52 | 2.97 |
| Multi-timeframe pack active wall (s) | 21.90 | 17.19 |

The repeat is not a controlled A/B speed comparison: provider/analyst caches
were warmer, chart requests fell from 144 to 106 and overnight requests fell
from 73 to 56, despite matching declared refresh policies. Compression
activation and body size reduction are verified; an app-wide causal latency
gain is not quantified. The one-minute goal is not met for the full button
workflow (77.63s), nor strictly for the measured calculation itself (60.51s).
Saved screenshot: quote-gzip-post-reboot-repeat.png.

Next measured targets are current-price wait, multi-timeframe indicator work
and the 17s pre-Today path. Timings overlap, so they must not be added. The
661 load_price_df calls in the repeat took 5.75s active wall, versus 21.56s
for 701 calls in the first run; call counts are not external request counts.
Existing exact-period frame reuse and TTL/source-order semantics should be
retained when investigating those paths.

Presentation follow-up: the pre-run previous-calculation download caption
still showed the first 103.4s record while the completed detail showed the
new 60.5s record. Verification and downloads used the detail's explicit
60d1fd4e measurement ID, not that earlier caption or a last_attempt file.

Primary references:
https://docs.python.org/3.11/library/gzip.html
https://docs.python.org/3.11/library/urllib.request.html
