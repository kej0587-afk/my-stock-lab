"""Run existing bounded regression contracts without regenerating their baselines.

This is a local correctness gate, not a live-data benchmark or investment backtest.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SCOPES = {
    "decision": (
        "test_decision_golden_snapshot", "test_decision_refactor_parity",
        "test_decision_inputs_refactor", "test_decision_signals_refactor",
        "test_execution_context", "test_precision_final_check_view",
        "test_market_guard_input_quality", "test_monthly_rebalance_refactor",
        "test_final_check_extraction", "test_decision_governance",
        "test_channel_display_lifecycle", "test_execution_readiness",
        "test_precision_display_consistency", "test_precision_gate",
        "test_precision_plan_panel", "test_precision_workflow_review",
        "test_scorecard_review", "test_precision_chart_view", "test_precision_review_export",
        "test_portfolio_dashboard_bridge", "test_portfolio_connection_audit",
        "test_portfolio_holding_review", "test_dashboard_consistency", "test_dashboard_view",
        "test_portfolio_candidate_view", "test_portfolio_helpers", "test_portfolio_renderer_refactor",
    ),
    "report": (
        "test_report_section_contract", "test_report_split_quality",
        "test_report_nov6_regressions", "test_report_quote_direction",
        "test_report_close_boundary", "test_report_intraday_account",
        "test_report_reference_history", "test_report_news_session_quality",
    ),
    "prices": (
        "test_history_preload_overlap", "test_kr_preload_connections", "test_result_cache",
        "test_today_queue_performance",
        "test_price_batch_selection",
        "test_price_history_scope", "test_latest_price_cache_key",
        "test_price_cache_recovery", "test_money_flow_cache_replay",
        "test_today_quote_performance", "test_performance_log_audit",
    ),
}
BASELINE_FLAGS = ("UPDATE_SNAPSHOTS", "CREATE_DECISION_REFACTOR_BASELINE")


def test_paths(scope):
    groups = SCOPES.values() if scope == "all" else (SCOPES[scope],)
    return list(dict.fromkeys(["tests/test_refactor_check.py", *(
        f"tests/{name}.py" for group in groups for name in group)]))


def safe_test_env(environ):
    if any(environ.get(key) == "1" for key in BASELINE_FLAGS):
        raise ValueError("Baseline regeneration is enabled; refusing verification")
    env = dict(environ)
    for key in (*BASELINE_FLAGS, "PYTEST_ADDOPTS"):
        env.pop(key, None)
    env["STOCK_LAB_FORCE_AUTH_MODE"] = "public_demo"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def source_hashes(root):
    # Include fixtures/tests as well as production code; never hash secrets/caches.
    paths = [root / "app.py", root / "requirements.txt", root / "requirements-dev.txt"]
    for directory in ("stock_lab_core", "tests", "scripts"):
        paths.extend((root / directory).rglob("*.py"))
    paths.extend((root / "tests" / "golden").glob("*.json"))
    paths.extend((root / "tests" / "fixtures").rglob("*.json"))
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(paths)) if p.is_file()}


def junit_counts(path):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    return {"tests": len(cases), **{
        name: sum(case.find(tag) is not None for case in cases)
        for name, tag in (("failures", "failure"), ("errors", "error"), ("skipped", "skipped"))}}


def gate_passes(returncode, counts, changed):
    return (returncode == 0 and counts.get("tests", 0) > 0
            and not any(counts.get(key, 0) for key in ("failures", "errors", "skipped"))
            and not changed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=(*SCOPES, "all"), default="all")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--list", action="store_true", help="List selected contracts without running")
    args = parser.parse_args(argv)
    paths = test_paths(args.scope)
    if args.list:
        print("\n".join(paths))
        return 0
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        env = safe_test_env(os.environ)
    except ValueError as exc:
        parser.error(str(exc))
    missing = [p for p in paths if not (ROOT / p).is_file()]
    if missing:
        parser.error(f"Missing contracts: {missing}")
    parent = ROOT / "cache" / "refactor_checks"
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=f"{args.scope}_", dir=parent))
    junit = folder / "junit.xml"
    command = [sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
               f"--junitxml={junit}", *paths]
    before = source_hashes(ROOT)
    started = datetime.now(timezone.utc).isoformat()
    clock = perf_counter()
    counts, error, returncode = {}, "", -1
    with (folder / "pytest.log").open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.timeout)
            returncode = result.returncode
            counts = junit_counts(junit)
        except (subprocess.TimeoutExpired, OSError, ET.ParseError) as exc:
            error = f"{type(exc).__name__}: {exc}"
    after = source_hashes(ROOT)
    changed = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    passed = not error and gate_passes(returncode, counts, changed)
    outcome = dict(scope=args.scope, started_utc=started, passed=passed,
                   elapsed_seconds=round(perf_counter() - clock, 3), counts=counts,
                   returncode=returncode, error=error, changed_during_run=changed,
                   selected_contracts=paths, source_hashes=before,
                   limits="Selected correctness contracts only; not full suite, live UI, speed or investment validation")
    (folder / "summary.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(f"{'PASS' if passed else 'BLOCKED'}: {counts}; {outcome['elapsed_seconds']}s")
    print(f"Evidence: {folder}")
    if not passed:
        print((folder / "pytest.log").read_text(encoding="utf-8", errors="replace")[-8000:])
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
