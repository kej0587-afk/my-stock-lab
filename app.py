import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import ta

st.set_page_config(page_title="대장님의 관제실 v3.7", layout="wide")

st.markdown("""
<style>
    .main { background-color: #0e1117; color: #ffffff; }
    .signal-box { padding:20px; border-radius:10px; text-align:center; margin-bottom: 15px; color: white; font-weight: bold; border: 1px solid #444; }
    .info-panel { background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #7f8c8d; color: #ecf0f1; font-size: 1.05em; }
    .smc-tag { font-size: 0.8em; color: #3498db; font-weight: normal; }
    .highlight { font-size: 1.3em; font-weight: bold; color: #f1c40f; }
    .score-text { font-size: 0.85em; font-weight: normal; opacity: 0.8; margin-top: 5px; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 REALTIME DIGITAL DASHBOARD v3.7 (SMC/Swing)")

# 종목 세팅
TICKER_MAP = {
    "나스닥100": ("379810.KS", True), "QQQM": ("QQQM", True), "QLD": ("QLD", True), "TQQQ": ("TQQQ", True), 
    "S&P500": ("379800.KS", True), "다우존스": ("458730.KS", True), "KODEX 200": ("069500.KS", True), 
    "MSFT": ("MSFT", False), "네비우스": ("NBIS", False), "삼성전자": ("005930.KS", False), 
    "두산에너빌리티": ("034020.KS", False), "시에나": ("CIEN", False), "하이닉스": ("000660.KS", False), 
    "한화에어로스페이스": ("012450.KS", False), "HD현대중공업": ("329180.KS", False), "에이피알": ("278470.KS", False), 
    "샌디스크": ("WDC", False), "TSM": ("TSM", False), "브로드컴": ("AVGO", False), "MRVL": ("MRVL", False), 
    "HD현대일렉트릭": ("267260.KS", False), "버티브홀딩스": ("VRT", False), "벤처글로벌": ("VG", False), 
    "마이크론": ("MU", False), "에이디테크놀러지": ("200710.KQ", False)
}

def format_currency(val, ticker):
    if ticker.endswith(".KS") or ticker.endswith(".KQ"):
        return f"₩{int(val):,}"
    else:
        return f"${val:,.2f}"

# --- 사이드바 ---
st.sidebar.header("🛠️ 관제탑 컨트롤")
selected_name = st.sidebar.selectbox("1. 종목 선택", list(TICKER_MAP.keys()))
selected_ticker, is_etf = TICKER_MAP[selected_name]
my_price = st.sidebar.number_input(f"2. 💰 {selected_name} 매입가", min_value=0.0, value=0.0, step=1.0)
rs_score = st.sidebar.radio("3. 📊 RS 점수", [0, 1, 2], index=1, horizontal=True)
fin_labels = {0: "0점 (ETF/해당없음)", 1: "1점 (🚨F급)", 2: "2점 (⚠️보통)", 3: "3점 (✅우량)", 4: "4점 (💎S급)"}
default_fin = 0 if is_etf else 2
fin_score = st.sidebar.radio("4. 🏢 재무 점수", [0, 1, 2, 3, 4], index=default_fin, format_func=lambda x: fin_labels[x])

@st.cache_data(ttl=60)
def get_data(ticker):
    df = yf.download(ticker, period="1y", interval="1d")
    if df.empty: return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.ffill(inplace=True); df.dropna(inplace=True)
    
    # 이평선
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA120'] = df['Close'].rolling(window=120).mean()
    
    # 지표
    df['RSI'] = ta.momentum.RSIIndicator(close=df['Close']).rsi()
    df['MFI'] = ta.volume.MFIIndicator(high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume']).money_flow_index()
    macd = ta.trend.MACD(close=df['Close'])
    df['MACD'] = macd.macd(); df['MACD_Sig'] = macd.macd_signal()
    
    # 볼린저 & SQZ
    bb = ta.volatility.BollingerBands(close=df['Close'])
    df['BB_Hi'] = bb.bollinger_hband(); df['BB_Lo'] = bb.bollinger_lband(); df['%B'] = (df['Close'] - df['BB_Lo']) / (df['BB_Hi'] - df['BB_Lo'])
    kc = ta.volatility.KeltnerChannel(high=df['High'], low=df['Low'], close=df['Close'], window=20, window_atr=20, multiplier=1.5)
    df['KC_Hi'] = kc.keltner_channel_hband(); df['KC_Lo'] = kc.keltner_channel_lband()
    df['SQZ_ON'] = (df['BB_Hi'] < df['KC_Hi']) & (df['BB_Lo'] > df['KC_Lo'])
    
    return df

df = get_data(selected_ticker)

if not df.empty:
    last = df.iloc[-1]; prev = df.iloc[-2]; cur_price = float(last['Close'])
    
    # 점수 계산
    trend_s = 2 if (last['MA20'] > last['MA50'] > last['MA120']) else (1 if last['MA20'] > last['MA50'] else 0)
    macd_s = 2 if (last['MACD'] > last['MACD_Sig'] and prev['MACD'] <= prev['MACD_Sig']) else 0
    rsi_s = 2 if last['RSI'] < 35 else (1 if last['RSI'] < 45 else 0)
    main_score = trend_s + macd_s + rsi_s
    mfi_score = -1 if last['MFI'] > 80 else (2 if last['MFI'] < 30 else 0)
    adj_score = main_score + rs_score + mfi_score
    
    sqz_status = "⏳압축중" if last['SQZ_ON'] else "➡️해제유지"
    suffix = f" (SQZ:{sqz_status} / 재무:{fin_score if not is_etf else 'ETF'})"

    # 판단 로직 (대장님 수식 반영)
    if not is_etf and fin_score == 1:
        decision, color = "🚨하드차단: 재무F급(처분)" + suffix, "#c0392b"
    elif last['MFI'] >= 85:
        decision, color = "🚫하드차단: MFI 극단적 과열" + suffix, "#c0392b"
    elif last['%B'] >= 0.95:
        decision, color = "🚫하드차단: 밴드 상단 이탈" + suffix, "#c0392b"
    elif my_price > 0: # 보유자
        if trend_s == 2 and rs_score == 2 and 45 < last['RSI'] <= 58 and 0.45 < last['%B'] < 0.8:
            decision, color = "🎯S급 눌림목: 탑승 찬스" + suffix, "#8e44ad"
        elif adj_score >= 4 and cur_price <= my_price:
            decision, color = "🎯A급: 기술적 반등신호" + suffix, "#27ae60"
        elif cur_price > my_price:
            decision, color = "⏳평단이상: 하락대기(보유)" + suffix, "#f39c12"
        else:
            decision, color = "✅평단이하: 분할매수" + suffix, "#27ae60"
    else: # 신규
        if adj_score >= 4.5 and rs_score == 2:
            decision, color = "🆕신규진입: 대장주 포착" + suffix, "#27ae60"
        else:
            decision, color = "🔍대기: 신규 타점 탐색" + suffix, "#7f8c8d"

    # --- 화면 배치 ---
    col1, col2 = st.columns([1.2, 2.3])
    
    with col1:
        st.subheader(f"📊 {selected_name}")
        st.markdown("<div class='info-panel'>", unsafe_allow_html=True)
        st.markdown(f"현재가: <span class='highlight'>{format_currency(cur_price, selected_ticker)}</span>", unsafe_allow_html=True)
        if my_price > 0:
            return_pct = ((cur_price - my_price) / my_price) * 100
            diff_color = "#2ecc71" if return_pct > 0 else "#e74c3c"
            st.markdown(f"매입가: <b>{format_currency(my_price, selected_ticker)}</b>")
            st.markdown(f"수익률: <span style='color:{diff_color}; font-weight:bold;'>{return_pct:+.2f}%</span>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
        st.markdown(f"""
        <div class="signal-box" style="background-color: {color};">
            <div style="font-size: 0.9em; opacity: 0.9;">실시간 마스터 판단</div>
            <div style="font-size: 1.4em; margin-top:5px;">{decision}</div>
            <div class="score-text">
                (Main: <b>{main_score}</b> | RS: <b>{rs_score}</b> | MFI: <b>{mfi_score}</b> ➔ Adj: <b>{adj_score}점</b>)
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 3. 🔍 SMC 관점의 이평선 전술판 (하자 보수 포인트!)
        st.markdown(f"""
        <div class='info-panel' style='border-left: 5px solid #3498db;'>
            <b>🛡️ SMC/Swing 전술 지표</b><br>
            • RSI: {last['RSI']:.1f} / MFI: {last['MFI']:.1f}<br>
            • SQZ: <b>{sqz_status}</b> (에너지 응축 여부)<br>
            <hr style='margin:10px 0; border-color:#444;'>
            <b>📊 주요 이평선 가격 (SMC 관점)</b><br>
            • <span class='smc-tag'>[단기 모멘텀]</span> <b>MA5 :</b> {format_currency(last['MA5'], selected_ticker)}<br>
            • <span class='smc-tag'>[스윙 구조물/Choch]</span> <b>MA20 :</b> {format_currency(last['MA20'], selected_ticker)}<br>
            • <span class='smc-tag'>[중기 추세지지]</span> <b>MA50 :</b> {format_currency(last['MA50'], selected_ticker)}<br>
            • <span class='smc-tag'>[기관 매집/최종 방어]</span> <b>MA120 :</b> {format_currency(last['MA120'], selected_ticker)}
        </div>
        """, unsafe_allow_html=True)

    with col2:
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='orange', width=1.5), name="MA20 (Swing Line)"))
        fig.add_trace(go.Scatter(x=df.index, y=df['MA120'], line=dict(color='white', width=1, dash='dot'), name="MA120 (Inst. Line)"))
        if my_price > 0:
            fig.add_hline(y=my_price, line_dash="dash", line_color="#2ecc71", annotation_text="내 평단가")
        fig.update_layout(template="plotly_dark", height=600, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)