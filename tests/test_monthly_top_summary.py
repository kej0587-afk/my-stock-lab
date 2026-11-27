"""Key monthly amounts at the top of 자산 현황: account totals, 미확인 never summed as a number."""

from stock_lab_core.monthly_execution import monthly_totals
from stock_lab_core import monthly_execution_view as view


def test_totals_use_standard_names_and_never_show_a_partial_sum():
    rows = [{"plan": 100000, "executed": 30000, "executable": 50000},
            {"plan": 0, "executed": 0, "executable": None}]
    assert monthly_totals(rows, executed_status="ok") == {
        "월계획액": "100,000원", "누적 집행기록액": "30,000원", "남은 계획액": "70,000원", "오늘 추가 가능액": "50,000원"}
    rows.append({"plan": 20000, "executed": 0, "executable": None})
    totals = monthly_totals(rows, executed_status="ok")
    assert totals["오늘 추가 가능액"] == "미확인(1종목 자료 부족)" and totals["월계획액"] == "120,000원"
    unread = monthly_totals(rows, executed_status="error")
    assert unread["누적 집행기록액"] == "미확인(집행 기록을 읽지 못함)" and unread["남은 계획액"].startswith("미확인")
    assert monthly_totals([], executed_status="ok") == {}


class Slot:
    def __init__(self, fail=False):
        self.text, self.fail = None, fail

    def markdown(self, text):
        if self.fail:
            raise RuntimeError("stale")
        self.text = text


class St:
    def __init__(self, slot):
        self.session_state = {view.SUMMARY_SLOT_KEY: slot} if slot else {}


def test_slot_is_filled_once_and_a_stale_slot_is_harmless():
    slot = Slot()
    st = St(slot)
    view._fill_top_summary(st, [{"plan": 1000, "executed": 0, "executable": 1000}], executed_status="ok",
                           month_key="2026-11", scope="acc")
    assert "**이번 달 월적립** (2026-11 · 계좌 범위 acc) · 월계획액 1,000원 · 누적 집행기록액 0원" in slot.text
    assert view.SUMMARY_SLOT_KEY not in st.session_state
    view._fill_top_summary(St(Slot(fail=True)), [{"plan": 1, "executed": 0, "executable": 0}],
                           executed_status="ok", month_key="2026-11", scope="acc")
    view._fill_top_summary(St(None), [], executed_status="ok", month_key="2026-11", scope="acc")


def test_missing_signals_name_the_fixable_cause():
    rows = [{"plan": None, "plan_src": "신호 미확인", "executed": 0, "executable": None},
            {"plan": None, "plan_src": "신호 미확인", "executed": 5000, "executable": None}]
    totals = monthly_totals(rows, executed_status="ok")
    assert totals["월계획액"] == totals["오늘 추가 가능액"] == "미확인(2종목 신호 미계산 · 자산 현황 ‘기술적 타점계산’ 후 표시)"
    assert totals["누적 집행기록액"] == "5,000원"
    mixed = rows + [{"plan": None, "plan_src": "", "executed": 0, "executable": None}]
    assert monthly_totals(mixed, executed_status="ok")["월계획액"] == "미확인(3종목 계획 미확인)"
