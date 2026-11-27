from copy import deepcopy
from pathlib import Path

from stock_lab_core.soxl_observation_brief import observation_rows, price


def test_existing_plan_is_presented_without_mutation():
    context = {"session_active": False, "signal": False, "reason": "채널 이탈"}
    ready = {"label": "실행 보류", "reason": "시장방어"}
    plan = {"entry": 64., "stop": 55., "target": 73.}
    before = deepcopy((context, ready, plan))
    rows = observation_rows(context, ready, plan, "2026-11-25 16:00 ET")
    assert len(rows) == 7
    assert "64.00" in rows[1]["내용"]
    assert "55.00" in rows[3]["내용"]
    assert "73.00" in rows[4]["내용"]
    assert "시장방어" in rows[-1]["내용"] and "채널 이탈" in rows[-1]["내용"]
    assert (context, ready, plan) == before


def test_missing_plan_does_not_invent_prices_or_permission():
    rows = observation_rows({}, {}, None, "미확인")
    assert "미확인" in rows[1]["내용"]
    assert "유효한 SOXL" in rows[-1]["내용"]
    assert price(float("nan")) == price(float("inf")) == price(-1) == "미확인"


def test_phone_metric_css_does_not_force_nested_chart_columns_to_half_width():
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    selector = "[data-testid='stHorizontalBlock']:has([data-testid='stMetric'])"
    assert app.count(selector) == 2
    assert app.count(selector + ":not(:has([data-testid='stHorizontalBlock']))") == 2
