"""Exit rows for the precision plan; all prices are supplied by the caller."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def build_precision_exit_rows(*, ticker, has_pos, cur, stop, target, tp1, tp2, tp3,
                              target_is_projection, format_currency, take_profit_condition):
    """Format existing targets without recomputing prices, amounts or policy."""
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
        rows += [
            {
                "단계": "1차 익절",
                "가격": format_currency(tp1, ticker),
                "금액/수량": "보유분 30~50%",
                "예상 R/R": "-",
                "조건": take_profit_condition(cur, stop, target),
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

