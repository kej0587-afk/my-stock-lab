import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta

# 1. 페이지 설정
st.set_page_config(page_title="대장님의 최종 관제실 v4.0", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0b0f19; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1px solid #1f2937; }
    h1, h2, h3, h4 { color: #f8fafc !important; font-weight: 800 !important; }
    .signal-box { padding: 20px; border-radius: 12px; text-align: center; margin-bottom: 15px; color: white !important; font-weight: bold; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.5); }
    .macro-panel { background-color: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-top: 4px solid #e74c3c; font-size: 0.95em; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .info-panel { background-color: #1e293b; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 5px solid #3b82f6; color: #f8fafc; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .smc-tag { font-size: 0.85em; color: #60a5fa; font-weight: bold; }
    .highlight { font-size: 1.4em; font-weight: bold; color: #fbbf24; text-shadow: 1px 1px 2px #000; }
    .score-detail { font-size: 0.85em; font-weight: normal; color: #cbd5e1; margin-top: 8px; }
    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] { background-color: #111827; border-radius: 8px; padding: 5px; }
    .stTabs [data-baseweb="tab"] { color: #94a3b8; font-weight: bold; }
    .stTabs [aria-selected="true"] { color: #ffffff !important; background-color: #3b82f6 !important; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 REALTIME DIGITAL DASHBOARD v4.0")

# --- 2. 매크로 추세 판독 엔진 ---
@st.cache_data(ttl=300)
def get_macro_analysis():
    tickers = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "MOVE": "^MOVE", "VIX": "^VIX"}
    results = {}; m_trend_score = 0; storm_count = 0
    for name, tkr in tickers.items():
        data = yf.download(tkr, period="2mo", interval="1d", progress=False)
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
            cur = float(data['Close'].iloc[-1])
            prev_m = float(data['Close'].iloc[-22]) if len(data) >= 22 else float(data['Close'].iloc[0])
            chg = ((cur - prev_m) / prev_m) * 100
            
            icon = "🔺" if chg > 2.0 else ("🔻" if chg < -2.0 else "➖")
            if icon == "🔺" and name in ["10Y 금리", "유가", "환율"]: m_trend_score += 0.5
            elif icon == "🔻" and name in ["10Y 금리", "유가", "환율"]: m_trend_score -= 0.5
            
            is_storm = (name == "VIX" and cur > 30) or (name == "환율" and cur > 1400) or (name == "10Y 금리" and cur > 4.7)
            if is_storm: storm_count += 1
            results[name] = {"val": cur, "icon": icon, "storm": is_storm}
            
    move_v = results.get("MOVE", {"val": 0})["val"]
    move_s = 1.5 if move_v >= 120 else (0.5 if move_v >= 100 else 0)
    risk = storm_count + m_trend_score + move_s
    penalty = 2.0 if risk >= 4 else (1.5 if risk >= 2.5 else (0.5 if risk >= 1.5 else 0))
    return results, risk, penalty

macro_res, m_risk, m_penalty = get_macro_analysis()

# 상단 매크로 패널 출력 (항상 보임)
m_cols = st.columns(len(macro_res))
for i, (n, info) in enumerate(macro_res.items()):
    s_tag = "<br><span style='color:#ef4444; font-weight:bold;'>🚨폭풍</span>" if info['storm'] else ""
    m_cols[i].markdown(f"<div class='macro-panel'>🌐 {n}: <b>{info['val']:,.1f}</b> {info['icon']}{s_tag}</div>", unsafe_allow_html=True)


# --- 3. 종목 세팅 ---
TICKER_MAP = {
    "나스닥100": ("379810.KS", True), "QQQM": ("QQQM", True), "QLD": ("QLD", True), "TQQQ": ("TQQQ", True), 
    "S&P500": ("379800.KS", True), "다우존스": ("458730.KS", True), "KODEX 200": ("069500.KS", True), 
    "MSFT": ("MSFT", False), "네비우스": ("NBIS", False), "삼성전자": ("005930.KS", False), 
    "두산에너빌리티": ("034020.KS", False), "하이닉스": ("000660.KS", False), "TSM": ("TSM", False)
}

def format_currency(val, ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"): return f"₩{int(val):,}"
    return f"${val:,.2f}"

# --- 4. 요약 전광판 전용 데이터 수집 함수 ---
@st.cache_data(ttl=300)
def get_all_summary():
    rows = []
    for name, (tkr, is_etf) in TICKER_MAP.items():
        df = yf.download(tkr, period="1y", interval="1d", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.ffill(inplace=True); df.dropna(inplace=True)
        
        c = df['Close']
        ma20 = c.rolling(20).mean().iloc[-1]
        ma50 = c.rolling(50).mean().iloc[-1]
        ma120 = c.rolling(120).mean().iloc[-1]
        
        trend = "🚀정배열" if (ma20 > ma50 > ma120) else ("↗️상승전환" if ma20 > ma50 else "🌊역배열")
        
        rsi = ta.momentum.RSIIndicator(c).rsi().iloc[-1]
        mfi = ta.volume.MFIIndicator(df['High'], df['Low'], c, df['Volume']).money_flow_index().iloc[-1]
        
        bb = ta.volatility.BollingerBands(c)
        bb_hi = bb.bollinger_hband().iloc[-1]; bb_lo = bb.bollinger_lband().iloc[-1]
        pct_b = (c.iloc[-1] - bb_lo) / (bb_hi - bb_lo) if (bb_hi - bb_lo) != 0 else 0.5
        
        kc = ta.volatility.KeltnerChannel(df['High'], df['Low'], c, 20, 20, 1.5)
        sqz_on = (bb_hi < kc.keltner_channel_hband().iloc[-1]) and (bb_lo > kc.keltner_channel_lband().iloc[-1])
        
        # 타점 자동 판독 (기본 기술적 기준)
        if pct_b >= 0.95 or mfi >= 85: sig = "🚫단기과열(주의)"
        elif rsi <= 35: sig = "🔥과매도(줍줍)"
        elif trend == "🚀정배열" and 45 < rsi <= 58 and 0.45 < pct_b < 0.8: sig = "🎯S급 눌림목"
        elif pct_b < 0.2: sig = "✅밴드하단 반등"
        else: sig = "🔍관망/대기"
        
        rows.append({
            "종목명": name,
            "현재가": format_currency(c.iloc[-1], tkr),
            "추세(MA)": trend,
            "RSI": round(rsi, 1),
            "MFI": round(mfi, 1),
            "볼린저 %B": round(pct_b, 2),
            "SQZ": "⏳압축" if sqz_on else "➡️분출",
            "🔥기술적 타점": sig
        })
    return pd.DataFrame(rows)


# --- 5. 탭(Tab) UI 구성 ---
tab1, tab2 = st.tabs(["📋 전체 요약 전광판 (한눈에 보기)", "🔍 개별 상세 관제탑 (정밀 판독)"])

with tab1:
    st.subheader("CCTV 통합 통제실 (전체 종목 스캔)")
    st.caption("※ 전체 종목의 기술적 지표를 실시간으로 긁어와 위험/기회를 판독합니다. (5분마다 자동 갱신)")
    with st.spinner('전체 현장 순찰 중입니다... 잠시만 기다려주십시오!'):
        summary_df = get_all_summary()
        # 데이터프레임 UI 출력
        st.dataframe(
            summary_df, 
            use_container_width=True, 
            height=600,
            hide_index=True
        )

with tab2:
    # 탭 2 안에서만 작동하는 것처럼 보이게 사이드바 설명 추가
    st.sidebar.markdown("<br><div style='background-color:#1e293b; padding:10px; border-radius:5px;'><b style='color:#fbbf24;'>※ 주의:</b> 아래 컨트롤은 [개별 상세 관제탑] 탭에서만 작동합니다.</div><br>", unsafe_allow_html=True)
    
    sel_name = st.sidebar.selectbox("1. 종목 선택", list(TICKER_MAP.keys()))
    sel_ticker, is_etf = TICKER_MAP[sel_name]
    my_price = st.sidebar.number_input(f"2. 💰 {sel_name} 매입가", min_value=0.0, value=0.0)
    rs_score = st.sidebar.radio("3. 📊 RS 점수", [0, 1, 2], index=1, horizontal=True)
    
    fin_labels = {0: "0점 (ETF/해당없음)", 1: "1점 (🚨F급)", 2: "2점 (⚠️보통)", 3: "3점 (✅우량)", 4: "4점 (💎S급)"}
    fin_score = st.sidebar.radio("4. 🏢 재무 점수", [0, 1, 2, 3, 4], index=(0 if is_etf else 2), format_func=lambda x: fin_labels[x])

    @st.cache_data(ttl=60)
    def get_stock_data(ticker):
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty: return df
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.ffill(inplace=True); df.dropna(inplace=True)
        df['MA5'] = df['Close'].rolling(window=5).mean(); df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA50'] = df['Close'].rolling(window=50).mean(); df['MA120'] = df['Close'].rolling(window=120).mean()
        df['RSI'] = ta.momentum.RSIIndicator(close=df['Close']).rsi()
        df['MFI'] = ta.volume.MFIIndicator(high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume']).money_flow_index()
        macd = ta.trend.MACD(close=df['Close'])
        df['MACD'] = macd.macd(); df['MACD_Sig'] = macd.macd_signal()
        bb = ta.volatility.BollingerBands(close=df['Close'])
        df['%B'] = (df['Close'] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband())
        kc = ta.volatility.KeltnerChannel(high=df['High'], low=df['Low'], close=df['Close'], window=20, window_atr=20, multiplier=1.5)
        df['SQZ_ON'] = (bb.bollinger_hband() < kc.keltner_channel_hband()) & (bb.bollinger_lband() > kc.keltner_channel_lband())
        return df

    df = get_stock_data(sel_ticker)

    if not df.empty:
        last = df.iloc[-1]; prev = df.iloc[-2]; cur_p = float(last['Close'])
        
        trend_s = 2 if (last['MA20'] > last['MA50'] > last['MA120']) else (1 if last['MA20'] > last['MA50'] else 0)
        macd_s = 2 if (last['MACD'] > last['MACD_Sig'] and prev['MACD'] <= prev['MACD_Sig']) else 0
        rsi_s = 2 if last['RSI'] < 35 else (1 if last['RSI'] < 45 else 0)
        main_score = trend_s + macd_s + rsi_s
        mfi_score = -1 if last['MFI'] > 80 else (2 if last['MFI'] < 30 else 0)
        adj_score = main_score + rs_score + mfi_score - m_penalty
        
        sqz_status = "⏳압축중" if last['SQZ_ON'] else "➡️해제유지"
        
        if not is_etf and fin_score == 1: dec, col = "🚨하드차단: 재무F급(처분)", "#dc2626"
        elif m_penalty >= 2.0: dec, col = "🛑하드차단: 매크로 퍼펙트스톰", "#dc2626"
        elif last['%B'] >= 0.95 or last['MFI'] >= 85: dec, col = "🚫하드차단: 단기 과열(추격금지)", "#dc2626"
        elif my_price > 0:
            if trend_s == 2 and rs_score == 2 and 45 < last['RSI'] <= 58 and 0.45 < last['%B'] < 0.8: dec, col = "🎯S급 눌림목: 탑승 찬스", "#8b5cf6"
            elif adj_score >= 4 and cur_p <= my_price: dec, col = "✅평단이하: 분할매수", "#16a34a"
            elif cur_p > my_price: dec, col = "⏳평단이상: 하락대기(보유)", "#d97706"
            else: dec, col = "✅분할매수 가능", "#16a34a"
        else:
            if adj_score >= 4.5 and rs_score == 2: dec, col = "🆕신규진입: 대장주 포착", "#16a34a"
            else: dec, col = "🔍대기: 신규 타점 탐색", "#64748b"

        c1, c2 = st.columns([1.2, 2.3])
        with c1:
            st.markdown(f"<h2>📊 {sel_name}</h2>", unsafe_allow_html=True)
            st.markdown(f"<div class='info-panel'>현재가: <span class='highlight'>{format_currency(cur_p, sel_ticker)}</span></div>", unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class="signal-box" style="background-color: {col};">
                <div style="font-size: 1.5em; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">{dec}</div>
                <div class="score-detail">
                    (Main:<b>{main_score}</b> | RS:<b>{rs_score}</b> | MFI:<b>{mfi_score}</b> | Macro:<b>-{m_penalty}</b>) ➔ Adj: <b style="color:white; font-size:1.1em;">{adj_score}점</b>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div class='info-panel' style='border-left: 5px solid #e67e22;'>
                <b>🛡️ SMC/Swing 전술 지표</b><br><br>
                • RSI: <b>{last['RSI']:.1f}</b> / MFI: <b>{last['MFI']:.1f}</b><br>
                • SQZ: <span style='color:#fbbf24;'><b>{sqz_status}</b></span> (에너지 응축)<br>
                <hr style='margin:12px 0; border-color:#334155;'>
                <span class='smc-tag'>[단기]</span> <b>MA5 :</b> {format_currency(last['MA5'], sel_ticker)}<br>
                <span class='smc-tag'>[스윙]</span> <b>MA20 :</b> {format_currency(last['MA20'], sel_ticker)}<br>
                <span class='smc-tag'>[중기]</span> <b>MA50 :</b> {format_currency(last['MA50'], sel_ticker)}<br>
                <span class='smc-tag'>[기관]</span> <b>MA120:</b> {format_currency(last['MA120'], sel_ticker)}
            </div>
            """, unsafe_allow_html=True)

        with c2:
            fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price")])
            fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#fbbf24', width=2), name="MA20 (Swing)"))
            fig.add_trace(go.Scatter(x=df.index, y=df['MA120'], line=dict(color='#94a3b8', width=1.5, dash='dot'), name="MA120 (Inst)"))
            if my_price > 0: fig.add_hline(y=my_price, line_dash="dash", line_color="#22c55e", annotation_text="내 평단가", annotation_position="bottom right")
            
            fig.update_layout(
                template="plotly_dark", height=600, margin=dict(l=0, r=0, t=20, b=0), xaxis_rangeslider_visible=False,
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("데이터 로드 실패. 티커를 확인해주세요.")
