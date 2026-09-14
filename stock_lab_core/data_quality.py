"""Data quality helpers for Stock Lab account inputs."""

import pandas as pd

from stock_lab_core.config import DIVIDENDS_COLUMNS, HOLDINGS_COLUMNS, MONTHLY_LOG_COLUMNS
from stock_lab_core.formatters import clean_float, normalize_ticker


QUALITY_REPORT_COLUMNS = ["등급", "영역", "티커", "문제", "확인/조치"]
QUALITY_SEVERITY_ORDER = {"위험": 0, "주의": 1, "참고": 2}


def add_quality_issue(issues, severity, area, ticker, problem, suggestion):
    issues.append({
        "등급": severity,
        "영역": area,
        "티커": str(ticker or "").strip(),
        "문제": problem,
        "확인/조치": suggestion,
    })


def sort_quality_issues(issues):
    report_df = pd.DataFrame(issues, columns=QUALITY_REPORT_COLUMNS)
    if report_df.empty:
        return report_df

    report_df["_order"] = report_df["등급"].map(QUALITY_SEVERITY_ORDER).fillna(9)
    return report_df.sort_values(["_order", "영역", "티커"]).drop(columns="_order").reset_index(drop=True)


def build_asset_quick_quality_report(settings, holdings_df, dividends_df, monthly_logs_df):
    issues = []
    settings = settings or {}
    holdings_df = holdings_df if holdings_df is not None else pd.DataFrame(columns=HOLDINGS_COLUMNS)
    dividends_df = dividends_df if dividends_df is not None else pd.DataFrame(columns=DIVIDENDS_COLUMNS)
    monthly_logs_df = monthly_logs_df if monthly_logs_df is not None else pd.DataFrame(columns=MONTHLY_LOG_COLUMNS)

    if clean_float(settings.get("usdkrw"), 0.0) <= 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "환율이 0 이하입니다.", "입력/수정 영역에서 USD/KRW 환율을 확인하세요.")
    if clean_float(settings.get("seed_money"), 0.0) < 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "시드머니가 음수입니다.", "시드머니를 0 이상으로 수정하세요.")

    if holdings_df.empty:
        add_quality_issue(issues, "참고", "보유자산", "", "등록된 보유자산이 없습니다.", "처음 사용하는 상태라면 정상입니다.")
    else:
        ticker_keys = []
        for idx, row in holdings_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            key = normalize_ticker(ticker)
            account_type = str(row.get("account_type", "일반")).strip()

            unique_key = f"{key} ({account_type})" if key else ""

            if key:
                ticker_keys.append(unique_key)
            else:
                add_quality_issue(issues, "위험", "보유자산", f"row {idx + 1}", "티커가 비어 있습니다.", "티커를 입력하거나 행을 삭제하세요.")

            if clean_float(row.get("qty"), 0.0) < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "보유량이 음수입니다.", "수량 입력값을 확인하세요.")
            if clean_float(row.get("avg_price"), 0.0) < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "매입가가 음수입니다.", "평균 매입가를 0 이상으로 수정하세요.")

            target_weight = clean_float(row.get("target_weight"), 0.0)
            if target_weight < 0 or target_weight > 100:
                add_quality_issue(issues, "주의", "보유자산", ticker, "목표비중이 0~100 범위를 벗어났습니다.", "목표비중을 확인하세요.")

        duplicated = pd.Series([key for key in ticker_keys if key]).value_counts()
        for key, count in duplicated[duplicated > 1].items():
            add_quality_issue(issues, "위험", "보유자산", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "중복 행을 정리하세요.")

    if not dividends_df.empty:
        for idx, row in dividends_df.fillna("").iterrows():
            if str(row.get("date", "")).strip() and pd.isna(pd.to_datetime(row.get("date"), errors="coerce")):
                add_quality_issue(issues, "주의", "배당", f"row {idx + 1}", "배당 날짜 형식이 애매합니다.", "YYYY-MM-DD 형식으로 입력하면 가장 안정적입니다.")
            if clean_float(row.get("amount"), 0.0) < 0:
                add_quality_issue(issues, "주의", "배당", str(row.get("ticker", "")), "배당금이 음수입니다.", "정정 입력이 아니라면 금액을 확인하세요.")

    if not monthly_logs_df.empty:
        months = []
        for idx, row in monthly_logs_df.fillna("").iterrows():
            month = str(row.get("month", "")).strip()
            if month:
                months.append(month)
            else:
                add_quality_issue(issues, "주의", "월별 로그", f"row {idx + 1}", "월 정보가 비어 있습니다.", "예: 2026-05 형식으로 입력하세요.")

            for col in ["total_invested", "evaluated_value", "dividend"]:
                if col in monthly_logs_df.columns and clean_float(row.get(col), 0.0) < 0:
                    add_quality_issue(issues, "주의", "월별 로그", month, f"{col} 값이 음수입니다.", "입력값을 확인하세요.")

        duplicated_months = pd.Series([m for m in months if m]).value_counts()
        for month, count in duplicated_months[duplicated_months > 1].items():
            add_quality_issue(issues, "주의", "월별 로그", month, f"같은 월이 {int(count)}번 등록되어 있습니다.", "월별 로그를 한 행으로 정리하세요.")

    return sort_quality_issues(issues)
