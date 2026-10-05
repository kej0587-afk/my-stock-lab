import pandas as pd

from stock_lab_core.execution_gate import (
    GATE_EXECUTABLE,
    GATE_WAIT,
    apply_execution_gate_columns,
    build_execution_gate,
    classify_sector_rs_state,
    classify_upside_state,
)


def test_execution_gate_blocks_low_rr_without_changing_final_read():
    row = {
        "티커": "AMD",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "실행메모": "분할 가능",
        "R/R": "0.42",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "R/R 0.42 < 1" in gate["게이트근거"]


def test_execution_gate_waits_when_rr_target_is_projection():
    row = {
        "티커": "NVDA",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "R/R": "2.00",
        "R/R성격": "투영상단",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "투영상단" in gate["게이트근거"]


def test_execution_gate_waits_on_weak_sector_rs_for_buyish_row():
    row = {
        "티커": "MU",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "R/R": "1.40",
        "섹터RS": "🐢약함",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "섹터RS 약함" in gate["게이트근거"]


def test_execution_gate_allows_clean_buyish_row():
    row = {
        "티커": "AAPL",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "R/R": "1.45",
        "섹터RS": "🚀강함",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_EXECUTABLE


def test_apply_execution_gate_columns_adds_quality_states():
    df = pd.DataFrame([
        {
            "티커": "LITE",
            "유형": "개별주",
            "판정분류": "buyish",
            "최종읽기": "✅정밀확인",
            "R/R": "1.20",
            "섹터RS": "-",
            "돈흐름_시장맥락": "미국 · 포토닉스",
            "애널목표Upside": "+12.3%",
        }
    ])

    out = apply_execution_gate_columns(df, upside_value_map={"LITE": 12.3})

    assert out.loc[0, "게이트상태"] == GATE_EXECUTABLE
    assert out.loc[0, "업사이드상태"] == "양수"
    assert out.loc[0, "섹터RS상태"] == "돈흐름맥락 확인"


def test_quality_state_helpers():
    assert classify_upside_state("-", is_etf=False) == "결측/수동확인"
    assert classify_upside_state("-", is_etf=True) == "ETF제외"
    assert classify_sector_rs_state("-", flow_context="KOSDAQ 테마") == "돈흐름맥락 확인"
