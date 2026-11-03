from copy import deepcopy

import pandas as pd

from stock_lab_core.market_guard_explanation import guard_basis_warnings, guard_explanation_lines


def test_delayed_input_is_exposed_without_changing_decision():
    guard = {"mode": "위험", "score": 12, "bench_df": [
        {"지역": "KR", "티커": "^KS11", "기준일": "2026-10-30", "최근수신봉": "2026-10-30"},
        {"지역": "KR", "티커": "069500.KS", "기준일": "2026-10-30", "최근수신봉": "2026-11-02"},
        {"지역": "US", "티커": "SPY", "기준일": "2026-11-02", "최근수신봉": "2026-11-02"},
    ]}
    before = deepcopy(guard)
    lines = guard_basis_warnings(guard, {"KR": "2026-11-02", "US": "2026-11-02"})
    assert len(lines) == 1
    assert "최신 수신봉 지연: ^KS11." in lines[0]
    assert "게이트 2026-10-30 / 리포트 정규장 종가 2026-11-02" in lines[0]
    assert guard == before
    assert lines[0] in guard_explanation_lines(guard, sessions={"KR": "2026-11-02"})


def test_equal_close_date_does_not_compare_against_intraday_or_weekend():
    guard = {"bench_df": pd.DataFrame([{"지역": "KR", "기준일": "2026-10-30"}])}
    assert guard_basis_warnings(guard, {"KR": "2026-10-30"}) == []
    assert guard_basis_warnings(guard, {"KR": "invalid"}) == []
    assert guard_basis_warnings(guard, None) == []


def test_missing_provenance_does_not_invent_a_delayed_provider():
    guard = {"bench_df": [{"지역": "KR", "티커": "^KS11", "기준일": "2026-10-30"}]}
    out = guard_basis_warnings(guard, {"KR": "2026-11-02"})[0]
    assert "지연 종목 특정 불가" in out
    assert "수신일 미확인: ^KS11" in out
    assert guard_basis_warnings({"bench_df": [{"지역": "KR", "기준일": None}]}, {"KR": "2026-11-02"}) == []
