"""Replay saved public histories, adding only the repaired Block quote.

Requires ignored cache artifacts from the 2026-11-01 source audit; no network.
"""

import json
from pathlib import Path
import pickle
from time import perf_counter
from unittest.mock import patch

import pandas as pd

from stock_lab_core import money_flow as flow
from stock_lab_core.flow_snapshot import flow_source_date_rows, flow_source_issue_rows


ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = pickle.loads((ROOT / "cache/flow_io_overlap_20261101_after_sources.pkl").read_bytes())
    repaired = pickle.loads((ROOT / "cache/flow_symbol_repair_20261101_live.pkl").read_bytes())
    histories = {ticker: value[0] for ticker, value in baseline["histories"].items()}
    histories["XYZ"] = repaired["XYZ"]
    calls = []

    def history(data, ticker):
        calls.append(ticker)
        return histories[ticker].copy(deep=True)

    started = perf_counter()
    with patch.object(flow, "build_money_flow_universe_with_naver_rankings", return_value=baseline["universe"]), \
         patch.object(flow, "download_money_flow_prices", return_value=pd.DataFrame()), \
         patch.object(flow, "get_money_flow_ohlc", side_effect=history):
        etf = flow.calculate_money_flow_df.__wrapped__()
        theme = flow.calculate_image_theme_flow_df.__wrapped__("")
    elapsed = perf_counter() - started
    pd.testing.assert_frame_equal(etf, baseline["tables"][0], check_exact=True)
    assert etf.attrs == baseline["tables"][0].attrs

    keys = ["테마", "하위테마", "종목명", "Ticker"]
    common = list(baseline["tables"][1].columns)

    def unchanged(frame):
        value = frame.loc[~frame["Ticker"].isin(["SQ", "XYZ", "QRVO"]), common].copy()
        for column in ("기준일", "거래량기준일"):
            value[column] = value[column].fillna("")
        return value.sort_values(keys).reset_index(drop=True)

    pd.testing.assert_frame_equal(unchanged(theme), unchanged(baseline["tables"][1]), check_exact=True)
    assert "SQ" not in calls and "QRVO" not in calls
    assert calls.count("XYZ") == 1
    snapshot = {"flow_df": etf, "theme_flow_df": theme}
    summary = {"scope": "saved public histories; XYZ is the only newly supplied price series",
        "etf_exact_equal": True, "unaffected_theme_rows_exact_equal": len(unchanged(theme)),
        "rows": {"etf": len(etf), "theme": len(theme)}, "history_wrapper_calls": len(calls),
        "cpu_replay_seconds": elapsed, "source_dates": flow_source_date_rows(snapshot),
        "symbol_rows": json.loads(theme.loc[theme["Ticker"].isin(["XYZ", "QRVO"]),
            ["Ticker", "종목명", "기준일", "현재가", "돈흐름점수", "상태", "상장상태", "마지막거래일"]].to_json(orient="records")),
        "source_issues": flow_source_issue_rows(snapshot)}
    target = ROOT / "cache/flow_symbol_repair_20261101_replay.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "source_issues"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
