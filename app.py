import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
import gspread
from google.oauth2.service_account import Credentials

# -------------------------------------------------
# 1. 기본 설정
# -------------------------------------------------
st.set_page_config(page_title="대장님의 최종 관제실 v7.7 (보완완성본)", layout="wide")

SPREADSHEET_ID = "195Mru5bqt_jvUQbgWcI1vHFDzEJV0wDJc05BXzmi9KA"
INVEST_SHEET_GID = "168627640"     # [3] 투자 데이터
ETF_SHEET_GID = "604547263"        # [4] 주식/채권(ETF)
CONTROL_SHEET_GID = "1420210871"   # 관제탑

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1px solid #1f2937; }
    h1, h2, h3, h4 { color: #f8fafc !important; font-weight: 800 !important; }
    .signal-box {
        padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 15px;
        color: white !important; font-weight: bold; border: 1px solid #334155;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
    }
    .macro-panel {
        background-color: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 10px;
        border-top: 4px solid #e74c3c; font-size: 0.95em; color: #f8fafc;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .info-panel {
        background-color: #1e293b; padding: 18px; border-radius: 10px; margin-bottom: 15px;
        border-left: 5px solid #3b82f6; color: #f8fafc;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .smc-tag { font-size: 0.85em; color: #60a5fa; font-weight: bold; }
    .highlight { font-size: 1.4em; font-weight: bold; color: #fbbf24; text-shadow: 1px 1px 2px #000; }
    .score-detail { font-size: 0.85em; font-weight: normal; color: #cbd5e1; margin-top: 8px; }
    .stTabs [data-baseweb="tab-list"] { background-color: #111827; border-radius: 8px; padding: 5px; }
    .stTabs [data-baseweb="tab"] { color: #94a3b8; font-weight: bold; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; background-color: #3b82f6 !important; border-radius: 5px; }

    div[data-baseweb="select"] > div { background-color: #1e293b !important; color: white !important; }
    ul[data-baseweb="menu"] li { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 REALTIME DIGITAL DASHBOARD v7.7")

# -------------------------------------------------
# 2. 구글 보안 인증 및 데이터 로드
# -------------------------------------------------
@st.cache_resource
def get_gspread_client():
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    return gspread.authorize(credentials)

@st.cache_data(ttl=300)
def load_sheet_by_gid(gid: str) -> pd.DataFrame:
    client = get_gspread_client()
    sh = client.open_by_key(SPREADSHEET_ID)
    ws = sh.get_worksheet_by_id(int(gid))
    data = ws.get_all_values()
    df = pd.DataFrame(data)

    if df.empty:
        return pd.DataFrame(columns=range(20), index=range(60)).fillna("")

    if df.shape[1] < 20:
        for col in range(df.shape[1], 20):
            df[col] = ""

    if len(df) < 60:
        pad_rows = pd.DataFrame([[""] * df.shape[1]] * (60 - len(df)))
        df = pd.concat([df, pad_rows], ignore_index=True)

    return df

# -------------------------------------------------
# 3. 유틸 함수
# -------------------------------------------------
def format_currency(val, ticker):
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"):
        return f"₩{int(val):,}"
    return f"${val:,.2f}"

def normalize_text(x):
    return str(x).strip().lower()

def normalize_ticker(t):
    return str(t).strip().lower().replace(".ks", "").replace(".kq", "")

def parse_num(v):
    if pd.isna(v):
        return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
    if s == "":
        return 0.0
    return pd.to_numeric(s, errors="coerce")

@st.cache_data(ttl=300)
def load_price_df(ticker, period="1y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.ffill(inplace=True)
    df.dropna(inplace=True)
    return df

def get_sqz_status(last_sqz_on: bool, prev_sqz_on: bool) -> str:
    if last_sqz_on and not prev_sqz_on:
        return "⏳재압축"
    elif last_sqz_on and prev_sqz_on:
        return "⏳압축중"
    elif (not last_sqz_on) and prev_sqz_on:
        return "🚀해제직후"
    return "➡️해제유지"

def get_macd_state(last_macd, last_sig, prev_macd, prev_sig):
    if last_macd > last_sig and prev_macd <= prev_sig:
        return "🔥매수신호(골든크로스)"
    elif last_macd > last_sig:
        return "📈추세유지(상승중)"
    elif last_macd < last_sig and prev_macd >= prev_sig:
        return "📉하락주의(데드크로스)"
    return "⏳추세관망"

def get_fin_label_map():
    return {
        0: "0점 (ETF/해당없음)",
        1: "1점 (🚨F급/처분)",
        2: "2점 (⚠️불안정/주의)",
        3: "3점 (✅회복형/중간형)",
        4: "4점 (💎완성형 우량)"
    }

# -------------------------------------------------
# 4. 매크로
# -------------------------------------------------
@st.cache_data(ttl=300)
def get_macro_analysis():
    tickers = {
        "10Y 금리": "^TNX",
        "유가": "CL=F",
        "환율": "USDKRW=X",
        "MOVE": "^MOVE",
        "VIX": "^VIX"
    }
    results = {}
    macro_trend = 0
    storm_count = 0

    for name, tkr in tickers.items():
        data = yf.download(tkr, period="2mo", interval="1d", progress=False)
        if data.empty:
            continue
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        cur = float(data["Close"].iloc[-1])
        prev_m = float(data["Close"].iloc[-22]) if len(data) >= 22 else float(data["Close"].iloc[0])
        chg = ((cur - prev_m) / prev_m) * 100
        icon = "🔺" if chg > 2.0 else ("🔻" if chg < -2.0 else "➖")

        if name in ["10Y 금리", "유가", "환율"]:
            if icon == "🔺":
                macro_trend += 0.5
            elif icon == "🔻":
                macro_trend -= 0.5

        is_storm = (
            (name == "VIX" and cur > 30) or
            (name == "환율" and cur > 1400) or
            (name == "10Y 금리" and cur > 4.7)
        )
        if is_storm:
            storm_count += 1

        results[name] = {"val": cur, "icon": icon, "storm": is_storm}

    move_val = results.get("MOVE", {"val": 0})["val"]
    move_score = 1.5 if move_val >= 120 else (0.5 if move_val >= 100 else 0)

    final_macro_risk = storm_count + macro_trend + move_score
    macro_penalty = 2 if final_macro_risk >= 4 else (1.5 if final_macro_risk >= 2.5 else (0.5 if final_macro_risk >= 1.5 else 0))
    return results, final_macro_risk, macro_penalty, move_val

macro_res, final_macro_risk, macro_penalty, move_val = get_macro_analysis()

m_cols = st.columns(len(macro_res))
for i, (n, info) in enumerate(macro_res.items()):
    s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] else ""
    m_cols[i].markdown(
        f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>",
        unsafe_allow_html=True
    )

# -------------------------------------------------
# 5. 구글시트 읽기
# -------------------------------------------------
@st.cache_data(ttl=300)
def load_invest_sheet():
    raw = load_sheet_by_gid(INVEST_SHEET_GID)
    seed_money = parse_num(raw.iloc[3, 17])      # R4
    current_asset = parse_num(raw.iloc[5, 15])   # P6
    cum_profit = parse_num(raw.iloc[5, 16])      # Q6
    return {
        "seed_money": float(seed_money) if pd.notna(seed_money) else 0.0,
        "current_asset": float(current_asset) if pd.notna(current_asset) else 0.0,
        "cum_profit": float(cum_profit) if pd.notna(cum_profit) else 0.0,
    }

@st.cache_data(ttl=300)
def load_portfolio_sheet():
    raw = load_sheet_by_gid(ETF_SHEET_GID)
    data = raw.iloc[5:35, 1:16].copy()   # B:P
    header = raw.iloc[4, 1:16].tolist()
    data.columns = header

    df = pd.DataFrame({
        "통화": data.iloc[:, 0],
        "자산클래스": data.iloc[:, 1],
        "국가": data.iloc[:, 2],
        "자산구분": data.iloc[:, 3],
        "자산명": data.iloc[:, 4],
        "요약": data.iloc[:, 5],
        "티커입력": data.iloc[:, 6],
        "보유량": data.iloc[:, 7],
        "매입가": data.iloc[:, 8],
        "현재가": data.iloc[:, 9],
        "수익률": data.iloc[:, 10],
        "평가손익": data.iloc[:, 11],
        "평가금액": data.iloc[:, 12],
        "원화환산": data.iloc[:, 13],
    })

    for col in ["통화", "자산클래스", "국가", "자산구분", "자산명", "요약", "티커입력"]:
        df[col] = df[col].astype(str).str.strip()

    for col in ["보유량", "매입가", "현재가", "수익률", "평가손익", "평가금액", "원화환산"]:
        df[col] = df[col].apply(parse_num).fillna(0)

    return df

@st.cache_data(ttl=300)
def load_control_sheet():
    raw = load_sheet_by_gid(CONTROL_SHEET_GID)
    block = raw.iloc[46:57, 3:7].copy()   # D47:G57
    block.columns = ["자산명", "티커", "목표비중", "현재비중"]
    block["자산명"] = block["자산명"].astype(str).str.strip().str.lower()
    block["티커"] = block["티커"].astype(str).str.strip().str.lower()

    for col in ["목표비중", "현재비중"]:
        block[col] = block[col].apply(parse_num).fillna(0)

    return block

invest_data = load_invest_sheet()
portfolio_df = load_portfolio_sheet()
control_df = load_control_sheet()

total_eval = invest_data["current_asset"] if invest_data["current_asset"] > 0 else float(portfolio_df["평가금액"].sum())

portfolio_value_map = {
    normalize_text(row["자산명"]): float(row["평가금액"])
    for _, row in portfolio_df.iterrows()
    if normalize_text(row["자산명"]) != ""
}

def get_current_weight(name: str) -> float:
    if total_eval <= 0:
        return 0.0
    return round((portfolio_value_map.get(normalize_text(name), 0.0) / total_eval) * 100, 2)

def get_target_weight_from_sheet(name: str, ticker: str) -> float:
    t = normalize_ticker(ticker)
    matched = control_df[control_df["티커"] == t]
    if not matched.empty:
        return float(matched.iloc[0]["목표비중"])

    n = normalize_text(name)
    matched = control_df[control_df["자산명"] == n]
    if not matched.empty:
        return float(matched.iloc[0]["목표비중"])

    return 0.0

def get_sheet_current_weight(name: str, ticker: str) -> float:
    t = normalize_ticker(ticker)
    matched = control_df[control_df["티커"] == t]
    if not matched.empty:
        return float(matched.iloc[0]["현재비중"])

    n = normalize_text(name)
    matched = control_df[control_df["자산명"] == n]
    if not matched.empty:
        return float(matched.iloc[0]["현재비중"])

    return get_current_weight(name)

def get_buy_amount(name: str, ticker: str) -> float:
    target_w = get_target_weight_from_sheet(name, ticker)
    current_w = get_sheet_current_weight(name, ticker)
    gap = max(target_w - current_w, 0)
    return round(total_eval * (gap / 100), 0)

def get_holding_row(name: str, ticker: str):
    t = normalize_ticker(ticker)
    n = normalize_text(name)

    # 시트 원본 복사본
    pf = portfolio_df.copy()
    pf["티커정리"] = pf["티커입력"].astype(str).apply(normalize_ticker)
    pf["자산명정리"] = pf["자산명"].astype(str).apply(normalize_text)

    # 1순위: 티커 정확매칭
    matched = pf[pf["티커정리"] == t]
    if not matched.empty:
        return matched.iloc[0]

    # 2순위: 자산명 정확매칭
    matched = pf[pf["자산명정리"] == n]
    if not matched.empty:
        return matched.iloc[0]

    # 3순위: 접미사 제거 후 티커 비교
    t_base = t.replace(".ks", "").replace(".kq", "")
    pf["티커기본"] = pf["티커정리"].str.replace(".ks", "", regex=False).str.replace(".kq", "", regex=False)
    matched = pf[pf["티커기본"] == t_base]
    if not matched.empty:
        return matched.iloc[0]

    # 4순위: 티커 부분매칭
    matched = pf[pf["티커기본"].str.contains(t_base, na=False)]
    if not matched.empty:
        return matched.iloc[0]

    # 5순위: 자산명 부분매칭
    matched = pf[pf["자산명정리"].str.contains(n, na=False)]
    if not matched.empty:
        return matched.iloc[0]

    return None

def get_my_price(name: str, ticker: str) -> float:
    row = get_holding_row(name, ticker)
    if row is None:
        return 0.0
    try:
        return float(row["매입가"]) if pd.notna(row["매입가"]) else 0.0
    except:
        return 0.0

def has_position(name: str, ticker: str) -> bool:
    row = get_holding_row(name, ticker)
    if row is None:
        return False

    try:
        qty = float(row["보유량"]) if pd.notna(row["보유량"]) else 0.0
    except:
        qty = 0.0

    try:
        eval_amt = float(row["평가금액"]) if pd.notna(row["평가금액"]) else 0.0
    except:
        eval_amt = 0.0

    return qty > 0 or eval_amt > 0
    
# -------------------------------------------------
# 6. 자산맵
# -------------------------------------------------
TICKER_MAP = {
    "나스닥": ("379810.KS", True, "us_etf_nasdaq"),
    "QQQM": ("QQQM", True, "us_etf_nasdaq"),
    "QLD": ("QLD", True, "us_etf_nasdaq"),
    "TQQQ": ("TQQQ", True, "us_etf_nasdaq"),
    "s&p500": ("379800.KS", True, "us_etf_sp"),
    "다우존스": ("458730.KS", True, "us_etf_sp"),
    "kodex 200": ("069500.KS", True, "kr_etf"),

    "MSFT": ("MSFT", False, "us_stock"),
    "네비우스": ("NBIS", False, "us_stock"),
    "시에나": ("CIEN", False, "us_stock"),
    "아리스타 네트웍스": ("ANET", False, "us_stock"),
    "샌디스크": ("SNDK", False, "us_stock"),
    "TSM": ("TSM", False, "us_stock"),
    "브로드컴": ("AVGO", False, "us_stock"),
    "MRVL": ("MRVL", False, "us_stock"),
    "버티브홀딩스": ("VRT", False, "us_stock"),
    "마이크론": ("MU", False, "us_stock"),

    "삼성전자": ("005930.KS", False, "kr_stock"),
    "두산에너빌리티": ("034020.KS", False, "kr_stock"),
    "하이닉스": ("000660.KS", False, "kr_stock"),
    "한화에어로스페이스": ("012450.KS", False, "kr_stock"),
    "HD현대중공업": ("329180.KS", False, "kr_stock"),
    "에이피알": ("278470.KS", False, "kr_stock"),
    "HD현대일렉트릭": ("267260.KS", False, "kr_stock"),
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"),
}

# -------------------------------------------------
# 7. RS 함수 및 지표
# -------------------------------------------------
@st.cache_data(ttl=300)
def get_rs_score(name, ticker, asset_class):
    bench = "069500.KS" if asset_class in ["kr_stock", "kr_etf"] else ("QQQM" if asset_class == "us_stock" else "379810.KS")

    if normalize_ticker(ticker) == normalize_ticker(bench):
        return 1, "➖보통"

    s_df = load_price_df(ticker, "3mo")
    b_df = load_price_df(bench, "3mo")
    if s_df.empty or b_df.empty:
        return 1, "➖보통"

    s = s_df["Close"].dropna().reset_index(drop=True)
    b = b_df["Close"].dropna().reset_index(drop=True)
    min_len = min(len(s), len(b))
    if min_len < 11:
        return 1, "➖보통"

    s = s.iloc[-min_len:].reset_index(drop=True)
    b = b.iloc[-min_len:].reset_index(drop=True)

    stock_now = float(s.iloc[-1])
    stock_10d = float(s.iloc[-11])
    market_now = float(b.iloc[-1])
    market_10d = float(b.iloc[-11])

    if market_now == 0 or market_10d == 0:
        return 1, "➖보통"

    rs_now = stock_now / market_now
    rs_10d = stock_10d / market_10d

    if rs_now > rs_10d * 1.03:
        return 2, "🚀강함"
    elif rs_now < rs_10d * 0.97:
        return 0, "🐢약함"
    return 1, "➖보통"

def build_indicators(df):
    df = df.copy()
    df["MA5"] = df["Close"].rolling(5).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA120"] = df["Close"].rolling(120).mean()

    df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["MFI"] = ta.volume.MFIIndicator(df["High"], df["Low"], df["Close"], df["Volume"]).money_flow_index()

    macd = ta.trend.MACD(df["Close"])
    df["MACD"] = macd.macd()
    df["MACD_Sig"] = macd.macd_signal()

    bb = ta.volatility.BollingerBands(df["Close"], 20, 2)
    bb_hi = bb.bollinger_hband()
    bb_lo = bb.bollinger_lband()
    df["%B"] = (df["Close"] - bb_lo) / (bb_hi - bb_lo)

    kc = ta.volatility.KeltnerChannel(df["High"], df["Low"], df["Close"], 20, 20, 1.5)
    df["SQZ_ON"] = (bb_hi < kc.keltner_channel_hband()) & (bb_lo > kc.keltner_channel_lband())
    return df

def calc_scores_and_decision(name, ticker, is_etf, asset_class, df, my_price, has_pos, fin_score):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    cur_p = float(last["Close"])

    trend_label = "🚀정배열(상승)" if (last["MA20"] > last["MA50"] > last["MA120"]) else ("⏳혼조세" if last["MA20"] > last["MA50"] else "🌊역배열(하락)")
    trend_s_final = 2 if trend_label == "🚀정배열(상승)" else (1 if trend_label == "⏳혼조세" else 0)

    macd_label = get_macd_state(last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"])
    rt_macd_label = "📈상승추세" if last["MACD"] > prev["MACD"] else ("📉하락추세" if last["MACD"] < prev["MACD"] else "⏳관망")

    rsi_now = float(last["RSI"])
    mfi_now = float(last["MFI"])
    pct_b_now = float(last["%B"])

    vol_ma20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if pd.notna(df["Volume"].rolling(20).mean().iloc[-1]) else 0
    vol_ratio = float(last["Volume"]) / vol_ma20 if vol_ma20 > 0 else 0

    rs_score, rs_label = get_rs_score(name, ticker, asset_class)
    sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))

    # 점수판단용
    macd_s_score = 2 if macd_label == "🔥매수신호(골든크로스)" else (1 if macd_label == "📈추세유지(상승중)" else (-2 if macd_label == "📉하락주의(데드크로스)" else 0))
    rt_macd_s = 1 if (rt_macd_label == "📈상승추세" and macd_label in ["📉하락주의(데드크로스)", "⏳추세관망"]) else 0
    sqz_s = 1 if (sqz_status == "🚀해제직후" and (macd_label in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"] or rt_macd_label == "📈상승추세")) else 0
    mfi_s = 2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0)
    tech_total = rs_score + mfi_s + (2 if trend_label == "🚀정배열(상승)" else 0) + macd_s_score + rt_macd_s + sqz_s

    # 최종판단용
    main_score = (
        trend_s_final +
        (2 if macd_label == "🔥매수신호(골든크로스)" else 0) +
        (2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)) +
        (1 if vol_ratio > 1.2 else 0)
    )
    adj_tech_score = (main_score + rs_score + (2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0))) - macro_penalty

    current_w = get_sheet_current_weight(name, ticker)
    target_w = get_target_weight_from_sheet(name, ticker)
    buy_amount = get_buy_amount(name, ticker)

    is_early_entry = (
        trend_label == "🚀정배열(상승)"
        and rs_label == "🚀강함"
        and rt_macd_label == "📈상승추세"
        and macd_label in ["📉하락주의(데드크로스)", "⏳추세관망"]
        and mfi_now < 80
        and pct_b_now < 0.85
        and 50 <= rsi_now <= 65
        and adj_tech_score >= 4.0
    )

    if is_etf:
        if target_w == 0 and has_pos:
            dec, col = "🚨비편입 자산: 정리 검토", "#dc2626"
        elif target_w == 0 and not has_pos:
            dec, col = "🚫비편입 자산: 신규매수 제외", "#64748b"
        elif current_w > target_w:
            dec, col = "🛑비중 초과: 추가매수 금지", "#dc2626"
        elif current_w >= target_w and target_w > 0:
            dec, col = "⏸️비중 충족: 관망", "#d97706"
        elif mfi_now >= 85 and pct_b_now >= 0.98:
            dec, col = "⚠️극단과열: 소액매수만", "#d97706"
        elif mfi_now >= 80:
            dec, col = "⚠️단기과열: 신규는 속도조절", "#d97706"
        elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
            dec, col = "🎯ETF 눌림목: 분할매수", "#8b5cf6"
        elif adj_tech_score >= 4:
            dec, col = "✅분할매수", "#16a34a"
        elif adj_tech_score >= 2:
            dec, col = "⏳관망/소액매수", "#64748b"
        else:
            dec, col = "🔍대기: 다음 기회 탐색", "#64748b"
    else:
        if fin_score == 1:
            dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif current_w > target_w and target_w > 0:
            dec, col = "🛑하드차단: 비중 초과", "#dc2626"
        elif current_w >= target_w and target_w > 0:
            dec, col = "⏸️하드차단: 비중 충족(관망)", "#d97706"
        elif final_macro_risk >= 4.5:
            dec, col = "🛑하드차단: 매크로 퍼펙트스톰(대피)", "#dc2626"
        elif mfi_now >= 85:
            dec, col = "🚫하드차단: MFI 극단적 과열(추격금지)", "#dc2626"
        elif pct_b_now >= 0.95:
            dec, col = "🚫하드차단: 볼린저밴드 상단 이탈(추격금지)", "#dc2626"
        elif has_pos:
            if trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80:
                dec, col = "⚠️단기과열: 추매 보류(보유자 영역)", "#d97706"
            elif rsi_now <= 30:
                dec, col = "🔥낙폭과대: 줍줍 찬스(역발상)", "#16a34a"
            elif rs_label == "🚀강함" and mfi_now < 35:
                dec, col = "💎S급: 주도주+과매도(풀매수)", "#16a34a"
            elif adj_tech_score >= 4 and cur_p <= my_price:
                dec, col = "🎯A급: 기술적 반등신호", "#16a34a"
            elif cur_p > my_price:
                dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            else:
                dec, col = "⏳보유중(신호대기)", "#64748b"
        else:
            if 0.85 <= pct_b_now < 0.95:
                dec, col = "⚠️상단부근: 눌림 대기", "#d97706"
            elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80:
                dec, col = "⚠️단기과열: 진입 보류(조정 대기)", "#d97706"
            elif rsi_now <= 30:
                dec, col = "🔥낙폭과대: 신규 진입 찬스", "#16a34a"
            elif is_early_entry:
                dec, col = "🟢선진입 가능: 실시간 반전 초입", "#16a34a"
            elif adj_tech_score >= 4.5 and rs_label == "🚀강함":
                dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5:
                dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
            elif trend_label == "🌊역배열(하락)":
                dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
            else:
                dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

    return {
        "cur_p": cur_p,
        "trend_label": trend_label,
        "macd_label": macd_label,
        "rt_macd_label": rt_macd_label,
        "rsi_now": rsi_now,
        "mfi_now": mfi_now,
        "pct_b_now": pct_b_now,
        "vol_ratio": vol_ratio,
        "rs_score": rs_score,
        "rs_label": rs_label,
        "sqz_status": sqz_status,
        "main_score": main_score,
        "adj_tech_score": adj_tech_score,
        "tech_total": tech_total,
        "rt_macd_s": rt_macd_s,
        "sqz_s": sqz_s,
        "mfi_s": mfi_s,
        "current_w": current_w,
        "target_w": target_w,
        "buy_amount": buy_amount,
        "dec": dec,
        "col": col,
    }
    
# -------------------------------------------------
# 8. 요약 전광판
# -------------------------------------------------
@st.cache_data(ttl=60)
def get_all_summary():
    rows = []

    for name, (tkr, is_etf, asset_class) in TICKER_MAP.items():
        df = load_price_df(tkr, "1y")
        if df.empty:
            continue

        df = build_indicators(df)
        my_price = get_my_price(name, tkr)
        has_pos = has_position(name, tkr)

        calc = calc_scores_and_decision(
            name, tkr, is_etf, asset_class, df, my_price, has_pos, 0 if is_etf else 2
        )

        rows.append({
            "종목명": name,
            "현재가": format_currency(calc["cur_p"], tkr),
            "현재비중": f'{calc["current_w"]:.2f}%',
            "목표비중": f'{calc["target_w"]:.2f}%',
            "부족매수액": f'{calc["buy_amount"]:,.0f}',
            "추세(MA)": calc["trend_label"],
            "MACD": calc["macd_label"],
            "실시간MACD": calc["rt_macd_label"],
            "RS": calc["rs_label"],
            "RSI": round(calc["rsi_now"], 1),
            "MFI": round(calc["mfi_now"], 1),
            "볼린저 %B": round(calc["pct_b_now"], 2),
            "SQZ": calc["sqz_status"],
            "🔥기술적 타점": calc["dec"],
            "Adj점수": round(calc["adj_tech_score"], 1)
        })

    return pd.DataFrame(rows)

# -------------------------------------------------
# 9. UI
# -------------------------------------------------
tab1, tab2 = st.tabs(["📋 전체 요약 전광판", "🔍 개별 상세 관제탑"])

with tab1:
    st.subheader("CCTV 통합 통제실")
    st.write(f'시드머니: {invest_data["seed_money"]:,.0f}원 | 현재자산: {invest_data["current_asset"]:,.0f}원 | 누적손익: {invest_data["cum_profit"]:,.0f}원')
    st.caption("※ 본 화면은 실시간 가격 기준으로 재계산되어 시트 종가판정과 다를 수 있음")
    st.dataframe(get_all_summary(), use_container_width=True, height=720, hide_index=True)

with tab2:
    sel_name = st.selectbox("종목 선택", list(TICKER_MAP.keys()))
    sel_ticker, is_etf, asset_class = TICKER_MAP[sel_name]

    my_price = get_my_price(sel_name, sel_ticker)
    has_pos = has_position(sel_name, sel_ticker)

    fin_labels = get_fin_label_map()
    fin_score = st.radio(
        "재무 점수",
        [0, 1, 2, 3, 4],
        index=(0 if is_etf else 2),
        format_func=lambda x: fin_labels[x],
        horizontal=True
    )

    df = load_price_df(sel_ticker, "1y")
    if not df.empty:
        df = build_indicators(df)
        calc = calc_scores_and_decision(sel_name, sel_ticker, is_etf, asset_class, df, my_price, has_pos, fin_score)
        last = df.iloc[-1]

        c1, c2 = st.columns([1.2, 2.3])

        with c1:
            st.markdown(f"<h2>📊 {sel_name}</h2>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='info-panel'>현재가: <span class='highlight'>{format_currency(calc['cur_p'], sel_ticker)}</span></div>",
                unsafe_allow_html=True
            )

            if has_pos and my_price > 0:
                st.markdown(
                    f"<div class='info-panel'><b>평단가</b><br><span class='highlight'>{format_currency(my_price, sel_ticker)}</span></div>",
                    unsafe_allow_html=True
                )
                st.write("매칭행 확인:", get_holding_row(sel_name, sel_ticker))
                st.write("매입가 확인:", my_price)

            st.markdown(
                f"<div class='info-panel'><b>비중</b><br>목표: {calc['target_w']:.2f}% | 현재: {calc['current_w']:.2f}%<br>부족 매수액: {calc['buy_amount']:,.0f}원</div>",
                unsafe_allow_html=True
            )

            st.markdown(f"""
            <div class="signal-box" style="background-color: {calc['col']};">
                <div style="font-size: 1.5em; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">{calc['dec']}</div>
                <div class="score-detail">
                    (Main:<b>{calc['main_score']}</b> | RS:<b>{calc['rs_score']}</b> | MFI:<b>{calc['mfi_s']}</b> | Macro:<b>-{macro_penalty}</b>)
                    ➔ Adj: <b style="color:white; font-size:1.1em;">{calc['adj_tech_score']:.1f}점</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class='info-panel' style='border-left: 5px solid #e67e22;'>
                <b>🛡️ SMC / Swing 전술 지표</b><br><br>
                • 추세: <b>{calc['trend_label']}</b><br>
                • MACD: <b>{calc['macd_label']}</b><br>
                • 실시간 MACD: <b>{calc['rt_macd_label']}</b><br>
                • RS: <b>{calc['rs_label']}</b><br>
                • RSI: <b>{calc['rsi_now']:.1f}</b> / MFI: <b>{calc['mfi_now']:.1f}</b><br>
                • 볼린저 %B: <b>{calc['pct_b_now']:.2f}</b><br>
                • SQZ: <span style='color:#fbbf24;'><b>{calc['sqz_status']}</b></span><br>
                <hr style='margin:12px 0; border-color:#334155;'>
                <span class='smc-tag'>[단기]</span> <b>MA5 :</b> {format_currency(last['MA5'], sel_ticker)}<br>
                <span class='smc-tag'>[스윙]</span> <b>MA20 :</b> {format_currency(last['MA20'], sel_ticker)}<br>
                <span class='smc-tag'>[중기]</span> <b>MA50 :</b> {format_currency(last['MA50'], sel_ticker)}<br>
                <span class='smc-tag'>[기관]</span> <b>MA120 :</b> {format_currency(last['MA120'], sel_ticker)}<br>
            </div>
            """, unsafe_allow_html=True)

        with c2:
            fig = go.Figure(data=[
                go.Candlestick(
                    x=df.index,
                    open=df["Open"],
                    high=df["High"],
                    low=df["Low"],
                    close=df["Close"],
                    name="Price"
                )
            ])
            fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], line=dict(color="#fbbf24", width=2), name="MA20"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA120"], line=dict(color="#94a3b8", width=1.5, dash="dot"), name="MA120"))

            if has_pos and my_price > 0:
                fig.add_hline(
                    y=my_price,
                    line_dash="dash",
                    line_color="#22c55e",
                    annotation_text="내 평단가",
                    annotation_position="bottom right"
                )

            fig.update_layout(
                template="plotly_dark",
                height=600,
                xaxis_rangeslider_visible=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, use_container_width=True)
