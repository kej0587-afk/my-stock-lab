import pandas as pd
import pytest

from stock_lab_core.market_memo import (
    _rankable_flow_rows,
    _summary_bullets,
    _summary_display_rows,
    _summary_overview,
    build_auto_market_memo,
)


def summary_row(ticker, *, held=False, gate="대기/관찰", score=None):
    return {
        "티커": ticker,
        "종목명": f"종목{ticker}",
        "보유수량": int(held),
        "게이트상태": gate,
        "게이트근거": "기존 게이트 근거",
        "최종읽기": "기존 판정",
        "돈흐름_돈흐름점수": score,
        "돈흐름_후보군": "관심후보" if score is not None else "",
    }


def test_report_keeps_all_holdings_once_and_caps_watch_details_without_mutating_input():
    watch = [summary_row(f"W{i:02}", score=100 - i) for i in range(75)]
    watch[-1]["게이트상태"] = "실행가능"
    holdings = [summary_row(f"H{i:02}", held=True, gate="방어우선") for i in range(10)]
    source = pd.DataFrame(watch + holdings)
    before = source.copy(deep=True)

    memo = build_auto_market_memo(summary_rows=source)
    insight = memo.split("🧠 핵심 해석", 1)[1].split("🧭 오늘점검", 1)[0]
    detail = memo.split("🧭 오늘점검", 1)[1]

    assert "보유 10개: 방어우선 10" in insight
    assert "관심 75개: 실행가능 1 / 대기/관찰 74" in insight
    assert "종목H" not in insight and "종목W" not in insight
    for row in holdings:
        assert memo.count(f"{row['종목명']}({row['티커']})") == 1
    assert detail.count("• 종목W") == 10
    assert detail.index("종목H00") < detail.index("종목W74") < detail.index("종목W00")
    assert "관심 나머지 65개" in detail
    assert "전일 비교자료 미연결" in detail
    assert "주의/차단 후보:" not in memo
    assert "하드차단 우선 확인:" not in memo
    pd.testing.assert_frame_equal(source, before)


@pytest.mark.parametrize("extra_gate,saturated", [(None, True), ("관망", False), ("실행가능", False)])
def test_saturation_reads_canonical_gates(extra_gate, saturated):
    rows = [summary_row(str(i), gate=gate) for i, gate in enumerate(
        ["방어우선", "대기/관찰", "데이터확인"]
    )]
    if extra_gate:
        rows.append(summary_row("extra", gate=extra_gate))
    assert ("분류 포화" in "\n".join(_summary_bullets(rows))) is saturated


def test_stale_buy_or_hard_labels_do_not_override_canonical_gate():
    row = summary_row("MSFT", held=True)
    row.update({"판정코드": "HARD_BLOCK_MFI", "최종읽기": "분할 매수 가능"})
    text = "\n".join(_summary_bullets([row]))
    assert "판정: 분할 매수 가능 | 게이트: 대기/관찰" in text
    assert "보유 리스크" not in text
    assert "실행가능 1" not in _summary_overview([row])
    row["게이트상태"] = pd.NA
    row["gate_state"] = "EXECUTABLE"
    assert _summary_display_rows([row])[0]["gate"] == "실행가능"
    row.pop("gate_state")
    assert _summary_display_rows([row])[0]["gate"] == "게이트미확인"


def test_ticker_aliases_are_not_double_counted_and_unknown_holdings_stay_unknown():
    original = summary_row("005930.KS", held=True, gate="방어우선")
    alias = {**original, "티커": "005930"}
    unknown = {"티커": "aapl", "게이트상태": "관망"}
    rows = _summary_display_rows([original, alias, unknown])
    assert len(rows) == 2
    assert rows[1]["held"] is None
    assert "보유여부 미확인 1개: 관망 1" in _summary_overview([original, alias, unknown])


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), pd.NA])
def test_missing_history_never_ranks_as_zero_and_valid_negative_rows_fill_top(missing):
    rows = [
        {"Ticker": "0227L0", "섹터": "신규ETF", "3개월수익률": missing, "돈흐름점수": 0},
        {"Ticker": "ZERO", "섹터": "영점", "3개월수익률": 0, "돈흐름점수": 0},
        {"Ticker": "NEG1", "섹터": "음수1", "3개월수익률": -0.01, "돈흐름점수": -1},
        {"Ticker": "NEG2", "섹터": "음수2", "3개월수익률": -0.02, "돈흐름점수": -2},
    ]
    valid, excluded = _rankable_flow_rows(rows)
    assert excluded == 1
    assert [row["Ticker"] for row in valid] == ["ZERO", "NEG1", "NEG2"]
    memo = build_auto_market_memo(flow_snapshot={"kr_top5": pd.DataFrame(rows)})
    assert "0227L0" not in memo
    assert "데이터 없음/이력 부족 1개" in memo
    assert "음수2(NEG2) 3M -2.0%" in memo
    assert "영점(ZERO) 3M +0.0%, 가속도 -, 돈흐름 0.0점" in memo


def test_strong_and_weak_leader_names_are_disjoint_in_same_insight():
    memo = build_auto_market_memo(flow_snapshot={
        "us_top5": [{"Ticker": "CIBR", "섹터": "사이버보안", "3개월수익률": 0.1,
                     "돈흐름점수": 20, "상태": "강세 가속"}],
        "kr_top5": [{"Ticker": "455850", "섹터": "소부장", "3개월수익률": -0.005,
                     "돈흐름점수": -3, "상태": "소외 지속"}],
    })
    line = next(line for line in memo.splitlines() if "상대 순위 상위 축은" in line)
    strong, weak = line.split("별도 회복 확인 대상")
    assert "CIBR" in strong and "455850" not in strong
    assert "455850" in weak and "CIBR" not in weak
