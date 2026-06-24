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
    pattern = "|".join(re.escape(str(keyword)) for keyword in keywords)
    filtered = rows[rows["name"].astype(str).str.contains(pattern, case=False, na=False, regex=True)].copy()
    return filtered if not filtered.empty else rows


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


def build_kr_cluster_snapshot(cluster_name: str, top_n: int = 3) -> dict[str, Any]:
    """Return KOSPI industry breadth/representative-stock context for a KR cluster.

    The main cluster score still comes from the app's ETF price-flow model. This
    snapshot is a same-day breadth guardrail so one hot ETF cannot make the whole
    Korean industry look healthy when the underlying constituents are weak.
    """
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
    constituent_rows = _keyword_filtered_rows(cluster_name, constituent_rows)
    if "ticker" in constituent_rows.columns:
        sort_cols = [col for col in ["rank", "volume"] if col in constituent_rows.columns]
        if sort_cols:
            constituent_rows = constituent_rows.sort_values(sort_cols, ascending=[True] * len(sort_cols))
        constituent_rows = constituent_rows.drop_duplicates("ticker", keep="first").copy()

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

    if pd.notna(breadth) and breadth >= 0.60 and (pd.isna(sector_avg) or sector_avg >= 0):
        status = "확산 우세"
    elif (pd.notna(breadth) and breadth < 0.40) or (pd.notna(sector_avg) and sector_avg < 0):
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
        "sectors": sectors,
        "sector_avg_change_pct": sector_avg,
        "constituent_avg_change_pct": const_avg,
        "breadth": breadth,
        "status": status,
        "warning": warning,
        "industries": _records(industry_top, name_col="sector_name", limit=top_n),
        "leaders": _records(representative_rows, limit=top_n),
        "laggards": _records(laggards, limit=top_n),
    }
