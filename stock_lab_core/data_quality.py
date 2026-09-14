"""Data quality helpers for Stock Lab account inputs."""

import pandas as pd

from stock_lab_core.config import DIVIDENDS_COLUMNS, HOLDINGS_COLUMNS, MONTHLY_LOG_COLUMNS
from stock_lab_core.asset_classifier import (
    asset_class_marks_fin_score_exempt,
    is_fin_score_exempt_asset,
    is_known_etf_ticker,
    is_known_individual_stock_ticker,
)
from stock_lab_core.formatters import clean_bool, clean_float, clean_int, normalize_ticker


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


def build_data_quality_report_from_frames(
    settings,
    holdings_df,
    holdings_table,
    dividends_df,
    monthly_logs_df,
    watchlist_items,
    fin_scores_df=None,
    fin_scores_error=None,
):
    issues = []
    settings = settings or {}
    holdings_df = holdings_df if holdings_df is not None else pd.DataFrame(columns=HOLDINGS_COLUMNS)
    holdings_table = holdings_table if holdings_table is not None else pd.DataFrame()
    dividends_df = dividends_df if dividends_df is not None else pd.DataFrame(columns=DIVIDENDS_COLUMNS)
    monthly_logs_df = monthly_logs_df if monthly_logs_df is not None else pd.DataFrame(columns=MONTHLY_LOG_COLUMNS)
    watchlist_items = watchlist_items or []
    fin_scores_df = fin_scores_df if fin_scores_df is not None else pd.DataFrame()

    usdkrw = clean_float(settings.get("usdkrw"), 0.0)
    seed_money = clean_float(settings.get("seed_money"), 0.0)
    if usdkrw <= 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "환율이 0 이하입니다.", "자산 관리에서 USD/KRW 환율을 확인하세요.")
    if seed_money < 0:
        add_quality_issue(issues, "위험", "기본 설정", "", "투입 원금이 음수입니다.", "자산 관리에서 투입 원금을 0 이상으로 수정하세요.")

    asset_lookup = {}
    if holdings_df.empty:
        add_quality_issue(issues, "참고", "보유자산", "", "등록된 보유자산이 없습니다.", "처음 사용하는 상태라면 정상입니다.")
    else:
        missing_cols = [col for col in HOLDINGS_COLUMNS if col not in holdings_df.columns]
        if missing_cols:
            add_quality_issue(issues, "위험", "보유자산", "", f"필수 컬럼이 없습니다: {', '.join(missing_cols)}", "백업/복구 파일 또는 DB 컬럼을 확인하세요.")

        ticker_keys = []
        for idx, row in holdings_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            name = str(row.get("name", "")).strip()
            key = normalize_ticker(ticker)
            account_type = str(row.get("account_type", "일반")).strip()
            unique_key = f"{key} ({account_type})" if key else ""

            if ticker:
                ticker_keys.append(unique_key)
                asset_lookup[key] = {
                    "ticker": ticker,
                    "name": name,
                    "is_etf": row.get("is_etf", False),
                    "asset_class": str(row.get("asset_class", "")).strip(),
                    "source": "보유자산",
                }

            if not ticker:
                add_quality_issue(issues, "위험", "보유자산", f"row {idx + 1}", "티커가 비어 있습니다.", "티커를 입력하거나 해당 행을 삭제하세요.")
            if ticker and not name:
                add_quality_issue(issues, "주의", "보유자산", ticker, "자산명이 비어 있습니다.", "전광판에서 보기 쉽게 자산명을 입력하세요.")

            qty = clean_float(row.get("qty"), 0.0)
            avg_price = clean_float(row.get("avg_price"), 0.0)
            target_weight = clean_float(row.get("target_weight"), 0.0)
            if qty < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "보유량이 음수입니다.", "수량 입력값을 확인하세요.")
            if avg_price < 0:
                add_quality_issue(issues, "위험", "보유자산", ticker, "매입가가 음수입니다.", "평균 매입가를 0 이상으로 수정하세요.")
            if target_weight < 0 or target_weight > 100:
                add_quality_issue(issues, "주의", "보유자산", ticker, "목표비중이 0~100 범위를 벗어났습니다.", "리밸런싱 기준 비중을 확인하세요.")

            asset_class = str(row.get("asset_class", "")).strip()
            saved_is_etf = clean_bool(row.get("is_etf", False))
            fin_exempt = is_fin_score_exempt_asset(ticker, saved_is_etf, asset_class, name)
            if saved_is_etf and is_known_individual_stock_ticker(ticker):
                add_quality_issue(issues, "위험", "ETF/재무점수", ticker, "앱 기준 개별주인데 ETF 체크가 켜져 있습니다.", "자산 관리에서 ETF 체크를 끄고 asset_class를 주식 계열로 저장하세요.")
            if fin_exempt and not saved_is_etf:
                add_quality_issue(issues, "주의", "ETF/재무점수", ticker, "ETF/ETN/레버리지로 보이지만 ETF 체크가 꺼져 있습니다.", "자산 관리에서 ETF/ETN/레버리지를 체크하세요.")
            if saved_is_etf and not asset_class_marks_fin_score_exempt(asset_class) and not is_known_etf_ticker(ticker):
                add_quality_issue(issues, "참고", "ETF/재무점수", ticker, "ETF 체크는 켜져 있지만 asset_class가 일반 주식 계열입니다.", "asset_class를 ETF/ETN 계열로 맞추면 분류가 더 안정적입니다.")

        duplicated = pd.Series([key for key in ticker_keys if key]).value_counts()
        for key, count in duplicated[duplicated > 1].items():
            add_quality_issue(issues, "위험", "보유자산", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "한 행으로 합치거나 중복 행을 정리하세요.")

    if not holdings_table.empty and "운용대상" in holdings_table.columns and "리밸런싱목표비중" in holdings_table.columns:
        active_rows = holdings_table[holdings_table["운용대상"].apply(clean_bool)]
        target_sum = active_rows["리밸런싱목표비중"].apply(clean_float).sum() if not active_rows.empty else 0.0
        if target_sum > 100.5:
            add_quality_issue(issues, "위험", "목표비중", "", f"운용대상 목표비중 합계가 {target_sum:.1f}%입니다.", "현금/예비자산 제외 후 목표비중 합계를 100% 이하로 맞추세요.")
        elif len(active_rows) > 0 and target_sum < 50:
            add_quality_issue(issues, "참고", "목표비중", "", f"운용대상 목표비중 합계가 {target_sum:.1f}%로 낮습니다.", "의도한 현금 비중이 큰 상태인지 확인하세요.")

    watch_keys = []
    for idx, item in enumerate(watchlist_items):
        ticker = str(item.get("ticker", "")).strip()
        name = str(item.get("name", "")).strip()
        key = normalize_ticker(ticker)
        if not ticker:
            add_quality_issue(issues, "주의", "관심목록", f"row {idx + 1}", "티커가 비어 있는 관심종목이 있습니다.", "관심목록에서 빈 행을 제거하세요.")
            continue

        watch_keys.append(key)
        asset_lookup.setdefault(key, {
            "ticker": ticker,
            "name": name,
            "is_etf": item.get("is_etf", False),
            "asset_class": str(item.get("asset_class", "")).strip(),
            "source": "관심목록",
        })

        asset_class = str(item.get("asset_class", "")).strip()
        saved_is_etf = clean_bool(item.get("is_etf", False))
        fin_exempt = is_fin_score_exempt_asset(ticker, saved_is_etf, asset_class, name)
        if saved_is_etf and is_known_individual_stock_ticker(ticker):
            add_quality_issue(issues, "위험", "관심목록", ticker, "앱 기준 개별주인데 ETF 체크가 켜져 있습니다.", "관심목록에서 ETF 체크를 끄고 asset_class를 주식 계열로 저장하세요.")
        if fin_exempt and not saved_is_etf:
            add_quality_issue(issues, "주의", "관심목록", ticker, "ETF/ETN/레버리지로 보이지만 ETF 체크가 꺼져 있습니다.", "관심목록 저장 시 ETF/ETN/레버리지로 분류하세요.")
        if fin_exempt and clean_int(item.get("fin_score"), 0) not in (0, None):
            add_quality_issue(issues, "주의", "관심목록", ticker, "재무점수 해당없음 대상인데 관심목록 재무점수가 남아 있습니다.", "관심목록을 다시 저장해 0/해당없음 상태로 맞추세요.")

    duplicated_watch = pd.Series([key for key in watch_keys if key]).value_counts()
    for key, count in duplicated_watch[duplicated_watch > 1].items():
        add_quality_issue(issues, "주의", "관심목록", key, f"같은 티커가 {int(count)}번 등록되어 있습니다.", "중복 관심종목을 정리하세요.")

    if fin_scores_error:
        add_quality_issue(issues, "참고", "재무점수", "", f"재무점수 테이블을 점검하지 못했습니다: {fin_scores_error}", "네트워크 또는 Supabase 연결을 확인하세요.")

    if not fin_scores_df.empty:
        for _, row in fin_scores_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            key = normalize_ticker(ticker)
            if not ticker:
                add_quality_issue(issues, "주의", "재무점수", "", "티커가 비어 있는 재무점수 행이 있습니다.", "fin_scores 데이터를 확인하세요.")
                continue

            manual_score = clean_int(row.get("manual_score"))
            source = str(row.get("source", "")).strip()
            meta = asset_lookup.get(key)
            if meta and is_fin_score_exempt_asset(meta["ticker"], meta["is_etf"], meta["asset_class"], meta["name"]):
                if manual_score is not None or source != "not_applicable":
                    add_quality_issue(issues, "주의", "재무점수", ticker, "ETF/ETN/레버리지인데 수동 재무점수 또는 일반 점수 출처가 남아 있습니다.", "정밀 관측소에서 해당없음 체크 상태를 확인한 뒤 저장하세요.")
            elif key not in asset_lookup and manual_score is not None:
                add_quality_issue(issues, "참고", "재무점수", ticker, "보유/관심목록에 없는 티커의 수동 재무점수가 남아 있습니다.", "더 이상 쓰지 않는 종목이면 정리 후보로 봐도 됩니다.")

    if not dividends_df.empty:
        missing_cols = [col for col in DIVIDENDS_COLUMNS if col not in dividends_df.columns]
        if missing_cols:
            add_quality_issue(issues, "주의", "배당", "", f"배당 필수 컬럼이 없습니다: {', '.join(missing_cols)}", "배당 복구 파일 또는 DB 컬럼을 확인하세요.")
        for idx, row in dividends_df.fillna("").iterrows():
            ticker = str(row.get("ticker", "")).strip()
            date_text = str(row.get("date", "")).strip()
            amount = clean_float(row.get("amount"), 0.0)
            if not ticker:
                add_quality_issue(issues, "주의", "배당", f"row {idx + 1}", "배당 티커가 비어 있습니다.", "배당을 받은 종목 티커를 입력하세요.")
            if amount < 0:
                add_quality_issue(issues, "주의", "배당", ticker, "배당금이 음수입니다.", "환입/정정 목적이 아니라면 금액을 확인하세요.")
            if date_text and pd.isna(pd.to_datetime(date_text, errors="coerce")):
                add_quality_issue(issues, "주의", "배당", ticker, "배당일 형식을 날짜로 읽지 못했습니다.", "YYYY-MM-DD 형식으로 입력하세요.")

    if not monthly_logs_df.empty:
        missing_cols = [col for col in MONTHLY_LOG_COLUMNS if col not in monthly_logs_df.columns]
        if missing_cols:
            add_quality_issue(issues, "주의", "월별 로그", "", f"월별 로그 필수 컬럼이 없습니다: {', '.join(missing_cols)}", "월별 로그 복구 파일 또는 DB 컬럼을 확인하세요.")

        month_values = monthly_logs_df.get("month", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
        duplicated_months = month_values[month_values.ne("")].value_counts()
        for month, count in duplicated_months[duplicated_months > 1].items():
            add_quality_issue(issues, "주의", "월별 로그", month, f"같은 월이 {int(count)}번 기록되어 있습니다.", "월별 로그는 월당 한 행으로 정리하세요.")

        for idx, row in monthly_logs_df.fillna("").iterrows():
            month = str(row.get("month", "")).strip()
            if not month:
                add_quality_issue(issues, "주의", "월별 로그", f"row {idx + 1}", "월 값이 비어 있습니다.", "YYYY-MM 형식으로 입력하세요.")
            elif pd.isna(pd.to_datetime(month, errors="coerce")):
                add_quality_issue(issues, "주의", "월별 로그", month, "월 형식을 날짜로 읽지 못했습니다.", "YYYY-MM 형식으로 입력하세요.")

            for col in ["total_invested", "evaluated_value", "dividend"]:
                if col in monthly_logs_df.columns and clean_float(row.get(col), 0.0) < 0:
                    add_quality_issue(issues, "주의", "월별 로그", month, f"{col} 값이 음수입니다.", "정정 목적이 아니라면 입력값을 확인하세요.")

    return sort_quality_issues(issues)


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
