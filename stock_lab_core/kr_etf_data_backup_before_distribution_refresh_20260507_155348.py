"""Domestic ETF reference data helpers for Stock Lab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


KR_ETF_DATA_PATH = Path(__file__).resolve().parent / "data" / "kr_etf_lab.csv"

ETF_COLUMNS = {
    "fund_code": "펀드코드",
    "name": "ETF 종목명",
    "code": "ETF 단축코드",
    "big": "ETF 대유형",
    "small": "ETF 소유형",
    "personal_pension": "개인연금",
    "retirement_pension": "퇴직연금",
    "risk_grade": "위험등급",
    "ret_1d": "1일(%)",
    "ret_1w": "1주(%)",
    "ret_1m": "1개월(%)",
    "ret_3m": "3개월(%)",
    "ret_6m": "6개월(%)",
    "ret_ytd": "연초후(%)",
    "ret_1y": "1년(%)",
    "ret_3y": "3년(%)",
    "total_fee": "총보수(%)",
    "ter": "합성총보수(TER)(%)",
    "real_fee": "실부담비율(%)",
    "current_price": "현재가(원)",
    "price_change": "전일대비(원)",
    "price_change_pct": "전일대비(%)",
    "aum": "운용규모(억원)",
    "volume": "거래량(주)",
    "trade_value": "거래대금(억원)",
    "premium_discount_3m": "3개월 괴리율(%)",
    "manager": "운용사명",
    "underlying_index": "기초지수",
    "replication": "복제방식",
    "tax_type": "과세유형",
    "listing_date": "상장일",
    "rep_big": "ETF 대표유형 대유형",
    "rep_small": "ETF 대표유형 소유형",
}

PAYMENT_COLUMNS = {
    "code": "상품코드",
    "name": "상품명",
    "distribution_type": "유형",
    "latest_distribution_rate": "최근월분배율",
    "distribution_ex_date": "분배부일",
    "distribution_base_date": "지급기준일",
    "distribution_per_share": "주당 분배금(원)",
    "annual_distribution_rate": "연분배율(%)(최근1년간)",
    "annual_distribution_total": "누적 분배금(원)(최근1년간)",
    "annual_distribution_count": "지급 횟수(회)(최근1년간)",
    "monthly_dividend_flag": "월배당 여부",
}

STANDARD_COLUMNS = [
    "code", "ticker", "name", "fund_code",
    "etf_big_type", "etf_small_type", "representative_big_type", "representative_small_type", "tags",
    "monthly_dividend", "source_monthly_summary", "source_distribution",
    "personal_pension", "retirement_pension", "risk_grade",
    "return_1d_pct", "return_1w_pct", "return_1m_pct", "return_3m_pct", "return_6m_pct", "return_ytd_pct", "return_1y_pct", "return_3y_pct",
    "total_fee_pct", "ter_pct", "real_fee_pct",
    "current_price_krw", "price_change_krw", "price_change_pct",
    "aum_krw_100m", "volume_shares", "trade_value_krw_100m", "premium_discount_3m_pct",
    "manager", "underlying_index", "replication", "tax_type", "listing_date",
    "distribution_type", "latest_distribution_rate_pct", "distribution_ex_date", "distribution_base_date",
    "distribution_per_share_krw", "annual_distribution_rate_pct", "annual_distribution_total_krw", "annual_distribution_count",
    "raw_monthly_dividend_flag",
    "top_1", "top_1_weight_pct", "top_2", "top_2_weight_pct", "top_3", "top_3_weight_pct", "top_4", "top_4_weight_pct", "top_5", "top_5_weight_pct",
    "data_generated_at", "source_files",
]


def normalize_kr_etf_code(value) -> str:
    text = "" if pd.isna(value) else str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    if text.endswith(".KS") or text.endswith(".KQ"):
        text = text.rsplit(".", 1)[0]
    if text.isdigit():
        text = text.zfill(6)
    return text


def kr_etf_ticker_from_code(code: str) -> str:
    code = normalize_kr_etf_code(code)
    return f"{code}.KS" if code else ""


def empty_kr_etf_lab_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def clean_kr_etf_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.dropna(how="all").dropna(axis=1, how="all").copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def text_value(row, column: str) -> str:
    if row is None or column not in getattr(row, "index", []):
        return ""
    value = row.get(column, "")
    if pd.isna(value):
        return ""
    return str(value).strip()


def yn_value(value) -> str:
    text = "" if pd.isna(value) else str(value).strip().upper()
    return "Y" if text in {"Y", "YES", "TRUE", "1", "월배당"} else ""


def derive_kr_etf_tags(name: str, big_type: str, small_type: str, rep_big: str, rep_small: str, is_monthly: bool) -> str:
    text_blob = " ".join([name, big_type, small_type, rep_big, rep_small]).upper()
    product_blob = " ".join([name, small_type, rep_big, rep_small]).upper()
    tags = []
    if is_monthly:
        tags.append("월배당")
    if "커버드콜" in text_blob:
        tags.append("커버드콜")
    if "고배당" in text_blob or "배당" in text_blob:
        tags.append("배당")
    if "채권" in text_blob or big_type == "채권":
        tags.append("채권")
    if "리츠" in text_blob or "부동산" in text_blob:
        tags.append("리츠/부동산")
    if "금리" in text_blob or "SOFR" in text_blob or "KOFR" in text_blob or "CD" in text_blob or big_type == "금리":
        tags.append("금리형")
    if "나스닥" in text_blob or "S&P500" in text_blob or "테크" in text_blob or "AI" in text_blob:
        tags.append("미국/테크")
    if "레버리지" in product_blob:
        tags.append("레버리지")
    if "인버스" in product_blob:
        tags.append("인버스")
    if "원자재" in text_blob or "국제금" in text_blob or "금현물" in text_blob:
        tags.append("원자재")
    return ", ".join(dict.fromkeys(tags))


def standardize_kr_etf_lab_dataframe(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_kr_etf_lab_dataframe()
    out = df.copy()
    for col in STANDARD_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out = out[STANDARD_COLUMNS].fillna("")
    out["code"] = out["code"].apply(normalize_kr_etf_code)
    out["ticker"] = out["ticker"].where(out["ticker"].astype(str).str.strip() != "", out["code"].apply(kr_etf_ticker_from_code))
    return out


def build_payment_lookup(payment_df: pd.DataFrame | None) -> pd.DataFrame:
    payment_df = clean_kr_etf_frame(payment_df)
    if payment_df.empty or PAYMENT_COLUMNS["code"] not in payment_df.columns:
        return pd.DataFrame()
    out = payment_df.copy()
    out["_code"] = out[PAYMENT_COLUMNS["code"]].apply(normalize_kr_etf_code)
    out = out[out["_code"] != ""].drop_duplicates("_code", keep="first")
    return out.set_index("_code")


def get_monthly_codes(monthly_df: pd.DataFrame | None) -> set[str]:
    monthly_df = clean_kr_etf_frame(monthly_df)
    if monthly_df.empty or ETF_COLUMNS["code"] not in monthly_df.columns:
        return set()
    return {normalize_kr_etf_code(x) for x in monthly_df[ETF_COLUMNS["code"]].dropna()}


def build_kr_etf_lab_dataframe(master_df: pd.DataFrame, monthly_df: pd.DataFrame | None = None, payment_df: pd.DataFrame | None = None, source_files: str = "") -> pd.DataFrame:
    master_df = clean_kr_etf_frame(master_df)
    if master_df.empty or ETF_COLUMNS["code"] not in master_df.columns:
        raise ValueError("국내 ETF 전체 목록 파일이 필요합니다.")

    monthly_codes = get_monthly_codes(monthly_df)
    payment_lookup = build_payment_lookup(payment_df)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for _, row in master_df.iterrows():
        code = normalize_kr_etf_code(row.get(ETF_COLUMNS["code"], ""))
        if not code:
            continue
        pay_row = payment_lookup.loc[code] if not payment_lookup.empty and code in payment_lookup.index else pd.Series(dtype=object)

        name = text_value(row, ETF_COLUMNS["name"]) or text_value(pay_row, PAYMENT_COLUMNS["name"])
        big = text_value(row, ETF_COLUMNS["big"])
        small = text_value(row, ETF_COLUMNS["small"])
        rep_big = text_value(row, ETF_COLUMNS["rep_big"])
        rep_small = text_value(row, ETF_COLUMNS["rep_small"])
        is_monthly = code in monthly_codes or yn_value(text_value(pay_row, PAYMENT_COLUMNS["monthly_dividend_flag"])) == "Y"

        out = {
            "code": code,
            "ticker": kr_etf_ticker_from_code(code),
            "name": name,
            "fund_code": text_value(row, ETF_COLUMNS["fund_code"]),
            "etf_big_type": big,
            "etf_small_type": small,
            "representative_big_type": rep_big,
            "representative_small_type": rep_small,
            "tags": derive_kr_etf_tags(name, big, small, rep_big, rep_small, is_monthly),
            "monthly_dividend": "Y" if is_monthly else "",
            "source_monthly_summary": "Y" if code in monthly_codes else "",
            "source_distribution": "Y" if not payment_lookup.empty and code in payment_lookup.index else "",
            "personal_pension": yn_value(text_value(row, ETF_COLUMNS["personal_pension"])),
            "retirement_pension": yn_value(text_value(row, ETF_COLUMNS["retirement_pension"])),
            "risk_grade": text_value(row, ETF_COLUMNS["risk_grade"]),
            "return_1d_pct": text_value(row, ETF_COLUMNS["ret_1d"]),
            "return_1w_pct": text_value(row, ETF_COLUMNS["ret_1w"]),
            "return_1m_pct": text_value(row, ETF_COLUMNS["ret_1m"]),
            "return_3m_pct": text_value(row, ETF_COLUMNS["ret_3m"]),
            "return_6m_pct": text_value(row, ETF_COLUMNS["ret_6m"]),
            "return_ytd_pct": text_value(row, ETF_COLUMNS["ret_ytd"]),
            "return_1y_pct": text_value(row, ETF_COLUMNS["ret_1y"]),
            "return_3y_pct": text_value(row, ETF_COLUMNS["ret_3y"]),
            "total_fee_pct": text_value(row, ETF_COLUMNS["total_fee"]),
            "ter_pct": text_value(row, ETF_COLUMNS["ter"]),
            "real_fee_pct": text_value(row, ETF_COLUMNS["real_fee"]),
            "current_price_krw": text_value(row, ETF_COLUMNS["current_price"]),
            "price_change_krw": text_value(row, ETF_COLUMNS["price_change"]),
            "price_change_pct": text_value(row, ETF_COLUMNS["price_change_pct"]),
            "aum_krw_100m": text_value(row, ETF_COLUMNS["aum"]),
            "volume_shares": text_value(row, ETF_COLUMNS["volume"]),
            "trade_value_krw_100m": text_value(row, ETF_COLUMNS["trade_value"]),
            "premium_discount_3m_pct": text_value(row, ETF_COLUMNS["premium_discount_3m"]),
            "manager": text_value(row, ETF_COLUMNS["manager"]),
            "underlying_index": text_value(row, ETF_COLUMNS["underlying_index"]),
            "replication": text_value(row, ETF_COLUMNS["replication"]),
            "tax_type": text_value(row, ETF_COLUMNS["tax_type"]),
            "listing_date": text_value(row, ETF_COLUMNS["listing_date"]),
            "distribution_type": text_value(pay_row, PAYMENT_COLUMNS["distribution_type"]),
            "latest_distribution_rate_pct": text_value(pay_row, PAYMENT_COLUMNS["latest_distribution_rate"]),
            "distribution_ex_date": text_value(pay_row, PAYMENT_COLUMNS["distribution_ex_date"]),
            "distribution_base_date": text_value(pay_row, PAYMENT_COLUMNS["distribution_base_date"]),
            "distribution_per_share_krw": text_value(pay_row, PAYMENT_COLUMNS["distribution_per_share"]),
            "annual_distribution_rate_pct": text_value(pay_row, PAYMENT_COLUMNS["annual_distribution_rate"]),
            "annual_distribution_total_krw": text_value(pay_row, PAYMENT_COLUMNS["annual_distribution_total"]),
            "annual_distribution_count": text_value(pay_row, PAYMENT_COLUMNS["annual_distribution_count"]),
            "raw_monthly_dividend_flag": text_value(pay_row, PAYMENT_COLUMNS["monthly_dividend_flag"]),
            "data_generated_at": generated_at,
            "source_files": source_files,
        }

        for n in range(1, 6):
            top_col = f"TOP {n}"
            ratio_col = "비율(%)" if n == 1 else f"비율(%).{n - 1}"
            out[f"top_{n}"] = text_value(row, top_col)
            out[f"top_{n}_weight_pct"] = text_value(row, ratio_col)
        rows.append(out)

    return standardize_kr_etf_lab_dataframe(pd.DataFrame(rows))


def apply_kr_etf_partial_updates(base_df: pd.DataFrame, monthly_df: pd.DataFrame | None = None, payment_df: pd.DataFrame | None = None, source_files: str = "") -> pd.DataFrame:
    out = standardize_kr_etf_lab_dataframe(base_df)
    if out.empty:
        raise ValueError("기존 ETF 데이터가 없으면 전체 ETF 목록 파일이 필요합니다.")

    monthly_codes = get_monthly_codes(monthly_df)
    if monthly_codes:
        out["source_monthly_summary"] = out["code"].apply(lambda x: "Y" if x in monthly_codes else "")
        out["monthly_dividend"] = out.apply(
            lambda r: "Y" if r["code"] in monthly_codes or str(r.get("source_distribution", "")) == "Y" else "",
            axis=1,
        )

    payment_lookup = build_payment_lookup(payment_df)
    if not payment_lookup.empty:
        payment_map = {
            "distribution_type": PAYMENT_COLUMNS["distribution_type"],
            "latest_distribution_rate_pct": PAYMENT_COLUMNS["latest_distribution_rate"],
            "distribution_ex_date": PAYMENT_COLUMNS["distribution_ex_date"],
            "distribution_base_date": PAYMENT_COLUMNS["distribution_base_date"],
            "distribution_per_share_krw": PAYMENT_COLUMNS["distribution_per_share"],
            "annual_distribution_rate_pct": PAYMENT_COLUMNS["annual_distribution_rate"],
            "annual_distribution_total_krw": PAYMENT_COLUMNS["annual_distribution_total"],
            "annual_distribution_count": PAYMENT_COLUMNS["annual_distribution_count"],
            "raw_monthly_dividend_flag": PAYMENT_COLUMNS["monthly_dividend_flag"],
        }
        for idx, row in out.iterrows():
            code = row["code"]
            if code not in payment_lookup.index:
                continue
            pay_row = payment_lookup.loc[code]
            out.at[idx, "source_distribution"] = "Y"
            out.at[idx, "monthly_dividend"] = "Y"
            for out_col, pay_col in payment_map.items():
                out.at[idx, out_col] = text_value(pay_row, pay_col)

    if monthly_codes or not payment_lookup.empty:
        out["data_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if source_files:
            out["source_files"] = source_files
        out["tags"] = out.apply(
            lambda r: derive_kr_etf_tags(
                r.get("name", ""), r.get("etf_big_type", ""), r.get("etf_small_type", ""),
                r.get("representative_big_type", ""), r.get("representative_small_type", ""),
                str(r.get("monthly_dividend", "")) == "Y",
            ),
            axis=1,
        )
    return standardize_kr_etf_lab_dataframe(out)


def classify_kr_etf_workbooks(frames: list[tuple[str, pd.DataFrame]]) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None, list[str]]:
    payment_df = None
    etf_frames = []
    messages = []

    for name, frame in frames:
        frame = clean_kr_etf_frame(frame)
        if frame.empty:
            messages.append(f"{name}: 빈 파일로 건너뜀")
            continue
        if PAYMENT_COLUMNS["code"] in frame.columns and PAYMENT_COLUMNS["distribution_per_share"] in frame.columns:
            payment_df = frame
            messages.append(f"{name}: 분배금 지급현황으로 인식")
        elif ETF_COLUMNS["code"] in frame.columns and ETF_COLUMNS["name"] in frame.columns:
            etf_frames.append((name, frame))
        else:
            messages.append(f"{name}: 지원하는 ETF 양식이 아니라 건너뜀")

    master_df = None
    monthly_df = None
    if etf_frames:
        etf_frames = sorted(etf_frames, key=lambda item: len(item[1]), reverse=True)
        if len(etf_frames) == 1 and len(etf_frames[0][1]) < 300:
            monthly_name, monthly_df = etf_frames[0]
            messages.append(f"{monthly_name}: 월배당 ETF 목록만 있는 것으로 인식")
        else:
            master_name, master_df = etf_frames[0]
            messages.append(f"{master_name}: 전체 ETF 목록으로 인식")
        if len(etf_frames) > 1:
            monthly_name, monthly_df = etf_frames[-1]
            messages.append(f"{monthly_name}: 월배당 ETF 목록으로 인식")

    return master_df, monthly_df, payment_df, messages


def read_kr_etf_excel_files(files: Iterable) -> list[tuple[str, pd.DataFrame]]:
    frames = []
    for file in files or []:
        name = getattr(file, "name", None) or Path(str(file)).name
        frames.append((name, pd.read_excel(file, dtype=str)))
    return frames


def build_kr_etf_lab_from_excel_files(files: Iterable, base_df: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    frames = read_kr_etf_excel_files(files)
    master_df, monthly_df, payment_df, messages = classify_kr_etf_workbooks(frames)
    source_files = " / ".join(name for name, _ in frames)

    if master_df is not None:
        return build_kr_etf_lab_dataframe(master_df, monthly_df, payment_df, source_files=source_files), messages
    return apply_kr_etf_partial_updates(base_df, monthly_df=monthly_df, payment_df=payment_df, source_files=source_files), messages


def load_kr_etf_lab_dataframe(path: Path = KR_ETF_DATA_PATH) -> pd.DataFrame:
    if not Path(path).exists():
        return empty_kr_etf_lab_dataframe()
    return standardize_kr_etf_lab_dataframe(pd.read_csv(path, dtype=str, encoding="utf-8-sig"))


def save_kr_etf_lab_dataframe(df: pd.DataFrame, path: Path = KR_ETF_DATA_PATH) -> Path:
    out = standardize_kr_etf_lab_dataframe(df)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return Path(path)
