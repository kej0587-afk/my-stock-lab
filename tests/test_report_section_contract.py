"""Whole-output contracts captured before section extraction (ef08d5e0)."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pytest

from stock_lab_core.report_evidence import report_sections


CLOCKS = ("2026-11-04T08:00:00+09:00", "2026-11-04T13:00:00+09:00",
          "2026-11-04T17:00:00+09:00", "2026-11-04T23:00:00+09:00",
          "2026-11-07T12:00:00+09:00", "2026-11-04T23:45:00+09:00")


def report_case(clock, held=True):
    now = datetime.fromisoformat(clock)
    prices = {ticker: dict(date="2026-11-03", previous_date="2026-11-02", return_5d=-.04,
                           price=100, **{"return": move})
              for ticker, move in (("^KS11", -.03), ("^KQ11", -.02), ("^GSPC", -.01),
                                   ("^IXIC", -.02), ("SOXX", -.03), ("SOXL", -.09),
                                   ("379800.KS", .01), ("MSFT", -.01))}
    context = dict(sessions={"KR": "2026-11-03", "US": "2026-11-03"}, prices=prices,
                   calendar_events=[dict(event="CPI", date="2026-11-06", source="BLS", source_url="https://www.bls.gov/cpi/")],
                   calendar_sources=[dict(name="BLS CPI", status="connected")],
                   economic_releases=[], missing=["fixture missing input"], history_status="fixture history", history_durable=True)
    rows = [dict(티커=ticker, 종목명=name, 보유량=1, 현재비중=weight, 목표비중=weight,
                 최종읽기="대기", 게이트상태="대기/관찰")
            for ticker, name, weight in (("SOXL", "Fixture leverage", 10), ("379800.KS", "Fixture core", 70))] if held else []
    rows += [dict(티커="MSFT", 종목명="Fixture watch", 보유량=0, Adj점수=2, 게이트상태="방어우선")]
    return dict(context=context, news=[], flow_rows=[], event_rows=[], summary_rows=rows, now=now)


def digest(result):
    return hashlib.sha256(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


# Expected hashes are generated from the previous implementation, not the new renderer.
EXPECTED = {
    "2026-11-04T23:45:00+09:00/False": "eb7a625b74ecb98efa9462e852ee937a3f92348c1926000505ffb9059f3b4d9a",
    "2026-11-04T23:45:00+09:00/True": "6fdb3c1f01bed89c4a0cb8d2be60400abdf2cbc6810ba0e4bd29c813330e26c4",
    "2026-11-04T08:00:00+09:00/False": "9371b28eb6589860d04bda02d9fc68170f64d26e60fe7efb8f0396618b22e768",
    "2026-11-04T08:00:00+09:00/True": "03638adb6625af53ee97d41fd9b86440f0abbd2be4542c4885c20a604ff31b37",
    "2026-11-04T13:00:00+09:00/False": "bd5efd06dfe440729a4dec14bd24142ee66429ca20f4dd93e248d65c686f9ae5",
    "2026-11-04T13:00:00+09:00/True": "6a4cc0f7e78dbc3bbb2145d573372785bb3c9b6ec08e4e55fcbe796e1bd80c29",
    "2026-11-04T17:00:00+09:00/False": "d6eb6809363c2bfe3551b3cee3f322940631147002595545f4b38849457a0dd6",
    "2026-11-04T17:00:00+09:00/True": "b4ac8f5af710552bea92c5dc2707f070ab9fe85295bd32fb7a947e9f6ea0453b",
    "2026-11-04T23:00:00+09:00/False": "5d6bfa283c798317860f445002eca80033122a7f2630f6e01c23061c6cd5f5be",
    "2026-11-04T23:00:00+09:00/True": "adf0bd7641fb1204efeba8210e0021701906c5f69222d187ed73e37bea15dcd5",
    "2026-11-07T12:00:00+09:00/False": "c9b387b524a267279e0c4fbb20a952d265f9b5d60e559c0cb35e20c5c6b2fc06",
    "2026-11-07T12:00:00+09:00/True": "cd26dfa1afc6a00eaa98c45870955c3ddd7fd9b8a3812534f2566500c6d33b15",
}


@pytest.mark.parametrize("clock", CLOCKS)
@pytest.mark.parametrize("held", [False, True])
def test_full_output_preserved_across_sessions(clock, held, monkeypatch):
    args = report_case(clock, held)
    before = deepcopy(args)
    # Nov08 deliberately adds editorial prose/reorders sections; these are
    # independently exercised in test_report_editorial_nov08. Keep the immutable
    # digest for the underlying legacy sections rather than regenerate goldens.
    from stock_lab_core import report_editorial, report_dashboard
    monkeypatch.setattr(report_editorial, "editorial_lines", lambda *a: [])
    monkeypatch.setattr(report_editorial, "reading_order", lambda lines: lines)
    original_status = report_dashboard.current_state_lines
    def legacy_status(context, states, now, metrics):
        lines = original_status(context, states, now, metrics)
        if "최근 확정 종가" in lines[1]:
            # This fixture has no intraday/extended/futures quotes. Only the old
            # misleading holiday sentence is restored for historical parity.
            assert not any(context.get(k) for k in ("intraday_prices", "extended_prices", "scenario_observations"))
            lines[1] = "**미국 현재 · 정규장 외** · 현재 시세 미연결(직전 종가는 아래 표) (미확정·지연 가능)"
        return lines
    monkeypatch.setattr(report_dashboard, "current_state_lines", legacy_status)
    output = report_sections(**args)
    # Approved Report 33 additions: explicitly state end-weight limitations.
    # Retain the old digest for every other byte, including all numeric output.
    additions = {
        "- 비중 기준은 점검 입력의 현재 평가비중(기간 시작 비중 아님)입니다. 가격 기준시각과 비중 산출시각은 다를 수 있습니다. 현재비중 × 누적 등락은 노출 참고값이며 실제 기간 손익이 아닙니다.",
        "- 시작 비중은 시작 총자산·수량·현금·환율·중간 거래가 있어야 복원됩니다. 현재비중 ÷ (1+수익률)만으로는 시작 총자산 분모가 복원되지 않아 시작비중 기여도를 추정해 채우지 않습니다.",
    }
    assert all(output[0].count(line) == 1 for line in additions)
    legacy = ([line for line in output[0] if line not in additions], output[1])
    assert digest(legacy) == EXPECTED[f"{clock}/{held}"]
    assert args == before
    lines, _ = output
    assert lines.count("## 내 보유 종목 영향") == 1
    assert lines.count("## 다가오는 일정") == 1
    assert lines.index("## 다가오는 일정") < lines.index("## 내 보유 종목 영향") < lines.index("## 오늘의 시장 스토리")


@pytest.mark.parametrize("as_of,date,valid", [
    ("2026-11-04T12:59:00+09:00", "2026-11-04", True),
    ("2026-11-04T12:45:00+09:00", "2026-11-04", True),
    ("2026-11-04T12:44:59+09:00", "2026-11-04", False),
    ("2026-11-04T09:00:00+09:00", "2026-11-04", False),
    ("2026-11-04T13:01:00+09:00", "2026-11-04", False),
    (None, "2026-11-04", False),
    ("2026-11-04T12:59:00+09:00", "2026-11-03", False),
])
def test_holdings_table_and_account_use_same_live_validity(as_of, date, valid):
    from stock_lab_core.report_intraday import intraday_account_metrics
    from stock_lab_core.report_session import market_session_states
    args = report_case(CLOCKS[1])
    args["context"]["intraday_prices"] = {"379800.KS": dict(date=date, as_of=as_of, **{"return": .1234})}
    output, _ = report_sections(**args)
    row = next(line for line in output if line.startswith("Fixture core(379800.KS) |"))
    assert ("+12.34%" in row.split(" | ")[3]) is valid
    metrics = intraday_account_metrics(args["summary_rows"][:2], args["context"]["intraday_prices"],
                                      states=market_session_states(args["now"]), now=args["now"])
    assert bool(metrics["coverage"]) is valid


def test_kr_semiconductor_reference_does_not_call_old_us_quote_live():
    args = report_case(CLOCKS[1])
    args["summary_rows"][1].update(티커="0167A0.KS", 종목명="Fixture semiconductor")
    args["context"]["intraday_prices"] = {"SOXX": dict(date="2026-11-03",
        as_of="2026-11-04T04:59:00+09:00", **{"return": .1234})}
    output, _ = report_sections(**args)
    row = next(line for line in output if line.startswith("Fixture semiconductor(0167A0.KS) |"))
    assert "SOXX -3.00%" in row
    assert "확정 종가 참고" in row
    assert "+12.34%" not in row
