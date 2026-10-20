import json

from scripts.audit_report_performance import audit, measurements_from_log


def test_log_parser_skips_other_and_malformed_lines():
    data = {"measurement_id": "a" * 32, "elapsed_seconds": 132.5}
    log = "\n".join(["WARNING provider failed", "Today queue performance: malformed",
                     "INFO:stock_lab.performance:Today queue performance: " + json.dumps(data)])
    assert measurements_from_log(log) == [data]


def test_render_only_json_cannot_be_mistaken_for_full_calculation():
    report = "점검 측정ID " + "a" * 32
    rerender = {"measurement_id": "b" * 32, "elapsed_seconds": 2.1,
                "functions": [{"category": "phase", "name": "market_guard", "failures": 0}]}
    result = audit(report, rerender)
    assert not result["measurement_ids_match"]
    assert not result["is_full_today_queue_measurement"]


def test_same_report_full_trace_lists_nonoverlapping_main_phases():
    data = {"measurement_id": "a" * 32, "measurement_status": "completed",
            "functions": [{"category": "phase", "name": name, "failures": 0}
                          for name in ["today_queue_render", "flow_refresh", "summary", "stock_signals"]]}
    result = audit("점검 측정ID " + "a" * 32, data)
    assert result["measurement_ids_match"]
    assert result["is_full_today_queue_measurement"]
    assert [row["name"] for row in result["main_phases"]] == ["flow_refresh", "summary"]
