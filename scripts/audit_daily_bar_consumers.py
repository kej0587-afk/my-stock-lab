"""Offline comparison of saved precision inputs; never recalculates a trade grade.

Reads JSON/CSV only. Public price diagnostics are written separately from the
private review ZIP. Clock, price and input identity come from that capture.
"""

import argparse
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stock_lab_core.chart_structure import latest_completed_chart_session
from stock_lab_core.decision_engine import apply_live_price_with_indicators, build_rr_context, calc_atr_for_decision
from stock_lab_core.decision_inputs import prepare_decision_price_inputs
from stock_lab_core.report_evidence import closed_daily_frame, intraday_observation, price_observation
from stock_lab_core.scenario_evidence import build_scenario_evidence, completed_scenario_frame
from stock_lab_core.signal_input_contract import price_input_identity
from stock_lab_core.ta_engine import build_indicators


def clock_from_basis(basis):
    # This explicit KST suffix is written by build_signal_basis; no naive guess.
    parsed = datetime.strptime(basis["계산시각"], "%Y-%m-%d %H:%M:%S KST")
    return pd.Timestamp(parsed).tz_localize("Asia/Seoul").to_pydatetime()


def frame_summary(frame):
    if frame.empty:
        return {"rows": 0, "last_date": None, "close": None, "rsi": None, "atr": None}
    return {"rows": len(frame), "last_date": str(frame.index[-1].date()),
            "close": float(frame.Close.iloc[-1]),
            "rsi": float(build_indicators(frame.copy(deep=True)).RSI.iloc[-1]),
            "atr": calc_atr_for_decision(frame)}


def compare_frames(source, chart, *, ticker, decision, basis, saved_scenario, applied=False):
    """Re-use real consumers, holding the saved input clock and quote constant.

    This bounded replay covers source partial bars, not live-price overlays or a
    full scoring replay (external RS, financial and portfolio inputs are absent).
    """
    if applied or chart.get("LiveQuoteOnly", pd.Series(False, index=chart.index)).fillna(False).any():
        raise ValueError("Quote-overlay captures are outside this source-bar audit")
    identity = price_input_identity(source, chart, ticker=ticker, input_price=decision["cur_p"])
    if identity != basis.get("가격입력ID"):
        raise ValueError("Saved price input identity mismatch")
    now = clock_from_basis(basis)
    expected = latest_completed_chart_session(ticker, now=now)
    if not expected:
        raise ValueError("Completed exchange session unavailable")
    completed, status = completed_scenario_frame(source, expected)
    indicators = build_indicators(chart.copy(deep=True))
    prepared = prepare_decision_price_inputs(source, ticker, decision["cur_p"],
        build_indicators=build_indicators, apply_live_price_with_indicators=apply_live_price_with_indicators,
        _live_indicator_context=(indicators, False, ""))
    selected = frame_summary(prepared["df"])
    observed = build_scenario_evidence(source, expected)
    matches = {key: math.isclose(float(value), float(decision[key]), rel_tol=1e-10, abs_tol=1e-10)
               for key, value in {"rsi": selected["rsi"], "atr": selected["atr"],
                                  "cur_p": prepared["cur_p"], "regular_day_ret": prepared["regular_day_ret"]}.items()}
    sensitivity = {"scope": "same_quote_and_captured_target_only_not_a_new_decision", "available": False}
    if not decision.get("rr_target_is_projection") and decision.get("rr_target_source") == "차트 구조: 최근 내부고점":
        levels = {"int_high": decision["rr_target"], "ext_high": 0}
        current_rr = build_rr_context(prepared["df"], decision["cur_p"], levels)["rr_ratio"]
        complete_rr = build_rr_context(completed, decision["cur_p"], levels)["rr_ratio"]
        matches["rr_ratio"] = math.isclose(current_rr, decision["rr_ratio"], rel_tol=1e-10, abs_tol=1e-10)
        sensitivity.update(available=True, fixed_quote=decision["cur_p"], fixed_target=decision["rr_target"],
                           current_rr=current_rr, completed_bar_rr=complete_rr)
    scenario_match = (observed.get("asof") == saved_scenario.get("asof")
                      and observed.get("close") == saved_scenario.get("close"))
    report_frame = closed_daily_frame(source, ticker, now)
    intraday = intraday_observation(source, ticker, now)
    return {"ticker": ticker, "input_id": identity, "calculation_clock": now.isoformat(),
            "completed_session": expected, "saved_numeric_matches": matches,
            "saved_scenario_date_price_match": scenario_match,
            "decision_source": selected, "decision_quote": prepared["cur_p"],
            "source_bar_provisional_by_calendar": source.index[-1].date().isoformat() > expected,
            "scenario_completed": dict(frame_summary(completed), status=status),
            "report_completed_same_source": dict(frame_summary(report_frame),
                observation=price_observation(source, ticker, now)),
            "report_intraday_same_source": intraday,
            "saved_day_return_label": decision.get("day_ret_label"),
            "saved_day_return": decision.get("day_ret"), "rr_sensitivity": sensitivity,
            "limits": ["Same-source consumer replay, not a full report or grade generation",
                       "KR production report uses separate regular-price history; this ZIP cannot verify that capture",
                       "Completed means calendar cutoff; it does not certify a stale supplier bar was finalized",
                       "Hypothetical exclusion holds quote/target fixed; other scoring inputs are not replayed"]}


def audit_zip(path):
    raw = Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        sections = json.loads(archive.read("snapshot.json"))["sections"]
        ticker = manifest["selected_ticker"]
        if ticker != manifest["result_ticker"]:
            raise ValueError("Selected/result symbol mismatch")
        frames = []
        for label in ("daily_source", "display_chart"):
            entry = manifest["ohlcv"][label]
            frame = pd.read_csv(io.BytesIO(archive.read(entry["file"])), float_precision="round_trip")
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("_row_index")))
            frame.attrs = entry.get("attrs", {})
            frames.append(frame)
        context = sections["context"]
        result = compare_frames(*frames, ticker=ticker, decision=sections["main_decision"],
            basis=context["signal_basis"], applied=context.get("live_ohlcv_applied", False),
            saved_scenario=context["scenario_analysis"].get("completed_evidence", {}))
    result["capture_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Preserve existing output; choose a new path")
    with patch("socket.socket.connect", side_effect=RuntimeError("Offline audit: network disabled")), \
         patch("socket.getaddrinfo", side_effect=RuntimeError("Offline audit: network disabled")):
        results = [audit_zip(path) for path in args.captures]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    for row in results:
        print(json.dumps({key: row[key] for key in ("ticker", "input_id", "saved_numeric_matches",
                                                  "saved_scenario_date_price_match")}, ensure_ascii=False))
    if any(not all(row["saved_numeric_matches"].values()) or not row["saved_scenario_date_price_match"] for row in results):
        raise SystemExit("Replay mismatch; see diagnostic output")


if __name__ == "__main__":
    main()
