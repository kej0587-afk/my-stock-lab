import pandas as pd

from stock_lab_core.execution_gate import (
    GATE_EXECUTABLE,
    GATE_DATA_CHECK,
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


def test_weak_sector_rs_is_candidate_context_not_an_entry_trigger():
    row = {
        "티커": "MU",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "R/R": "1.40",
        "섹터RS": "🐢약함",
    }

    result = apply_execution_gate_columns(pd.DataFrame([row])).iloc[0]
    assert result["게이트상태"] == GATE_EXECUTABLE
    assert "섹터RS 약함" in result["후보검토사항"]


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


def test_execution_gate_waits_when_money_flow_is_negative_watch():
    row = {
        "티커": "AMAT",
        "판정분류": "buyish",
        "최종읽기": "✅정밀확인",
        "R/R": "1.10",
        "돈흐름_판정": "관망",
        "돈흐름_후보군": "레이더 관찰",
        "돈흐름_돈흐름점수": "-23.5",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "돈흐름 약함 -23.5" in gate["게이트근거"]


def test_leveraged_scout_label_is_wait_not_executable():
    row = {
        "티커": "RAM",
        "판정분류": "buyish",
        "최종읽기": "✅레버리지정찰",
        "실행메모": "보험성 1차 정찰",
        "🔥기술적 타점": "⚡레버리지 회복정찰: 보험성 1차",
        "판정코드": "LEVERAGED_RECOVERY_DCA_CONDITIONAL",
        "R/R": "1.20",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "레버리지 조건부 확인 대기" in gate["게이트근거"]


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
    assert out.loc[0, "섹터RS상태"] == "벤치확인 필요"


def test_quality_state_helpers():
    assert classify_upside_state("-", is_etf=False) == "결측/수동확인"
    assert classify_upside_state("-", is_etf=True) == "ETF제외"
    assert classify_sector_rs_state("-", flow_context="KOSDAQ 테마") == "벤치확인 필요"
    assert classify_sector_rs_state("-", is_etf=True) == "ETF/광역 제외"
    assert classify_sector_rs_state("공통거래일없음") == "가격이력 확인"


def test_panw_quality_candidate_waits_for_actual_entry_confirmation():
    row = {
        "티커": "PANW", "판정분류": "buyish", "최종읽기": "✅정밀확인",
        "📌후보등급": "✅A급 (분할 매수)", "R/R": "2.00",
        "🔥기술적 타점": "🔍A급 정배열: 타점 탐색 중",
        "실행메모": "눌림/종가 확인", "1차조건": "FVG 상단 눌림 확인 후 1차",
    }
    original = row.copy()
    assert build_execution_gate(row)["게이트상태"] == GATE_WAIT
    assert row == original


def test_explanatory_mfi_and_resistance_do_not_block_a_confirmed_signal():
    row = {
        "판정분류": "buyish", "최종읽기": "✅정밀확인", "R/R": 1.6,
        "🔥기술적 타점": "신규진입: 대장주 포착",
        "핵심근거": "MFI 60 / 저항 돌파 확인 / 상단 목표 참고",
    }
    assert build_execution_gate(row)["게이트상태"] == GATE_EXECUTABLE


def test_missing_rr_cannot_be_executable_and_display_upside_is_parsed():
    assert build_execution_gate({"판정분류": "buyish"})["게이트상태"] == GATE_DATA_CHECK
    out = apply_execution_gate_columns(pd.DataFrame([{
        "판정분류": "buyish", "R/R": 1.5, "애널목표Upside": "-5.2%",
    }]))
    assert out.iloc[0]["업사이드상태"] == "음수"
    assert out.iloc[0]["게이트상태"] == GATE_EXECUTABLE
    assert "-5.2%" in out.iloc[0]["후보검토사항"]


def test_caution_precision_confirm_does_not_become_executable():
    row = {
        "티커": "MSFT",
        "판정분류": "caution",
        "최종읽기": "✅정밀확인",
        "R/R": "1.80",
    }

    gate = build_execution_gate(row)

    assert gate["게이트상태"] == GATE_WAIT
    assert "주의 판정" in gate["게이트근거"]
