"""Pure fallback briefing text from existing results; no decision or I/O."""
import pandas as pd
from stock_lab_core.formatters import normalize_ticker, sanitize_ticker_value


def build_briefing_summary_text(df, *, buyish_mask, wait_mask, buyish_count, market_defensive,
                               core_hold_lines, review_lines, keep_lines, cash_available,
                               reserve_available, pending):
    def _row_name_list(mask, limit=3) -> list[str]:
        if df.empty:
            return []
        names = []
        try:
            view = df.loc[mask.reindex(df.index, fill_value=False)] if isinstance(mask, pd.Series) else pd.DataFrame()
        except Exception:
            view = pd.DataFrame()
        for _, row in view.head(limit).iterrows():
            nm = str(row.get("종목명", row.get("자산명", "")) or "").strip()
            tk = normalize_ticker(sanitize_ticker_value(row.get("티커", "")))
            if nm and tk:
                names.append(f"{nm}({tk})")
            elif nm or tk:
                names.append(nm or tk)
        return names

    execution_names = _row_name_list(buyish_mask)
    wait_names = _row_name_list(wait_mask)
    recommendation_lines: list[str] = []
    if market_defensive:
        recommendation_lines.append("신규 추천은 보수적으로 봅니다. 현금 유지, 손절선 확인, 레버리지 추가매수 중단이 우선입니다.")
    if core_hold_lines:
        recommendation_lines.append("S&P500/나스닥 같은 장기코어는 교체보다 유지·적립속도 조절로 분리합니다.")
    if review_lines:
        recommendation_lines.append("레버리지/위성 손실 종목은 물타기보다 회복 시 축소·대체 후보 검토가 우선입니다.")
    if execution_names and not market_defensive:
        recommendation_lines.append("정밀확인 우선 후보: " + " / ".join(execution_names))
    elif wait_names:
        recommendation_lines.append("관심만 유지할 후보: " + " / ".join(wait_names))
    if reserve_available > 0:
        recommendation_lines.append("폭락장 예비자금은 평상시 매수 재원이 아니라 급락 전용으로 분리 유지합니다.")
    if not recommendation_lines:
        recommendation_lines.append("오늘은 종목을 바꾸기보다 관심목록 정리와 목표비중 점검이 중심입니다.")

    if pending:
        headline = "종목 계산 전입니다. 시장·뉴스·시황만 먼저 보고, 새로고침 후 내 포트 판단을 채우세요."
    elif market_defensive and core_hold_lines and review_lines:
        headline = "장기코어는 교체가 아니라 유지/속도조절, 레버리지·위성은 추가매수 중단과 회복 시 축소 검토가 우선입니다."
    elif review_lines:
        headline = "오늘은 목표비중대로 더 사기보다 레버리지/위성 손실 원인과 대체 후보를 먼저 점검하는 구간입니다."
    elif market_defensive:
        headline = "시장 안전벨트가 방어 쪽입니다. 신규/추매는 줄이고 보유 위험과 현금 계획을 먼저 보세요."
    elif keep_lines and cash_available > 0:
        headline = "비중 미달 종목은 있지만, 정해둔 목표비중 안에서만 천천히 분할 접근하는 구간입니다."
    elif buyish_count > 0:
        headline = "후보는 있으나 현금·과열·비중 조건을 함께 확인한 뒤 실행하세요."
    else:
        headline = "오늘은 보유 유지, 관심 후보 정리, 뉴스 확인이 중심입니다."

    return headline, recommendation_lines


from stock_lab_core.report_build import register_loaded_source
register_loaded_source(__name__, __file__)
