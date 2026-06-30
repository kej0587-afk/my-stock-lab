from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_DIR = Path(__file__).resolve().parent / "data"
US_INDUSTRY_SNAPSHOT_PATH = DATA_DIR / "us_industry_snapshot.csv"
US_SECTOR_CONSTITUENTS_PATH = DATA_DIR / "us_sector_constituents.csv"


US_DETAIL_GROUP_ALIASES: dict[str, str] = {
    "AI·반도체": "AI·빅테크",
    "반도체": "반도체",
    "반도체 iShares": "반도체",
    "반도체 VanEck": "반도체",
    "미국 반도체": "반도체",
    "PCB·기판 글로벌": "반도체",
    "전자부품·MLCC": "반도체",
    "포토닉스·광통신": "포토닉스·광통신",
    "광통신": "포토닉스·광통신",
    "포토닉스": "포토닉스·광통신",
    "소프트웨어·사이버": "소프트웨어",
    "소프트웨어": "소프트웨어",
    "사이버보안": "소프트웨어",
    "미국 AI·빅테크": "AI·빅테크",
    "로봇/AI": "AI·로봇",
    "양자컴퓨팅": "AI·로봇",
    "핀테크": "금융·핀테크",
    "금융": "금융·핀테크",
    "미국 금융·핀테크": "금융·핀테크",
    "바이오": "헬스케어·바이오",
    "헬스케어": "헬스케어·바이오",
    "미국 헬스케어·바이오텍": "헬스케어·바이오",
    "바이오·헬스": "헬스케어·바이오",
    "방산·우주": "방산·항공",
    "방산": "방산·항공",
    "항공방산": "방산·항공",
    "우주/위성통신": "우주·통신",
    "우주·위성 RF통신": "우주·통신",
    "우주항공·방산": "방산·항공",
    "산업재·원자재": "산업재·원자재",
    "산업재": "산업재·인프라",
    "글로벌 인프라·산업재": "산업재·인프라",
    "인프라": "산업재·인프라",
    "주택건설": "주택·건설",
    "소재": "소재",
    "원자재(구리)": "소재",
    "에너지": "에너지·유틸",
    "신재생": "에너지·유틸",
    "AI전력그리드": "전력·그리드",
    "전력·인프라": "전력·그리드",
    "전력·에너지 인프라": "전력·그리드",
    "글로벌 원전·SMR": "전력·그리드",
    "유틸리티": "에너지·유틸",
    "부동산": "리츠·부동산",
    "소비재": "소비재",
    "경기소비재": "경기소비재",
    "필수소비재": "필수소비재",
    "2차전지·EV": "EV·배터리",
    "리튬/EV밸류체인": "EV·배터리",
}


US_DETAIL_GROUPS: dict[str, dict[str, Any]] = {
    "반도체": {
        "sectors": ["반도체및반도체장비", "컴퓨터및전자장비"],
        "subsegments": [
            {"name": "반도체·장비", "sectors": ["반도체및반도체장비"]},
            {"name": "컴퓨터·전자장비", "sectors": ["컴퓨터및전자장비"]},
            {"name": "통신장비", "sectors": ["통신장비"]},
        ],
    },
    "포토닉스·광통신": {
        "sectors": ["통신장비", "반도체및반도체장비", "컴퓨터및전자장비"],
        "subsegments": [
            {"name": "광통신·통신장비", "sectors": ["통신장비"]},
            {"name": "반도체·장비", "sectors": ["반도체및반도체장비"]},
            {"name": "컴퓨터·전자장비", "sectors": ["컴퓨터및전자장비"]},
        ],
    },
    "소프트웨어": {
        "sectors": ["소프트웨어및IT서비스"],
        "subsegments": [
            {"name": "소프트웨어·IT서비스", "sectors": ["소프트웨어및IT서비스"]},
            {"name": "컴퓨터·전자장비", "sectors": ["컴퓨터및전자장비"]},
        ],
    },
    "AI·빅테크": {
        "sectors": ["소프트웨어및IT서비스", "컴퓨터및전자장비", "반도체및반도체장비", "미디어"],
        "subsegments": [
            {"name": "소프트웨어·클라우드", "sectors": ["소프트웨어및IT서비스"]},
            {"name": "AI 하드웨어", "sectors": ["컴퓨터및전자장비", "반도체및반도체장비"]},
            {"name": "미디어·플랫폼", "sectors": ["미디어"]},
        ],
    },
    "AI·로봇": {
        "sectors": ["소프트웨어및IT서비스", "컴퓨터및전자장비", "기계및전기장비", "반도체및반도체장비"],
        "subsegments": [
            {"name": "로봇·자동화", "sectors": ["기계및전기장비"]},
            {"name": "AI 소프트웨어", "sectors": ["소프트웨어및IT서비스"]},
            {"name": "AI 하드웨어", "sectors": ["컴퓨터및전자장비", "반도체및반도체장비"]},
        ],
    },
    "금융·핀테크": {
        "sectors": ["금융서비스", "상업은행", "보험"],
        "subsegments": [
            {"name": "금융서비스·핀테크", "sectors": ["금융서비스"]},
            {"name": "은행", "sectors": ["상업은행"]},
            {"name": "보험", "sectors": ["보험"]},
        ],
    },
    "헬스케어·바이오": {
        "sectors": ["건강관리장비및서비스", "제약", "바이오"],
        "subsegments": [
            {"name": "헬스케어 장비·서비스", "sectors": ["건강관리장비및서비스"]},
            {"name": "제약", "sectors": ["제약"]},
            {"name": "바이오", "sectors": ["바이오"]},
        ],
    },
    "방산·항공": {
        "sectors": ["우주항공및국방", "항공사및항공운송", "기계및전기장비"],
        "subsegments": [
            {"name": "우주항공·국방", "sectors": ["우주항공및국방"]},
            {"name": "항공운송", "sectors": ["항공사및항공운송"]},
            {"name": "기계·전기장비", "sectors": ["기계및전기장비"]},
        ],
    },
    "우주·통신": {
        "sectors": ["우주항공및국방", "통신장비", "무선통신", "유선및기타통신"],
        "subsegments": [
            {"name": "우주항공·국방", "sectors": ["우주항공및국방"]},
            {"name": "통신장비", "sectors": ["통신장비"]},
            {"name": "통신서비스", "sectors": ["무선통신", "유선및기타통신"]},
        ],
    },
    "산업재·인프라": {
        "sectors": ["기계및전기장비", "건설및건축제품", "상업및전문서비스", "운송인프라(도로선로)"],
        "subsegments": [
            {"name": "기계·전기장비", "sectors": ["기계및전기장비"]},
            {"name": "건설·건축제품", "sectors": ["건설및건축제품"]},
            {"name": "상업·전문서비스", "sectors": ["상업및전문서비스"]},
        ],
    },
    "산업재·원자재": {
        "sectors": ["기계및전기장비", "건설및건축제품", "상업및전문서비스", "금속및채광", "화학", "소재산업(기타)"],
        "subsegments": [
            {"name": "산업재·인프라", "sectors": ["기계및전기장비", "건설및건축제품", "상업및전문서비스"]},
            {"name": "금속·채광", "sectors": ["금속및채광"]},
            {"name": "화학·기타소재", "sectors": ["화학", "소재산업(기타)"]},
        ],
    },
    "주택·건설": {
        "sectors": ["건설및건축제품", "건축자재", "가정용내구재"],
        "subsegments": [
            {"name": "건설·건축제품", "sectors": ["건설및건축제품"]},
            {"name": "건축자재", "sectors": ["건축자재"]},
            {"name": "가정용내구재", "sectors": ["가정용내구재"]},
        ],
    },
    "소재": {
        "sectors": ["화학", "금속및채광", "소재산업(기타)", "건축자재"],
        "subsegments": [
            {"name": "화학", "sectors": ["화학"]},
            {"name": "금속·채광", "sectors": ["금속및채광"]},
            {"name": "기타 소재", "sectors": ["소재산업(기타)"]},
        ],
    },
    "에너지·유틸": {
        "sectors": ["에너지및관련서비스", "전기", "가스", "공익사업(기타)"],
        "subsegments": [
            {"name": "에너지 서비스", "sectors": ["에너지및관련서비스"]},
            {"name": "전력", "sectors": ["전기"]},
            {"name": "가스·유틸", "sectors": ["가스", "공익사업(기타)"]},
        ],
    },
    "전력·그리드": {
        "sectors": ["전기", "공익사업(기타)", "기계및전기장비", "에너지및관련서비스"],
        "subsegments": [
            {"name": "전력 유틸", "sectors": ["전기"]},
            {"name": "그리드·전기장비", "sectors": ["기계및전기장비"]},
            {"name": "공익사업", "sectors": ["공익사업(기타)"]},
        ],
    },
    "리츠·부동산": {
        "sectors": ["REIT및부동산관리개발"],
        "subsegments": [
            {"name": "REIT·부동산", "sectors": ["REIT및부동산관리개발"]},
        ],
    },
    "경기소비재": {
        "sectors": ["자동차", "자동차관련부품", "레져서비스및제품", "소비자서비스", "도/소매", "가정용내구재"],
        "subsegments": [
            {"name": "자동차", "sectors": ["자동차", "자동차관련부품"]},
            {"name": "레저·소비서비스", "sectors": ["레져서비스및제품", "소비자서비스"]},
            {"name": "소매·내구재", "sectors": ["도/소매", "가정용내구재"]},
        ],
    },
    "필수소비재": {
        "sectors": ["음식료및담배생산", "음식료소매", "가정및개인용품"],
        "subsegments": [
            {"name": "음식료·담배", "sectors": ["음식료및담배생산"]},
            {"name": "음식료 소매", "sectors": ["음식료소매"]},
            {"name": "가정·개인용품", "sectors": ["가정및개인용품"]},
        ],
    },
    "소비재": {
        "sectors": [
            "자동차", "자동차관련부품", "레져서비스및제품", "소비자서비스", "도/소매", "가정용내구재",
            "음식료및담배생산", "음식료소매", "가정및개인용품",
        ],
        "subsegments": [
            {"name": "경기소비재", "sectors": ["자동차", "자동차관련부품", "레져서비스및제품", "소비자서비스", "도/소매", "가정용내구재"]},
            {"name": "필수소비재", "sectors": ["음식료및담배생산", "음식료소매", "가정및개인용품"]},
        ],
    },
    "EV·배터리": {
        "sectors": ["자동차", "자동차관련부품", "금속및채광", "화학"],
        "subsegments": [
            {"name": "EV·자동차", "sectors": ["자동차", "자동차관련부품"]},
            {"name": "배터리 소재", "sectors": ["화학"]},
            {"name": "금속·채광", "sectors": ["금속및채광"]},
        ],
    },
}


def _clean_numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False),
        errors="coerce",
    )


def _pct_series(series: pd.Series) -> pd.Series:
    values = _clean_numeric_series(series)
    non_na = values.dropna()
    if not non_na.empty and non_na.abs().max() <= 1.0:
        values = values * 100.0
    return values


def _sector_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("/", "").replace(",", "").replace(" ", "")


def _empty_industry_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["industry_name", "change_pct"])


def _empty_constituent_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "sector",
            "ticker",
            "name",
            "current",
            "change_sign",
            "change_abs",
            "change_pct",
            "volume",
            "market_cap_thousand",
            "per",
        ]
    )


@lru_cache(maxsize=1)
def load_us_industry_snapshot() -> pd.DataFrame:
    if not US_INDUSTRY_SNAPSHOT_PATH.exists():
        return _empty_industry_df()
    try:
        df = pd.read_csv(US_INDUSTRY_SNAPSHOT_PATH)
    except Exception:
        return _empty_industry_df()
    if "change_pct" in df.columns:
        df["change_pct"] = _pct_series(df["change_pct"])
    return df


@lru_cache(maxsize=1)
def load_us_sector_constituents() -> pd.DataFrame:
    if not US_SECTOR_CONSTITUENTS_PATH.exists():
        return _empty_constituent_df()
    try:
        df = pd.read_csv(US_SECTOR_CONSTITUENTS_PATH)
    except Exception:
        return _empty_constituent_df()
    for col in ["current", "change_abs", "volume", "market_cap_thousand", "per"]:
        if col in df.columns:
            df[col] = _clean_numeric_series(df[col])
    if "change_pct" in df.columns:
        df["change_pct"] = _pct_series(df["change_pct"])
    return df


def _resolve_detail_group(detail_name: str = "", cluster_name: str = "") -> tuple[str, dict[str, Any]]:
    candidates = [str(detail_name or "").strip(), str(cluster_name or "").strip()]
    for candidate in candidates:
        if not candidate:
            continue
        direct = US_DETAIL_GROUPS.get(candidate)
        if direct:
            return candidate, direct
        alias = US_DETAIL_GROUP_ALIASES.get(candidate)
        if alias and alias in US_DETAIL_GROUPS:
            return alias, US_DETAIL_GROUPS[alias]

    joined = " ".join(candidate for candidate in candidates if candidate)
    for keyword, alias in US_DETAIL_GROUP_ALIASES.items():
        if keyword and keyword in joined and alias in US_DETAIL_GROUPS:
            return alias, US_DETAIL_GROUPS[alias]
    return "", {}


def _filter_by_sectors(df: pd.DataFrame, sectors: list[str], col: str) -> pd.DataFrame:
    if df.empty or col not in df.columns or not sectors:
        return df.iloc[0:0].copy()
    sector_keys = {_sector_key(sector) for sector in sectors}
    return df[df[col].map(_sector_key).isin(sector_keys)].copy()


def _records(df: pd.DataFrame, limit: int = 3, name_col: str = "name") -> list[dict[str, Any]]:
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


def _subsector_records(
    constituent_df: pd.DataFrame,
    industry_df: pd.DataFrame,
    detail_group: dict[str, Any],
    limit: int = 3,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for segment in detail_group.get("subsegments", []) or []:
        name = str(segment.get("name", "") or "").strip()
        sectors = [str(sector) for sector in segment.get("sectors", []) or []]
        if not name or not sectors:
            continue
        segment_rows = _filter_by_sectors(constituent_df, sectors, "sector")
        valid = segment_rows.dropna(subset=["change_pct"]) if "change_pct" in segment_rows else pd.DataFrame()
        if not valid.empty:
            change_pct = float(valid["change_pct"].mean())
            breadth = float((valid["change_pct"] > 0).mean())
            count = int(len(valid))
        else:
            industry_rows = _filter_by_sectors(industry_df, sectors, "industry_name")
            if industry_rows.empty:
                continue
            change_pct = float(industry_rows["change_pct"].mean())
            breadth = float("nan")
            count = 0
        records.append({"name": name, "ticker": "", "change_pct": change_pct, "breadth": breadth, "count": count})
    return records[:limit]


def build_us_cluster_snapshot(cluster_name: str, top_n: int = 3, detail_name: str = "") -> dict[str, Any]:
    """Return US industry breadth and representative-stock context for a sector/theme."""
    detail_key, detail_group = _resolve_detail_group(detail_name=detail_name, cluster_name=cluster_name)
    if not detail_group:
        return {}
    sectors = detail_group.get("sectors", []) or []
    if not sectors:
        return {}

    industry_df = load_us_industry_snapshot()
    constituent_df = load_us_sector_constituents()
    if industry_df.empty and constituent_df.empty:
        return {}

    industry_rows = _filter_by_sectors(industry_df, sectors, "industry_name")
    constituent_rows = _filter_by_sectors(constituent_df, sectors, "sector")
    if industry_rows.empty and constituent_rows.empty:
        return {}

    sector_avg = float(industry_rows["change_pct"].mean()) if "change_pct" in industry_rows and not industry_rows.empty else float("nan")
    valid_const = constituent_rows.dropna(subset=["change_pct"]) if "change_pct" in constituent_rows else pd.DataFrame()
    breadth = float((valid_const["change_pct"] > 0).mean()) if not valid_const.empty else float("nan")
    const_avg = float(valid_const["change_pct"].mean()) if not valid_const.empty else float("nan")

    industry_top = industry_rows.sort_values("change_pct", ascending=False) if "change_pct" in industry_rows else industry_rows
    subsector_rows = _subsector_records(valid_const, industry_rows, detail_group, limit=top_n)
    representative_rows = (
        valid_const.sort_values(["market_cap_thousand", "volume"], ascending=[False, False])
        if not valid_const.empty and "market_cap_thousand" in valid_const.columns
        else valid_const
    )
    laggards = (
        valid_const[valid_const["change_pct"] < 0].sort_values(["market_cap_thousand", "volume"], ascending=[False, False])
        if not valid_const.empty and "market_cap_thousand" in valid_const.columns
        else valid_const
    )

    if pd.notna(breadth) and breadth >= 0.60 and (pd.isna(sector_avg) or sector_avg >= 0):
        status = "확산 우세"
    elif (pd.notna(breadth) and breadth < 0.40) or (pd.notna(sector_avg) and sector_avg <= -1.0):
        status = "확산 약함"
    else:
        status = "혼조"

    warning = ""
    if status == "확산 약함":
        warning = "US 업종 내부 확산 약함: ETF·대장주 쏠림 가능"
    elif pd.notna(breadth) and breadth < 0.50:
        warning = "US 업종 내부 확인 필요: 상승 종목 비율이 낮음"

    return {
        "cluster": cluster_name,
        "detail": detail_key,
        "market": "US",
        "sectors": sectors,
        "sector_avg_change_pct": sector_avg,
        "constituent_avg_change_pct": const_avg,
        "breadth": breadth,
        "status": status,
        "warning": warning,
        "industries": _records(industry_top, name_col="industry_name", limit=top_n),
        "subsectors": subsector_rows,
        "leaders": _records(representative_rows, limit=top_n),
        "laggards": _records(laggards, limit=top_n),
    }
