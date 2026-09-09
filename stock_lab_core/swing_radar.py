"""Pure swing radar helpers.

This module owns swing-radar templates and DataFrame shaping only. It should
not import Streamlit, Supabase, or price/scoring code.
"""

from __future__ import annotations

import pandas as pd

from stock_lab_core.asset_classifier import is_fin_score_exempt_asset
from stock_lab_core.config import (
    RESERVE_BUCKETS,
    RESERVE_TICKERS,
    SWING_RADAR_COLUMNS,
    SWING_TEMPLATE_TEXT_FIELDS,
)
from stock_lab_core.formatters import dataframe_from_rows, normalize_bucket, normalize_ticker


SWING_TEMPLATE_MAP = {
    "267260": {
        "idea": "전력기기 슈퍼사이클, 북미 전력망 투자, 수주/마진 성장 모멘텀",
        "check_1": "수주잔고와 신규수주 흐름이 유지되는지",
        "check_2": "영업이익률이 둔화되지 않는지",
        "check_3": "전력 인프라/변압기 수요 뉴스가 계속 나오는지",
        "risk_1": "실적 쇼크 또는 마진 둔화",
        "risk_2": "수주 피크아웃 우려",
        "risk_3": "고밸류 구간에서 장기 이평선 이탈",
        "entry_rule": "시스템 승인 + 과열 해소 + 목표비중 미달",
        "exit_rule": "시스템 차단, 추세 훼손, 실적/마진 둔화 확인",
        "next_event": "분기 실적/수주 업데이트",
    },
    "278470": {
        "idea": "뷰티 디바이스/화장품 성장, 해외 확장, 실적 모멘텀",
        "check_1": "해외 매출 성장률이 유지되는지",
        "check_2": "영업이익률과 마케팅비 부담이 관리되는지",
        "check_3": "신제품/채널 확장 뉴스가 이어지는지",
        "risk_1": "성장률 둔화",
        "risk_2": "밸류 부담과 수급 이탈",
        "risk_3": "보호예수/대주주/경쟁 심화 이슈",
        "entry_rule": "시스템 승인 + 눌림목 + 과열 신호 해소",
        "exit_rule": "시스템 차단, 추세 훼손, 성장률 둔화 확인",
        "next_event": "분기 실적/해외 매출 업데이트",
    },
}


DEFAULT_SWING_TEMPLATE = {
    "idea": "시스템 승인 기반 단기/중기 스윙 후보",
    "check_1": "실적 또는 가이던스가 훼손되지 않는지",
    "check_2": "섹터 돈흐름과 상대강도가 유지되는지",
    "check_3": "추세와 수급이 급격히 꺾이지 않는지",
    "risk_1": "실적 쇼크 또는 주요 뉴스 악화",
    "risk_2": "MFI 과열 뒤 수급 이탈",
    "risk_3": "MA50/MA120 등 주요 추세선 이탈",
    "entry_rule": "시스템 승인 + 목표비중 미달 + 과열 해소",
    "exit_rule": "시스템 차단, 추세 훼손, 투자 아이디어 무효화",
    "next_event": "다음 실적/주요 뉴스 확인",
}


DEFAULT_SWING_ETF_TEMPLATE = {
    "idea": "섹터/지수 흐름 기반 ETF 스윙 후보",
    "check_1": "돈흐름 레이더에서 해당 ETF나 관련 섹터 흐름이 유지되는지",
    "check_2": "시장벤치 대비 RS가 약해지지 않는지",
    "check_3": "MFI/RSI 과열 뒤 수급 이탈이 나오지 않는지",
    "risk_1": "기초지수 추세 훼손",
    "risk_2": "레버리지/테마 ETF의 변동성 확대",
    "risk_3": "매크로 리스크 상승 또는 금리/환율 급변",
    "entry_rule": "돈흐름 우호 + 시스템 승인 + 과열 해소",
    "exit_rule": "시스템 차단, 기초지수 추세 훼손, 돈흐름 둔화",
    "next_event": "돈흐름 레이더/시장벤치 RS 주간 확인",
}


SWING_EXCLUDED_TICKERS = {"krw_cash", "usd_cash", "cash"}


def get_swing_template(ticker, is_etf=False, asset_class=""):
    key = normalize_ticker(ticker)
    if key in SWING_TEMPLATE_MAP:
        return dict(SWING_TEMPLATE_MAP[key])
    if is_fin_score_exempt_asset(ticker, is_etf, asset_class):
        return dict(DEFAULT_SWING_ETF_TEMPLATE)
    return dict(DEFAULT_SWING_TEMPLATE)


def make_swing_candidate_row(name, ticker, asset_class="", is_etf=False, today=None):
    template = get_swing_template(ticker, is_etf=is_etf, asset_class=asset_class)
    row = {col: "" for col in SWING_RADAR_COLUMNS}
    row.update(template)
    row.update({
        "ticker": str(ticker).strip(),
        "name": str(name or ticker).strip(),
        "asset_class": str(asset_class or "").strip(),
        "status": "진행",
        "decision": "관망",
        "importance": "중",
        "last_checked": str(today or pd.Timestamp.today().strftime("%Y-%m-%d")),
    })
    return row


def infer_swing_row_is_etf(row):
    ticker = str(row.get("ticker", "")).strip()
    asset_class = str(row.get("asset_class", "")).strip()
    name = str(row.get("name", "")).strip()
    return is_fin_score_exempt_asset(ticker, False, asset_class, name)


def fill_empty_swing_templates(df, today=None):
    if df is None or df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    today_value = str(today or pd.Timestamp.today().strftime("%Y-%m-%d"))

    for idx, row in work.iterrows():
        ticker = str(row.get("ticker", "")).strip()
        if not ticker:
            continue

        asset_class = str(row.get("asset_class", "")).strip()
        template = get_swing_template(
            ticker,
            is_etf=infer_swing_row_is_etf(row),
            asset_class=asset_class,
        )

        for col in SWING_TEMPLATE_TEXT_FIELDS:
            if not str(work.at[idx, col] or "").strip():
                work.at[idx, col] = template.get(col, "")

        if not str(work.at[idx, "status"] or "").strip():
            work.at[idx, "status"] = "진행"
        if not str(work.at[idx, "decision"] or "").strip():
            work.at[idx, "decision"] = "관망"
        if not str(work.at[idx, "importance"] or "").strip():
            work.at[idx, "importance"] = "중"
        if not str(work.at[idx, "last_checked"] or "").strip():
            work.at[idx, "last_checked"] = today_value

    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


def set_swing_row_status(df, ticker, status, today=None):
    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    key = normalize_ticker(ticker)
    mask = work["ticker"].apply(normalize_ticker) == key
    if mask.any():
        work.loc[mask, "status"] = status
        work.loc[mask, "last_checked"] = str(today or pd.Timestamp.today().strftime("%Y-%m-%d"))
    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


def remove_swing_row(df, ticker):
    work = dataframe_from_rows(df, SWING_RADAR_COLUMNS).copy()
    key = normalize_ticker(ticker)
    work = work[work["ticker"].apply(normalize_ticker) != key]
    return dataframe_from_rows(work, SWING_RADAR_COLUMNS)


def is_swing_excluded_ticker(ticker):
    key = normalize_ticker(ticker)
    return (not key) or key in RESERVE_TICKERS or key in SWING_EXCLUDED_TICKERS


def _infer_bucket_for_swing(ticker, value=""):
    key = normalize_ticker(ticker)
    raw = str(value or "").strip().lower()
    if key in RESERVE_TICKERS and raw in ["", "core", "nan", "none"]:
        return "reserve"
    if raw in ["core", "swing", "reserve", "cash", "leverage"]:
        return raw
    return "core"


def is_swing_candidate_allowed(ticker, is_etf=False, bucket="", asset_class="", include_etf=False):
    if is_swing_excluded_ticker(ticker):
        return False
    if normalize_bucket(_infer_bucket_for_swing(ticker, bucket)) in RESERVE_BUCKETS:
        return False
    asset_class_text = str(asset_class or "").strip().lower()
    if asset_class_text in ["cash", "reserve", "krw_cash", "usd_cash"]:
        return False
    if (not include_etf) and is_fin_score_exempt_asset(ticker, is_etf, asset_class_text):
        return False
    return True


def build_swing_radar_df(
    saved_df,
    *,
    auto_candidates=None,
    include_hidden=False,
    include_auto=True,
):
    rows_by_key = {}

    if saved_df is not None and not saved_df.empty:
        for _, row in saved_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            rows_by_key[normalize_ticker(ticker)] = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}

    if include_auto:
        for key, item in (auto_candidates or {}).items():
            ticker_value = item.get("ticker") or key
            candidate_key = normalize_ticker(ticker_value)
            if not candidate_key:
                continue
            if candidate_key not in rows_by_key:
                rows_by_key[candidate_key] = make_swing_candidate_row(
                    item.get("name") or ticker_value,
                    ticker_value,
                    item.get("asset_class", ""),
                    item.get("is_etf", False),
                )
            else:
                if not str(rows_by_key[candidate_key].get("name", "")).strip():
                    rows_by_key[candidate_key]["name"] = item.get("name")
                if not str(rows_by_key[candidate_key].get("asset_class", "")).strip():
                    rows_by_key[candidate_key]["asset_class"] = item.get("asset_class", "")

    df = pd.DataFrame(list(rows_by_key.values()))
    for col in SWING_RADAR_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    if df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    if not include_hidden:
        df = df[df["status"].astype(str).str.strip() != "숨김"]

    if df.empty:
        return dataframe_from_rows([], SWING_RADAR_COLUMNS)

    return df[SWING_RADAR_COLUMNS].sort_values(["importance", "name"], ascending=[True, True])


def merge_swing_editor_with_saved(saved_df, edited_df, visible_df):
    rows_by_key = {}

    if saved_df is not None and not saved_df.empty:
        for _, row in saved_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            rows_by_key[normalize_ticker(ticker)] = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}

    visible_keys = {
        normalize_ticker(row.get("ticker", ""))
        for _, row in visible_df.iterrows()
        if str(row.get("ticker", "")).strip()
    } if visible_df is not None and not visible_df.empty else set()

    edited_keys = {
        normalize_ticker(row.get("ticker", ""))
        for _, row in edited_df.iterrows()
        if str(row.get("ticker", "")).strip()
    } if edited_df is not None and not edited_df.empty else set()

    for key in visible_keys - edited_keys:
        rows_by_key.pop(key, None)

    if edited_df is not None and not edited_df.empty:
        for _, row in edited_df.iterrows():
            ticker = str(row.get("ticker", "")).strip()
            if not ticker or is_swing_excluded_ticker(ticker):
                continue
            rows_by_key[normalize_ticker(ticker)] = {col: row.get(col, "") for col in SWING_RADAR_COLUMNS}

    merged = pd.DataFrame(list(rows_by_key.values()))
    for col in SWING_RADAR_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""
    return dataframe_from_rows(merged, SWING_RADAR_COLUMNS) if not merged.empty else dataframe_from_rows([], SWING_RADAR_COLUMNS)


def get_swing_editor_base_key(df, show_hidden, include_auto, include_etf):
    if df is None or df.empty:
        ticker_part = "empty"
    else:
        ticker_part = "|".join(
            df["ticker"].astype(str).apply(normalize_ticker).fillna("").tolist()
        )
    return f"{show_hidden}|{include_auto}|{include_etf}|{ticker_part}"
