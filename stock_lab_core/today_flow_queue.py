"""Existing auto-queue ordering and selection, separate from snapshot lookup."""
import re
import numpy as np
import pandas as pd


def select_flow_queue_items(shortlist_df, existing_items, limit, *,
                            normalize_ticker, sanitize_ticker_value, _flow_text,
                            sanitize_asset_name, is_fin_score_exempt_asset,
                            infer_asset_class_for_ticker, is_kr_listed,
                            sanitize_watchlist_item, UNCALCULATED_FIN_DEFAULT_SCORE):
    if not isinstance(shortlist_df, pd.DataFrame) or shortlist_df.empty:
        return tuple()

    existing_keys = {
        normalize_ticker(sanitize_ticker_value(item.get("ticker", "")))
        for item in (existing_items or [])
        if isinstance(item, dict)
    }
    picked: list[dict] = []
    seen_keys = set(existing_keys)

    def _auto_queue_priority(row) -> int:
        registered = _flow_text(row.get("등록상태", ""))
        group = _flow_text(row.get("후보군", ""))
        verdict = _flow_text(row.get("판정", ""))
        timing = _flow_text(row.get("타이밍", ""))
        joined = " ".join([group, verdict, timing])
        if registered and registered != "미등록":
            return 0
        if "스윙" in joined or "급등 포착" in joined:
            return 1
        if "회복" in joined:
            return 2
        if "고점주의" in group or "고점권" in timing or "추격금지" in verdict:
            return 4
        return 3

    work = shortlist_df.copy()
    work["_auto_queue_priority"] = work.apply(_auto_queue_priority, axis=1)
    if "돈흐름점수" not in work.columns:
        work["돈흐름점수"] = np.nan
    work = work.sort_values(
        ["_auto_queue_priority", "돈흐름점수"],
        ascending=[True, False],
        na_position="last",
    )

    for _, row in work.iterrows():
        if len(picked) >= int(limit):
            break
        ticker = sanitize_ticker_value(row.get("Ticker", row.get("티커", "")))
        key = normalize_ticker(ticker)
        if not key or key in seen_keys:
            continue
        verdict = _flow_text(row.get("판정", ""))
        timing = _flow_text(row.get("타이밍", ""))
        group = _flow_text(row.get("후보군", ""))
        flow_text = " ".join([verdict, timing, group])
        if re.search(r"관망|제외", verdict) and not re.search(r"눌림|추격|회복|스윙|장기|우선|주도", flow_text):
            continue

        name = sanitize_asset_name(row.get("종목명", ticker), ticker)
        is_etf = is_fin_score_exempt_asset(ticker, False, str(row.get("asset_class", "")), name)
        asset_class = (
            infer_asset_class_for_ticker(ticker, str(row.get("asset_class", "")))
            if is_etf
            else ("kr_stock" if is_kr_listed(ticker) else "us_stock")
        )
        picked.append(sanitize_watchlist_item({
            "name": name,
            "ticker": ticker,
            "is_etf": is_etf,
            "asset_class": asset_class,
            "fin_score": 0 if is_etf else UNCALCULATED_FIN_DEFAULT_SCORE,
            "bucket": "flow_candidate",
        }))
        seen_keys.add(key)
    return tuple(picked)


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
