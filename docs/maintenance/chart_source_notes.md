# Chart Enrichment Helpers

Scope: pure calculations in `stock_lab_core/chart_enrichment.py`. No fetching,
Streamlit imports, composite scores, execution gates, or threshold changes.
The app renderer now uses these helpers; integration is summarized in
`20261018_market_report_chart_board.md`.

## Existing Logic Reviewed

- `app.py`: `build_liquidity_thermal_profile`, `_add_liquidity_thermal_overlays`,
  `render_precision_candlestick_chart`, `_derive_valuation_fields`,
  `build_valuation_fields_from_fin_meta`, and existing financial-score panels.
- `stock_lab_core/chart_patterns.py`: existing trendline and pattern helpers.
- `stock_lab_core/chart_execution.py`: existing execution guides and RVOL helper.
- `stock_lab_core/financial_score.py`: reused optional parsing/snapshot unwrapping.

The new profile adds volume-conserving range allocation, contiguous value area
and local HVNs. The existing close-distance thermal profile may attribute one
bar to multiple bins and can use unit weights when volume is unavailable.
Choose one profile overlay when integrating; do not stack competing POC/support
interpretations. Existing trendlines and financial scores remain the owners of
their respective behavior. Existing valuation enrichment should run before
passing already available `info` to the new snapshot helper.

## Provenance

- Supplied `Volume Signal` attachment credits mossst's modification of
  `MarketSmith Volumes`, copyright Fred6724, and names MPL 2.0.
  Original link: <https://www.tradingview.com/script/DRT8QZSp/>.
  The Python adaptation preserves attribution and an MPL 2.0 notice in its
  source file. License: <https://www.mozilla.org/en-US/MPL/2.0/>.
- Classification precedence and current-inclusive moving average follow the
  attachment. Backdated pivot labels, repainting recent peaks, and truncation
  are not included. All signal rows use current/past bars only.
- `Stocks: Dashboard Pro [invincible3]` has no known supplied license. None of
  its source, score thresholds, composite formulas, grades, layout, or styling
  is copied. Financial rows independently expose standard existing metadata.
- The volume-at-price implementation is independent of the supplied scripts.

## API

```python
from stock_lab_core.chart_enrichment import (
    build_volume_signal_series,
    build_volume_signal_tail,
    build_volume_at_price_profile,
    build_financial_snapshot_rows,
)

signals = build_volume_signal_series(ohlcv, timeframe="daily")
tail = build_volume_signal_tail(ohlcv, bars=5, timeframe="daily")
profile = build_volume_at_price_profile(ohlcv, bins=31, value_area=0.70)
financial_rows = build_financial_snapshot_rows(existing_info, is_etf=is_etf)
```

Inputs use chronological unique indexes and standard `Close`/`Volume` or
`High`/`Low`/`Close`/`Volume` columns. Unsorted/duplicate indexes raise
`ValueError` instead of silently shifting alignment. Inputs are not mutated.
Empty/missing data produces empty or unavailable output, not synthetic volume.

`signals` is an index-aligned DataFrame. Important columns are `volume`,
`volume_ma`, `rvol`, `buzz_pct`, `direction`, `up_volume_sum`, `down_volume_sum`,
`up_down_ratio`, `signal`, `color`, plus overlapping `is_*` conditions.
`tail` computes on full history first, preserving historical MA/record context.
The signal precedence is HVE > HVY > HVQ > POCKET_PIVOT > POWER > HIGH >
DRY60 > DRY20 > BASE. Zero-volume bars do not count as volume records.

HVE means highest in loaded history **through that bar**, not lifetime history.
HVY/HVQ use 252/63 daily, 52/13 weekly, 12/3 monthly bars. Extrema use available
history; short histories do not prove full-year/full-quarter records. MA uses
50 daily/monthly or 10 weekly bars by default and requires a complete window.
U/D sums also require a complete window. Direction uses previous close; flat
bars qualify as up for pocket-pivot eligibility but contribute to neither U/D
sum. Pocket pivots compare strictly against the previous N bars' largest down
volume, excluding the current bar. No down volume means an unavailable U/D
ratio. `rvol = volume / current-inclusive SMA`, so a valid final bar can revise
as incoming volume changes. Drop an unfinished bar when only closed-bar signals
are wanted. Dry labels mean long/short windows, default 60/20, in the supplied
bar timeframe. Overrides affect only annotations, never existing app gates.

`profile["rows"]` contains disjoint bins: `low`, `high`, `mid`, `volume`,
`fraction`, `intensity`, `in_value_area`. `poc` is one row; `hvn_levels` is a
volume-ranked list of local peaks. `value_area_low/high` are boundary prices;
`value_area_fraction` reports actual coverage, which may exceed the target.
POC ties choose the lower-price bin. Value area grows toward the higher-volume
neighbor, lower-price neighbor on ties. A flat HVN plateau is one node at its
midpoint. Constant-price history is one bin. Zero-range bars belong to exactly
one bin, including bars on bin edges. Missing/invalid/zero volume is excluded.
Lookback is applied before filtering, with `bars_used/excluded` reported.

This is a **daily-OHLCV estimate**, not actual exchange volume at each price,
an order book, a buy/sell-volume split, or proof of resting orders. It spreads
each day's volume uniformly across its high-low range, weighted by overlap.
The exact traded-price distribution is unavailable in daily bars. Profiles
describe the whole supplied window; for historical analysis pass
`ohlcv.loc[:cutoff]` to avoid using future bars. The returned `note` exposes
this limitation to the UI. Weekly/monthly inputs lose further intrabar detail.

Financial rows contain `key`, `group`, `label`, numeric `value`, `unit`,
`currency`. Missing/nonfinite values are excluded, while actual zero and
negative values remain. Fractional Yahoo-style ratio fields become percentage
points; explicit percent strings are already percentage points and are not
multiplied again. Percent strings in price/multiple fields are excluded.
Ambiguous `dividendYield` and `debtToEquity` units are not guessed.
Normalize provider fields upstream, especially values from mixed sources.
Monetary financial-statement rows prefer `financialCurrency`; price/market cap
use quote `currency`. Raw `info` and `{"data": info}` wrappers are supported.
No score is calculated or averaged. ETFs/ETNs/mutual funds (by `is_etf` or
`quoteType`) receive only price, trailing distribution yield, assets, NAV and
expense data when present. These are metadata snapshots, not historical
point-in-time financial statements. Display the existing cache's source/time
metadata alongside the table; do not backtest with today's snapshot.

## Plotly / Streamlit Integration

For a volume subplot on a separate y axis, the existing UI owner can add:

```python
fig.add_trace(go.Bar(
    x=signals.index, y=signals["volume"], marker_color=signals["color"],
    name="Volume", customdata=signals[["signal", "rvol"]].to_numpy(),
    hovertemplate="%{customdata[0]}<br>RVOL %{customdata[1]:.2f}<extra></extra>",
), row=2, col=1)
fig.add_trace(go.Scatter(
    x=signals.index, y=signals["volume_ma"], name="Volume MA",
), row=2, col=1)
if profile["ok"]:
    fig.add_hline(y=profile["poc"]["mid"], annotation_text="Estimated POC", row=1, col=1)
    fig.add_hrect(y0=profile["value_area_low"], y1=profile["value_area_high"],
                  fillcolor="gray", opacity=0.08, line_width=0, row=1, col=1)
    for node in profile["hvn_levels"]:
        fig.add_hline(y=node["mid"], line_dash="dot", row=1, col=1)
st.caption(profile["note"])
if financial_rows:
    st.dataframe(pd.DataFrame(financial_rows), hide_index=True)
```

This alternative example assumes a two-row `make_subplots(..., shared_xaxes=True)`
figure with price traces on row 1. The integrated renderer uses a separate lower
`y2` domain for volume; do not add a second duplicate volume pane or put raw
volume on the price axis. Export POC/value-area/HVN only as annotations. Do not feed this
estimate or these metadata rows into the existing trade gates or financial
score. The existing app RVOL helper has a shorter default window; label the
new volume panel's MA period so the two displays are distinguishable.

Focused verification: `.venv311/Scripts/python.exe -m pytest tests/test_chart_enrichment.py -q`.
