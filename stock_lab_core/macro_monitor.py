"""On-demand macro observatory. Observations do not change investment gates."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import StringIO
import math

import pandas as pd
import requests

from stock_lab_core.result_cache import cache_result
from stock_lab_core.performance import submit_with_context


@dataclass(frozen=True)
class Metric:
    symbol: str
    name: str
    group: str
    unit: str
    provider: str = "Yahoo"
    scale: float = 1
    frequency: str = "일간"
    note: str = "가격 움직임이며 방향 예측이나 매수 신호가 아닙니다."

    @property
    def url(self):
        if self.provider == "FRED":
            return "https://fred.stlouisfed.org/series/" + self.symbol
        if self.provider == "CNN":
            return "https://www.cnn.com/markets/fear-and-greed"
        if self.provider == "Cboe":
            return "https://www.cboe.com/markets/us/options/market-statistics/daily"
        if self.provider == "Npay":
            code = self.symbol.split(".")[0]
            return f"https://stock.naver.com/api/stockSecurity/items/v2/domestic/{code}/daily-prices/paged?index=0&size=100"
        from urllib.parse import quote
        return "https://finance.yahoo.com/quote/" + quote(self.symbol, safe="") + "/"


METRICS = (
    Metric("^GSPC", "S&P 500", "주요 시장", "pt"),
    Metric("^IXIC", "나스닥 종합", "주요 시장", "pt"),
    Metric("^KS11", "코스피", "주요 시장", "pt"),
    Metric("^KQ11", "코스닥", "주요 시장", "pt"),
    Metric("005930.KS", "삼성전자", "주요 시장", "원", "Npay", note="Npay의 KRX 정규장 종가. 가격 수준만으로 저평가 여부를 판단하지 않습니다."),
    Metric("GC=F", "금 선물", "주요 시장", "USD/oz", note="연속 선물 일봉. 현물·정산가와 다르고 월물 교체 영향을 받을 수 있습니다."),
    Metric("BTC-USD", "비트코인", "주요 시장", "USD", note="24시간 거래·UTC 일봉. 주식 정규장 종가와 관측 시각이 다릅니다."),
    Metric("EWZ", "브라질 ETF", "국가 ETF", "USD"),
    Metric("INDA", "인도 ETF", "국가 ETF", "USD"),
    Metric("VNM", "베트남 ETF", "국가 ETF", "USD"),
    Metric("EWJ", "일본 ETF", "국가 ETF", "USD", note="일본은 선진시장입니다. 미국 상장 ETF의 달러 가격으로 현지 지수와 다를 수 있습니다."),
    Metric("FNG", "공포·탐욕", "심리·스트레스", "점", "CNN", note="복합 심리지수. 극단적 공포가 반등이나 저점을 보장하지 않습니다."),
    Metric("VIXCLS", "VIX", "심리·스트레스", "pt", "FRED", note="S&P 500 옵션의 기대 변동성. 가격 방향을 뜻하지 않습니다."),
    Metric("BAMLH0A0HYM2", "하이일드 OAS", "심리·스트레스", "%", "FRED", note="국채 대비 신용 위험 보상. 확대는 신용 부담, 축소는 완화 가능성을 나타냅니다."),
    Metric("STLFSI4", "금융 스트레스", "심리·스트레스", "표준편차", "FRED", frequency="주간", note="0은 장기 평균. 상승은 스트레스 확대이며 앱 시장점수와 별도입니다."),
    Metric("^SKEW", "SKEW", "옵션 위험", "pt", note="옵션 꼬리위험 가격. 급락 확률 그 자체가 아닙니다."),
    Metric("^VVIX", "VVIX", "옵션 위험", "pt", note="VIX의 기대 변동성. VIX 수준과 구분합니다."),
    Metric("^OVX", "OVX", "옵션 위험", "pt", note="원유 관련 옵션의 기대 변동성. 유가 상승·하락 방향과 별개입니다."),
    Metric("PCR", "전체 옵션 풋/콜 비율", "옵션 위험", "배", "Cboe", note="Cboe TOTAL PUT/CALL RATIO. 주식 전용 비율과 다릅니다. 공식 최신 표의 단일 관측치이며 과거 차트는 미연결입니다."),
    Metric("DX-Y.NYB", "달러 인덱스", "금리·환율·원자재", "pt"),
    Metric("KRW=X", "원/달러", "금리·환율·원자재", "원/USD", note="상승은 원화 약세. 환노출 자산의 원화 평가에 영향을 줄 수 있습니다."),
    Metric("JPY=X", "달러/엔", "금리·환율·원자재", "엔/USD"),
    Metric("DGS10", "미국 10년 금리", "금리·환율·원자재", "%", "FRED", note="국채 금리. 변화는 %가 아닌 %p로 비교합니다. 상승 원인은 성장·물가·발행 수급을 함께 확인해야 합니다."),
    Metric("T10Y2Y", "10년-2년 금리차", "금리·환율·원자재", "%p", "FRED", note="음수는 역전. 역전·재확대만으로 침체 시점이나 주가 방향을 확정할 수 없습니다."),
    Metric("CL=F", "WTI 선물", "금리·환율·원자재", "USD/배럴", note="연속 선물 일봉. 정산가와 구분하며 월물 교체 시 수익률 비교에 주의합니다."),
    Metric("HG=F", "구리 선물", "금리·환율·원자재", "USD/파운드", note="수요뿐 아니라 공급·달러의 영향도 받습니다. 연속 선물 일봉입니다."),
    Metric("M2SL", "미국 M2", "유동성·고용", "십억 USD", "FRED", frequency="월간", note="광의 통화량. 증가가 주식시장으로의 유입을 직접 의미하지 않습니다."),
    Metric("UNRATE", "미국 실업률", "유동성·고용", "%", "FRED", frequency="월간", note="실업률과 노동참여율·고용 증가를 함께 봅니다."),
    Metric("ICSA", "신규 실업수당", "유동성·고용", "천 건", "FRED", .001, "주간", "주간 청구 건수. 계절조정·정정 가능; 한 주 변동보다 추세를 함께 확인합니다."),
    Metric("WALCL", "연준 총자산", "연준·재무부", "십억 USD", "FRED", .001, "주간", "연준 자산. 원자료 백만 달러를 십억 달러로 변환; 증감도 같은 단위입니다."),
    Metric("WRESBAL", "지급준비금", "연준·재무부", "십억 USD", "FRED", .001, "주간", "은행 지급준비금의 주간 평균. 절대 잔액 하나로 안전 여부를 단정하지 않습니다."),
    Metric("RRPONTSYD", "익일 역레포", "연준·재무부", "십억 USD", "FRED", note="감소분이 모두 주식 매수로 이동한 것은 아닙니다. 준비금·TGA와 함께 확인합니다."),
    Metric("WTREGEN", "재무부 TGA", "연준·재무부", "십억 USD", "FRED", .001, "주간", "정부 계좌 주간 평균. 증가 시 유동성 흡수 가능성이 있지만 다른 항목의 상쇄 효과가 있습니다."),
)
CATALOG = {item.symbol: item for item in METRICS}
GROUPS = tuple(dict.fromkeys(item.group for item in METRICS))


def parse_fred_csv(body, metric):
    frame = pd.read_csv(StringIO(body), na_values=["."])
    date_col = "observation_date" if "observation_date" in frame else "DATE"
    if date_col not in frame or metric.symbol not in frame:
        return pd.Series(dtype=float)
    return pd.Series(pd.to_numeric(frame[metric.symbol], errors="coerce").to_numpy() * metric.scale,
                     index=pd.to_datetime(frame[date_col], errors="coerce"), name=metric.name)


def parse_cboe_ratio(body):
    from bs4 import BeautifulSoup
    from datetime import datetime
    soup = BeautifulSoup(body, "html.parser")
    field = soup.select_one('input[placeholder="yyyy/mm/dd"]')
    if field is None:
        return pd.Series(dtype=float)
    # The page date, not request time, is the observation date.
    day = datetime.strptime(field.get("value", ""), "%d %B %Y")
    for row in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td,th")]
        if len(cells) == 2 and cells[0] == "TOTAL PUT/CALL RATIO":
            value = float(cells[1])
            if math.isfinite(value) and value >= 0:
                return pd.Series([value], index=pd.DatetimeIndex([day]))
    return pd.Series(dtype=float)


@cache_result(ttl=900, failure_ttl=30, is_success=lambda r: not r[0].empty, trace_name="macro_monitor")
def load_macro_series(symbol, years, as_of):
    item = CATALOG[symbol]
    try:
        if item.provider == "FRED":
            start = (pd.Timestamp(as_of) - pd.DateOffset(years=years)).date().isoformat()
            with requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                              params={"id": symbol, "cosd": start}, timeout=(2, 6)) as response:
                response.raise_for_status()
                series = parse_fred_csv(response.text, item)
        elif item.provider == "Cboe":
            with requests.get(item.url, timeout=(2, 6)) as response:
                response.raise_for_status()
                series = parse_cboe_ratio(response.text)
            return series, "공식 최신 표 · 단일 관측, 이력 미연결" if not series.empty else "공식 표의 일자·전체 비율 미연결"
        elif item.provider == "CNN":
            with requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                              headers={"User-Agent": "Mozilla/5.0"}, timeout=(2, 6)) as response:
                response.raise_for_status()
                data = response.json().get("fear_and_greed_historical", {}).get("data", [])
            series = pd.Series([row.get("y") for row in data],
                               index=pd.to_datetime([row.get("x") for row in data], unit="ms", utc=True))
        else:
            raise ValueError("use_batch_price_loader")
        return series, "" if not series.empty else "유효 관측치 미수집"
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "미확인"
        return pd.Series(dtype=float), f"공급처 HTTP {status} · 값 대체 안 함"
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        return pd.Series(dtype=float), type(exc).__name__


def completed_price_history(frame, market, now):
    from stock_lab_core.market_board import completed_close_series
    from stock_lab_core.report_eventstudy import _exchange_schedule
    series, _ = completed_close_series(frame, market, now=now)
    clock = pd.Timestamp(now)
    clock = clock.tz_localize("Asia/Seoul") if clock.tzinfo is None else clock
    if market == "CRYPTO":
        expected = (clock.tz_convert("UTC") - pd.Timedelta(days=1)).date()
    else:
        schedule = _exchange_schedule(market, str((clock - pd.Timedelta(days=14)).date()), str(clock.date()))
        completed = schedule.loc[pd.to_datetime(schedule["market_close"], utc=True) + pd.Timedelta(minutes=15) <= clock]
        if completed.empty:
            return series.iloc[0:0]
        expected = pd.Timestamp(completed.index[-1]).date()
    series = series.loc[series.index.date <= expected].copy()
    series.attrs["expected_date"] = expected.isoformat()
    return series


def load_group(group, years, now):
    from stock_lab_core.prices import load_price_frames_batch
    from stock_lab_core.kr_regular_history import load_regular_payload, regular_close_frame

    selected = [item for item in METRICS if item.group == group]
    symbols = tuple(sorted(item.symbol for item in selected if item.provider == "Yahoo" and not item.symbol.endswith(".KS")))
    frames = load_price_frames_batch(symbols, f"{years}y") if symbols else {}
    output = {}
    def collect(item):
        if item.provider not in {"Yahoo", "Npay"}:
            return item.symbol, load_macro_series(item.symbol, years, str(pd.Timestamp(now).date()))
        if item.provider == "Npay":
            frame = regular_close_frame(load_regular_payload(item.symbol), now)
            series = frame.get("Close", pd.Series(dtype=float)).copy()
            series.attrs["expected_date"] = frame.attrs.get("report_regular_expected", "")
            return item.symbol, (series, "정규장 종가 최대 100개 거래일")
        market = "KR" if item.symbol in {"^KS11", "^KQ11"} else "CRYPTO" if item.symbol.endswith("-USD") else "US"
        series = completed_price_history(frames.get(item.symbol), market, now)
        return item.symbol, (series, "" if not series.empty else "완료 일봉 미수집")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [submit_with_context(pool, collect, item) for item in selected]
        output.update(future.result() for future in futures)
    return output


def observation(item, series, now, reason=""):
    expected = series.attrs.get("expected_date", "")
    series = pd.to_numeric(series, errors="coerce").copy()
    series.index = pd.to_datetime(series.index, errors="coerce", utc=True).tz_localize(None)
    cutoff = pd.Timestamp(now).tz_localize(None)
    series = series.loc[~series.index.isna() & (series.index <= cutoff)].sort_index()
    series = series.loc[~series.index.duplicated(keep="last")].dropna()
    series = series.loc[series.map(math.isfinite)]
    if series.empty:
        return {"지표": item.name, "값": "미연결", "직전 관측 대비": "-", "관측일": "-", "주기": item.frequency,
                "상태": reason or "유효 관측치 없음", "출처": item.url}, series
    value = float(series.iloc[-1])
    delta = float(series.iloc[-1] - series.iloc[-2]) if len(series) > 1 else None
    age = (cutoff.date() - series.index[-1].date()).days
    limit = {"일간": 7, "주간": 21, "월간": 75}[item.frequency]
    change_unit = "%p" if item.unit == "%" else item.unit
    change = f"{delta:+,.2f} {change_unit}" if delta is not None else "비교값 없음"
    if item.provider in {"Yahoo", "Npay"} and delta is not None and series.iloc[-2] > 0:
        change += f" ({delta / series.iloc[-2] * 100:+.2f}%)"
    state = reason or "관측 연결"
    if expected and series.index[-1].date().isoformat() < expected:
        state = f"완료 일봉 지연 · 최근 완료일 {expected}"
    elif age > limit:
        state = f"관측일 {age}일 경과 · 발표/갱신일 별도 확인"
    return {"지표": item.name, "값": f"{value:,.2f} {item.unit}",
            "직전 관측 대비": change,
            "관측일": str(series.index[-1].date()), "주기": item.frequency,
            "상태": state, "출처": item.url}, series


def render_macro_monitor(st, *, key="macro_monitor", data=None, now=None, explicit_refresh=False):
    import plotly.graph_objects as go
    now = pd.Timestamp.now(tz="Asia/Seoul") if now is None else pd.Timestamp(now)
    st.subheader("매크로 관측실")
    group = st.radio("관측 분야", GROUPS, horizontal=True, key=key + "_group")
    years = st.selectbox("조회 기간", (1, 3, 5, 10), format_func=lambda n: f"{n}년", key=key + "_years")
    selected = [item for item in METRICS if item.group == group]
    captured_at = None
    if explicit_refresh and data is None:
        capture_key = "_macro_observation_captures"
        captures = dict(st.session_state.get(capture_key, {}))
        selection = (group, years)
        if st.button("관측 자료 조회/새로고침", icon=":material/refresh:", key=key + "_refresh"):
            captures[selection] = {"data": load_group(group, years, now), "at": now.isoformat()}
            st.session_state[capture_key] = captures
        captured = captures.get(selection)
        if captured is None:
            st.info("선택한 분야·기간의 저장 관측치가 없습니다.")
            return
        data = captured["data"]
        captured_at = captured["at"]
        from stock_lab_core.formatters import format_zoned_timestamp
        st.caption(f"자료 조회: {format_zoned_timestamp(captured_at)} · 저장 시점 기준 · 현재 신선도 미재검증")
    supplied = load_group(group, years, now) if data is None else data
    rows, histories = [], {}
    for item in selected:
        series, reason = supplied.get(item.symbol, (pd.Series(dtype=float), "조회 자료 없음"))
        row, history = observation(item, series, now, reason)
        if captured_at:
            row["상태"] = "저장 시점 기준 · " + row["상태"] + " · 현재 미재검증"
        rows.append(row)
        histories[item.symbol] = history.loc[history.index >= now.tz_localize(None) - pd.DateOffset(years=years)]
    st.caption("관측용 · 기존 시장방어·매매 판정과 별도 · 관측일은 발표일/조회시각과 다릅니다. 미수집은 0으로 채우지 않습니다.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"출처": st.column_config.LinkColumn("출처", display_text="원자료")})
    symbol = st.selectbox("상세 지표", [item.symbol for item in selected],
                          format_func=lambda s: CATALOG[s].name, key=key + "_" + group + "_symbol")
    item, series = CATALOG[symbol], histories[symbol]
    st.markdown(f"**{item.name}**")
    st.write(item.note)
    st.link_button("원자료 확인", item.url)
    if series.empty:
        st.warning("검증 가능한 시계열 미연결. 임의 값이나 다른 지표로 대체하지 않습니다.")
        return
    mode = st.radio("차트", ("수준", "기간 내 고점 대비"), horizontal=True, key=key + "_mode") if item.provider in {"Yahoo", "Npay"} else "수준"
    values = (series / series.cummax() - 1) * 100 if mode != "수준" else series
    figure = go.Figure(go.Scatter(x=values.index, y=values, mode="lines" if len(values) > 1 else "markers", connectgaps=False,
                                  line=dict(color="#0d9488", width=2), name=item.name))
    figure.update_layout(height=340, margin=dict(l=8, r=8, t=12, b=8),
                         yaxis_title="% (선택 기간 내 고점 기준)" if mode != "수준" else item.unit,
                         xaxis_title=None, hovermode="x unified")
    st.plotly_chart(figure, width="stretch", key=key + "_plot")
    st.caption(f"관측 {len(series)}개 · {series.index[0].date()} ~ {series.index[-1].date()} · 배당 포함 총수익률/실시간 체결가 아님")
    with st.expander("관측치 원문"):
        st.dataframe(series.rename(item.unit).rename_axis("관측일").to_frame(), width="stretch")
