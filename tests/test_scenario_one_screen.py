"""2026-11-27 request 3: SOXL case headline, comparison and entry basis read together."""

from stock_lab_core.entry_prices import build_entry_price_plan
from stock_lab_core.precision_scenarios import _one_screen


def soxl_model():
    ev = {"available": True, "fresh": True, "asof": "2026-11-25", "close": 32.02, "last_low": 31.5,
          "support": {"price": 29.82}, "recovery": {"price": 40.59}}
    scen = [{"name": n, "evidence": "월·주·일 추세훼손", "condition": "c", "invalidate": "i"}
            for n in ("A안 · 지지·회복", "B안 · 이탈·악화", "C안 · 횡보·관망")]
    rows = [{"안": "A", "확인 가격": "$40.59 종가 회복 후 재확인", "다음 가격": "$56.36", "실패·전환": "$29.82 종가 이탈 시 재검토"},
            {"안": "B", "확인 가격": "$29.82 종가 이탈", "다음 가격": "관측 가격대 없음", "실패·전환": "$40.59 회복 시 B 재검토"},
            {"안": "C", "확인 가격": "$29.82 ~ $40.59", "다음 가격": "상단 회복 시 A / 하단 이탈 시 B", "실패·전환": "범위 안 체류만으로 추가매수하지 않음"}]
    return {"focus": "B안 · 하방 위험 우선 감시", "thesis": "t", "execution": "신규·추가매수 보류 유지 · 레버리지 시장방어",
            "has_pos": False, "completed_evidence": ev, "scenarios": scen, "price_rows": rows}


def test_soxl_headline_and_comparison():
    plan = {"entry_basis": [{"단계": "1차 진입", "가격": "$34.91", "기준선·산식": "일봉 MA5 값", "실행·수량": "보류 · 수량 미산출"}]}
    m = _one_screen(soxl_model(), plan, "SOXL", "월봉·주봉·일봉 추세훼손")
    h = m["headline"]
    assert h["보유 여부"] == "미보유"
    assert h["기준 종가"] == "2026-11-25 완료 일봉 종가 $32.02"
    assert h["현재 가격 위치"] == "두 경계 안($29.82~$40.59)"
    assert h["우선 감시"].startswith("B안 · 하방 위험 우선 감시 · 월봉·주봉·일봉 추세훼손")
    assert "레버리지 시장방어" in h["오늘 실행"]
    rows = {r["대응안"][0]: r for r in m["compare_rows"]}
    assert "하단 종가 이탈 미충족" in rows["B"]["확인 가격과 조건"]
    assert "상단 종가 회복 미충족" in rows["A"]["확인 가격과 조건"]
    assert "아래 꼬리 미관측" in rows["A"]["확인 가격과 조건"]
    assert "범위 안" in rows["C"]["확인 가격과 조건"]
    assert m["entry_rows"][0]["실행·수량"] == "보류 · 수량 미산출"


def test_original_a_dip_and_recover_is_observed_separately():
    model = soxl_model()
    model["completed_evidence"]["last_low"] = 29.0
    m = _one_screen(model, {}, "SOXL", "s")
    a = m["compare_rows"][0]["확인 가격과 조건"]
    assert "저가 $29.00가 $29.82 아래 후 종가 회복 관측" in a and "상단 종가 회복 미충족" in a


def test_entry_price_basis_names_each_formula():
    c = {"cur_p": 100.0, "rr_stop": 80.0, "rr_target": 140.0, "atr": 4.0, "ma5": 94.0, "ma20": 90.0}
    p = build_entry_price_plan(c, wait_for_pullback=True)
    assert [e[0] for e in p["entries"]] == ["0.5ATR", "1ATR", "MA5"]
    assert p["basis"] == ("판정가 − 0.5×ATR", "판정가 − 1×ATR", "일봉 MA5 값")
    p = build_entry_price_plan({"cur_p": 100.0, "rr_stop": 80.0, "rr_target": 140.0}, wait_for_pullback=False)
    assert p["basis"][0] == "판정가(현재가 기준 1차)" and p["basis"][1].startswith("지지 후보 없음")
    assert p["basis"][2] == "손절 + 위험폭×0.25"
