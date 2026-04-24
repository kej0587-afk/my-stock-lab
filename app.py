import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta

# -------------------------------------------------
# 1. 기본 설정
# -------------------------------------------------
st.set_page_config(page_title="대장님의 최종 관제실 v7.1", layout="wide")

SPREADSHEET_ID = "195Mru5bqt_jvUQbgWcI1vHFDzEJV0wDJc05BXzmi9KA"

INVEST_SHEET_GID = "168627640"      # [3] 투자 데이터
ETF_SHEET_GID = "604547263"         # [4] 주식/채권(ETF)
CONTROL_SHEET_GID = "1420210871"    # 관제탑

INVEST_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={INVEST_SHEET_GID}"
ETF_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={ETF_SHEET_GID}"
CONTROL_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={CONTROL_SHEET_GID}"

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
</style>
""", unsafe_allow_html=True)

st.title("🚀 REALTIME DIGITAL DASHBOARD v7.1")

# -------------------------------------------------
# 2. 유틸 함수
# -------------------------------------------------
def format_currency(val, ticker):
    if str(ticker).endswith(".KS") or str(ticker).endswith(".KQ"):
        return f"₩{int(val):,}"
    return f"${val:,.2f}"

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
        return 2, "🔥매수신호(골든크로스)"
    elif last_macd > last_sig:
        return 1, "📈추세유지(상승중)"
    elif last_macd < last_sig and prev_macd >= prev_sig:
        return -2, "📉하락주의(데드크로스)"
    return 0, "⏳추세관망"

def get_fin_label_map():
    return {
        0: "0점 (ETF/해당없음)",
        1: "1점 (🚨F급/처분)",
        2: "2점 (⚠️불안정/주의)",
        3: "3점 (✅회복형/중간형)",
        4: "4점 (💎완성형 우량)"
    }

# -------------------------------------------------
# 3. 매크로
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
    m_trend_score = 0
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

        if icon == "🔺" and name in ["10Y 금리", "유가", "환율"]:
            m_trend_score += 0.5
        elif icon == "🔻" and name in ["10Y 금리", "유가", "환율"]:
            m_trend_score -= 0.5

        is_storm = (
            (name == "VIX" and cur > 30) or
            (name == "환율" and cur > 1400) or
            (name == "10Y 금리" and cur > 4.7)
        )
        if is_storm:
            storm_count += 1

        results[name] = {"val": cur, "icon": icon, "storm": is_storm}

    move_v = results.get("MOVE", {"val": 0})["val"]
    move_s = 1.5 if move_v >= 120 else (0.5 if move_v >= 100 else 0)

    risk = storm_count + m_trend_score + move_s
    penalty = 2.0 if risk >= 4 else (1.5 if risk >= 2.5 else (0.5 if risk >= 1.5 else 0))
    return results, risk, penalty

macro_res, m_risk, m_penalty = get_macro_analysis()

m_cols = st.columns(len(macro_res))
for i, (n, info) in enumerate(macro_res.items()):
    s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info["storm"] else ""
    m_cols[i].markdown(
        f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>",
        unsafe_allow_html=True
    )

# -------------------------------------------------
# 4. 구글시트 읽기
# -------------------------------------------------
@st.cache_data(ttl=300)
def load_invest_sheet():
    df = pd.read_csv(INVEST_SHEET_URL, header=None)

    # 시드머니: R4 -> row 3, col 17
    seed_money = pd.to_numeric(df.iloc[3, 17], errors="coerce")

    # 자산클래스: B:F 6~13행
    asset_class = df.iloc[5:13, 1:6].copy()
    asset_class.columns = ["구분", "평가금액", "비율", "차이", "목표"]

    # 국가별: B:F 14~20행
    country = df.iloc[13:20, 1:6].copy()
    country.columns = ["구분", "평가금액", "비율", "차이", "목표"]

    # 포지션별: B:F 21~26행
    position = df.iloc[20:26, 1:6].copy()
    position.columns = ["구분", "평가금액", "비율", "차이", "목표"]

    # 우측 요약: P:R 7~19행
    right_summary = df.iloc[6:19, 15:18].copy()

    return {
        "seed_money": float(seed_money) if pd.notna(seed_money) else 0.0,
        "asset_class": asset_class,
        "country": country,
        "position": position,
        "right_summary": right_summary
    }

@st.cache_data(ttl=300)
def load_portfolio_sheet():
    df = pd.read_csv(ETF_SHEET_URL, header=4)
    df = df.iloc[0:30].copy()  # 6행~35행

    df = df.rename(columns={
        df.columns[1]: "통화",
        df.columns[2]: "자산클래스",
        df.columns[3]: "국가",
        df.columns[4]: "자산구분",
        df.columns[5]: "자산명",
        df.columns[6]: "요약",
        df.columns[7]: "티커입력",
        df.columns[8]: "보유량",
        df.columns[9]: "매입가",
        df.columns[10]: "현재가",
        df.columns[11]: "수익률",
        df.columns[12]: "평가손익",
        df.columns[13]: "평가금액",
        df.columns[14]: "원화환산",
    })

    for col in ["자산명", "티커입력", "통화", "자산클래스", "국가", "자산구분"]:
        df[col] = df[col].astype(str).str.strip()

    for col in ["보유량", "매입가", "현재가", "평가손익", "평가금액", "원화환산"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df

@st.cache_data(ttl=300)
def load_control_sheet():
    df = pd.read_csv(CONTROL_SHEET_URL, header=None)

    # D47:G57
    block = df.iloc[46:57, 3:7].copy()
    block.columns = ["자산명", "티커", "목표비중", "현재비중"]

    block["자산명"] = block["자산명"].astype(str).str.strip()
    block["티커"] = block["티커"].astype(str).str.strip()
    block["목표비중"] = pd.to_numeric(block["목표비중"], errors="coerce").fillna(0)
    block["현재비중"] = pd.to_numeric(block["현재비중"], errors="coerce").fillna(0)

    return block

invest_data = load_invest_sheet()
portfolio_df = load_portfolio_sheet()
control_df = load_control_sheet()

total_eval = float(portfolio_df["평가금액"].sum())

portfolio_value_map = {
    row["자산명"]: float(row["평가금액"])
    for _, row in portfolio_df.iterrows()
    if row["자산명"] != ""
}

def get_current_weight(name: str) -> float:
    if total_eval <= 0:
        return 0.0
    return round((portfolio_value_map.get(name, 0.0) / total_eval) * 100, 2)

def get_target_weight_from_sheet(name: str) -> float:
    matched = control_df[control_df["자산명"] == name]
    if matched.empty:
        return 0.0
    return float(matched.iloc[0]["목표비중"])

def get_buy_amount(name: str) -> float:
    target_w = get_target_weight_from_sheet(name)
    current_w = get_current_weight(name)
    gap = max(target_w - current_w, 0)
    return round(total_eval * (gap / 100), 0)

# -------------------------------------------------
# 5. 자산맵
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

@st.cache_data(ttl=300)
def get_rs_score(name, ticker, asset_class):
    if asset_class == "kr_stock":
        bench = "069500.KS"         # KODEX200
    elif asset_class == "us_stock":
        bench = "QQQM"              # 미국 개별 성장주
    elif asset_class == "us_etf_nasdaq":
        bench = "379810.KS"         # 나스닥100
    elif asset_class == "us_etf_sp":
        bench = "379810.KS"         # 네 기준대로 나스닥100
    elif asset_class == "kr_etf":
        bench = "069500.KS"
    else:
        return 1, "➖보통"

    if ticker == bench:
        return 1, "➖보통"

    stock_df = load_price_df(ticker, period="6mo")
    bench_df = load_price_df(bench, period="6mo")
    if stock_df.empty or bench_df.empty:
        return 1, "➖보통"

    stock_ret = stock_df["Close"].pct_change(63).iloc[-1]
    bench_ret = bench_df["Close"].pct_change(63).iloc[-1]
    diff = stock_ret - bench_ret

    if diff >= 0.10:
        return 2, "🚀강함"
    elif diff >= -0.03:
        return 1, "➖보통"
    return 0, "🐢약함"

# -------------------------------------------------
# 6. 요약 전광판
# -------------------------------------------------
@st.cache_data(ttl=300)
def get_all_summary():
    rows = []

    for name, (tkr, is_etf, asset_class) in TICKER_MAP.items():
        df = load_price_df(tkr, period="1y")
        if df.empty:
            continue

        c = df["Close"]
        last = df.iloc[-1]
        prev = df.iloc[-2]

        ma20 = c.rolling(20).mean()
        ma50 = c.rolling(50).mean()
        ma120 = c.rolling(120).mean()

        last_ma20 = ma20.iloc[-1]
        last_ma50 = ma50.iloc[-1]
        last_ma120 = ma120.iloc[-1]

        if last_ma20 > last_ma50 > last_ma120:
            trend = "🚀정배열"
            trend_score = 2
        elif last_ma20 > last_ma50:
            trend = "⏳혼조세"
            trend_score = 1
        else:
            trend = "🌊역배열"
            trend_score = 0

        rsi = ta.momentum.RSIIndicator(c).rsi()
        mfi = ta.volume.MFIIndicator(df["High"], df["Low"], c, df["Volume"]).money_flow_index()

        last_rsi = float(rsi.iloc[-1])
        last_mfi = float(mfi.iloc[-1])

        bb = ta.volatility.BollingerBands(c, window=20, window_dev=2)
        bb_hi = bb.bollinger_hband()
        bb_lo = bb.bollinger_lband()
        pct_b = (c - bb_lo) / (bb_hi - bb_lo)
        last_pct_b = float(pct_b.iloc[-1])

        kc = ta.volatility.KeltnerChannel(
            high=df["High"], low=df["Low"], close=c,
            window=20, window_atr=20, multiplier=1.5
        )
        sqz_series = (bb_hi < kc.keltner_channel_hband()) & (bb_lo > kc.keltner_channel_lband())
        sqz_status = get_sqz_status(bool(sqz_series.iloc[-1]), bool(sqz_series.iloc[-2]))

        macd = ta.trend.MACD(c)
        macd_score, macd_label = get_macd_state(
            macd.macd().iloc[-1],
            macd.macd_signal().iloc[-1],
            macd.macd().iloc[-2],
            macd.macd_signal().iloc[-2]
        )

        rs_score, rs_label = get_rs_score(name, tkr, asset_class)
        mfi_score = -1 if last_mfi > 80 else (2 if last_mfi < 30 else 0)

        vol_ma20 = df["Volume"].rolling(20).mean().iloc[-1]
        vol_score = 1 if float(last["Volume"]) > float(vol_ma20) * 1.2 else 0
        rsi_score = 2 if last_rsi < 35 else (1 if last_rsi < 45 else 0)

        main_score = trend_score + max(macd_score, 0) + rsi_score + vol_score
        total_score = main_score + rs_score + mfi_score

        current_w = get_current_weight(name)
        target_w = get_target_weight_from_sheet(name)
        buy_amount = get_buy_amount(name)

        if is_etf:
            if current_w > target_w and target_w > 0:
                signal = "🛑비중 초과"
            elif current_w >= target_w and target_w > 0:
                signal = "⏸️비중 충족"
            elif last_mfi >= 85 and last_pct_b >= 0.98:
                signal = "⚠️극단과열: 소액만"
            elif last_mfi >= 80:
                signal = "⚠️단기과열: 속도조절"
            elif trend == "🚀정배열" and rs_label == "🚀강함" and 45 < last_rsi <= 58 and 0.45 < last_pct_b < 0.8:
                signal = "🎯ETF 눌림목"
            elif total_score >= 4:
                signal = "✅분할매수"
            else:
                signal = "🔍관망/대기"
        else:
            if last_mfi >= 85:
                signal = "🚫MFI 과열"
            elif last_pct_b >= 0.95:
                signal = "🚫상단이탈"
            elif trend == "🚀정배열" and rs_label == "🚀강함" and 45 < last_rsi <= 58 and 0.45 < last_pct_b < 0.8:
                signal = "🎯S급 눌림목"
            elif last_rsi <= 30:
                signal = "🔥과매도"
            else:
                signal = "🔍신규 타점 탐색"

        rows.append({
            "종목명": name,
            "현재가": format_currency(c.iloc[-1], tkr),
            "현재비중": f"{current_w:.2f}%",
            "목표비중": f"{target_w:.2f}%",
            "부족매수액": f"{buy_amount:,.0f}",
            "추세(MA)": trend,
            "MACD": macd_label,
            "RS": rs_label,
            "RSI": round(last_rsi, 1),
            "MFI": round(last_mfi, 1),
            "볼린저 %B": round(last_pct_b, 2),
            "SQZ": sqz_status,
            "🔥기술적 타점": signal,
            "총점(기술)": total_score
        })

    return pd.DataFrame(rows)

# -------------------------------------------------
# 7. UI
# -------------------------------------------------
tab1, tab2 = st.tabs(["📋 전체 요약 전광판", "🔍 개별 상세 관제탑"])

with tab1:
    st.subheader("CCTV 통합 통제실")
    st.write(f"시드머니: {invest_data['seed_money']:,.0f}원")
    st.write(f"총 평가금액: {total_eval:,.0f}원")

    summary_df = get_all_summary()
    st.dataframe(summary_df, use_container_width=True, height=720, hide_index=True)

with tab2:
    sel_name = st.selectbox("종목 선택", list(TICKER_MAP.keys()))
    sel_ticker, is_etf, asset_class = TICKER_MAP[sel_name]

    matched = portfolio_df[portfolio_df["자산명"] == sel_name]
    my_price = float(matched.iloc[0]["매입가"]) if not matched.empty else 0.0

    fin_labels = get_fin_label_map()
    fin_score = st.radio(
        "재무 점수",
        [0, 1, 2, 3, 4],
        index=(0 if is_etf else 2),
        format_func=lambda x: fin_labels[x],
        horizontal=True
    )

    df = load_price_df(sel_ticker, period="1y")
    if not df.empty:
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

        last = df.iloc[-1]
        prev = df.iloc[-2]
        cur_p = float(last["Close"])

        trend_s = 2 if (last["MA20"] > last["MA50"] > last["MA120"]) else (1 if last["MA20"] > last["MA50"] else 0)
        trend_label = "🚀정배열(상승)" if trend_s == 2 else ("⏳혼조세" if trend_s == 1 else "🌊역배열(하락)")
        macd_s, macd_label = get_macd_state(last["MACD"], last["MACD_Sig"], prev["MACD"], prev["MACD_Sig"])

        rsi_now = float(last["RSI"])
        mfi_now = float(last["MFI"])
        pct_b_now = float(last["%B"])

        rsi_s = 2 if rsi_now < 35 else (1 if rsi_now < 45 else 0)
        mfi_s = -1 if mfi_now > 80 else (2 if mfi_now < 30 else 0)

        rs_score, rs_label = get_rs_score(sel_name, sel_ticker, asset_class)
        sqz_status = get_sqz_status(bool(last["SQZ_ON"]), bool(prev["SQZ_ON"]))
        sqz_s = 1 if sqz_status == "🚀해제직후" else 0

        vol_ma20 = df["Volume"].rolling(20).mean().iloc[-1]
        vol_score = 1 if float(last["Volume"]) > float(vol_ma20) * 1.2 else 0

        main_score = trend_s + max(macd_s, 0) + rsi_s + vol_score
        tech_score = main_score + rs_score + mfi_s + sqz_s
        adj_score = tech_score

        current_w = get_current_weight(sel_name)
        target_w = get_target_weight_from_sheet(sel_name)
        buy_amount = get_buy_amount(sel_name)

        if is_etf:
            if current_w > target_w and target_w > 0:
                dec, col = "🛑비중 초과: 추가매수 금지", "#dc2626"
            elif current_w >= target_w and target_w > 0:
                dec, col = "⏸️비중 충족: 관망", "#d97706"
            elif mfi_now >= 85 and pct_b_now >= 0.98:
                dec, col = "⚠️극단과열: 소액매수만", "#d97706"
            elif mfi_now >= 80:
                dec, col = "⚠️단기과열: 신규는 속도조절", "#d97706"
            elif trend_s == 2 and rs_score == 2 and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                dec, col = "🎯ETF 눌림목: 분할매수", "#8b5cf6"
            elif adj_score >= 4:
                dec, col = "✅추세 양호: 분할매수", "#16a34a"
            elif adj_score >= 2:
                dec, col = "⏳관망/소액매수", "#64748b"
            else:
                dec, col = "🔍대기: 다음 기회 탐색", "#64748b"
        else:
            if fin_score == 1:
                dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
            elif mfi_now >= 85:
                dec, col = "🚫하드차단: MFI 극단적 과열(추격금지)", "#dc2626"
            elif pct_b_now >= 0.95:
                dec, col = "🚫하드차단: 볼린저밴드 상단 이탈(추격금지)", "#dc2626"
            elif my_price > 0:
                if trend_s == 2 and rs_score == 2 and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                    dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
                elif mfi_now >= 80:
                    dec, col = "⚠️단기과열: 추매 보류(보유자 영역)", "#d97706"
                elif rsi_now <= 30:
                    dec, col = "🔥낙폭과대: 줍줍 찬스", "#16a34a"
                elif adj_score >= 4 and cur_p <= my_price:
                    dec, col = "✅평단이하: 분할매수", "#16a34a"
                elif cur_p > my_price:
                    dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
                else:
                    dec, col = "⏳보유중(신호대기)", "#64748b"
            else:
                if 0.85 <= pct_b_now < 0.95:
                    dec, col = "⚠️상단부근: 눌림 대기", "#d97706"
                elif trend_s == 2 and rs_score == 2 and 45 < rsi_now <= 58 and 0.45 < pct_b_now < 0.8:
                    dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
                elif mfi_now >= 80:
                    dec, col = "⚠️단기과열: 진입 보류(조정 대기)", "#d97706"
                elif rsi_now <= 30:
                    dec, col = "🔥낙폭과대: 신규 진입 찬스", "#16a34a"
                elif adj_score >= 4.5 and rs_score == 2:
                    dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
                elif trend_s == 0:
                    dec, col = "🚫진입보류: 역배열 대기", "#dc2626"
                else:
                    dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

        c1, c2 = st.columns([1.2, 2.3])

        with c1:
            st.markdown(f"## 📊 {sel_name}")
            st.markdown(f"현재가: **{format_currency(cur_p, sel_ticker)}**")
            st.markdown(f"비중: 목표 **{target_w:.2f}%** | 현재 **{current_w:.2f}%**")
            st.markdown(f"부족 매수액: **{buy_amount:,.0f}원**")
            st.markdown(f"판정: **{dec}**")
            st.markdown(f"점수: Main {main_score} / RS {rs_score} / MFI {mfi_s} / SQZ {sqz_s} / Adj {adj_score}")
            st.markdown(f"추세: {trend_label}")
            st.markdown(f"MACD: {macd_label}")
            st.markdown(f"RS: {rs_label}")
            st.markdown(f"SQZ: {sqz_status}")
            st.markdown(f"RSI: {rsi_now:.1f} / MFI: {mfi_now:.1f} / %B: {pct_b_now:.2f}")

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

            if my_price > 0:
                fig.add_hline(
                    y=my_price,
                    line_dash="dash",
                    line_color="#22c55e",
                    annotation_text="내 평단가",
                    annotation_position="bottom right"
                )

            fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
