import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta
import gspread
from google.oauth2.service_account import Credentials
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# -------------------------------------------------
# 1. 기본 설정 및 CSS
# -------------------------------------------------
st.set_page_config(page_title="대장님의 최종 관제실 v13.1 (그랜드 오픈 마감판)", layout="wide")

SPREADSHEET_ID = "195Mru5bqt_jvUQbgWcI1vHFDzEJV0wDJc05BXzmi9KA"
INVEST_SHEET_GID = "168627640"
ETF_SHEET_GID = "604547263"
CONTROL_SHEET_GID = "1420210871"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1px solid #1f2937; }
    h1, h2, h3, h4 { color: #f8fafc !important; font-weight: 800 !important; }
    .signal-box { padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 15px; color: white !important; font-weight: bold; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); }
    .macro-panel { background-color: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-top: 4px solid #e74c3c; font-size: 0.95em; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .info-panel { background-color: #1e293b; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #3b82f6; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); line-height: 1.7; }
    .smc-tag { font-size: 0.85em; color: #60a5fa; font-weight: bold; background-color: #111827; padding: 2px 6px; border-radius: 4px; border: 1px solid #334155; }
    .highlight { font-size: 1.4em; font-weight: bold; color: #fbbf24; text-shadow: 1px 1px 2px #000; }
    .score-detail { font-size: 0.9em; font-weight: normal; color: #cbd5e1; margin-top: 10px; }
    .news-box { background-color: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 8px; border-left: 4px solid #10b981; font-size: 0.9em; }
    .news-box a { color: #60a5fa; text-decoration: none; font-weight: bold; }
    .news-box a:hover { text-decoration: underline; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🛠️ 관제탑 세팅")
    app_mode = st.radio("사용 모드", ["개인모드", "범용모드"], index=0, help="개인모드는 구글 시트 연동, 범용모드는 직접 입력 방식입니다.")
    news_debug = st.checkbox("뉴스 디버그 보기", value=False)

st.title(f"🚀 REALTIME DIGITAL DASHBOARD v13.1 ({app_mode})")

# -------------------------------------------------
# 2. 유틸리티 함수
# -------------------------------------------------
def format_currency(val, ticker):
    if pd.isna(val): return "-"
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"): return f"₩{int(val):,}"
    return f"${val:,.2f}"

def normalize_text(x): return str(x).strip().lower()
def normalize_ticker(t): return str(t).strip().lower().replace(".ks", "").replace(".kq", "")
def parse_num(v):
    if pd.isna(v): return 0.0
    s = str(v).replace(",", "").replace("%", "").replace("₩", "").replace("$", "").strip()
    return pd.to_numeric(s, errors="coerce") if s != "" else 0.0

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
# 3. 뉴스 듀얼 모터
# -------------------------------------------------
@st.cache_data(ttl=600)
def get_ticker_news(ticker, name, debug=False):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    search_query = name.replace("탐색: ", "").replace(".KS", "").replace(".KQ", "").strip()
    encoded = urllib.parse.quote(search_query)
    logs = [f"검색어: {search_query}"]
    
    try:
        url = f"https://newssearch.naver.com/search.naver?where=rss&query={encoded}"
        if debug: logs.append(f"네이버 URL: {url}")
        req = urllib.request.Request(url, headers=headers)
        root = ET.fromstring(urllib.request.urlopen(req, timeout=4).read())
        items = root.findall("./channel/item")
        if items:
            res = [{"title": i.find("title").text.replace("<b>","").replace("</b>","").replace("&quot;","\"").replace("&amp;","&") if i.find("title") is not None else "제목 없음", 
                    "link": i.find("link").text if i.find("link") is not None else "#", 
                    "publisher": "네이버 뉴스"} for i in items[:3]]
            logs.append(f"네이버 뉴스 성공 ({len(items)}건)")
            return res, logs
    except Exception as e: logs.append(f"네이버 뉴스 실패: {e}")

    try:
        url = f"https://news.google.com/rss/search?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        if debug: logs.append(f"구글 URL: {url}")
        req = urllib.request.Request(url, headers=headers)
        root = ET.fromstring(urllib.request.urlopen(req, timeout=4).read())
        items = root.findall("./channel/item")
        if items:
            res = [{"title": i.find("title").text if i.find("title") is not None else "제목 없음", 
                    "link": i.find("link").text if i.find("link") is not None else "#", 
                    "publisher": i.find("source").text if i.find("source") is not None else "구글 뉴스"} for i in items[:3]]
            logs.append(f"구글 뉴스 성공 ({len(items)}건)")
            return res, logs
    except Exception as e: logs.append(f"구글 뉴스 실패: {e}")
    
    return [], logs

# -------------------------------------------------
# 4. 데이터 로드 및 시트 연동
# -------------------------------------------------
@st.cache_resource
def get_gspread_client():
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_data(ttl=300)
def load_sheet_by_gid(gid: str) -> pd.DataFrame:
    try:
        client = get_gspread_client()
        sh = client.open_by_key(SPREADSHEET_ID)
        ws = sh.get_worksheet_by_id(int(gid))
        df = pd.DataFrame(ws.get_all_values())
        if df.empty: return pd.DataFrame(columns=range(20), index=range(60)).fillna("")
        if df.shape[1] < 20:
            for col in range(df.shape[1], 20): df[col] = ""
        if len(df) < 60:
            pad = pd.DataFrame([[""] * df.shape[1]] * (60 - len(df)), columns=df.columns)
            df = pd.concat([df, pad], ignore_index=True)
        return df
    except Exception as e:
        print(f"Sheet Load Error: {e}")
        return pd.DataFrame(columns=range(20), index=range(60)).fillna("")

@st.cache_data(ttl=300)
def load_price_df(ticker, period="1y"):
    df = yf.download(ticker, period=period, interval="1d", progress=False)
    if not df.empty:
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.ffill(inplace=True); df.dropna(inplace=True)
    return df

@st.cache_data(ttl=300)
def get_macro_analysis():
    tickers = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "MOVE": "^MOVE", "VIX": "^VIX"}
    results = {}; macro_trend = 0; storm_count = 0
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

@st.cache_data(ttl=300)
def load_invest_sheet():
    raw = load_sheet_by_gid(INVEST_SHEET_GID)
    return {"seed_money": parse_num(raw.iloc[3, 17]), "current_asset": parse_num(raw.iloc[5, 15]), "cum_profit": parse_num(raw.iloc[5, 16])}

@st.cache_data(ttl=300)
def load_portfolio_sheet():
    raw = load_sheet_by_gid(ETF_SHEET_GID)
    data = raw.iloc[5:35, 1:16].copy()
    data.columns = raw.iloc[4, 1:16].tolist()
    df = pd.DataFrame({
        "자산명": data.iloc[:, 5], "티커입력": data.iloc[:, 7], 
        "보유량": data.iloc[:, 8].apply(parse_num), "매입단가": data.iloc[:, 9].apply(parse_num),
        "현재가(시트)": data.iloc[:, 10].apply(parse_num), "평가금액": data.iloc[:, 13].apply(parse_num)
    })
    df["자산명"] = df["자산명"].astype(str).str.strip()
    df["티커입력"] = df["티커입력"].astype(str).str.strip()
    return df

@st.cache_data(ttl=300)
def load_control_sheet():
    raw = load_sheet_by_gid(CONTROL_SHEET_GID)
    block = raw.iloc[46:57, 3:7].copy()
    block.columns = ["자산명", "티커", "목표비중", "현재비중"]
    for col in ["목표비중", "현재비중"]: block[col] = block[col].apply(parse_num).fillna(0)
    return block

# -------------------------------------------------
# 5. SMC 헬퍼 및 엔진 로직
# -------------------------------------------------
def get_pivot_highs_lows(df, l=3, r=3):
    highs, lows = [], []
    for i in range(l, len(df)-r):
        if df["High"].iloc[i] == df["High"].iloc[i-l:i+r+1].max(): highs.append((i, float(df["High"].iloc[i])))
        if df["Low"].iloc[i] == df["Low"].iloc[i-l:i+r+1].min(): lows.append((i, float(df["Low"].iloc[i])))
    return highs, lows

def get_recent_levels(df):
    ih, il = get_pivot_highs_lows(df, 3, 3)
    eh, el = get_pivot_highs_lows(df, 10, 10)
    return {
        "int_high": ih[-1][1] if ih else df["High"].tail(20).max(),
        "int_low": il[-1][1] if il else df["Low"].tail(20).min(),
        "ext_high": eh[-1][1] if eh else df["High"].tail(120).max(),
        "ext_low": el[-1][1] if el else df["Low"].tail(120).min()
    }

def detect_structure_event(df, levels):
    c_now, c_prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
    ie, ee = "None", "None"
    if c_prev <= levels["int_high"] < c_now: ie = "Bullish BoS"
    elif c_prev >= levels["int_low"] > c_now: ie = "Bearish BoS"
    if c_prev <= levels["ext_high"] < c_now: ee = "Bullish BoS"
    elif c_prev >= levels["ext_low"] > c_now: ee = "Bearish BoS"
    m20, m50 = float(df["MA20"].iloc[-1]), float(df["MA50"].iloc[-1])
    if "Bullish" in ee and m20 < m50: ee = "Bullish CHoCH"
    if "Bearish" in ee and m20 > m50: ee = "Bearish CHoCH"
    return ie, ee

def detect_liquidity_grab(df, levels, tol=0.002):
    c, h, l = float(df["Close"].iloc[-1]), float(df["High"].iloc[-1]), float(df["Low"].iloc[-1])
    if h > levels["int_high"]*(1+tol) and c < levels["int_high"]: return "상단 유동성 청산"
    if l < levels["int_low"]*(1-tol) and c > levels["int_low"]: return "하단 유동성 청산"
    return "없음"

def detect_recent_fvg(df):
    for i in range(len(df)-1, 1, -1):
        h2, l2, h0, l0 = float(df["High"].iloc[i-2]), float(df["Low"].iloc[i-2]), float(df["High"].iloc[i]), float(df["Low"].iloc[i])
        if l0 > h2: return {"type": "Bullish FVG", "top": l0, "bottom": h2, "active": float(df["Low"].iloc[-1]) > h2}
        if h0 < l2: return {"type": "Bearish FVG", "top": l2, "bottom": h0, "active": float(df["High"].iloc[-1]) < l2}
    return {"type": "없음", "top": None, "bottom": None, "active": False}

def get_pd_zone(df):
    c, m, s = float(df["Close"].iloc[-1]), df["Close"].rolling(200).mean().iloc[-1], df["Close"].rolling(200).std().iloc[-1]
    if pd.isna(m): return "Neutral"
    if c >= m + 2*s: return "Premium"
    if c <= m - 2*s: return "Discount"
    return "Neutral"

def summarize_smc_action(ext, int_s, ie, ee, liq, fvg, pdz):
    if "CHoCH" in ee: return "구조적 반전 포착: 방향 재설정 필요"
    if liq == "상단 유동성 청산" and pdz == "Premium": return "상단 유동성 청산 후 조정 경계"
    if fvg["type"] == "Bullish FVG" and fvg["active"] and ext == "Bullish": return "상승 FVG 유지: 눌림 매수 유리"
    if ext == "Bullish": return "상승 추세 유지: 눌림 대기"
    return "구조 혼조: 관망"

def get_rs_score(ticker, asset_class):
    bench = "069500.KS" if asset_class in ["kr_stock", "kr_etf"] else ("QQQM" if asset_class == "us_stock" else "379810.KS")
    if normalize_ticker(ticker) == normalize_ticker(bench): return 1, "➖보통"
    s_df, b_df = load_price_df(ticker, "3mo"), load_price_df(bench, "3mo")
    if len(s_df) < 15 or len(b_df) < 15: return 1, "➖보통"
    s_now, s_10d = float(s_df["Close"].iloc[-1]), float(s_df["Close"].iloc[-11])
    b_now, b_10d = float(b_df["Close"].iloc[-1]), float(b_df["Close"].iloc[-11])
    rs_now, rs_10d = s_now / b_now, s_10d / b_10d
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
    bb = ta.volatility.BollingerBands(df["Close"], 20, 2); df["%B"] = (df["Close"] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())
    kc = ta.volatility.KeltnerChannel(df["High"], df["Low"], df["Close"], 20, 20, 1.5)
    df["SQZ_ON"] = (bb.bollinger_hband() < kc.keltner_channel_hband()) & (bb.bollinger_lband() > kc.keltner_channel_lband())
    return df

# -------------------------------------------------
# 6. 범용화 인터페이스 함수
# -------------------------------------------------
def get_effective_total_asset(mode, user_asset, sheet_eval):
    return sheet_eval if mode == "개인모드" else (float(user_asset) if user_asset > 0 else 0.0)

def get_effective_weights(mode, name, ticker, u_curr_w, u_targ_w):
    if mode == "개인모드":
        t_norm = normalize_ticker(ticker); n_norm = normalize_text(name)
        m_t = control_df[control_df["티커"].apply(normalize_ticker) == t_norm]
        m_n = control_df[control_df["자산명"].apply(normalize_text) == n_norm]
        cw = float(m_t.iloc[0]["현재비중"]) if not m_t.empty else (float(m_n.iloc[0]["현재비중"]) if not m_n.empty else 0.0)
        tw = float(m_t.iloc[0]["목표비중"]) if not m_t.empty else (float(m_n.iloc[0]["목표비중"]) if not m_n.empty else 0.0)
        return cw, tw
    return float(u_curr_w), float(u_targ_w)

def get_effective_buy_amount(mode, name, ticker, eff_total, u_curr_w, u_targ_w):
    cw, tw = get_effective_weights(mode, name, ticker, u_curr_w, u_targ_w)
    return round(eff_total * (max(tw - cw, 0) / 100), 0)

# -------------------------------------------------
# 7. 기술적 분석 메인 엔진
# -------------------------------------------------
def calc_scores_and_decision(name, ticker, is_etf, asset_class, df, my_price, has_pos, fin_score, 
                             is_free=False, app_mode="개인모드", user_total_asset=0.0, user_curr_w=0.0, user_targ_w=0.0):
    last, prev, cur_p = df.iloc[-1], df.iloc[-2], float(df.iloc[-1]["Close"])
    p3m = df["Close"].iloc[-61] if len(df) >= 61 else df["Close"].iloc[0]
    p6m = df["Close"].iloc[-121] if len(df) >= 121 else df["Close"].iloc[0]
    ret_3m, ret_6m = (cur_p / p3m) - 1, (cur_p / p6m) - 1
    high_52w = df["High"].rolling(252).max().iloc[-1] if len(df) >= 252 else df["High"].max()
    current_dd = (cur_p / high_52w) - 1 if high_52w > 0 else 0.0

    trend_label = "🚀정배열(상승)" if (last["MA20"] > last["MA50"] > last["MA120"]) else ("⏳혼조세" if last["MA20"] > last["MA50"] else "🌊역배열(하락)")
    macd_state = get_macd_state(last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"])
    rt_macd_label = "📈상승추세" if last["MACD"] > prev["MACD"] else ("📉하락추세" if last["MACD"] < prev["MACD"] else "⏳관망")
    rsi_now, mfi_now, pct_b_now = float(last["RSI"]), float(last["MFI"]), float(last["%B"])
    _, rs_label = get_rs_score(ticker, asset_class)
    sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))

    rs_s = 2 if rs_label == "🚀강함" else (1 if rs_label == "➖보통" else 0)
    mfi_s = 2 if mfi_now < 30 else (-1 if mfi_now > 80 else 0)
    trend_s = 2 if trend_label == "🚀정배열(상승)" else 0
    macd_s = 2 if macd_state == "🔥매수신호(골든크로스)" else (1 if macd_state == "📈추세유지(상승중)" else (-2 if macd_state == "📉하락주의(데드크로스)" else 0))
    sqz_s = 1 if (sqz_status == "🚀해제직후" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]) else 0
    
    tech_total = rs_s + mfi_s + trend_s + macd_s + sqz_s
    vol_ma20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if pd.notna(df["Volume"].rolling(20).mean().iloc[-1]) else 1
    vol_ratio = float(last["Volume"]) / vol_ma20 if vol_ma20 > 0 else 0
    
    main_score = (
        (2 if trend_label == "🚀정배열(상승)" else (1 if trend_label == "⏳혼조세" else 0)) +
        (2 if macd_state == "🔥매수신호(골든크로스)" else 0) +
        (2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)) +
        (1 if vol_ratio > 1.2 else 0)
    )
    adj_tech_score = (main_score + rs_s + mfi_s) - macro_penalty

    if is_etf:
        t_score = tech_total
        if tech_total < 1: grade = "⏳ETF 관망"
        elif tech_total < 3: grade = "⚖️ETF 보통"
        elif tech_total < 5: grade = "✅ETF 양호"
        else: grade = "💎ETF 우수"
    else:
        t_score = tech_total + fin_score
        if fin_score == 1: grade = "🚨F급 (재무위험/처분)"
        elif t_score < 3: grade = "🚨F급 (기술/재무 부진)"
        elif t_score < 5: grade = "⏳C급 (주의/대기)"
        elif t_score < 7: grade = "⚖️B급 (신중/관망)"
        elif t_score < 9: grade = "✅A급 (분할 매수)"
        else: grade = "💎S급 (강력 매수)"

    levels = get_recent_levels(df)
    ext_structure = "Bullish" if trend_label == "🚀정배열(상승)" else ("Bearish" if trend_label == "🌊역배열(하락)" else "Neutral")
    
    int_structure = (
        "Bullish" if rs_label == "🚀강함" and macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"]
        else ("Bearish" if trend_label == "🌊역배열(하락)" or rs_label == "🐢약함" else "Mixed")
    )
    
    int_event, ext_event = detect_structure_event(df, levels)
    liq_state = detect_liquidity_grab(df, levels)
    fvg_info = detect_recent_fvg(df)
    pd_zone = get_pd_zone(df)
    smc_action = summarize_smc_action(ext_structure, int_structure, int_event, ext_event, liq_state, fvg_info, pd_zone)

    if rsi_now <= 30: smc_insight = "과매도 극단. 유동성 청산 후 구조적 반등(CHoCH) 여부 관찰."
    elif mfi_now >= 80: smc_insight = "스마트머니 익절 가능성이 높은 단기 과열 구간."
    elif 0.45 < pct_b_now < 0.8 and sqz_status == "🚀해제직후": smc_insight = "응축 후 발산 초기. 모멘텀 실리는 타점 구간."
    elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함": smc_insight = "구조적 상승(BoS) 진행 중. MA20 눌림 여부 확인 필요."
    elif trend_label == "🌊역배열(하락)": smc_insight = "하락 구조 우세. 추세 전환 전까지 보수적 접근 권장."
    else: smc_insight = "주요 매물대(FVG/Order Block) 소화 중. 방향성 확정 대기."

    eff_total = get_effective_total_asset(app_mode, user_total_asset, total_eval)
    curr_w, targ_w = get_effective_weights(app_mode, name, ticker, user_curr_w, user_targ_w)
    buy_amount = get_effective_buy_amount(app_mode, name, ticker, eff_total, user_curr_w, user_targ_w)

    is_early_entry = (trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and last["MACD"] > prev["MACD"] and 
                      macd_state in ["📉하락주의(데드크로스)", "⏳추세관망"] and mfi_now < 80 and pct_b_now < 0.85 and 50 <= rsi_now <= 65 and adj_tech_score >= 4.0)
    is_breakout_extreme = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and pct_b_now > 1.02 and rs_label == "🚀강함"
    is_breakout_normal = (not is_etf) and fin_score == 4 and adj_tech_score >= 4.0 and 0.95 <= pct_b_now <= 1.02 and rs_label == "🚀강함"
   
    # -------------------------------
    # 예외 승인 프로세스 (정찰대 진입)
    # -------------------------------
    ma5_now = float(last["MA5"]) if pd.notna(last["MA5"]) else 0.0
    low_now = float(last["Low"])

    is_leader_base = (
        (not is_etf) and
        fin_score == 4 and
        trend_label == "🚀정배열(상승)" and
        rs_label == "🚀강함" and
        macd_state in ["🔥매수신호(골든크로스)", "📈추세유지(상승중)"] and
        adj_tech_score >= 4.0
    )

    is_ma5_pullback = (
        ma5_now > 0 and (
            abs(cur_p - ma5_now) / ma5_now <= 0.015 or
            low_now <= ma5_now * 1.01
        )
    )

    is_bullish_fvg_pullback = (
        fvg_info["type"] == "Bullish FVG" and
        fvg_info["bottom"] is not None and
        fvg_info["top"] is not None and
        float(fvg_info["bottom"]) * 0.995 <= cur_p <= float(fvg_info["top"]) * 1.01
    )

    is_exception_entry = (
        is_leader_base and
        (is_ma5_pullback or is_bullish_fvg_pullback) and
        mfi_now < 90 and
        pct_b_now < 1.08
    )
                                 
    if is_free:
        if mfi_now >= 85: dec, col = "🚫극단과열: 추격금지", "#dc2626"
        elif is_breakout_extreme: dec, col = "⚠️과열확장: 추격금지, MA5 대기", "#d97706"
        elif is_breakout_normal: dec, col = "🔥불뿜는 대장주: 초단기 눌림(MA5) 진입", "#ec4899"
        elif pct_b_now >= 0.95: dec, col = "⚠️밴드상단: 눌림 대기", "#d97706"
        elif current_dd <= -0.2: dec, col = "🚨위기/패닉: 투매 포착", "#dc2626"
        elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
        elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입", "#16a34a"
        elif is_early_entry: dec, col = "🟢선진입 가능 구간", "#16a34a"
        elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
        elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
        elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
        elif trend_label == "🌊역배열(하락)": dec, col = "🚫역배열: 진입 보류", "#dc2626"
        else: dec, col = "🔍관망: 타점 대기", "#64748b"
    else:
        if not is_etf and fin_score == 1: dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif curr_w > targ_w and targ_w > 0: dec, col = "🛑하드차단: 비중 초과", "#dc2626"
        elif curr_w >= targ_w and targ_w > 0: dec, col = "⏸️하드차단: 비중 충족(관망)", "#d97706"
        elif current_dd <= -0.5: dec, col = "💣패닉(-50%↓): 최종투입", "#7f1d1d"
        elif current_dd <= -0.4: dec, col = "💣패닉(-40%↓): 현금 투입", "#991b1b"
        elif current_dd <= -0.3: dec, col = "🚨위기(-30%↓): 코어 집중", "#b91c1c"
        elif current_dd <= -0.2: dec, col = "🚨위기(-20%↓): 현금 확보", "#dc2626"
        elif final_macro_risk >= 4.5: dec, col = "🛑하드차단: 퍼펙트스톰(대피)", "#dc2626"
        elif is_exception_entry and has_pos:
            dec, col = "🟣예외승인: 정찰대 추매(MA5/FVG)", "#7c3aed"
        elif is_exception_entry and (not has_pos):
            dec, col = "🟣예외승인: 정찰대 진입(MA5/FVG)", "#7c3aed"     
        elif mfi_now >= 85: dec, col = "🚫하드차단: MFI 극단 과열", "#dc2626"
        elif is_breakout_extreme: dec, col = "⚠️과열확장: 추격금지, MA5 대기", "#d97706"
        elif is_breakout_normal: dec, col = "🔥불뿜는 대장주: MA5 눌림 진입", "#ec4899"
        elif pct_b_now >= 0.95: dec, col = "🚫하드차단: 볼린상단 이탈", "#dc2626"
        elif has_pos:
            if trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 추매", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 추매 보류", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 줍줍 찬스", "#16a34a"
            elif rs_label == "🚀강함" and mfi_now < 35: dec, col = "💎S급: 과매도(풀매수)", "#16a34a"
            elif adj_tech_score >= 4 and cur_p <= my_price: dec, col = "🎯A급: 기술적 반등", "#16a34a"
            elif trend_label == "🚀정배열(상승)" and pct_b_now < 0.8 and rsi_now < 60 and cur_p <= my_price: dec, col = "📈정배열: 눌림목 매수", "#16a34a"
            elif cur_p > my_price: dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            elif cur_p <= my_price: dec, col = "✅평단이하: 분할매수", "#16a34a"
            else: dec, col = "⏳보유중(신호대기)", "#64748b"
        else:
            if 0.85 <= pct_b_now < 0.95: dec, col = "⚠️상단부근: 눌림 대기", "#d97706"
            elif trend_label == "🚀정배열(상승)" and rs_label == "🚀강함" and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif mfi_now >= 80: dec, col = "⚠️단기과열: 진입 보류", "#d97706"
            elif rsi_now <= 30: dec, col = "🔥낙폭과대: 신규 진입", "#16a34a"
            elif is_early_entry: dec, col = "🟢선진입 가능: 반전 초입", "#16a34a"
            elif adj_tech_score >= 4.5 and rs_label == "🚀강함": dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            elif trend_label == "🌊역배열(하락)" and adj_tech_score >= 5: dec, col = "🎯낙폭과대: 분할매수", "#8b5cf6"
            elif ret_3m < 0 and trend_label in ["🌊역배열(하락)", "⏳혼조세"]: dec, col = "⚠️하락추세: 진입보류", "#dc2626"
            elif trend_label == "🌊역배열(하락)": dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
            else: dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

    return {
        "cur_p": cur_p, "rsi": rsi_now, "mfi": mfi_now, "pct_b": pct_b_now, "rs_label": rs_label, "adj": adj_tech_score, "dec": dec, "col": col,
        "grade": grade, "t_score": tech_total + (0 if is_etf else fin_score), "tech_total": tech_total, "fin_score": fin_score,
        "dd": current_dd, "ret_3m": ret_3m, "ret_6m": ret_6m, "target_w": targ_w, "current_w": curr_w, "buy_amt": buy_amount,
        "ext_structure": ext_structure, "int_structure": int_structure, "pd_zone": pd_zone, "smc_action": smc_action,
        "ma5": last["MA5"], "ma20": last["MA20"], "ma50": last["MA50"], "ma120": last["MA120"], "sqz": sqz_status, "macd": macd_state, "rt_macd": rt_macd_label,
        "trend": trend_label, "fvg_type": fvg_info["type"], "fvg_active": fvg_info["active"], "fvg_top": fvg_info["top"], "fvg_bottom": fvg_info["bottom"],
        "liq_state": liq_state, "int_event": int_event, "ext_event": ext_event, 
        "main_s": main_score, "rs_s": rs_s, "mfi_s": mfi_s, 
        "trend_s": trend_s, "macd_s": macd_s, "sqz_s": sqz_s, 
        "smc_insight": smc_insight
    }

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

@st.cache_data(ttl=60)
def get_all_summary(fin_score_map_items, mode):
    rows = []; fin_map = dict(fin_score_map_items)
    for name, (tkr, is_etf, a_class) in TICKER_MAP.items():
        df = load_price_df(tkr, "1y")
        if df.empty: continue
        
        # [수정] 원본 df에 지표를 덮어쓰기 위해 build_indicators 분리 실행
        df = build_indicators(df)
        f_score = fin_map.get(name, 0 if is_etf else 2)
        c = calc_scores_and_decision(name, tkr, is_etf, a_class, df, 0, False, f_score, app_mode=mode)
        
        rows.append({
            "종목명": name, "현재가": format_currency(c["cur_p"], tkr), "MDD": f"{c['dd']*100:.1f}%",
            "현재비중": f"{c['current_w']:.2f}%", "목표비중": f"{c['target_w']:.2f}%",
            "📌후보등급": c["grade"], "RS": c["rs_label"], "RSI": round(c["rsi"], 1), "MFI": round(c["mfi"], 1), 
            "볼린저 %B": round(c["pct_b"], 2), "🔥기술적 타점": c["dec"], "Adj점수": round(c["adj"], 1)
        })
    return pd.DataFrame(rows)

# legacy helper: 현재는 get_effective_weights() 경로를 주로 사용
def get_sheet_current_weight(name, ticker):
    t = normalize_ticker(ticker); matched = control_df[control_df["티커"].apply(normalize_ticker) == t]
    return float(matched.iloc[0]["현재비중"]) if not matched.empty else 0.0

# legacy helper: 현재는 get_effective_weights() 경로를 주로 사용
def get_target_weight_from_sheet(name, ticker):
    t = normalize_ticker(ticker); matched = control_df[control_df["티커"].apply(normalize_ticker) == t]
    return float(matched.iloc[0]["목표비중"]) if not matched.empty else 0.0

def get_my_price(name, ticker):
    t_norm = normalize_ticker(ticker)
    pf = portfolio_df.copy()
    pf["티커정리"] = pf["티커입력"].apply(normalize_ticker)
    matched = pf[pf["티커정리"] == t_norm]
    return float(matched.iloc[0]["매입단가"]) if not matched.empty and pd.notna(matched.iloc[0]["매입단가"]) else 0.0

def has_position(name, ticker):
    t_norm = normalize_ticker(ticker)
    pf = portfolio_df.copy()
    pf["티커정리"] = pf["티커입력"].apply(normalize_ticker)
    matched = pf[pf["티커정리"] == t_norm]
    return (not matched.empty) and (parse_num(matched.iloc[0]["보유량"]) > 0)

# -------------------------------------------------
# 8. 메인 UI 렌더링
# -------------------------------------------------
macro_res, final_macro_risk, macro_penalty, move_val = get_macro_analysis()

st.caption(f"모드: {app_mode} | 매크로 리스크: {final_macro_risk:.1f} | 매크로 패널티: -{macro_penalty}")

if macro_res:
    m_cols = st.columns(len(macro_res))
    for i, (n, info) in enumerate(macro_res.items()):
        s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] else ""
        m_cols[i].markdown(
            f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>",
            unsafe_allow_html=True
        )
else:
    st.info("매크로 데이터를 불러오지 못했습니다.")

invest_data = load_invest_sheet()
portfolio_df = load_portfolio_sheet()
control_df = load_control_sheet()
total_eval = invest_data["current_asset"]

if "fin_score_map" not in st.session_state: st.session_state.fin_score_map = {}

tab1, tab2 = st.tabs(["📋 전체 요약 전광판", "🔍 종목 정밀 관측소"])

with tab1:
    st.subheader("CCTV 통합 통제실")
    if app_mode == "개인모드": st.write(f'현재자산: {invest_data["current_asset"]:,.0f}원 | 누적손익: {invest_data["cum_profit"]:,.0f}원')
    st.dataframe(get_all_summary(tuple(sorted(st.session_state.fin_score_map.items())), app_mode), use_container_width=True, height=720, hide_index=True)

with tab2:
    options = ["🆓 자유 종목 탐색 (티커 입력)"] + list(TICKER_MAP.keys())
    sel = st.selectbox("종목 선택", options)
    is_free = (sel == "🆓 자유 종목 탐색 (티커 입력)")

    if is_free:
        c1, c2 = st.columns([2, 1])
        with c1: user_tkr_raw = st.text_input("티커/종목코드 (예: GOOGL, 005930)", "GOOGL").upper().strip()
        with c2: mkt_opt = st.selectbox("시장 (한국주식 시)", ["KOSPI (.KS)", "KOSDAQ (.KQ)"])
        if user_tkr_raw.isdigit() and len(user_tkr_raw) == 6: tkr = f"{user_tkr_raw}{'.KS' if 'KOSPI' in mkt_opt else '.KQ'}"
        else: tkr = user_tkr_raw
        is_etf, a_class, name, my_p, has_p = False, ("kr_stock" if tkr.endswith((".KS", ".KQ")) else "us_stock"), f"탐색: {tkr}", 0.0, False
    else:
        name = sel; tkr, is_etf, a_class = TICKER_MAP[sel]
        my_p, has_p = get_my_price(name, tkr), has_position(name, tkr)

    u_asset, u_price, u_curr_w, u_targ_w = 0.0, my_p, 0.0, 0.0
    if app_mode == "범용모드":
        st.markdown("### 🧩 범용 입력값")
        in1, in2 = st.columns(2)
        with in1:
            u_asset = st.number_input("총 자산(원)", min_value=0.0, value=10000000.0, step=100000.0)
            u_price = st.number_input("내 평단가", min_value=0.0, value=0.0, step=1.0)
        with in2:
            u_curr_w = st.number_input("현재비중(%)", min_value=0.0, value=0.0, step=0.1)
            u_targ_w = st.number_input("목표비중(%)", min_value=0.0, value=0.0, step=0.1)

    f_labels = get_fin_label_map(); default_f = st.session_state.fin_score_map.get(name, 0 if is_etf else 2)
    fin_score = st.radio("재무 점수", [0, 1, 2, 3, 4], index=default_f, format_func=lambda x: f_labels[x], horizontal=True)
    st.session_state.fin_score_map[name] = fin_score
    get_all_summary.clear()

    df = load_price_df(tkr, "1y")
    if not df.empty:
        
        # [수정] 원본 df에 지표를 덮어쓰기 위해 분리 실행 (차트 에러 방지용)
        df = build_indicators(df)
        
        c = calc_scores_and_decision(name, tkr, is_etf, a_class, df, u_price if app_mode=="범용모드" else my_p, 
                                     (u_price > 0 or u_curr_w > 0) if app_mode=="범용모드" else has_p, fin_score, is_free, 
                                     app_mode, u_asset, u_curr_w, u_targ_w)
        
        L, R = st.columns([1.1, 2.4])
        with L:
            st.markdown(f"<h2>📊 {name}</h2>", unsafe_allow_html=True)
            dd_c = "#dc2626" if c['dd'] <= -0.2 else ("#d97706" if c['dd'] <= -0.1 else "#2ecc71")
            ret3_color = "#2ecc71" if c["ret_3m"] > 0 else "#dc2626"
            ret6_color = "#2ecc71" if c["ret_6m"] > 0 else "#dc2626"

            st.markdown(
                f"<div class='info-panel'>"
                f"현재가: <span class='highlight'>{format_currency(c['cur_p'], tkr)}</span><br>"
                f"3개월 수익률: <span style='color:{ret3_color}; font-weight:bold;'>{c['ret_3m']*100:.1f}%</span><br>"
                f"6개월 수익률: <span style='color:{ret6_color}; font-weight:bold;'>{c['ret_6m']*100:.1f}%</span><br>"
                f"고점대비 MDD: <span style='color:{dd_c}; font-weight:bold;'>{c['dd']*100:.1f}%</span>"
                f"</div>",
                unsafe_allow_html=True
            )
            
            if is_free or app_mode == "범용모드": 
                st.info("💡 직접 입력 기반 분석 모드입니다.")
            else:
                if has_p and my_p > 0: st.markdown(f"<div class='info-panel' style='border-left: 5px solid #27ae60;'><b>내 평단가 (엑셀 연동)</b><br><span class='highlight' style='color:#2ecc71;'>{format_currency(my_p, tkr)}</span></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='info-panel'><b>비중</b><br>목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>부족 매수액: {c['buy_amt']:,.0f}원</div>", unsafe_allow_html=True)
            
            if app_mode == "범용모드": 
                st.markdown(
                    f"<div class='info-panel'><b>입력 기준</b><br>"
                    f"총 자산: {u_asset:,.0f}원<br>"
                    f"평단가: {format_currency(u_price, tkr)}<br>"
                    f"목표: {c['target_w']:.2f}% | 현재: {c['current_w']:.2f}%<br>"
                    f"<b>부족 매수액: {c['buy_amt']:,.0f}원</b></div>",
                    unsafe_allow_html=True
                )
            
            st.markdown(f'<div class="signal-box" style="background-color: {c["col"]};"><div style="font-size: 1.5em;">{c["dec"]}</div><div class="score-detail">Adj: {c["adj"]:.1f}점</div></div>', unsafe_allow_html=True)
            
            fin_text = "해당없음" if is_etf else f"{c['fin_score']}/4"
            st.markdown(
                f"<div class='info-panel' style='border-left: 5px solid #8b5cf6;'>"
                f"<b>📌 후보 등급 판정</b><br>"
                f"<span class='highlight' style='font-size:1.1em;'>{c['grade']}</span> (총점: {c['t_score']}점)<br>"
                f"└ 🛠️기술: {c['tech_total']} (RS:{c['rs_s']}, MFI:{c['mfi_s']}, 추세:{c['trend_s']}, MACD:{c['macd_s']}, SQZ:{c['sqz_s']})<br>"
                f"└ 💰재무: {fin_text}</div>",
                unsafe_allow_html=True
            )
        
        with R:
            fig = go.Figure(data=[go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Price")])
            fig.add_trace(go.Scatter(x=df.index, y=df["MA20"], line=dict(color="#fbbf24", width=2), name="MA20"))
            fig.add_trace(go.Scatter(x=df.index, y=df["MA120"], line=dict(color="#94a3b8", width=1.5, dash="dot"), name="MA120"))
            p_line = u_price if app_mode == "범용모드" else my_p
            if p_line > 0 and ((app_mode == "범용모드" and c['current_w'] > 0) or (app_mode == "개인모드" and not is_free and has_p)): 
                fig.add_hline(y=p_line, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
            fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        b1, b2 = st.columns(2)
        with b1: 
            f_txt = f"{c['fvg_type']} | {'미충족' if c['fvg_active'] else '터치됨'}" if c['fvg_type'] != "없음" else "없음"
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #e67e22;'><b>🛡️ SMC 구조 해석</b><br>• 외부구조: <b>{c['ext_structure']}</b><br>• 내부구조: <b>{c['int_structure']}</b><br>• 내부 이벤트: <b>{c['int_event']}</b><br>• 외부 이벤트: <b>{c['ext_event']}</b><br>• 유동성 상태: <b>{c['liq_state']}</b><br>• FVG 상태: <b>{f_txt}</b><br>• P/D Zone: <b>{c['pd_zone']}</b><br>• 실시간 MACD: <b>{c['rt_macd']}</b><br>• SQZ: <b>{c['sqz']}</b><hr style='margin:10px 0; border-color:#334155;'>🎯 <b>실행 해석:</b> {c['smc_action']}</div>", unsafe_allow_html=True)
        with b2: 
            st.markdown(f"<div class='info-panel' style='border-left: 5px solid #10b981;'><b>📐 전술 지표</b><br>• 추세: <b>{c['trend']}</b> | MACD: <b>{c['macd']}</b><br>• RS: <b>{c['rs_label']}</b> | RSI: <b>{c['rsi']:.1f}</b> | MFI: <b>{c['mfi']:.1f}</b><br>• 볼린저 %B: <b>{c['pct_b']:.2f}</b> | SQZ: <b>{c['sqz']}</b><hr style='margin:10px 0; border-color:#334155;'><span class='smc-tag'>MA5</span> {format_currency(c['ma5'], tkr)}<br><span class='smc-tag'>MA20</span> {format_currency(c['ma20'], tkr)}<br><span class='smc-tag'>MA50</span> {format_currency(c['ma50'], tkr)}<br><span class='smc-tag'>MA120</span> {format_currency(c['ma120'], tkr)}<hr style='margin:10px 0; border-color:#334155;'>💡 <b>보조 해석:</b> {c['smc_insight']}</div>", unsafe_allow_html=True)

        st.markdown("### 📰 최신 현장 뉴스")
        news_items, news_logs = get_ticker_news(tkr, name, news_debug)
        if news_items:
            for item in news_items: st.markdown(f"<div class='news-box'><a href='{item['link']}' target='_blank'>🔗 {item['title']}</a> <span style='color:#94a3b8; font-size:0.8em;'>출처: {item['publisher']}</span></div>", unsafe_allow_html=True)
        else: st.info("현재 제공되는 최신 뉴스가 없습니다.")
        
        if news_debug: 
            with st.expander("🛠️ 뉴스 디버그 로그"):
                for log in news_logs: st.write(log)
    else: st.error("해당 종목의 차트 데이터를 불러올 수 없습니다. 티커를 다시 확인해 주십시오.")
