"""Exit rows for the precision plan; all prices are supplied by the caller."""

import math

from stock_lab_core.report_build import register_loaded_source


def build_entry_basis_rows(rows, prices, entries, ticker, *, gate_open, target, stop, target_source, stop_source,
                           format_currency):
    """Display only (2026-11-27): each planned entry price with the line/formula that produced it."""
    stages = [row for row in rows if str(row.get("단계", "")).startswith(("1차 진입", "추가 1차", "2차 추가", "3차 예비"))]
    out = []
    for row, raw, basis in zip(stages, entries, prices.get("basis") or ()):
        amount = str(row.get("금액/수량") or "-")
        out.append({
            "단계": row.get("단계"), "가격": row.get("가격"),
            "기준선·산식": f"{basis} · 반올림 전 {raw:.4f}" if math.isfinite(float(raw)) else basis,
            "R/R(최종 목표·손절 기준)": row.get("예상 R/R", "-"),
            "실행·수량": (amount if gate_open and amount != "-" else
                       "보류 · 수량 미산출" if not gate_open else "수량 미산출"),
        })
    out.append({"단계": "최종 목표", "가격": format_currency(target, ticker), "기준선·산식": target_source,
                "R/R(최종 목표·손절 기준)": "-", "실행·수량": "진입 후 재산출"})
    out.append({"단계": "계획 무효·손절", "가격": format_currency(stop, ticker),
                "기준선·산식": f"{stop_source} · 종가 기준 · 일봉 B 경계·단기 손절과 별개",
                "R/R(최종 목표·손절 기준)": "-", "실행·수량": "신규·추가 계획 무효선"})
    return out

register_loaded_source(__name__, __file__)


def build_precision_exit_rows(*, ticker, has_pos, cur, stop, target, tp1, tp2, tp3,
                              target_is_projection, format_currency, take_profit_condition):
    """Format targets; cur is the first planned entry's risk basis, not a live quote."""
    rows = []
    if target_is_projection:
        rows += [
            {
                "단계": "1차 익절(+1ATR)",
                "가격": format_currency(tp1, ticker),
                "금액/수량": "보유분 20~30%",
                "예상 R/R": "-",
                "조건": "신고가 가격발견 구간의 첫 변동성 목표. 체결 후 잔여 손절을 본전~MA5 근처로 상향",
            },
            {
                "단계": "2차 익절(+2ATR)",
                "가격": format_currency(tp2, ticker),
                "금액/수량": "보유분 30~40%",
                "예상 R/R": "-",
                "조건": "기본 변동성 목표. RSI/MFI/%B 과열이 동반되면 추가 회수",
            },
            {
                "단계": "강세 상단(+4ATR)",
                "가격": format_currency(tp3, ticker),
                "금액/수량": "잔여 일부만",
                "예상 R/R": "-",
                "조건": "확정 목표가가 아니라 공격 시나리오 상단. 전량 지정가보다 일부만 열어두기",
            },
            {
                "단계": "잔여 추적손절",
                "가격": "MA5/전일저가/1ATR 이탈",
                "금액/수량": "잔여분",
                "예상 R/R": "-",
                "조건": "상단 목표를 맞히기보다 추세가 꺾일 때 정리. 종가 기준 이탈 우선",
            },
        ]
    else:
        condition = take_profit_condition(cur, stop, target)
        condition += f" · 1차 계획 진입가 {format_currency(cur, ticker)} 기준(실제 체결·추가 진입 후 재산출)"
        rows += [
            {
                "단계": "1차 익절",
                "가격": format_currency(tp1, ticker),
                "금액/수량": "보유분 30~50%",
                "예상 R/R": "-",
                "조건": condition,
            },
            {
                "단계": "최종 익절",
                "가격": format_currency(tp2, ticker),
                "금액/수량": "잔여분",
                "예상 R/R": "-",
                "조건": "구조 목표가 도달 또는 MFI/%B 과열 동반 시",
            },
        ]
    rows.append({
        "단계": "손절",
        "가격": format_currency(stop, ticker),
        "금액/수량": "전량 또는 계획분",
        "예상 R/R": "-",
        "조건": "종가 기준 이탈 시 추가매수 시나리오 무효" if has_pos else "종가 기준 이탈 시 신규진입 시나리오 무효",
    })
    return rows



def build_trend_exit_rows(*, ticker, stop, atr, format_currency, size_text="정찰분 전량"):
    """Trend-following exit (C-1 step 1): no fixed target, a trailing stop from the highest close."""
    from stock_lab_core.trend_exit_policy import INITIAL_STOP_ATR, TRAIL_ATR
    trail = f"진입 후 최고 종가 - {TRAIL_ATR:g}ATR" + (f" (현재 ATR {format_currency(TRAIL_ATR * atr, ticker)})" if atr and atr > 0 else "")
    return [
        {
            "단계": "추세추적 정리",
            "가격": trail,
            "금액/수량": size_text,
            "예상 R/R": "-",
            "조건": "고정 목표가 없이 추적손절이 매일 올라갑니다(내려가지 않음). 종가가 추적손절 아래로 마감하면 정리",
        },
        {
            "단계": "초기 손절",
            "가격": format_currency(stop, ticker),
            "금액/수량": size_text,
            "예상 R/R": "-",
            "조건": f"진입가 - {INITIAL_STOP_ATR:g}ATR. 장중 이탈 시 정리하고 신규진입 시나리오 무효",
        },
    ]
