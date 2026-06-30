from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_DIR = Path(__file__).resolve().parent / "data"
KOSPI_INDUSTRY_SNAPSHOT_PATH = DATA_DIR / "kr_kospi_industry_snapshot.csv"
KOSPI_SECTOR_CONSTITUENTS_PATH = DATA_DIR / "kr_kospi_sector_constituents.csv"


KR_CLUSTER_INDUSTRY_MAP: dict[str, list[str]] = {
    "AI·반도체": ["전기,전자", "기계,장비"],
    "전력·인프라": ["전기,가스", "기계,장비", "전기,전자", "금속"],
    "원전·우라늄": ["기계,장비", "전기,가스", "금속", "건설"],
    "방산·조선": ["운송장비,부품", "기계,장비", "금속"],
    "K뷰티·콘텐츠": ["화학", "유통", "오락,문화", "it서비스"],
    "바이오": ["제약", "의료,정밀기기"],
    "금융": ["금융", "증권", "보험"],
    "2차전지": ["화학", "전기,전자"],
    "리츠": ["부동산"],
    "에너지·건설": ["전기,가스", "건설", "금속", "기계,장비"],
}

KR_CLUSTER_REPRESENTATIVE_KEYWORDS: dict[str, list[str]] = {
    "AI·반도체": [
        "하이닉스",
        "삼성전자",
        "삼성전기",
        "LG이노텍",
        "한미반도체",
        "DB하이텍",
        "이수페타시스",
        "대덕전자",
        "해성디에스",
        "삼화콘덴서",
    ],
    "전력·인프라": [
        "두산에너빌리티",
        "효성중공업",
        "HD현대일렉트릭",
        "LS ELECTRIC",
        "일진전기",
        "대한전선",
        "한국전력",
    ],
    "방산·조선": ["한화에어로스페이스", "한화오션", "HD현대중공업", "현대로템", "한국항공우주", "LIG넥스원"],
    "K뷰티·콘텐츠": ["아모레", "LG생활건강", "코스맥스", "한국콜마", "하이브", "크래프톤", "카카오", "NAVER"],
    "바이오": ["삼성바이오", "셀트리온", "유한양행", "한미약품", "SK바이오"],
    "금융": ["KB금융", "신한지주", "하나금융", "우리금융", "삼성생명", "미래에셋"],
    "2차전지": ["LG에너지솔루션", "삼성SDI", "LG화학", "포스코퓨처엠", "에코프로"],
    "에너지·건설": ["두산에너빌리티", "한국전력", "현대건설", "GS건설", "SK이노베이션", "S-Oil"],
}


KR_DETAIL_GROUP_ALIASES: dict[str, str] = {
    "AI·반도체": "반도체/HBM",
    "IT/기술": "반도체/HBM",
    "반도체": "반도체/HBM",
    "국내 반도체": "반도체/HBM",
    "국내 AI 반도체·소부장": "반도체/HBM",
    "PCB·기판 글로벌": "기판·MLCC",
    "전자부품·MLCC": "기판·MLCC",
    "포토닉스·광통신": "포토닉스/광통신",
    "전력·인프라": "전력기기",
    "전력인프라": "전력기기",
    "전력기기": "전력기기",
    "전력·에너지 인프라": "전력기기",
    "전력 인프라": "전력기기",
    "원전·우라늄": "원전/SMR",
    "원자력": "원전/SMR",
    "원자력TOP10": "원전/SMR",
    "글로벌 원전·SMR": "원전/SMR",
    "방산·조선": "방산",
    "방산": "방산",
    "우주항공·방산": "방산",
    "조선": "조선",
    "조선·해양": "조선",
    "K뷰티·콘텐츠": "K뷰티",
    "K-뷰티": "K뷰티",
    "화장품": "K뷰티",
    "K-뷰티·소비재": "K뷰티",
    "K콘텐츠": "K콘텐츠",
    "바이오": "바이오",
    "바이오·제약": "바이오",
    "금융": "금융",
    "한국 금융": "금융",
    "2차전지": "2차전지",
    "2차전지 밸류체인": "2차전지",
    "리츠": "리츠/부동산",
    "부동산": "리츠/부동산",
    "에너지·건설": "에너지",
    "에너지": "에너지",
    "건설/유틸": "건설/유틸",
}


KR_DETAIL_GROUPS: dict[str, dict[str, Any]] = {
    "반도체/HBM": {
        "sectors": ["전기,전자", "기계,장비"],
        "subsegments": [
            {"name": "HBM·메모리 대형", "keywords": ["하이닉스", "삼성전자"]},
            {"name": "반도체 장비", "keywords": ["한미반도체", "두산", "DB하이텍"]},
            {"name": "기판·MLCC", "keywords": ["삼성전기", "LG이노텍", "대덕전자", "삼화콘덴서", "코리아써키트"]},
        ],
    },
    "기판·MLCC": {
        "sectors": ["전기,전자", "기계,장비"],
        "subsegments": [
            {"name": "MLCC·수동부품", "keywords": ["삼성전기", "삼화콘덴서"]},
            {"name": "기판·패키징", "keywords": ["LG이노텍", "대덕전자", "코리아써키트"]},
            {"name": "반도체 장비", "keywords": ["한미반도체", "DB하이텍"]},
        ],
    },
    "포토닉스/광통신": {
        "sectors": ["전기,전자", "기계,장비"],
        "subsegments": [
            {"name": "광학·카메라모듈", "keywords": ["LG이노텍", "삼성전기"]},
            {"name": "전자부품", "keywords": ["삼성전기", "삼화콘덴서"]},
            {"name": "반도체 장비", "keywords": ["한미반도체", "DB하이텍"]},
        ],
    },
    "전력기기": {
        "sectors": ["전기,전자", "기계,장비", "전기,가스", "금속"],
        "subsegments": [
            {"name": "변압기·전력기기", "keywords": ["HD현대일렉트릭", "효성중공업", "LS ELECTRIC", "일진전기", "산일전기"]},
            {"name": "전선·케이블", "keywords": ["대한전선", "대원전선", "가온전선"]},
            {"name": "전력·발전", "keywords": ["한국전력", "두산에너빌리티"]},
        ],
    },
    "원전/SMR": {
        "sectors": ["기계,장비", "전기,가스", "건설", "금속"],
        "subsegments": [
            {"name": "원전·발전", "keywords": ["두산에너빌리티", "한국전력"]},
            {"name": "EPC·건설", "keywords": ["현대건설", "대우건설", "DL이앤씨", "GS건설"]},
            {"name": "소재·기자재", "keywords": ["금양", "부국철강", "포스코스틸리온"]},
        ],
    },
    "방산": {
        "sectors": ["운송장비,부품", "기계,장비", "금속"],
        "subsegments": [
            {"name": "방산 대형", "keywords": ["한화에어로스페이스", "현대로템", "한국항공우주", "LIG"]},
            {"name": "방산·조선 혼합", "keywords": ["한화오션", "HD현대중공업"]},
            {"name": "기계·부품", "keywords": ["두산", "한화엔진"]},
        ],
    },
    "조선": {
        "sectors": ["운송장비,부품", "기계,장비", "금속"],
        "subsegments": [
            {"name": "조선 대형", "keywords": ["한화오션", "HD현대중공업", "HD현대미포", "삼성중공업"]},
            {"name": "조선 기자재", "keywords": ["한화엔진", "한국카본", "세진중공업"]},
            {"name": "운송·부품", "keywords": ["현대모비스", "HL만도", "한온시스템"]},
        ],
    },
    "K뷰티": {
        "sectors": ["화학", "유통"],
        "subsegments": [
            {"name": "화장품 브랜드", "keywords": ["아모레", "LG생활건강"]},
            {"name": "ODM·제조", "keywords": ["코스맥스", "한국콜마", "콜마"]},
            {"name": "소비·유통", "keywords": ["신세계", "광주신세계", "더본코리아"]},
        ],
    },
    "K콘텐츠": {
        "sectors": ["오락,문화", "it서비스", "유통"],
        "subsegments": [
            {"name": "플랫폼", "keywords": ["NAVER", "카카오"]},
            {"name": "엔터·콘텐츠", "keywords": ["하이브", "CJ", "제일기획"]},
            {"name": "게임", "keywords": ["크래프톤", "엔씨소프트", "넷마블"]},
        ],
    },
    "바이오": {
        "sectors": ["제약", "의료,정밀기기"],
        "subsegments": [
            {"name": "바이오 대형/CDMO", "keywords": ["삼성바이오", "셀트리온"]},
            {"name": "제약 대형", "keywords": ["유한양행", "한미약품", "한올바이오파마"]},
            {"name": "의료기기·진단", "keywords": ["덴티움", "클래시스", "의료"]},
        ],
    },
    "금융": {
        "sectors": ["금융", "증권", "보험"],
        "subsegments": [
            {"name": "은행지주", "keywords": ["KB금융", "신한지주", "하나금융", "우리금융"]},
            {"name": "보험", "keywords": ["삼성생명", "삼성화재", "DB손해보험", "한화생명"]},
            {"name": "증권", "keywords": ["미래에셋증권", "키움증권", "NH투자증권"]},
        ],
    },
    "2차전지": {
        "sectors": ["화학", "전기,전자"],
        "subsegments": [
            {"name": "배터리 셀", "keywords": ["LG에너지솔루션", "삼성SDI"]},
            {"name": "소재", "keywords": ["LG화학", "포스코퓨처엠", "SKC"]},
            {"name": "부품·장비", "keywords": ["후성", "삼화콘덴서"]},
        ],
    },
    "리츠/부동산": {
        "sectors": ["부동산"],
        "subsegments": [
            {"name": "리츠", "keywords": ["리츠"]},
            {"name": "부동산", "keywords": ["부동산"]},
        ],
    },
    "에너지": {
        "sectors": ["전기,가스", "화학", "기계,장비"],
        "subsegments": [
            {"name": "정유·화학", "keywords": ["SK이노베이션", "S-Oil", "GS"]},
            {"name": "전력·가스", "keywords": ["한국전력", "한국가스공사"]},
            {"name": "발전·에너지장비", "keywords": ["두산에너빌리티", "효성중공업"]},
        ],
    },
    "건설/유틸": {
        "sectors": ["건설", "전기,가스", "금속"],
        "subsegments": [
            {"name": "건설/EPC", "keywords": ["현대건설", "대우건설", "DL이앤씨", "GS건설"]},
            {"name": "유틸리티", "keywords": ["한국전력", "한국가스공사"]},
            {"name": "건설소재", "keywords": ["부국철강", "포스코스틸리온", "다스코"]},
        ],
    },
}


def _clean_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
        errors="coerce",
    )


def _normalize_bool_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _sector_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("/", ",").replace(" ", "")


def _keyword_filtered_rows(cluster_name: str, rows: pd.DataFrame) -> pd.DataFrame:
    keywords = KR_CLUSTER_REPRESENTATIVE_KEYWORDS.get(cluster_name, [])
    if not keywords or rows.empty or "name" not in rows.columns:
        return rows
    return _keyword_filtered_rows_by_keywords(rows, keywords, fallback=rows)


def _keyword_filtered_rows_by_keywords(
    rows: pd.DataFrame,
    keywords: list[str],
    fallback: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if not keywords or rows.empty or "name" not in rows.columns:
        return rows
    pattern = "|".join(re.escape(str(keyword)) for keyword in keywords)
    filtered = rows[rows["name"].astype(str).str.contains(pattern, case=False, na=False, regex=True)].copy()
    if not filtered.empty:
        return filtered
    return rows if fallback is None else fallback


def _resolve_detail_group(detail_name: str = "", cluster_name: str = "") -> tuple[str, dict[str, Any]]:
    candidates = [str(detail_name or "").strip(), str(cluster_name or "").strip()]
    for candidate in candidates:
        if not candidate:
            continue
        direct = KR_DETAIL_GROUPS.get(candidate)
        if direct:
            return candidate, direct
        alias = KR_DETAIL_GROUP_ALIASES.get(candidate)
        if alias and alias in KR_DETAIL_GROUPS:
            return alias, KR_DETAIL_GROUPS[alias]

    joined = " ".join(candidate for candidate in candidates if candidate)
    for keyword, alias in KR_DETAIL_GROUP_ALIASES.items():
        if keyword and keyword in joined and alias in KR_DETAIL_GROUPS:
            return alias, KR_DETAIL_GROUPS[alias]
    return "", {}


def _detail_keywords(detail_group: dict[str, Any]) -> list[str]:
    keywords: list[str] = []
    for segment in detail_group.get("subsegments", []) or []:
        keywords.extend(str(keyword) for keyword in segment.get("keywords", []) or [])
    return keywords


def _subsector_records(rows: pd.DataFrame, detail_group: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    if rows.empty or not detail_group:
        return []
    records: list[dict[str, Any]] = []
    for segment in detail_group.get("subsegments", []) or []:
        name = str(segment.get("name", "") or "").strip()
        keywords = [str(keyword) for keyword in segment.get("keywords", []) or [] if str(keyword).strip()]
        if not name or not keywords:
            continue
        segment_rows = _keyword_filtered_rows_by_keywords(rows, keywords, fallback=pd.DataFrame())
        valid = segment_rows.dropna(subset=["change_pct"]) if "change_pct" in segment_rows else pd.DataFrame()
        if valid.empty:
            continue
        records.append(
            {
                "name": name,
                "ticker": "",
                "change_pct": float(valid["change_pct"].mean()),
                "breadth": float((valid["change_pct"] > 0).mean()),
                "count": int(len(valid)),
            }
        )
    return records[:limit]


def _empty_industry_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "sector_code",
            "sector_name",
            "current",
            "change_abs",
            "change_sign",
            "change_pct",
            "volume",
        ]
    )


def _empty_constituent_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "sector",
            "rank",
            "ticker",
            "name",
            "current",
            "change_abs",
            "change_sign",
            "change_pct",
            "volume",
            "is_fund_like",
        ]
    )


@lru_cache(maxsize=1)
def load_kospi_industry_snapshot() -> pd.DataFrame:
    if not KOSPI_INDUSTRY_SNAPSHOT_PATH.exists():
        return _empty_industry_df()
    try:
        df = pd.read_csv(KOSPI_INDUSTRY_SNAPSHOT_PATH)
    except Exception:
        return _empty_industry_df()
    if "change_pct" in df.columns:
        df["change_pct"] = _clean_numeric_series(df["change_pct"])
    if "volume" in df.columns:
        df["volume"] = _clean_numeric_series(df["volume"])
    return df


@lru_cache(maxsize=1)
def load_kospi_sector_constituents() -> pd.DataFrame:
    if not KOSPI_SECTOR_CONSTITUENTS_PATH.exists():
        return _empty_constituent_df()
    try:
        df = pd.read_csv(KOSPI_SECTOR_CONSTITUENTS_PATH)
    except Exception:
        return _empty_constituent_df()
    if "change_pct" in df.columns:
        df["change_pct"] = _clean_numeric_series(df["change_pct"])
    if "volume" in df.columns:
        df["volume"] = _clean_numeric_series(df["volume"])
    if "rank" in df.columns:
        df["rank"] = _clean_numeric_series(df["rank"])
    if "is_fund_like" in df.columns:
        df["is_fund_like"] = _normalize_bool_series(df["is_fund_like"])
    else:
        df["is_fund_like"] = False
    return df


def _coerce_float_value(value: Any) -> float:
    try:
        text = str(value or "").strip().replace(",", "").replace("%", "")
        if not text or text.lower() in {"nan", "none", "null"}:
            return float("nan")
        return float(text)
    except Exception:
        return float("nan")


def _price_lookup_key(ticker: Any) -> str:
    return str(ticker or "").strip().upper()


def _load_latest_prices_for_snapshot(tickers: list[str]) -> dict[str, float]:
    try:
        from stock_lab_core.prices import load_latest_prices_batch

        return load_latest_prices_batch(tickers)
    except Exception:
        return {}


def _align_live_price_scale(live_price: float, reference_price: float) -> float:
    """Align Naver live prices to the stored KOSPI snapshot scale when needed."""
    if not np.isfinite(live_price) or not np.isfinite(reference_price):
        return live_price
    if live_price <= 0 or reference_price <= 0:
        return live_price

    ratio = live_price / reference_price
    if 0.50 <= ratio <= 1.50:
        return live_price

    candidates = [live_price]
    for factor in (10.0, 100.0, 1000.0, 0.1, 0.01, 0.001):
        candidates.append(live_price * factor)
    return min(candidates, key=lambda value: abs((value / reference_price) - 1.0))


def _infer_previous_close(row: pd.Series, current_price: float, change_pct: float) -> float:
    if np.isfinite(current_price) and current_price > 0 and np.isfinite(change_pct) and change_pct > -99:
        divisor = 1.0 + (change_pct / 100.0)
        if divisor > 0:
            return current_price / divisor

    change_abs = _coerce_float_value(row.get("change_sign", np.nan))
    if np.isfinite(current_price) and current_price > 0 and np.isfinite(change_abs):
        previous_close = current_price - change_abs
        if previous_close > 0:
            return previous_close
    return float("nan")


def _refresh_constituent_rows_with_live_prices(rows: pd.DataFrame) -> pd.DataFrame:
    """Refresh current price/change_pct before picking KR cluster leaders/laggards."""
    if rows.empty or "ticker" not in rows.columns or "current" not in rows.columns:
        return rows

    tickers = [str(ticker or "").strip() for ticker in rows["ticker"].tolist() if str(ticker or "").strip()]
    latest_prices = _load_latest_prices_for_snapshot(tickers)
    if not latest_prices:
        return rows

    refreshed = rows.copy()
    if "change_pct" not in refreshed.columns:
        refreshed["change_pct"] = np.nan
    for numeric_col in ("current", "change_pct", "change_sign"):
        if numeric_col in refreshed.columns:
            refreshed[numeric_col] = _clean_numeric_series(refreshed[numeric_col]).astype("float64")

    for idx, row in refreshed.iterrows():
        ticker = str(row.get("ticker", "") or "").strip()
        live_price = _coerce_float_value(latest_prices.get(_price_lookup_key(ticker), np.nan))
        if not np.isfinite(live_price) or live_price <= 0:
            continue

        stored_current = _coerce_float_value(row.get("current", np.nan))
        stored_pct = _coerce_float_value(row.get("change_pct", np.nan))
        aligned_live = _align_live_price_scale(live_price, stored_current)
        previous_close = _infer_previous_close(row, stored_current, stored_pct)
        refreshed.at[idx, "current"] = aligned_live

        if np.isfinite(previous_close) and previous_close > 0:
            new_change_abs = aligned_live - previous_close
            refreshed.at[idx, "change_pct"] = (aligned_live / previous_close - 1.0) * 100.0
            if "change_sign" in refreshed.columns:
                refreshed.at[idx, "change_sign"] = new_change_abs
            if "change_abs" in refreshed.columns:
                if new_change_abs > 0:
                    refreshed.at[idx, "change_abs"] = "▲"
                elif new_change_abs < 0:
                    refreshed.at[idx, "change_abs"] = "▼"
                else:
                    refreshed.at[idx, "change_abs"] = ""
    return refreshed


def _records(df: pd.DataFrame, name_col: str = "name", limit: int = 3) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        rows.append(
            {
                "name": str(row.get(name_col, "") or "").strip(),
                "ticker": str(row.get("ticker", "") or "").strip(),
                "change_pct": float(row.get("change_pct", np.nan))
                if pd.notna(row.get("change_pct", np.nan))
                else float("nan"),
            }
        )
    return rows


def build_kr_cluster_snapshot(
    cluster_name: str,
    top_n: int = 3,
    detail_name: str = "",
    live_prices: bool = True,
) -> dict[str, Any]:
    """Return KOSPI industry breadth/representative-stock context for a KR cluster.

    The main cluster score still comes from the app's ETF price-flow model. This
    snapshot is a same-day breadth guardrail so one hot ETF cannot make the whole
    Korean industry look healthy when the underlying constituents are weak.
    """
    detail_key, detail_group = _resolve_detail_group(detail_name=detail_name, cluster_name=cluster_name)
    sectors = detail_group.get("sectors", []) if detail_group else []
    if not sectors:
        sectors = KR_CLUSTER_INDUSTRY_MAP.get(str(cluster_name or "").strip(), [])
    if not sectors:
        return {}
    sector_keys = {_sector_key(sector) for sector in sectors}

    industry_df = load_kospi_industry_snapshot()
    constituent_df = load_kospi_sector_constituents()
    if industry_df.empty and constituent_df.empty:
        return {}

    if "sector_name" in industry_df.columns:
        industry_rows = industry_df[industry_df["sector_name"].map(_sector_key).isin(sector_keys)].copy()
    else:
        industry_rows = _empty_industry_df()
    if "sector" in constituent_df.columns:
        constituent_rows = constituent_df[constituent_df["sector"].map(_sector_key).isin(sector_keys)].copy()
    else:
        constituent_rows = _empty_constituent_df()
    if "is_fund_like" in constituent_rows.columns:
        constituent_rows = constituent_rows[~constituent_rows["is_fund_like"].fillna(False)].copy()
    if detail_group:
        detail_rows = _keyword_filtered_rows_by_keywords(
            constituent_rows,
            _detail_keywords(detail_group),
            fallback=pd.DataFrame(),
        )
        constituent_rows = detail_rows if not detail_rows.empty else _keyword_filtered_rows(cluster_name, constituent_rows)
    else:
        constituent_rows = _keyword_filtered_rows(cluster_name, constituent_rows)
    if "ticker" in constituent_rows.columns:
        sort_cols = [col for col in ["rank", "volume"] if col in constituent_rows.columns]
        if sort_cols:
            constituent_rows = constituent_rows.sort_values(sort_cols, ascending=[True] * len(sort_cols))
        constituent_rows = constituent_rows.drop_duplicates("ticker", keep="first").copy()
    if live_prices:
        constituent_rows = _refresh_constituent_rows_with_live_prices(constituent_rows)

    if industry_rows.empty and constituent_rows.empty:
        return {}

    sector_avg = float(industry_rows["change_pct"].mean()) if "change_pct" in industry_rows else float("nan")
    valid_const = constituent_rows.dropna(subset=["change_pct"]) if "change_pct" in constituent_rows else pd.DataFrame()
    breadth = float((valid_const["change_pct"] > 0).mean()) if not valid_const.empty else float("nan")
    const_avg = float(valid_const["change_pct"].mean()) if not valid_const.empty else float("nan")

    industry_top = (
        industry_rows.sort_values("change_pct", ascending=False)
        if "change_pct" in industry_rows
        else industry_rows
    )
    subsector_rows = _subsector_records(valid_const, detail_group, limit=top_n)
    representative_rows = (
        valid_const.sort_values(["rank", "volume"], ascending=[True, False])
        if not valid_const.empty
        else valid_const
    )
    laggards = (
        valid_const[valid_const["change_pct"] < 0].sort_values(["rank", "volume"], ascending=[True, False])
        if not valid_const.empty
        else valid_const
    )

    status_avg = const_avg if pd.notna(const_avg) else sector_avg
    if pd.notna(breadth) and breadth >= 0.60 and (pd.isna(status_avg) or status_avg >= 0):
        status = "확산 우세"
    elif (pd.notna(breadth) and breadth < 0.40) or (pd.notna(status_avg) and status_avg < 0):
        status = "확산 약함"
    else:
        status = "혼조"

    warning = ""
    if status == "확산 약함":
        warning = "KOSPI 업종 내부 확산 약함: ETF·대장주 쏠림 가능"
    elif pd.notna(breadth) and breadth < 0.50:
        warning = "KOSPI 업종 내부 확인 필요: 상승 종목 비율이 낮음"

    return {
        "cluster": cluster_name,
        "detail": detail_key,
        "sectors": sectors,
        "sector_avg_change_pct": sector_avg,
        "constituent_avg_change_pct": const_avg,
        "breadth": breadth,
        "status": status,
        "warning": warning,
        "industries": _records(industry_top, name_col="sector_name", limit=top_n),
        "subsectors": subsector_rows,
        "leaders": _records(representative_rows, limit=top_n),
        "laggards": _records(laggards, limit=top_n),
    }
