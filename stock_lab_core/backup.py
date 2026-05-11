"""Backup and recovery CSV helpers for Stock Lab.

This module contains file-format helpers only. It does not write to Supabase,
read Streamlit secrets, or run app-level restore actions.
"""

import io
import zipfile

import pandas as pd

from stock_lab_core.config import (
    DIVIDENDS_COLUMNS,
    FIN_SCORE_COLUMNS,
    HOLDINGS_COLUMNS,
    MONTHLY_LOG_COLUMNS,
    SETTINGS_COLUMNS,
    SWING_RADAR_COLUMNS,
    WATCHLIST_COLUMNS,
)
from stock_lab_core.formatters import normalize_ticker


def count_valid_rows(df, key_columns):
    if df is None or df.empty:
        return 0

    count = 0
    for _, row in df.iterrows():
        if any(str(row.get(col, "")).strip() for col in key_columns):
            count += 1
    return count


def dataframe_to_csv_bytes(df):
    if df is None:
        df = pd.DataFrame()
    return df.to_csv(index=False).encode("utf-8-sig")


def build_portfolio_backup_zip(settings, holdings_df, dividends_df, monthly_logs_df, watchlist_items, dashboard_df, fin_scores_df, swing_radar_df=None):
    settings_df = pd.DataFrame([settings or {}])
    watchlist_df = pd.DataFrame(watchlist_items or [])

    files = {
        "settings.csv": settings_df,
        "holdings.csv": holdings_df,
        "dividends.csv": dividends_df,
        "monthly_logs.csv": monthly_logs_df,
        "watchlist.csv": watchlist_df,
        "fin_scores.csv": fin_scores_df,
        "swing_radar.csv": swing_radar_df if swing_radar_df is not None else pd.DataFrame(columns=SWING_RADAR_COLUMNS),
        "dashboard.csv": dashboard_df,
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, df in files.items():
            zf.writestr(filename, dataframe_to_csv_bytes(df))

    buffer.seek(0)
    return buffer.getvalue()


def classify_recovery_csv(df):
    cols = set(df.columns)

    if {"seed_money", "krw_cash", "usd_cash", "usdkrw", "reserve_target_weight"}.issubset(cols):
        return "settings"
    if {"ticker", "name", "qty", "avg_price", "target_weight", "asset_class", "is_etf", "bucket"}.issubset(cols):
        return "holdings"
    if {"date", "ticker", "amount", "currency"}.issubset(cols):
        return "dividends"
    if {"month", "total_invested", "evaluated_value", "dividend"}.issubset(cols):
        return "monthly_logs"
    if {"name", "ticker", "is_etf", "asset_class"}.issubset(cols):
        return "watchlist"
    if {"ticker", "auto_score", "manual_score", "final_score", "source", "notes_json"}.issubset(cols):
        return "fin_scores"
    if set(SWING_RADAR_COLUMNS).issubset(cols):
        return "swing_radar"
    if {"자산명", "티커", "보유량", "매입가", "원화환산", "bucket"}.issubset(cols):
        return "dashboard"

    return "unknown"


RECOVERY_KIND_INFO = {
    "settings": {
        "label": "기본 설정",
        "required": SETTINGS_COLUMNS,
        "key_columns": ["seed_money", "krw_cash", "usd_cash", "usdkrw"],
        "restore_mode": "마지막 행 기준으로 설정 저장",
    },
    "holdings": {
        "label": "보유자산",
        "required": HOLDINGS_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 보유자산을 대체",
    },
    "dividends": {
        "label": "배당 내역",
        "required": DIVIDENDS_COLUMNS,
        "key_columns": ["date", "ticker"],
        "restore_mode": "기존 배당 내역을 대체",
    },
    "monthly_logs": {
        "label": "월별 로그",
        "required": MONTHLY_LOG_COLUMNS,
        "key_columns": ["month"],
        "unique_column": "month",
        "restore_mode": "기존 월별 로그를 대체",
    },
    "watchlist": {
        "label": "관심목록",
        "required": WATCHLIST_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 관심목록을 대체",
    },
    "fin_scores": {
        "label": "재무점수",
        "required": FIN_SCORE_COLUMNS,
        "key_columns": ["ticker"],
        "restore_mode": "티커별 업서트",
    },
    "swing_radar": {
        "label": "스윙 레이더",
        "required": SWING_RADAR_COLUMNS,
        "key_columns": ["ticker"],
        "unique_column": "ticker",
        "restore_mode": "기존 스윙 레이더를 대체",
    },
    "dashboard": {
        "label": "계산 결과/현금 추출",
        "required": ["자산명", "티커", "보유량", "매입가", "원화환산", "bucket"],
        "key_columns": ["티커"],
        "restore_mode": "현금/환율 보조 추출",
    },
}


def add_recovery_issue(issues, severity, dataset, target, problem, suggestion):
    issues.append({
        "등급": severity,
        "데이터": dataset,
        "대상": str(target or "").strip(),
        "문제": problem,
        "확인/조치": suggestion,
    })


def normalize_recovery_key(value, column):
    text = str(value or "").strip()
    if column in ["ticker", "티커"]:
        return normalize_ticker(text)
    return text


def get_duplicate_recovery_values(df, columns):
    """
    지정된 컬럼(단일 문자열 또는 리스트)을 기준으로 중복된 값과 그 개수를 반환합니다.
    """
    if df is None or df.empty:
        return []
    
    # 1. 단어 하나(문자열)가 들어오면 리스트로 감싸서 처리하게 만듭니다.
    if isinstance(columns, str):
        columns = [columns]
        
    # 2. 우리가 찾는 컬럼들이 엑셀 데이터에 모두 있는지 안전하게 검사합니다.
    for col in columns:
        if col not in df.columns:
            return []
            
    # 3. 그룹으로 묶어서 중복(2개 이상)인 것들을 찾아냅니다.
    sizes = df.groupby(columns, dropna=False).size()
    dups = sizes[sizes > 1]
    
    # 4. 화면에 예쁘게 출력되도록 텍스트를 다듬어서 반환합니다.
    result = []
    for idx, count in dups.items():
        # 컬럼이 여러 개일 경우 (예: MSFT, 일반) 슬래시로 이어붙입니다.
        if isinstance(idx, tuple):
            val_str = " / ".join(str(v) for v in idx)
        else:
            val_str = str(idx)
        result.append((val_str, count))
        
    return result

def read_recovery_csv_bytes(raw_bytes):
    for encoding in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), encoding=encoding)
            df.columns = [str(col).strip().lstrip("\ufeff") for col in df.columns]
            return df
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.BytesIO(raw_bytes))
    df.columns = [str(col).strip().lstrip("\ufeff") for col in df.columns]
    return df


def read_recovery_csv(uploaded_file):
    uploaded_file.seek(0)
    return read_recovery_csv_bytes(uploaded_file.read())


def add_recovery_frame(frames, kind, df):
    if kind in frames:
        frames[kind] = pd.concat([frames[kind], df], ignore_index=True)
    else:
        frames[kind] = df


def collect_recovery_frames(uploaded_files):
    frames = {}
    unknown_files = []
    read_errors = []
    parsed_files = []

    for uploaded_file in uploaded_files or []:
        filename = str(getattr(uploaded_file, "name", "uploaded_file"))
        raw = uploaded_file.getvalue()

        if not raw:
            read_errors.append(f"{filename}: 빈 파일입니다.")
            continue

        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    for zip_name in zf.namelist():
                        if zip_name.endswith("/") or not zip_name.lower().endswith(".csv"):
                            continue

                        file_label = f"{filename}:{zip_name}"
                        try:
                            df = read_recovery_csv_bytes(zf.read(zip_name))
                        except Exception as exc:
                            read_errors.append(f"{file_label}: CSV 읽기 실패 ({exc})")
                            continue

                        kind = classify_recovery_csv(df)
                        if kind == "unknown":
                            unknown_files.append(file_label)
                            continue

                        add_recovery_frame(frames, kind, df)
                        parsed_files.append({
                            "파일": file_label,
                            "데이터": RECOVERY_KIND_INFO.get(kind, {}).get("label", kind),
                            "행수": len(df),
                        })
            except zipfile.BadZipFile:
                read_errors.append(f"{filename}: ZIP 파일로 읽을 수 없습니다.")
            continue

        try:
            df = read_recovery_csv_bytes(raw)
        except Exception as exc:
            read_errors.append(f"{filename}: CSV 읽기 실패 ({exc})")
            continue

        kind = classify_recovery_csv(df)
        if kind == "unknown":
            unknown_files.append(filename)
            continue

        add_recovery_frame(frames, kind, df)
        parsed_files.append({
            "파일": filename,
            "데이터": RECOVERY_KIND_INFO.get(kind, {}).get("label", kind),
            "행수": len(df),
        })

    return frames, unknown_files, read_errors, pd.DataFrame(parsed_files, columns=["파일", "데이터", "행수"])

