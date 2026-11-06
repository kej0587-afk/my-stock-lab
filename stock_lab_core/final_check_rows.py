"""Ordered final-check rows; no I/O, session state or execution override."""

from stock_lab_core.formatters import finite_num
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def build_risk_check_rows(
    *, is_core_dca, dd, live_gap_shock, day_ret, structure_risk, trend, rs_label,
    mtf_bias_label, mtf_bias_text, mfi, rsi, pct_b, core_dca_label,
):
    """Preserve the existing structure, timeframe and overheat checks in order."""
    rows = []

    def add_check(category, status, detail):
        rows.append({"점검항목": category, "상태": status, "해석": detail})

    if is_core_dca and dd <= -0.2:
        add_check("구조/추세", "주의", f"52주 고점대비 {dd * 100:.1f}%. 코어 ETF 급락 구간은 원인 확인 후 파킹자산 일부 투입 후보로 봅니다.")
    elif live_gap_shock:
        add_check("구조/추세", "차단", f"현재/전거래일 대비 {day_ret * 100:.1f}% 실시간 급락 구간입니다. 정규장 종가와 거래량 확인 전 신규/추매는 보류합니다.")
    elif structure_risk or dd <= -0.2:
        add_check("구조/추세", "차단", f"52주 고점대비 {dd * 100:.1f}% 또는 구조위험이 있습니다. 원인 확인 전 추매는 금지에 가깝게 봅니다.")
    elif "역배열" in trend or "약함" in rs_label:
        add_check("구조/추세", "주의", f"{trend} / {rs_label}. 추세 회복을 확인하고 접근하는 쪽이 낫습니다.")
    else:
        add_check("구조/추세", "통과", f"{trend} / {rs_label}. 즉시 구조 경고는 크지 않습니다.")

    if mtf_bias_label == "상위 시간대 경고":
        add_check("상위 시간대", "차단", mtf_bias_text or "주봉/월봉 흐름이 일봉 신호와 충돌합니다. 신규/추매는 보류가 우선입니다.")
    elif mtf_bias_label == "정찰만 적합":
        add_check("상위 시간대", "주의", mtf_bias_text or "주봉/월봉 가격대가 높아 풀진입보다 1차 정찰만 적합합니다.")
    elif mtf_bias_label == "상위 시간대 우호":
        add_check("상위 시간대", "통과", mtf_bias_text or "일봉과 주봉/월봉 흐름이 크게 충돌하지 않습니다.")
    elif mtf_bias_label:
        add_check("상위 시간대", "주의", mtf_bias_text or "상위 시간대 확인이 필요합니다.")

    overheated = (finite_num(mfi) and mfi >= 85) or (finite_num(rsi) and rsi >= 75) or (finite_num(pct_b) and pct_b >= 1.02)
    if is_core_dca and overheated:
        add_check("과열", "주의", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 코어 ETF라 추격매수 대신 {core_dca_label}으로 제한합니다.")
    elif overheated:
        add_check("과열", "차단", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 추격매수 부담이 큽니다.")
    elif (finite_num(mfi) and mfi >= 80) or (finite_num(rsi) and rsi >= 70) or (finite_num(pct_b) and pct_b >= 0.95):
        add_check("과열", "주의", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 눌림 대기가 더 유리할 수 있습니다.")
    elif not all(finite_num(value) for value in (mfi, rsi, pct_b)):
        add_check("과열", "미확인", "RSI/MFI/볼린저 %B 중 미수집 항목이 있습니다. 과열 없음으로 간주하지 않습니다.")
    else:
        add_check("과열", "통과", f"MFI {mfi:.1f}, RSI {rsi:.1f}, %B {pct_b:.2f}. 극단 과열은 아닙니다.")

    return rows


def build_portfolio_check_rows(
    *, has_pos, target_w, curr_w, weight_gap, macro_risk, trend, rs_label, price_vs_avg,
):
    """Preserve weight, macro and holding checks; do not decide order budgets."""
    rows = []

    def add_check(category, status, detail):
        rows.append({"점검항목": category, "상태": status, "해석": detail})

    if has_pos and target_w <= 0 and curr_w > 0:
        add_check("비중", "차단", f"현재 {curr_w:.2f}% / 목표 {target_w:.2f}%. 목표비중이 0%라 추가매수 대상이 아닙니다.")
    elif target_w > 0 and curr_w >= target_w:
        add_check("비중", "차단", f"현재 {curr_w:.2f}% / 목표 {target_w:.2f}%. 목표비중을 이미 채웠습니다.")
    elif target_w > 0 and weight_gap > 0:
        add_check("비중", "통과", f"현재 {curr_w:.2f}% / 목표 {target_w:.2f}%. 남은 여유비중 {weight_gap:.2f}%p입니다.")
    else:
        add_check("비중", "주의", "목표비중이 없거나 부족 매수액 계산이 약합니다. 먼저 목표비중을 정하는 편이 좋습니다.")

    if finite_num(macro_risk) and macro_risk >= 4.5:
        add_check("매크로", "차단", f"매크로 리스크 {macro_risk:.1f}. 신규/추매는 막고, 기존 보유는 손절선·비중·하락 원인 중심으로 점검합니다.")
    elif finite_num(macro_risk) and macro_risk >= 2.5:
        add_check("매크로", "주의", f"매크로 리스크 {macro_risk:.1f}. 분할 접근이 적합합니다.")
    elif not finite_num(macro_risk):
        add_check("매크로", "미확인", "매크로 리스크 원자료 미확인")
    else:
        add_check("매크로", "통과", "-" if not finite_num(macro_risk) else f"매크로 리스크 {macro_risk:.1f}. 큰 차단 신호는 아닙니다.")

    if not has_pos:
        if trend == "🚀정배열(상승)" and rs_label == "🚀강함":
            add_check("보유상태", "통과", "신규 진입. 추세/RS가 양호해 정찰 비중으로 시작 가능합니다.")
        else:
            add_check("보유상태", "주의", "신규 진입. 첫 진입은 정찰 비중으로 시작하는 편이 안전합니다.")
    elif finite_num(price_vs_avg) and price_vs_avg < -0.07:
        add_check("보유상태", "주의", f"평단 대비 {price_vs_avg * 100:.1f}%. 추가매수보다 손상 원인 확인이 먼저입니다.")
    elif finite_num(price_vs_avg):
        add_check("보유상태", "통과", f"평단 대비 {price_vs_avg * 100:.1f}%. 보유 관리 범위 안에서 판단 가능합니다.")
    else:
        add_check("보유상태", "통과", "보유 정보 기준의 특이 위험은 크지 않습니다.")

    return rows
