"""Money-flow universe and calculations for Stock Lab."""

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf


def finite_num(x):
    return x is not None and not pd.isna(x) and np.isfinite(float(x))

MONEY_FLOW_UNIVERSE = [
    {"구분": "미국 섹터", "섹터": "나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "미국 섹터", "섹터": "S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 VanEck", "ticker": "SMH", "name": "VanEck Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "반도체 iShares", "ticker": "SOXX", "name": "iShares Semiconductor ETF"},
    {"구분": "미국 섹터", "섹터": "기술", "ticker": "XLK", "name": "Technology Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "커뮤니케이션", "ticker": "XLC", "name": "Communication Services SPDR"},
    {"구분": "미국 섹터", "섹터": "금융", "ticker": "XLF", "name": "Financial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "헬스케어", "ticker": "XLV", "name": "Health Care Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "에너지", "ticker": "XLE", "name": "Energy Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "산업재", "ticker": "XLI", "name": "Industrial Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "소재", "ticker": "XLB", "name": "Materials Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "경기소비재", "ticker": "XLY", "name": "Consumer Discretionary SPDR"},
    {"구분": "미국 섹터", "섹터": "필수소비재", "ticker": "XLP", "name": "Consumer Staples SPDR"},
    {"구분": "미국 섹터", "섹터": "유틸리티", "ticker": "XLU", "name": "Utilities Select Sector SPDR"},
    {"구분": "미국 섹터", "섹터": "부동산", "ticker": "VNQ", "name": "Vanguard Real Estate ETF"},
    {"구분": "미국 섹터", "섹터": "바이오", "ticker": "IBB", "name": "iShares Biotechnology ETF"},
    {"구분": "미국 섹터", "섹터": "신재생", "ticker": "ICLN", "name": "iShares Global Clean Energy ETF"},
    {"구분": "미국 섹터", "섹터": "인프라", "ticker": "PAVE", "name": "Global X U.S. Infrastructure Development ETF"},
    {"구분": "미국 섹터", "섹터": "방산", "ticker": "SHLD", "name": "Global X Defense Tech ETF"},
    {"구분": "미국 섹터", "섹터": "항공방산", "ticker": "ITA", "name": "iShares U.S. Aerospace & Defense ETF"},
    {"구분": "미국 섹터", "섹터": "소프트웨어", "ticker": "IGV", "name": "iShares Expanded Tech-Software Sector ETF"},

    {"구분": "한국 섹터", "섹터": "코스피", "ticker": "069500.KS", "name": "KODEX 200"},
    {"구분": "한국 섹터", "섹터": "코스닥", "ticker": "229200.KS", "name": "KODEX 코스닥150"},
    {"구분": "한국 섹터", "섹터": "반도체", "ticker": "396500.KS", "name": "TIGER 반도체TOP10"},
    {"구분": "한국 섹터", "섹터": "IT/기술", "ticker": "139260.KS", "name": "TIGER 200 IT"},
    {"구분": "한국 섹터", "섹터": "2차전지", "ticker": "305540.KS", "name": "TIGER 2차전지테마"},
    {"구분": "한국 섹터", "섹터": "전력인프라", "ticker": "487240.KS", "name": "KODEX AI전력핵심설비"},
    {"구분": "한국 섹터", "섹터": "전력기기", "ticker": "0117V0.KS", "name": "TIGER 코리아AI전력기기TOP3플러스"},
    {"구분": "한국 섹터", "섹터": "원자력", "ticker": "434730.KS", "name": "HANARO 원자력iSelect"},
    {"구분": "한국 섹터", "섹터": "원자력TOP10", "ticker": "433500.KS", "name": "ACE 원자력TOP10"},
    {"구분": "한국 섹터", "섹터": "조선", "ticker": "494670.KS", "name": "TIGER 조선TOP10"},
    {"구분": "한국 섹터", "섹터": "방산", "ticker": "449450.KS", "name": "PLUS K방산"},
    {"구분": "한국 섹터", "섹터": "K-뷰티", "ticker": "479850.KS", "name": "HANARO K-뷰티"},
    {"구분": "한국 섹터", "섹터": "에너지", "ticker": "139250.KS", "name": "TIGER 200 에너지화학"},
    {"구분": "한국 섹터", "섹터": "금융", "ticker": "139270.KS", "name": "TIGER 200 금융"},
    {"구분": "한국 섹터", "섹터": "바이오", "ticker": "244580.KS", "name": "KODEX 바이오"},
    {"구분": "한국 섹터", "섹터": "부동산", "ticker": "329200.KS", "name": "TIGER 리츠부동산인프라"},
    {"구분": "한국 섹터", "섹터": "건설/유틸", "ticker": "139220.KS", "name": "TIGER 200 건설"},

    {"구분": "글로벌", "섹터": "미국 나스닥", "ticker": "QQQ", "name": "Invesco QQQ Trust"},
    {"구분": "글로벌", "섹터": "미국 S&P500", "ticker": "VOO", "name": "Vanguard S&P 500 ETF"},
    {"구분": "글로벌", "섹터": "일본", "ticker": "EWJ", "name": "iShares MSCI Japan ETF"},
    {"구분": "글로벌", "섹터": "캐나다", "ticker": "EWC", "name": "iShares MSCI Canada ETF"},
    {"구분": "글로벌", "섹터": "한국", "ticker": "EWY", "name": "iShares MSCI South Korea ETF"},
    {"구분": "글로벌", "섹터": "대만", "ticker": "EWT", "name": "iShares MSCI Taiwan ETF"},
    {"구분": "글로벌", "섹터": "홍콩", "ticker": "EWH", "name": "iShares MSCI Hong Kong ETF"},
    {"구분": "글로벌", "섹터": "중국", "ticker": "MCHI", "name": "iShares MSCI China ETF"},
    {"구분": "글로벌", "섹터": "인도", "ticker": "FLIN", "name": "Franklin FTSE India ETF"},
    {"구분": "글로벌", "섹터": "글로벌AI전력인프라", "ticker": "491010.KS", "name": "TIGER 글로벌AI전력인프라액티브"},
    {"구분": "글로벌", "섹터": "미국AI전력인프라", "ticker": "487230.KS", "name": "KODEX 미국AI전력핵심인프라"},
    {"구분": "글로벌", "섹터": "우라늄/원전", "ticker": "URA", "name": "Global X Uranium ETF"},
    {"구분": "글로벌", "섹터": "브라질", "ticker": "EWZ", "name": "iShares MSCI Brazil ETF"},
    {"구분": "글로벌", "섹터": "멕시코", "ticker": "EWW", "name": "iShares MSCI Mexico ETF"},
    {"구분": "글로벌", "섹터": "사우디", "ticker": "KSA", "name": "iShares MSCI Saudi Arabia ETF"},
    {"구분": "글로벌", "섹터": "베트남", "ticker": "VNM", "name": "VanEck Vietnam ETF"},

    {"구분": "매크로", "섹터": "금", "ticker": "IAU", "name": "iShares Gold Trust"},
    {"구분": "매크로", "섹터": "미국 장기채", "ticker": "TLT", "name": "iShares 20+ Year Treasury Bond ETF"},
]

def normalize_money_flow_ticker(ticker):
    t = str(ticker).strip().upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        code, suffix = t.split(".", 1)
        return f"{code.zfill(6)}.{suffix}"
    return t

@st.cache_data(ttl=900, show_spinner=False)
def download_money_flow_prices(tickers):
    tickers = sorted({normalize_money_flow_ticker(t) for t in tickers if str(t).strip()})
    if not tickers:
        return pd.DataFrame()
    data = yf.download(
        tickers,
        period="1y",
        interval="1d",
        progress=False,
        group_by="ticker",
        threads=True,
        auto_adjust=False,
    )
    return data

def get_money_flow_ohlc(data, ticker):
    ticker = normalize_money_flow_ticker(ticker)
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = list(data.columns.get_level_values(0))
        level1 = list(data.columns.get_level_values(1))

        if ticker in level0:
            out = data[ticker].copy()
        elif ticker in level1:
            out = data.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        out = data.copy()

    needed = [c for c in ["Close", "High", "Low"] if c in out.columns]
    if len(needed) < 3:
        return pd.DataFrame()

    out = out[["Close", "High", "Low"]].ffill().dropna()
    return out

def get_return_by_days(close, days):
    if close is None or len(close) < 2:
        return np.nan
    idx = -days if len(close) > days else 0
    old = float(close.iloc[idx])
    new = float(close.iloc[-1])
    if old <= 0:
        return np.nan
    return (new / old) - 1

def classify_money_flow_state(ret_3m, ret_6m, accel):
    if finite_num(ret_3m) and finite_num(accel) and ret_3m >= 0.05 and accel >= 0.03:
        return "신규 유입"
    if finite_num(ret_3m) and finite_num(ret_6m) and ret_3m >= 0.05 and ret_6m >= 0.05 and (not finite_num(accel) or accel >= -0.03):
        return "주도 유지"
    if finite_num(ret_6m) and finite_num(accel) and ret_6m >= 0.05 and accel <= -0.05:
        return "둔화 경고"
    if finite_num(ret_3m) and finite_num(ret_6m) and ret_3m < 0 and ret_6m < 0:
        return "소외 지속"
    return "관찰"

def calculate_money_flow_df():
    universe = [dict(item, ticker=normalize_money_flow_ticker(item["ticker"])) for item in MONEY_FLOW_UNIVERSE]
    tickers = [item["ticker"] for item in universe]
    data = download_money_flow_prices(tickers)

    rows = []
    for item in universe:
        px = get_money_flow_ohlc(data, item["ticker"])
        if px.empty or len(px) < 20:
            continue

        close = px["Close"]
        cur = float(close.iloc[-1])
        high_52w = float(px["High"].max())
        low_52w = float(px["Low"].min())
        period_ret = get_return_by_days(close, len(close) - 1)
        ret_1m = get_return_by_days(close, 21)
        ret_3m = get_return_by_days(close, 63)
        ret_6m = get_return_by_days(close, 126)
        accel = ret_3m - ret_6m if finite_num(ret_3m) and finite_num(ret_6m) else np.nan
        price_level = (cur - low_52w) / (high_52w - low_52w) if high_52w > low_52w else np.nan
        flow_score = (
            (ret_3m if finite_num(ret_3m) else 0) * 45 +
            (ret_6m if finite_num(ret_6m) else 0) * 35 +
            (accel if finite_num(accel) else 0) * 20
        )

        rows.append({
            "구분": item["구분"],
            "섹터": item["섹터"],
            "Ticker": item["ticker"],
            "ETF 이름": item["name"],
            "현재가": cur,
            "가격수준": price_level,
            "기간수익률": period_ret,
            "1개월수익률": ret_1m,
            "3개월수익률": ret_3m,
            "6개월수익률": ret_6m,
            "가속도": accel,
            "돈흐름점수": flow_score,
            "상태": classify_money_flow_state(ret_3m, ret_6m, accel),
            "52주 최고가": high_52w,
            "52주 최저가": low_52w,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["히트맵크기"] = (df["3개월수익률"].abs().fillna(0) * 100).clip(lower=1)
    return df.sort_values("돈흐름점수", ascending=False)


