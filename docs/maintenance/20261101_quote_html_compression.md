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

Primary references:
https://docs.python.org/3.11/library/gzip.html
https://docs.python.org/3.11/library/urllib.request.html
