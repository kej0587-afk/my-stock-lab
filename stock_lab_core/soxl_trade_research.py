"""Compatibility facade: preserve the existing SOXL research contract exactly."""

from stock_lab_core import short_trade_research as shared
from stock_lab_core.chart_structure import build_parallel_channel
from stock_lab_core.soxl_trade_plan import RULE
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

execution_grid = shared.execution_grid
protective_exit = shared.protective_exit
summarize = shared.summarize
compare_policies = shared.compare_policies


def signal_rows(frame):
    rows = shared.signal_rows(frame, channel_builder=build_parallel_channel)
    return [dict(time=r["time"], formation=r["formation"],
                 soxx_stop=r["reference_stop"], soxx_upper=r["reference_upper"]) for r in rows]


def _legacy(trades, rejected):
    for trade in trades:
        if trade["reason"] == "reference_stop_next_open":
            trade["reason"] = "soxx_stop_next_open"
    return trades, {key.replace("reference", "soxx").replace("instrument", "soxl"): count
                    for key, count in rejected.items()}


def simulate(observations, soxx, soxl, slots, *, same_day=True, cost_bps=10, gates=None):
    rows = [dict(time=r["time"], formation=r["formation"], reference_stop=r["soxx_stop"],
                 reference_upper=r["soxx_upper"]) for r in observations]
    return _legacy(*shared.simulate(rows, soxx, soxl, slots, same_day=same_day,
                                    cost_bps=cost_bps, gates=gates))


def replay(frames, schedule, now):
    report = shared.replay(frames, schedule, now, reference="SOXX", instrument="SOXL",
                           rule=RULE, market_tz="America/New_York")
    if report.get("issue") == "기준/거래 종목 동시각 OHLC 미확보":
        report["issue"] = "SOXX/SOXL 동시각 OHLC 미확보"
    for policy in report["policies"].values():
        policy["trades"], policy["rejected"] = _legacy(policy["trades"], policy["rejected"])
    return report
