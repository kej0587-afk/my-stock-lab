"""Source-inspired display scorecard, independent from Stock Lab trade gates."""

import math
import pandas as pd
from stock_lab_core.chart_enrichment import build_financial_snapshot_rows, build_volume_signal_series
from stock_lab_core.financial_score import optional_float


def _higher(value, bad, good):
    return None if value is None else max(0, min(100, (value - bad) / (good - bad) * 100))


def _mid(value, low, ideal, high):
    if value is None:
        return None
    return _higher(value, low, ideal) if value <= ideal else _higher(-value, -high, -ideal)


def build_chart_scorecard(info, frame, *, is_etf=False, benchmark=None):
    values = {row["key"]: row["value"] for row in build_financial_snapshot_rows(info, is_etf=is_etf)}
    info = dict(info or {})
    factors = []

    def add(axis, label, value, score, unit=""):
        factors.append({"축": axis, "항목": label, "값": value, "단위": unit, "점수": score})

    for key, label, bad, good in (("returnOnEquity", "ROE", 5, 25), ("returnOnAssets", "ROA", 2, 15),
                                  ("operatingMargins", "영업이익률", 5, 30), ("profitMargins", "순이익률", 3, 25)):
        value = values.get(key)
        add("품질", label, value, _higher(value, bad, good), "%")
    for key, label, good, bad in (("trailingPE", "후행 PER", 8, 45), ("forwardPE", "선행 PER", 8, 40),
                                  ("priceToSalesTrailing12Months", "PSR", 1, 15), ("priceToBook", "PBR", 1, 12),
                                  ("enterpriseToEbitda", "EV/EBITDA", 5, 30)):
        value = values.get(key)
        # Negative P/E is a loss, not a cheap valuation.
        score = _higher(-value, -bad, -good) if value is not None and value > 0 else None
        add("가치", label, value, score, "x")
    for key, label, good in (("revenueGrowth", "매출 성장", 25), ("earningsGrowth", "이익 성장", 30)):
        value = values.get(key)
        add("성장", label, value, _higher(value, 0, good), "%")
    for key, label, bounds in (("currentRatio", "유동비율", (.5, 2, 5)), ("quickRatio", "당좌비율", (.3, 1.5, 4))):
        value = values.get(key)
        add("재무건전성", label, value, _mid(value, *bounds), "x")
    for key, label in (("operatingCashflow", "영업현금흐름"), ("freeCashflow", "잉여현금흐름")):
        value = values.get(key)
        add("재무건전성", label, value, None if value is None else 100 if value > 0 else 0)
    for key, label in (("trailingAnnualDividendYield", "후행 배당수익률"), ("payoutRatio", "배당성향")):
        value = values.get(key)
        score = _mid(value, 0, 40, 100) if key == "payoutRatio" else _higher(value, 0, 5)
        add("주주환원", label, value, score, "%")
    fcf, cap = values.get("freeCashflow"), values.get("marketCap")
    fcf_yield = fcf / cap * 100 if fcf is not None and cap is not None and cap > 0 else None
    add("주주환원", "FCF 수익률", fcf_yield, _higher(fcf_yield, 0, 8), "%")
    close = pd.to_numeric(frame["Close"], errors="coerce").dropna() if frame is not None and "Close" in frame else pd.Series(dtype=float)
    rsi = position = ma_score = volatility = None
    if len(close) >= 15:
        from ta.momentum import RSIIndicator
        rsi = optional_float(RSIIndicator(close).rsi().iloc[-1])
    if len(close) >= 252:
        high = pd.to_numeric(frame["High"], errors="coerce").tail(252).max() if "High" in frame else close.tail(252).max()
        low = pd.to_numeric(frame["Low"], errors="coerce").tail(252).min() if "Low" in frame else close.tail(252).min()
        position = float((close.iloc[-1] - low) / (high - low) * 100) if high > low else None
    if len(close) >= 200:
        price, ma20, ma50, ma200 = close.iloc[-1], close.tail(20).mean(), close.tail(50).mean(), close.tail(200).mean()
        ma_score = 100 if price > max(ma20, ma50, ma200) else 80 if price > max(ma50, ma200) else 60 if price > ma200 else 45 if price > ma50 else 25
    if len(close) >= 31:
        volatility = float(close.pct_change().tail(30).std() * math.sqrt(252) * 100)
    add("모멘텀", "RSI(14)", rsi, _mid(rsi, 30, 60, 85))
    add("모멘텀", "52주 위치", position, _higher(position, 20, 90), "%")
    add("모멘텀", "MA20/50/200", ma_score, ma_score)
    add("모멘텀", "30일 연율변동성", volatility, _higher(-volatility, -80, -10) if volatility is not None else None, "%")
    for days, label, bad, good in ((126, "6M RS", -20, 25), (252, "12M RS", -25, 35)):
        relative = None
        if benchmark is not None and "Close" in benchmark and len(close) > days:
            bclose = pd.to_numeric(benchmark["Close"], errors="coerce")
            bclose = bclose.reindex(close.index)
            start, end = bclose.iloc[-days - 1], bclose.iloc[-1]
            if pd.notna(start) and pd.notna(end) and start > 0:
                relative = float(((close.iloc[-1] / close.iloc[-days - 1] - 1) - (end / start - 1)) * 100)
        add("모멘텀", label, relative, _higher(relative, bad, good), "%p")
    if is_etf:
        factors = [item for item in factors if item["축"] == "모멘텀"]
    rows = []
    for axis in ("품질", "가치", "성장", "재무건전성", "주주환원", "모멘텀"):
        items = [item for item in factors if item["축"] == axis]
        scores = [item["점수"] for item in items if item["점수"] is not None]
        # Partial adapted coverage, not a claim of exact TradingView replication.
        rows.append({"축": axis, "점수": round(sum(scores) / len(scores), 1) if scores else None,
                     "자료": f"{len(scores)}/{len(items)}" if items else "ETF 기업재무 해당없음",
                     "근거": " · ".join(f"{item['항목']} {item['값']:.2f}{item['단위']}" for item in items if item["값"] is not None) or "미수집"})
    return rows, factors


def volume_review(frame, ticker=""):
    signals = build_volume_signal_series(frame)
    if signals.empty:
        return [], "거래량 이력 미수집"
    last = signals.iloc[-1]
    labels = {"HVE": "로드 구간 최고 거래량", "HVY": "최근 252봉 최고 거래량", "HVQ": "최근 63봉 최고 거래량",
              "POCKET_PIVOT": "Pocket Pivot(거래량 조건만)", "POWER": "평균 2배 이상 거래량", "HIGH": "평균 1.5배 이상 거래량",
              "DRY60": "평균 50% 이하 + 60봉 최저 수축", "DRY20": "평균 50% 이하 + 20봉 최저 수축", "BASE": "평균적 거래량", "UNAVAILABLE": "자료 미수집"}
    close = optional_float(frame["Close"].iloc[-1])
    currency = "KRW" if ticker.endswith((".KS", ".KQ")) or (len(ticker) == 6 and ticker[0].isdigit()) else "USD"
    avg, current = optional_float(last["volume_ma"]), optional_float(last["volume"])
    rows = [{"항목": "평균 거래량(50봉)", "값": avg, "단위": "주"},
            {"항목": "평균 거래대금(종가×평균 거래량)", "값": close * avg if close is not None and avg is not None else None, "단위": currency},
            {"항목": "당일 거래대금", "값": close * current if close is not None and current is not None else None, "단위": currency},
            {"항목": "Volume Buzz", "값": optional_float(last["buzz_pct"]), "단위": "%"},
            {"항목": "U/D Vol(50봉)", "값": optional_float(last["up_down_ratio"]), "단위": "배"}]
    note = labels.get(last["signal"], last["signal"])
    ratio = optional_float(last["up_down_ratio"])
    if ratio is not None:
        note += f" · U/D {ratio:.2f}: " + ("상승일 거래량 우세" if ratio >= 1 else "하락일 거래량 우세")
    return rows, note + ". 거래량만으로 매집/매수 확정 불가. 종가 위치와 이후 봉을 함께 확인합니다."


def render_chart_scorecard(st, frame, *, info=None, ticker="", is_etf=False, source=""):
    rows, factors = build_chart_scorecard(info, frame, is_etf=is_etf)
    st.markdown("#### 재무·모멘텀 성적표")
    st.dataframe(pd.DataFrame(rows)[["축", "점수", "자료"]], hide_index=True, width="stretch",
                 column_config={"축": st.column_config.TextColumn("축", width=100),
                                "점수": st.column_config.ProgressColumn("점수(0~100)", min_value=0, max_value=100, format="%.1f", width=130),
                                "자료": st.column_config.TextColumn("자료", width=95)})
    st.caption(f"첨부 지표를 가용 항목으로 축약 적용 · 결측 제외 평균/자료 충족도 · {source or '재무 기준시각 미제공'} · 기존 4점 재무/후보등급/매매판정과 별개")
    with st.expander("성적표 산식·자료"):
        st.dataframe(pd.DataFrame(factors), hide_index=True, width="stretch")
        st.caption("선형 0~100점: ROE 5~25%, PER 45~8배, 매출성장 0~25%. 자사주 매입·ROIC·Piotroski 등 미연결 항목은 추정하지 않음. 업종 상대평가가 아닌 참고 점수.")


def render_volume_review(st, frame, ticker=""):
    rows, note = volume_review(frame, ticker)
    st.markdown("#### 거래량 종합 해설")
    st.write(note)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with st.expander("거래량 색상·그래프 읽기"):
        st.markdown("보라 HVE/HVY/HVQ: 로드구간/252봉/63봉 최고. 핑크 Pocket Pivot: 상승·보합일 거래량이 직전 10봉 하락일 최대보다 큼(이평·가격 조건 제외). 청록/주황: 상승/하락일 평균 2배, 연한색: 1.5배. 검정/남색: 평균 50% 이하이면서 60/20봉 최저. 회색: 기타. 위 분류부터 하나만 적용합니다.")
        st.write("U/D는 최근 50봉 상승일 거래량 합 ÷ 하락일 합입니다. 분모가 0이거나 이력이 짧으면 미수집입니다. 하루 대량 거래에 치우칠 수 있어 여러 봉의 가격·거래량 동행을 봅니다. 거래대금은 체결가 합계가 아닌 종가 기반 근사치입니다.")
