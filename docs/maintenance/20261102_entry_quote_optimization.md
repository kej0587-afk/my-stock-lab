# Entry Initialization Timing

## Baseline And Scope

The verified 95-item repeated refresh 60d1fd4e717e4dbba37e347d8fbf796b
recorded 17.00s before Today Queue, 60.51s queue and 77.63s full script.
The first post-reboot calculation was 17.21s / 103.41s / 120.75s.
Neither profile attributed the pre-queue wait to individual entry tasks.

The first change adds a separate PerformanceTrace around the existing
initialization block: macro, events, settings, holdings, dividends, monthly
records, FX, holdings valuation and portfolio total. The same calls execute
in the same order and scope. UI, authentication, DB reads/writes, decisions,
source precedence, cache TTLs and price fallbacks are not changed.

Each Today attempt retains that same run's entry trace in entry_initialization
and the remaining uninstrumented before_today time in other_before_today_seconds.
The existing measurement ID and completed-vs-partial retention behavior remain
unchanged. The timing panel includes an entry-phase table for that report,
not the newest unrelated render's entry snapshot.

## Verification Before Measurement

- Entry business AST is identical to 7e67afba after removing timing wrappers.
- Live/demo stubs preserve calls, values and session-state keys/frames.
- Interrupted entry calls retain their exceptions and restore trace context.
- Timing panel includes the new table and retains the previous full result.
- Focused entry/performance tests: 26 passed in 23.23s.

## Optimization Boundary

The US batch quote loop and holdings display-price override are serial in
the baseline. Parallelizing them blindly can lose Streamlit session context,
change cooldown admission, or remove the independent display-source override.
No batch value is substituted for a display quote, and failed quote retries
are not memoized away. Further changes require the actual entry profile.
