"""Display-only return evidence; synthetic prices and no application import."""

import ast
from copy import deepcopy
from pathlib import Path
import socket
from unittest.mock import Mock

import pandas as pd
import pytest

from stock_lab_core import decision_engine, report_exchange_clock
from stock_lab_core.quote_observation import observed_price
from stock_lab_core.signal_basis import build_signal_basis, render_signal_basis, source_return_basis
from stock_lab_core.signal_input_contract import price_input_identity


NEW_KEYS = {"등락비교기준", "등락봉시간상태", "최신가비교기준"}
CALCULATED = "2026-11-21 00:36:10 KST"
UNKNOWN = {"등락비교기준": "원자료 비교쌍 미확인", "등락봉시간상태": "완료 여부 미확인"}
ENDED = "마감시각 경과 · 공급처 확정 여부 미확인"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    guards = []
    for target, name in ((socket, "getaddrinfo"), (socket.socket, "connect"),
                         (socket.socket, "connect_ex")):
        guard = Mock(side_effect=AssertionError("Unexpected network request"))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


def source_frame(days=("2026-11-18", "2026-11-19", "2026-11-20")):
    closes = [100. + 5 * i for i in range(len(days))]
    frame = pd.DataFrame({"Open": closes, "High": [p + 2 for p in closes],
                          "Low": [p - 2 for p in closes], "Close": closes,
                          "Volume": [1000.] * len(days)}, index=pd.to_datetime(list(days)))
    frame.attrs = {"source": "synthetic", "audit": {"keep": ["original"]}}
    return frame


def quote(price=106., ticker="GOOGL"):
    return observed_price(price, ticker=ticker, source="yahoo_chart",
                          observed_at="2026-11-20T15:36:10Z", session="regular", timestamp_kind="bar_start")


def test_actual_source_pair_keeps_gap_and_daily_labels_without_mutation():
    frame = source_frame(("2026-11-13", "2026-11-16", "2026-11-20"))
    frame.index = frame.index.tz_localize("Asia/Seoul")
    original = deepcopy(frame)
    result = source_return_basis(frame, "GOOGL", CALCULATED)
    assert result == {"등락비교기준": "원자료 Close 2026-11-16 → 2026-11-20",
                      "등락봉시간상태": "장중 원자료 · 미확정"}
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    assert frame.attrs == original.attrs


@pytest.mark.parametrize("ticker,days,at,status", [
    ("GOOGL", ("2026-11-19", "2026-11-20"), "2026-11-20T14:29:59Z", "개장 전 날짜의 원자료 · 확인 필요"),
    ("GOOGL", ("2026-11-19", "2026-11-20"), CALCULATED, "장중 원자료 · 미확정"),
    ("GOOGL", ("2026-11-19", "2026-11-20"), "2026-11-20T21:00Z", ENDED),
    ("379810.KS", ("2026-11-18", "2026-11-19"), "2026-11-19T16:00+09:00", "장중 원자료 · 미확정"),
    ("379810.KS", ("2026-11-18", "2026-11-19"), "2026-11-19T16:30+09:00", ENDED),
    ("379810.KS", ("2026-10-08", "2026-10-09"), "2026-10-09T17:00+09:00", "비거래일 날짜의 원자료 · 확인 필요"),
    ("GOOGL", ("2026-11-25", "2026-11-26"), "2026-11-26T22:00Z", "비거래일 날짜의 원자료 · 확인 필요"),
    ("GOOGL", ("2026-11-25", "2026-11-27"), "2026-11-27T18:00Z", ENDED),
])
def test_calendar_clock_describes_time_boundary_without_certifying_supplier(ticker, days, at, status):
    result = source_return_basis(source_frame(days), ticker, at)
    assert result == {"등락비교기준": f"원자료 Close {days[0]} → {days[1]}", "등락봉시간상태": status}
    if status == ENDED:
        later = source_return_basis(source_frame(days), ticker, "2026-12-01T22:00Z")
        assert later == result  # More elapsed time still does not certify the supplier bar.


def test_invalid_last_pair_never_searches_older_rows_or_invents_dates():
    valid = source_frame()
    invalid = [None, pd.DataFrame(), valid.iloc[:1], valid.drop(columns="Close"), valid.reset_index(drop=True)]
    for position in (-2, -1):
        for value in (0., -1., float("nan"), float("inf"), pd.NA, "bad"):
            broken = valid.copy(deep=True)
            broken["Close"] = broken.Close.astype(object)
            broken.iloc[position, broken.columns.get_loc("Close")] = value
            invalid.append(broken)
    for dates in (("2026-11-18", "2026-11-20", "2026-11-20"),
                  ("2026-11-18", "2026-11-20", "2026-11-19"),
                  ("2026-11-18", None, "2026-11-20")):
        broken = valid.copy(deep=True)
        broken.index = pd.to_datetime(list(dates))
        invalid.append(broken)
    for frame in invalid:
        assert source_return_basis(frame, "GOOGL", CALCULATED) == UNKNOWN


def test_missing_naive_and_invalid_calculation_clock_remain_unknown(monkeypatch):
    calendar = Mock(side_effect=AssertionError("invalid clock must not reach calendar"))
    monkeypatch.setattr(report_exchange_clock, "session_on_date", calendar)
    for at in (None, "", pd.NaT, "bad", "2026-11-20 15:36:10", "2026-02-30 12:00:00 KST"):
        result = source_return_basis(source_frame(), "GOOGL", at)
        assert result == {"등락비교기준": "원자료 Close 2026-11-19 → 2026-11-20",
                          "등락봉시간상태": "완료 여부 미확인"}
    calendar.assert_not_called()


def test_unavailable_calendar_keeps_actual_pair_without_fallback(monkeypatch):
    monkeypatch.setattr(report_exchange_clock, "session_on_date",
                        lambda *_: {"known": False, "trading_day": None})
    result = source_return_basis(source_frame(), "GOOGL", "2026-11-21T22:00Z")
    assert result == {"등락비교기준": "원자료 Close 2026-11-19 → 2026-11-20",
                      "등락봉시간상태": "거래일정 미확인"}


def test_unknown_market_does_not_borrow_equity_calendar(monkeypatch):
    calendar = Mock(side_effect=AssertionError("unknown instrument calendar"))
    monkeypatch.setattr(report_exchange_clock, "session_on_date", calendar)
    for ticker in ("", "CL=F", "BTC-USD", "USDKRW=X"):
        result = source_return_basis(source_frame(), ticker, CALCULATED)
        assert result["등락비교기준"] == "원자료 Close 2026-11-19 → 2026-11-20"
        assert result["등락봉시간상태"] == "완료 여부 미확인"
    calendar.assert_not_called()


def test_build_preserves_preexisting_keys_identity_and_input_frames():
    source = source_frame()
    chart = source.copy(deep=True)
    originals = deepcopy((source, chart))
    selected = quote()
    identity = price_input_identity(source, chart, ticker="GOOGL", input_price=float(selected))
    result = build_signal_basis(source, (chart, False, ""), ticker="GOOGL",
                                input_price=selected, calculated_at=CALCULATED)
    expected = {
        "가격자료기준일": "2026-11-20", "지표마지막봉": "2026-11-20", "가격반영": "가격 이력 기준",
        "수급자료기준": "가격·거래량 원자료", "자료주의": "", "ATR기준일": "2026-11-20", "ATR가격봉수": 3,
        "가격입력ID": identity, "현재가출처": "yahoo_chart", "현재가관측시각": "2026-11-21 00:36:10 KST",
        "현재가관측UTC": "2026-11-20T15:36:10+00:00", "현재가세션": "정규장",
        "현재가시각종류": "분봉 시작시각 · 체결시각 아님",
        "원자료봉상태": "정규장 시세와 같은 날짜의 원자료 봉 · 장중 미완성 가능",
        "임시봉날짜의미": "원자료 봉 날짜", "계산시각": CALCULATED,
    }
    # Explicit old evidence fields, not a second implementation of the new helper.
    assert {key: value for key, value in result.items() if key not in NEW_KEYS} == expected
    assert NEW_KEYS <= result.keys()
    assert result["등락봉시간상태"] == "장중 원자료 · 미확정"
    assert result["최신가비교기준"] == (
        "선택 현재가 / 2026-11-20 원자료 Close · 시세시각 2026-11-21 00:36:10 KST · 세션 정규장")
    for frame, original in zip((source, chart), originals):
        pd.testing.assert_frame_equal(frame, original, check_exact=True)
        assert frame.attrs == original.attrs


@pytest.mark.parametrize("overlay_day", ["2026-11-20", "2026-11-23"])
def test_live_overlay_uses_original_source_pair_and_latest_source_base(overlay_day, monkeypatch):
    source = source_frame()
    monkeypatch.setattr(decision_engine, "_get_live_price_row_date", lambda _: pd.Timestamp(overlay_day))
    selected = quote(140.)
    chart, applied = decision_engine.apply_live_price_to_ohlcv(source, selected, "GOOGL")
    assert applied and chart.Close.iloc[-1] == 140.
    originals = deepcopy((source, chart))
    identity = price_input_identity(source, chart, ticker="GOOGL", input_price=selected)
    result = build_signal_basis(source, (chart, applied, ""), ticker="GOOGL",
                                input_price=selected, calculated_at=CALCULATED)
    assert result["등락비교기준"] == "원자료 Close 2026-11-19 → 2026-11-20"
    assert result["최신가비교기준"].startswith("선택 현재가 / 2026-11-20 원자료 Close · 시세시각 ")
    assert result["지표마지막봉"] == overlay_day
    assert result["ATR기준일"] == "2026-11-20" and result["ATR가격봉수"] == 3
    assert result["가격입력ID"] == identity
    for frame, original in zip((source, chart), originals):
        pd.testing.assert_frame_equal(frame, original, check_exact=True)
        assert frame.attrs == original.attrs


def test_missing_supplier_time_manual_and_wrong_symbol_never_borrow_calculation_clock():
    source = source_frame()
    for selected, manual in ((106., False), (quote(ticker="SOXL"), False), (quote(), True)):
        result = build_signal_basis(source, (source, False, ""), ticker="GOOGL", input_price=selected,
                                    manual=manual, calculated_at="2026-11-21 09:00:00 KST")
        assert result["등락봉시간상태"] == ENDED
        assert result["현재가관측UTC"] == "" and result["현재가관측시각"] == "미확인"
        assert result["최신가비교기준"] == "선택 현재가 / 2026-11-20 원자료 Close · 시세시각 미확인 · 세션 미확인"
    no_quote = build_signal_basis(source, (source, False, ""), ticker="GOOGL", calculated_at=CALCULATED)
    assert no_quote["최신가비교기준"] == "비교기준 미확인"


def test_evidence_renderer_adds_rows_and_accepts_legacy_basis_without_mutation():
    source = source_frame()
    basis = build_signal_basis(source, (source, False, ""), ticker="GOOGL", calculated_at=CALCULATED)
    original = deepcopy(basis)
    st = Mock()
    render_signal_basis(st, basis)
    rows = st.dataframe.call_args.args[0].set_index("항목")
    assert rows.loc["일간 등락 비교", "기준일/봉 날짜"] == basis["등락비교기준"]
    assert rows.loc["일간 등락 비교", "가격 기준"] == "장중 원자료 · 미확정"
    assert rows.loc["최신가 비교가 표시될 때", "가격 기준"] == "비교기준 미확인"
    assert basis == original
    legacy = {key: value for key, value in basis.items() if key not in NEW_KEYS}
    render_signal_basis(st, legacy)
    old_rows = st.dataframe.call_args.args[0]
    assert "일간 등락 비교" not in old_rows["항목"].tolist()
    assert len(old_rows) == len(rows) - 2


def test_static_ui_reads_evidence_keys_and_today_details_keep_them():
    root = Path(__file__).resolve().parents[1]
    for filename in ("app.py", "stock_lab_core/precision_narrative.py"):
        tree = ast.parse((root / filename).read_text(encoding="utf-8-sig"))
        reads = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                reads.add(node.slice.value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)):
                reads.add(node.args[0].value)
        assert NEW_KEYS <= reads, filename
        assert "input_basis" in reads, filename
    tree = ast.parse((root / "stock_lab_core/today_queue_view.py").read_text(encoding="utf-8-sig"))
    columns = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "DETAIL_COLUMNS" for target in node.targets))
    assert NEW_KEYS <= set(columns)
