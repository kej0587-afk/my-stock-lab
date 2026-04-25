import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
import gspread
from google.oauth2.service_account import Credentials

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="대장님의 최종 관제실 v8.8 (로직 정석복구)", layout="wide")

SPREADSHEET_ID = "195Mru5bqt_jvUQbgWcI1vHFDzEJV0wDJc05BXzmi9KA"
INVEST_SHEET_GID = "168627640"     # [3] 투자 데이터
ETF_SHEET_GID = "604547263"        # [4] 주식/채권(ETF)
CONTROL_SHEET_GID = "1420210871"   # 관제탑

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
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
        box-shadow: 0 4px 6px rgba(0,0,0,0.3); line-height: 1.6;
    }
    .smc-tag { font-size: 0.85em; color: #60a5fa; font-weight: bold; }
    .highlight { font-size: 1.4em; font-weight: bold; color: #fbbf24; text-shadow: 1px 1px 2px #000; }
    .score-detail { font-size: 0.9em; font-weight: normal; color: #cbd5e1; margin-top: 10px; }
    div[data-baseweb="select"] > div { background-color: #1e293b !important; color: white !important; }
    ul[data-baseweb="menu"] li { color: #000000 !important; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 REALTIME DIGITAL DASHBOARD v8.8")

# -------------------------------------------------
# 2. 구글 인증 & 데이터 로드
# -------------------------------------------------
@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

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
        for col in range(df.shape[1], 20): df[col] = ""
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
    return pd.to_numeric(s, errors="coerce") if s != "" else 0.0

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
    if last_sqz_on and not prev_sqz_on: return "⏳재압축"
    elif last_sqz_on and prev_sqz_on: return "⏳압축중"
    elif (not last_sqz_on) and prev_sqz_on: return "🚀해제직후"
    return "➡️해제유지"

def get_macd_state(last_macd, last_sig, prev_macd, prev_sig):
    if last_macd > last_sig and prev_macd <= prev_sig: return "🔥매수신호(골든크로스)"
    elif last_macd > last_sig: return "📈추세유지(상승중)"
    elif last_macd < last_sig and prev_macd >= prev_sig: return "📉하락주의(데드크로스)"
    return "⏳추세관망"

def get_fin_label_map():
    return {0: "0점 (ETF/해당없음)", 1: "1점 (🚨F급/처분)", 2: "2점 (⚠️불안정/주의)", 3: "3점 (✅회복형/중간형)", 4: "4점 (💎완성형 우량)"}

# -------------------------------------------------
# 4. 매크로
# -------------------------------------------------
@st.cache_data(ttl=300)
def get_macro_analysis():
    tickers = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "MOVE": "^MOVE", "VIX": "^VIX"}
    results = {}
    macro_trend = 0
    storm_count = 0
    for name, tkr in tickers.items():
        data = yf.download(tkr, period="2mo", interval="1d", progress=False)
        if data.empty: continue
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        cur = float(data["Close"].iloc[-1])
        prev_m = float(data["Close"].iloc[-22]) if len(data) >= 22 else float(data["Close"].iloc[0])
        chg = ((cur - prev_m) / prev_m) * 100
        icon = "🔺" if chg > 0.5 else ("🔻" if chg < -0.5 else "➖")
        
        if name in ["10Y 금리", "유가", "환율"]:
            if icon == "🔺": macro_trend += 0.5
            elif icon == "🔻": macro_trend -= 0.5
            
        is_storm = ((name == "VIX" and cur > 30) or (name == "환율" and cur > 1400) or (name == "10Y 금리" and cur > 4.7))
        if is_storm: storm_count += 1
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
    m_cols[i].markdown(f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>", unsafe_allow_html=True)

# -------------------------------------------------
# 5. 구글 시트 연동 (다이어트 포기, 정석 코딩)
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
        "cum_profit": float(cum_profit) if pd.notna(cum_profit) else 0.0
    }

@st.cache_data(ttl=300)
def load_portfolio_sheet():
    raw = load_sheet_by_gid(ETF_SHEET_GID)
    data = raw.iloc[5:35, 1:16].copy()   # B:P
    header = raw.iloc[4, 1:16].tolist()
    data.columns = header

    # 대장님이 주셨던 가장 완벽하고 정확한 인덱스 맵핑
    df = pd.DataFrame({
        "통화": data.iloc[:, 0],        # B
        "자산클래스": data.iloc[:, 1],  # C
        "국가": data.iloc[:, 2],        # D
        "자산구분": data.iloc[:, 3],    # E
        "자산명": data.iloc[:, 4],      # F
        "요약": data.iloc[:, 5],        # G
        "티커입력": data.iloc[:, 6],    # H
        "보유량": data.iloc[:, 7],      # I
        "매입단가": data.iloc[:, 9],    # K
        "현재가(시트)": data.iloc[:, 10], # L
        "수익률": data.iloc[:, 11],     # M
        "평가손익": data.iloc[:, 12],   # N
        "평가금액": data.iloc[:, 13],   # O
        "원화환산": data.iloc[:, 14],   # P
    })

    for col in ["통화", "자산클래스", "국가", "자산구분", "자산명", "요약", "티커입력"]:
        df[col] = df[col].astype(str).str.strip()

    for col in ["보유량", "매입단가", "현재가(시트)", "수익률", "평가손익", "평가금액", "원화환산"]:
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

if "fin_score_map" not in st.session_state:
    st.session_state.fin_score_map = {}

total_eval = invest_data["current_asset"] if invest_data["current_asset"] > 0 else float(portfolio_df["평가금액"].sum())

portfolio_value_map = {
    normalize_text(row["자산명"]): float(row["평가금액"])
    for _, row in portfolio_df.iterrows()
    if normalize_text(row["자산명"]) != ""
}

# -------------------------------------------------
# 6. 비중 및 보유 확인 함수들
# -------------------------------------------------
def get_current_weight(name: str) -> float:
    if total_eval <= 0: return 0.0
    return round((portfolio_value_map.get(normalize_text(name), 0.0) / total_eval) * 100, 2)

def get_target_weight_from_sheet(name: str, ticker: str) -> float:
    t = normalize_ticker(ticker)
    matched = control_df[control_df["티커"] == t]
    if not matched.empty: return float(matched.iloc[0]["목표비중"])

    n = normalize_text(name)
    matched = control_df[control_df["자산명"] == n]
    if not matched.empty: return float(matched.iloc[0]["목표비중"])

    return 0.0

def get_sheet_current_weight(name: str, ticker: str) -> float:
    t = normalize_ticker(ticker)
    matched = control_df[control_df["티커"] == t]
    if not matched.empty: return float(matched.iloc[0]["현재비중"])

    n = normalize_text(name)
    matched = control_df[control_df["자산명"] == n]
    if not matched.empty: return float(matched.iloc[0]["현재비중"])

    return get_current_weight(name)

def get_buy_amount(name: str, ticker: str) -> float:
    target_w = get_target_weight_from_sheet(name, ticker)
    current_w = get_sheet_current_weight(name, ticker)
    gap = max(target_w - current_w, 0)
    return round(total_eval * (gap / 100), 0)

def get_holding_row(name: str, ticker: str):
    t = normalize_ticker(ticker)
    n = normalize_text(name)
    pf = portfolio_df.copy()
    pf["티커정리"] = pf["티커입력"].astype(str).apply(normalize_ticker)
    pf["자산명정리"] = pf["자산명"].astype(str).apply(normalize_text)

    matched = pf[pf["티커정리"] == t]
    if not matched.empty: return matched.iloc[0]

    matched = pf[pf["자산명정리"] == n]
    if not matched.empty: return matched.iloc[0]

    t_base = t.replace(".ks", "").replace(".kq", "")
    pf["티커기본"] = pf["티커정리"].str.replace(".ks", "", regex=False).str.replace(".kq", "", regex=False)
    matched = pf[pf["티커기본"] == t_base]
    if not matched.empty: return matched.iloc[0]

    return None

def get_my_price(name: str, ticker: str) -> float:
    row = get_holding_row(name, ticker)
    if row is None: return 0.0
    try: return float(row["매입단가"]) if pd.notna(row["매입단가"]) else 0.0
    except: return 0.0

def has_position(name: str, ticker: str) -> bool:
    row = get_holding_row(name, ticker)
    if row is None: return False
    try: qty = float(row["보유량"]) if pd.notna(row["보유량"]) else 0.0
    except: qty = 0.0
    try: eval_amt = float(row["평가금액"]) if pd.notna(row["평가금액"]) else 0.0
    except: eval_amt = 0.0
    return qty > 0 or eval_amt > 0

# -------------------------------------------------
# 7. 자산 맵 & 분석 엔진
# -------------------------------------------------
TICKER_MAP = {
    "나스닥": ("379810.KS", True, "us_etf_nasdaq"), "QQQM": ("QQQM", True, "us_etf_nasdaq"), "QLD": ("QLD", True, "us_etf_nasdaq"), "TQQQ": ("TQQQ", True, "us_etf_nasdaq"),
    "s&p500": ("379800.KS", True, "us_etf_sp"), "다우존스": ("458730.KS", True, "us_etf_sp"), "kodex 200": ("069500.KS", True, "kr_etf"),
    "MSFT": ("MSFT", False, "us_stock"), "네비우스": ("NBIS", False, "us_stock"), "시에나": ("CIEN", False, "us_stock"), "아리스타 네트웍스": ("ANET", False, "us_stock"),
    "샌디스크": ("SNDK", False, "us_stock"), "TSM": ("TSM", False, "us_stock"), "브로드컴": ("AVGO", False, "us_stock"), "MRVL": ("MRVL", False, "us_stock"),
    "버티브홀딩스": ("VRT", False, "us_stock"), "마이크론": ("MU", False, "us_stock"), "삼성전자": ("005930.KS", False, "kr_stock"),
    "두산에너빌리티": ("034020.KS", False, "kr_stock"), "하이닉스": ("000660.KS", False, "kr_stock"), "한화에어로스페이스": ("012450.KS", False, "kr_stock"),
    "HD현대중공업": ("329180.KS", False, "kr_stock"), "에이피알": ("278470.KS", False, "kr_stock"), "HD현대일렉트릭": ("267260.KS", False, "kr_stock"),
    "에이디테크놀러지": ("200710.KQ", False, "kr_stock"),
}

@st.cache_data(ttl=300)
def get_rs_score(ticker, asset_class):
    bench = "069500.KS" if asset_class in ["kr_stock", "kr_etf"] else ("QQQM" if asset_class == "us_stock" else "379810.KS")
    s_df, b_df = load_price_df(ticker, "3mo"), load_price_df(bench, "3mo")
    if s_df.empty or b_df.empty or len(s_df) < 11: return 1, "➖보통"
    s, b = s_df["Close"].dropna().reset_index(drop=True), b_df["Close"].dropna().reset_index(drop=True)
    min_len = min(len(s), len(b))
    if min_len < 11: return 1, "➖보통"
    s, b = s.iloc[-min_len:], b.iloc[-min_len:]
    stock_now, stock_10d = float(s.iloc[-1]), float(s.iloc[-11])
    market_now, market_10d = float(b.iloc[-1]), float(b.iloc[-11])
    if market_now == 0 or market_10d == 0: return 1, "➖보통"
    rs_now, rs_10d = stock_now / market_now, stock_10d / market_10d
    if rs_now > rs_10d * 1.03: return 2, "🚀강함"
    elif rs_now < rs_10d * 0.97: return 0, "🐢약함"
    return 1, "➖보통"

def build_indicators(df):
    df = df.copy()
    df["MA5"] = df["Close"].rolling(5).mean(); df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean(); df["MA120"] = df["Close"].rolling(120).mean()
    df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["MFI"] = ta.volume.MFIIndicator(df["High"], df["Low"], df["Close"], df["Volume"]).money_flow_index()
    macd = ta.trend.MACD(df["Close"]); df["MACD"] = macd.macd(); df["MACD_Sig"] = macd.macd_signal()
    bb = ta.volatility.BollingerBands(df["Close"], 20, 2)
    bb_hi, bb_lo = bb.bollinger_hband(), bb.bollinger_lband()
    df["%B"] = (df["Close"] - bb_lo) / (bb_hi - bb_lo)
    kc = ta.volatility.KeltnerChannel(df["High"], df["Low"], df["Close"], 20, 20, 1.5)
    df["SQZ_ON"] = (bb_hi < kc.keltner_channel_hband()) & (bb_lo > kc.keltner_channel_lband())
    return df

def calc_scores_and_decision(name, ticker, is_etf, asset_class, df, my_price, has_pos, fin_score, is_free_search=False):
    last, prev, cur_p = df.iloc[-1], df.iloc[-2], float(df.iloc[-1]["Close"])
    
    price_3m = df["Close"].iloc[-63] if len(df) >= 63 else df["Close"].iloc[0]
    ret_3m = (cur_p - price_3m) / price_3m if price_3m > 0 else 0.0

    high_52w = df["High"].rolling(252).max().iloc[-1] if len(df) >= 252 else df["High"].max()
    current_dd = (cur_p - high_52w) / high_52w if high_52w > 0 else 0.0

    trend_label = "🚀정배열(상승)" if (last["MA20"] > last["MA50"] > last["MA120"]) else ("⏳혼조세" if last["MA20"] > last["MA50"] else "🌊역배열(하락)")
    macd_state = "🔥매수신호(골든크로스)" if last["MACD"] > last["MACD_Sig"] and prev["MACD"] <= prev["MACD_Sig"] else \
                 ("📈추세유지(상승중)" if last["MACD"] > last["MACD_Sig"] else \
                 ("📉하락주의(데드크로스)" if last["MACD"] < last["MACD_Sig"] and prev["MACD"] >= prev["MACD_Sig"] else "⏳추세관망"))
    
    rsi_now, mfi_now, pct_b_now = float(last["RSI"]), float(last["MFI"]), float(last["%B"])
    rs_s_val, rs_label = get_rs_score(ticker, asset_class)
    sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))

    rs_s = 2 if rs_label == "🚀강함" else (1 if rs_label == "➖보통" else 0)
    mfi_s = 2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0)
    trend_s = 2 if trend_label == "🚀정배열(상승)" else 0
    macd_s = 2 if macd_state == "🔥매수신호(골든크로스)" else (1 if macd_state == "📈추세유지(상승중)" else (-2 if macd_state == "📉하락주의(데드크로스)" else 0))
    sqz_s = 1 if (sqz_status == "🚀해제직후" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]) else 0
    
    tech_total = rs_s + mfi_s + trend_s + macd_s + sqz_s
    
    vol_ma20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if pd.notna(df["Volume"].rolling(20).mean().iloc[-1]) else 1
    vol_ratio = float(last["Volume"]) / vol_ma20
    main_score = (2 if trend_label == "🚀정배열(상승)" else (1 if trend_label == "⏳혼조세" else 0)) + \
                 (2 if macd_state == "🔥매수신호(골든크로스)" else 0) + \
                 (2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)) + \
                 (1 if vol_ratio > 1.2 else 0)
    adj_tech_score = (main_score + rs_s + mfi_s) - macro_penalty

    t_score = tech_total + (0 if is_etf else fin_score)
    if not is_etf and fin_score == 1: grade = "🚨F급 (재무위험/처분)"
    elif t_score < 3: grade = "🚨F급 (기술/재무 부진)"
    elif t_score < 5: grade = "⏳C급 (주의/대기)"
    elif t_score < 7: grade = "⚖️B급 (신중/관망)"
    elif t_score < 9: grade = "✅A급 (분할 매수)"
    else: grade = "💎S급 (강력 매수)"

    is_early_entry = (trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and last["MACD"] > prev["MACD"] and 
                      macd_state in ["📉하락주의(데드크로스)", "⏳추세관망"] and mfi_now < 80 and pct_b_now < 0.85 and 50 <= rsi_now <= 65 and adj_tech_score >= 4.0)

    current_w = get_sheet_current_weight(name, ticker) if not is_free_search else 0.0
    target_w = get_target_weight_from_sheet(name, ticker) if not is_free_search else 0.0
    buy_amount = get_buy_amount(name, ticker) if not is_free_search else 0.0

    if is_free_search:
        if mfi_now >= 85: dec, col = "🚫극단과열: 추격금지", "#dc2626"
        elif pct_b_now >= 0.95: dec, col = "⚠️밴드상단: 눌림 대기", "#d97706"
        elif current_dd <= -0.2: dec, col = "🚨위기/패닉: 투매 포착(분할접근)", "#dc2626"
        elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
        elif rsi_now <= 30: dec, col = "🔥낙폭과대: 단기 반등 노림", "#16a34a"
        elif is_early_entry: dec, col = "🟢선진입 가능 구간", "#16a34a"
        elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
        elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
        elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
        elif trend_label == "🌊역배열(하락)": dec, col = "🚫역배열: 진입 보류", "#dc2626"
        else: dec, col = "🔍관망: 타점 대기", "#64748b"

    else:
        if not is_etf and fin_score == 1: dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif current_w > target_w and target_w > 0: dec, col = "🛑하드차단: 비중 초과", "#dc2626"
        elif current_w >= target_w and target_w > 0: dec, col = "⏸️하드차단: 비중 충족(관망)", "#d97706"
        elif current_dd <= -0.5: dec, col = "💣패닉(-50%↓): 나스닥100% 보너스 30% 최종투입", "#7f1d1d"
        elif current_dd <= -0.4: dec, col = "💣패닉(-40%↓): 나스닥100% 보너스 40% 투입", "#991b1b"
        elif current_dd <= -0.3: dec, col = "🚨위기(-30%↓): 나스닥60% 집중 보너스30% 투입", "#b91c1c"
        elif current_dd <= -0.2: dec, col = "🚨위기(-20%↓): 현금30% 확보 및 코어 집중", "#dc2626"
        elif final_macro_risk >= 4.5: dec, col = "🛑하드차단: 매크로 퍼펙트스톰(대피)", "#dc2626"
        elif mfi_now >= 85: dec, col = "🚫하드차단: MFI 극단적 과열(추격금지)", "#dc2626"
        elif pct_b_now >= 0.95: dec, col = "🚫하드차단: 볼린저밴드 상단 이탈(추격금지)", "#dc2626"
        elif has_pos:
            if trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 추매 보류(보유자 영역)", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 줍줍 찬스(역발상)", "#16a34a"
            elif rs_label == "🚀강함" and mfi_now < 35: dec, col = "💎S급: 주도주+과매도(풀매수)", "#16a34a"
            elif adj_tech_score >= 4 and cur_p <= my_price: dec, col = "🎯A급: 기술적 반등신호", "#16a34a"
            elif trend_label == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and cur_p <= my_price: dec, col = "📈정배열: 눌림목 매수", "#16a34a"
            elif cur_p > my_price: dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            elif cur_p <= my_price: dec, col = "✅평단이하: 분할매수", "#16a34a"
            else: dec, col = "⏳보유중(신호대기)", "#64748b"
        else:
            if 0.85 <= pct_b_now < 0.95: dec, col = "⚠️상단부근: 눌림 대기", "#d97706"
            elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 진입 보류(조정 대기)", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입 찬스", "#16a34a"
            elif is_early_entry: dec, col = "🟢선진입 가능: 실시간 반전 초입", "#16a34a"
            elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
            elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
            elif trend_label == "🌊역배열(하락)": dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
            else: dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

    return {"cur_p": cur_p, "trend": trend_label, "macd": macd_state, "rsi": rsi_now, "mfi": mfi_now, "pct_b": pct_b_now, "rs_label": rs_label, "sqz": sqz_status, "adj": adj_tech_score, "dec": dec, "col": col, "grade": grade, "t_score": t_score, "tech_total": tech_total, "fin_score": fin_score, "rs_s": rs_s, "mfi_s": mfi_s, "trend_s": trend_s, "macd_s": macd_s, "sqz_s": sqz_s, "main_s": main_score, "dd": current_dd, "ret_3m": ret_3m, "target_w": target_w, "current_w": current_w, "buy_amt": buy_amount}

@st.cache_data(ttl=60)
def get_all_summary(fin_score_map_items):
    rows = []
    fin_map = dict(fin_score_map_items)
    for name, (tkr, is_etf, a_class) in TICKER_MAP.items():
        df = load_price_df(tkr, "1y")
        if df.empty: continue
        df = build_indicators(df)
        my_p = get_my_price(name, tkr)
        has_p = has_position(name, tkr)
        f_score = fin_map.get(name, 0 if is_etf else 2)
        c = calc_scores_and_decision(name, tkr, is_etf, a_class, df, my_p, has_p, f_score)
        rows.append({
            "종목명": name, "현재가": format_currency(c["cur_p"], tkr), "MDD": f"{c['dd']*100:.1f}%",
            "현재비중": f"{c['current_w']:.2f}%", "목표비중": f"{c['target_w']:.2f}%", 
            "RS": c["rs_label"], "RSI": round(c["rsi"], 1), "MFI": round(c["mfi"], 1), "볼린저 %B": round(c["pct_b"], 2), 
            "🔥기술적 타점": c["dec"], "Adj점수": round(c["adj"], 1)
        })
    return pd.DataFrame(rows)

# -------------------------------------------------
# 8. UI
# -------------------------------------------------
tab1, tab2 = st.tabs(["📋 전체 요약 전광판", "🔍 종목 정밀 관측소"])

with tab1:
    st.subheader("CCTV 통합 통제실")
    st.write(f'현재자산: {invest_data["current_asset"]:,.0f}원 | 누적손익: {invest_data["cum_profit"]:,.0f}원')
    with st.expander("🛠️ 엑셀 원본 데이터 확인 (디버그용)"):
        st.write(portfolio_df[["자산명", "티커입력", "보유량", "매입단가", "현재가(시트)", "평가금액"]].head(10))
    st.dataframe(get_all_summary(tuple(sorted(st.session_state.fin_score_map.items()))), use_container_width=True, height=720, hide_index=True)

with tab2:
    options = ["🆓 자유 종목 탐색 (티커 입력)"] + list(TICKER_MAP.keys())
    sel = st.selectbox("종목 선택", options)
    is_free = (sel == "🆓 자유 종목 탐색 (티커 입력)")
    
    if is_free:
        user_tkr = st.text_input("티커 입력 (예: GOOGL, 005930.KS)", "GOOGL").upper()
        tkr, is_etf, a_class, name = user_tkr, False, ("kr_stock" if ".K" in user_tkr else "us_stock"), f"탐색: {user_tkr}"
        my_p, has_p = 0.0, False
    else:
        name = sel; tkr, is_etf, a_class = TICKER_MAP[sel]
        my_p = get_my_price(name, tkr); has_p = has_position(name, tkr)

    f_labels = get_fin_label_map(); default_f = st.session_state.fin_score_map.get(name, 0 if is_etf else 2)
    fin_score = st.radio("재무 점수", [0, 1, 2, 3, 4], index=default_f, format_func=lambda x: f_labels[x], horizontal=True)
    st.session_state.fin_score_map[name] = fin_score
    get_all_summary.clear()

    df = load_price_df(tkr, "1y")
    if not df.empty:
        df = build_indicators(df)
        c = calc_scores_and_decision(name, tkr, is_etf, a_class, df, my_p, has_p, fin_score, is_free)
        
        col1, col2 = st.columns([1.2, 2.3])
        
        with col1:
            st.markdown(f"<h2>📊 {name}</h2>", unsafe_allow_html=True)
            dd_color = "#dc2626" if c['dd'] <= -0.2 else ("#d97706" if c['dd'] <= -0.1 else "#2ecc71")
            st.markdown(f"""
            <div class='info-panel'>
                실시간 현재가: <span class='highlight'>{format_currency(c['cur_p'], tkr)}</span><br>
                고점대비 MDD: <span style='color:{dd_color}; font-weight:bold;'>{c['dd']*100:.1f}%</span><br>
                3개월 수익률: <span style='color:{"#2ecc71" if c['ret_3m']>0 else "#dc2626"}; font-weight:bold;'>{c['ret_3m']*100:.1f}%</span>
            </div>
            """, unsafe_allow_html=True)
            
            if is_free:
                st.info("💡 엑셀 미등록 종목입니다. 순수 기술적 타점만 분석합니다.")
            else:
                if has_p and my_p > 0:
                    st.markdown(f"<div class='info-panel' style='border-left: 5px solid #27ae60;'><b>내 평단가 (엑셀 연동)</b><br><span class='highlight' style='color:#2ecc71;'>{format_currency(my_p, tkr)}</span></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-panel'><b>비중</b><br>목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>부족 매수액: {c['buy_amt']:,.0f}원</div>", unsafe_allow_html=True)

            st.markdown(f"""
            <div class="signal-box" style="background-color: {c['col']};">
                <div style="font-size: 1.6em; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">{c['dec']}</div>
                <div class="score-detail">
                    (Main:<b>{c['main_s']}</b> | RS:<b>{c['rs_s']}</b> | MFI:<b>{c['mfi_s']}</b> | Macro:<b>-{macro_penalty}</b>)
                    ➔ Adj: <b style="color:white; font-size:1.1em;">{c['adj']:.1f}점</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class='info-panel' style='border-left: 5px solid #8b5cf6;'>
                <b>📌 후보 등급 판정</b><br><br>
                <span class='highlight' style='font-size:1.1em;'>{c['grade']}</span> (총합: {c['t_score']}점)<br>
                └ 🛠️기술: <b>{c['tech_total']}</b> (RS:{c['rs_s']}, MFI:{c['mfi_s']}, 추세:{c['trend_s']}, MACD:{c['macd_s']}, SQZ:{c['sqz_s']})<br>
                └ 💰재무: <b>{c['fin_score']}</b>/4
            </div>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class='info-panel' style='border-left: 5px solid #e67e22;'>
                <b>🛡️ SMC / Swing 전술 지표</b><br>
                • 추세: <b>{c['trend']}</b> | MACD: <b>{c['macd']}</b><br>
                • RS: <b>{c['rs_label']}</b> | RSI: <b>{c['rsi']:.1f}</b> | MFI: <b>{c['mfi']:.1f}</b><br>
                • 볼린저 %B: <b>{c['pct_b']:.2f}</b> | SQZ: <span style='color:#fbbf24;'><b>{c['sqz']}</b></span>
            </div>
            """, unsafe_allow_html=True)

        with col2:
            fig = go.Figure(data=[go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price")])
            fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], line=dict(color="#fbbf24", width=2), name="MA20"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA120"], line=dict(color="#94a3b8", width=1.5, dash="dot"), name="MA120"))
            if not is_free and has_p and my_p > 0:
                fig.add_hline(y=my_p, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가", annotation_position="bottom right")
            fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("해당 종목의 차트 데이터를 불러올 수 없습니다. 티커를 확인해 주십시오.")
