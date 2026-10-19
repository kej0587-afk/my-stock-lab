"""A bounded market board with explicit live-bar and completed-close modes.

Integration: ``ticker = render_market_board(st, key="today_market", frames=frames)``.
``frames`` is an authoritative flat {provider_symbol: OHLC DataFrame} mapping;
even an empty mapping disables fetching. Otherwise only the selected market is
requested: the existing batch provider for US/crypto, one bounded Yahoo batch for
KR including ETFs. Successful downloads are cached for 300 seconds, failures for
15 seconds. No constituents, company metadata, or market-cap estimates are fetched.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import math

import pandas as pd

from stock_lab_core.result_cache import cache_result


@dataclass(frozen=True)
class Instrument:
    ticker: str
    name: str
    sector: str
    group: str
    kind: str = "basket"


MARKET_LABELS = {"KR": "국내증시", "US": "미국증시", "CRYPTO": "코인"}
MARKET_UNIVERSES = {
    "KR": (
        Instrument("^KS11", "KOSPI", "종합지수", "대표 지수", "index"),
        Instrument("^KQ11", "KOSDAQ", "종합지수", "대표 지수", "index"),
        Instrument("069500.KS", "KOSPI200 · KODEX 200 ETF", "대형주", "대표 지수", "index"),
        Instrument("229200.KS", "KOSDAQ150 · KODEX ETF", "성장주", "대표 지수", "index"),
        Instrument("396500.KS", "TIGER Fn반도체TOP10", "AI·반도체", "성장·소비"),
        Instrument("266360.KS", "KODEX K콘텐츠", "콘텐츠", "성장·소비"),
        Instrument("305540.KS", "TIGER 2차전지테마", "2차전지", "성장·소비"),
        Instrument("487240.KS", "KODEX AI전력핵심설비", "전력·인프라", "산업·에너지"),
        Instrument("434730.KS", "HANARO 원자력iSelect", "원전", "산업·에너지"),
        Instrument("449450.KS", "PLUS K방산", "방산", "산업·에너지"),
        Instrument("139250.KS", "TIGER 200 에너지화학", "에너지·화학", "산업·에너지"),
        Instrument("244580.KS", "KODEX 바이오", "바이오", "금융·헬스·리츠"),
        Instrument("139270.KS", "TIGER 200 금융", "금융", "금융·헬스·리츠"),
        Instrument("329200.KS", "TIGER 리츠부동산인프라", "리츠", "금융·헬스·리츠"),
    ),
    "US": (
        Instrument("^GSPC", "S&P 500", "종합지수", "대표 지수", "index"),
        Instrument("^IXIC", "나스닥 종합", "종합지수", "대표 지수", "index"),
        Instrument("^DJI", "다우 산업", "종합지수", "대표 지수", "index"),
        Instrument("^RUT", "러셀 2000", "소형주", "대표 지수", "index"),
        Instrument("XLK", "Technology Select Sector SPDR", "기술", "성장·소비"),
        Instrument("XLC", "Communication Services Select Sector SPDR", "커뮤니케이션", "성장·소비"),
        Instrument("XLY", "Consumer Discretionary Select Sector SPDR", "경기소비재", "성장·소비"),
        Instrument("XLI", "Industrial Select Sector SPDR", "산업재", "경기민감"),
        Instrument("XLB", "Materials Select Sector SPDR", "소재", "경기민감"),
        Instrument("XLE", "Energy Select Sector SPDR", "에너지", "경기민감"),
        Instrument("XLF", "Financial Select Sector SPDR", "금융", "경기민감"),
        Instrument("XLV", "Health Care Select Sector SPDR", "헬스케어", "방어"),
        Instrument("XLP", "Consumer Staples Select Sector SPDR", "필수소비재", "방어"),
        Instrument("XLU", "Utilities Select Sector SPDR", "유틸리티", "방어"),
        Instrument("XLRE", "Real Estate Select Sector SPDR", "부동산", "경기민감"),
    ),
    "CRYPTO": (
        Instrument("BTC-USD", "비트코인", "BTC", "주요 코인"),
        Instrument("ETH-USD", "이더리움", "ETH", "주요 코인"),
        Instrument("SOL-USD", "솔라나", "SOL", "기타 대표 코인"),
        Instrument("XRP-USD", "XRP", "XRP", "기타 대표 코인"),
        Instrument("BNB-USD", "BNB", "BNB", "기타 대표 코인"),
        Instrument("DOGE-USD", "도지코인", "DOGE", "기타 대표 코인"),
    ),
}
PERIODS = ("1D", "1W", "1M", "3M")
COLOR_LIMITS = {"1D": 5.0, "1W": 10.0, "1M": 20.0, "3M": 40.0}
COLOR_SCALE = ((0.0, "#b91c1c"), (0.5, "#f1f3f5"), (1.0, "#15803d"))
MISSING_COLOR = "#cbd0d6"
_TIMEZONES = {"KR": "Asia/Seoul", "US": "America/New_York", "CRYPTO": "UTC"}
_COLUMNS = (
    "ticker", "name", "sector", "group", "kind", "close", "return_pct",
    "close_date", "base_date", "base_close", "status", "incomplete_rows",
)


def market_instruments(market: str, scope="basket"):
    if scope == "basket" or market == "CRYPTO":
        return MARKET_UNIVERSES[market]
    if scope != "stocks":
        raise ValueError("Unsupported market-board scope")
    from stock_lab_core.market_board_universe import STOCK_UNIVERSES
    indices = tuple(item for item in MARKET_UNIVERSES[market] if item.kind == "index")
    return indices + tuple(Instrument(ticker, name, sector, sector, "stock")
                           for ticker, name, sector in STOCK_UNIVERSES[market])


def market_tickers(market: str, scope="basket") -> tuple[str, ...]:
    return tuple(sorted(item.ticker for item in market_instruments(market, scope)))


@cache_result(ttl=300, failure_ttl=15, is_success=bool)
def load_kr_market_frames(scope="basket") -> dict:
    """Download the fixed KR universe once; preserve null closes for the board.

    The shared overseas batch excludes .KS symbols. Its public Close extractor
    is safe to reuse after rejecting ambiguous flat multi-symbol responses.
    """
    import yfinance as yf
    from stock_lab_core.prices import extract_download_close_series
    from stock_lab_core.yahoo_transport import YAHOO_HISTORY_LOCK, yahoo_session_kwargs

    tickers = market_tickers("KR", scope)
    try:
        with YAHOO_HISTORY_LOCK:
            data = yf.download(list(tickers), period="6mo", interval="1d", group_by="ticker",
                               progress=False, threads=4, auto_adjust=False, keepna=True,
                               timeout=6.0, **yahoo_session_kwargs())
    except Exception:
        return {}
    if not isinstance(data, pd.DataFrame) or data.empty or not isinstance(data.columns, pd.MultiIndex):
        return {}
    frames = {}
    for ticker in tickers:
        try:
            close = extract_download_close_series(data, ticker)
            if not isinstance(close, pd.Series):
                continue
            close = pd.to_numeric(close, errors="coerce")
            close = pd.Series(close.to_numpy(dtype=float, na_value=float("nan")), index=close.index)
            if (close.map(math.isfinite) & (close > 0)).any():
                frames[ticker] = close.to_frame("Close")
        except (TypeError, ValueError, KeyError):
            continue
    return frames


def load_market_frames(market: str, scope="basket") -> dict:
    """Reuse the provider's 300-second cache without extending its retention."""
    if market == "KR":
        return load_kr_market_frames() if scope == "basket" else load_kr_market_frames(scope)
    from stock_lab_core.prices import load_price_frames_batch

    tickers = market_tickers(market, scope)
    try:
        loaded = load_price_frames_batch(tickers, "6mo")
    except Exception:
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    return {ticker: loaded[ticker] for ticker in tickers if ticker in loaded}


def _utc_now():
    return pd.Timestamp.now(tz="UTC")


def _as_utc(now=None) -> pd.Timestamp:
    stamp = pd.Timestamp(_utc_now() if now is None else now)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def completed_close_series(frame, market: str, *, now=None, include_current=False) -> tuple[pd.Series, int]:
    """Retain null candles and provider session-date labels; never forward-fill.

    Today's stock candle is conservatively excluded until normal close + 15 min
    (also on early-close days). Crypto candles complete at the next UTC midnight.
    Exchange holidays are not synthesized; only dates actually supplied are used.
    """
    empty = pd.Series(dtype=float)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "Close" not in frame:
        return empty, 0
    if isinstance(frame.columns, pd.MultiIndex) or frame.columns.has_duplicates:
        return empty, 0
    raw_dates = frame["Date"] if "Date" in frame else frame.index
    if pd.api.types.is_numeric_dtype(raw_dates):
        return empty, 0
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(raw_dates, errors="coerce"))
        # Daily indexes label sessions, not UTC instants to shift to another date.
        dates = dates.tz_localize(None).normalize()
    except (TypeError, ValueError):
        return empty, 0
    values = pd.to_numeric(frame["Close"], errors="coerce").to_numpy(dtype=float, na_value=float("nan"))
    close = pd.Series(values, index=dates, dtype=float)
    close = close[~close.index.isna()]
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close = close.where(close.map(lambda value: math.isfinite(value) and value > 0))
    local = _as_utc(now).tz_convert(_TIMEZONES[market])
    today = local.tz_localize(None).normalize()
    if market == "CRYPTO":
        completed = close.index < today
    else:
        close_minute = 15 * 60 + 45 if market == "KR" else 16 * 60 + 15
        cutoff = today if local.hour * 60 + local.minute >= close_minute else today - pd.Timedelta(days=1)
        completed = (close.index <= cutoff) & (close.index.dayofweek < 5)
    eligible = close.index <= today if include_current else completed
    if market != "CRYPTO":
        eligible &= close.index.dayofweek < 5
    return close.loc[eligible], int((~eligible).sum())


def build_market_snapshot(market: str, frames: Mapping, period="1D", *, now=None, include_current=False, scope="basket") -> pd.DataFrame:
    """Compute percent returns from raw Close, with explicit actual comparison dates.

    1D uses the preceding supplied session. 1W/1M/3M use the last supplied close
    on/before the calendar target, at most ten days before it. Missing, short, or
    lagging series stay missing instead of entering unchanged/neutral counts.
    """
    if period not in PERIODS:
        raise ValueError(f"Unsupported market-board period: {period}")
    now = _as_utc(now)
    rows = []
    for item in market_instruments(market, scope):
        close, excluded = completed_close_series(frames.get(item.ticker), market, now=now, include_current=include_current)
        row = dict(ticker=item.ticker, name=item.name, sector=item.sector, group=item.group,
                   kind=item.kind, close=float("nan"), return_pct=float("nan"),
                   close_date=None, base_date=None, base_close=float("nan"),
                   status="일봉 없음", incomplete_rows=excluded)
        if not close.empty:
            end = close.index[-1]
            row.update(close=float(close.iloc[-1]), close_date=end.date().isoformat())
            if pd.isna(close.iloc[-1]):
                row["status"] = "종가 결측"
            else:
                if period == "1D":
                    base = close.iloc[-2:-1]
                else:
                    offset = pd.Timedelta(days=7) if period == "1W" else pd.DateOffset(months=1 if period == "1M" else 3)
                    target = end - offset
                    base = close.loc[(close.index <= target) & (close.index >= target - pd.Timedelta(days=10))].tail(1)
                if base.empty:
                    row["status"] = "비교 기간 부족"
                else:
                    row.update(base_date=base.index[-1].date().isoformat(), base_close=float(base.iloc[-1]))
                    if pd.isna(base.iloc[-1]):
                        row["status"] = "비교 종가 결측"
                    else:
                        change = (float(close.iloc[-1]) / float(base.iloc[-1]) - 1.0) * 100.0
                        row.update(return_pct=change if math.isfinite(change) else float("nan"), status="완료 일봉")
                        if include_current:
                            completed, _ = completed_close_series(frames.get(item.ticker), market, now=now)
                            if end not in completed.index:
                                row["status"] = "진행 중 일봉 · 공급처 지연 가능"
            if excluded:
                row["status"] += " · 미완료 봉 제외"
        elif excluded:
            row["status"] = "완료 일봉 없음 · 미완료 봉 제외"
        rows.append(row)
    result = pd.DataFrame(rows, columns=_COLUMNS)
    available_dates = result["close_date"].dropna()
    if not available_dates.empty:
        latest = available_dates.max()
        lagging = result["close_date"].notna() & (result["close_date"] < latest)
        result.loc[lagging, "return_pct"] = float("nan")
        result.loc[lagging, "status"] = "기준일 지연"
    local = now.tz_convert(_TIMEZONES[market])
    open_minute = 540 if market == "KR" else 570
    if include_current and market != "CRYPTO" and local.weekday() < 5 and local.hour * 60 + local.minute >= open_minute:
        stale = result["close_date"].notna() & result["close_date"].lt(local.date().isoformat())
        result.loc[stale, "return_pct"] = float("nan")
        result.loc[stale, "status"] = "오늘자 일봉 미수집 · 과거 등락 표시 보류"
    return result


def breadth_counts(rows: pd.DataFrame) -> dict[str, int]:
    values = pd.to_numeric(rows["return_pct"], errors="coerce").where(lambda s: s.map(math.isfinite))
    return {"positive": int((values > 0).sum()), "negative": int((values < 0).sum()),
            "neutral": int((values == 0).sum()), "missing": int(values.isna().sum())}


def _pct(value) -> str:
    return f"{value:+.2f}%" if pd.notna(value) and math.isfinite(value) else "결측"


def build_treemap(rows: pd.DataFrame, period="1D"):
    """Equal-size leaves with actual values in text, independently clipped colors."""
    import plotly.express as px
    from plotly.colors import sample_colorscale

    limit = COLOR_LIMITS[period]
    nodes, fills = [], {}
    for group, members in rows.groupby("group", sort=False):
        parent = f"group:{group}"
        nodes.append(dict(id=parent, parent="", label=group, size=len(members), color=0.0,
                          ticker="", name=group, return_text="", close_date="", base_date="",
                          status=f"대표 바스켓 {len(members)}개", close_text="", base_text=""))
        fills[parent] = "#f1f3f5"
        for row in members.itertuples(index=False):
            finite = pd.notna(row.return_pct) and math.isfinite(row.return_pct)
            bounded = max(-limit, min(limit, row.return_pct)) if finite else float("nan")
            label = row.name if row.kind == "stock" else row.sector
            nodes.append(dict(id=row.ticker, parent=parent, label=f"{label}<br>{row.ticker}",
                              size=1, color=bounded, ticker=row.ticker, name=row.name,
                              return_text=_pct(row.return_pct), close_date=row.close_date or "미제공",
                              base_date=row.base_date or "미제공", status=row.status,
                              close_text=f"{row.close:,.2f}" if pd.notna(row.close) else "결측",
                              base_text=f"{row.base_close:,.2f}" if pd.notna(row.base_close) else "결측"))
            fills[row.ticker] = sample_colorscale([list(stop) for stop in COLOR_SCALE], [(bounded + limit) / (2 * limit)])[0] if finite else MISSING_COLOR
    if not nodes:
        import plotly.graph_objects as go
        return go.Figure()
    custom = ["ticker", "name", "return_text", "close_date", "base_date", "status", "close_text", "base_text"]
    figure = px.treemap(pd.DataFrame(nodes), ids="id", names="label", parents="parent", values="size",
                        branchvalues="total", color="color", custom_data=custom,
                        color_continuous_scale=list(COLOR_SCALE), range_color=(-limit, limit),
                        color_continuous_midpoint=0)
    trace = figure.data[0]
    # Explicit fills distinguish unavailable leaves from real zero-return leaves.
    trace.marker.update(colors=[fills[node_id] for node_id in trace.ids], coloraxis=None,
                        cmin=-limit, cmax=limit, cmid=0, colorscale=list(COLOR_SCALE),
                        showscale=False, line=dict(width=1, color="#ffffff"))
    figure.update_traces(texttemplate="%{label}<br>%{customdata[2]}", sort=False,
                         tiling=dict(pad=3), textfont=dict(size=14),
                         hovertemplate=("<b>%{customdata[1]}</b><br>%{customdata[0]}<br>"
                                        "수익률 %{customdata[2]}<br>종가 %{customdata[6]} · %{customdata[3]}"
                                        "<br>비교 종가 %{customdata[7]} · %{customdata[4]}"
                                        "<br>%{customdata[5]}<extra></extra>"))
    figure.update_layout(height=620 if len(rows) > 25 else 365, margin=dict(t=4, l=0, r=0, b=0),
                         paper_bgcolor="rgba(0,0,0,0)", font=dict(size=13),
                         uniformtext=dict(minsize=10, mode="hide"))
    return figure


def selected_ticker_from_event(event, allowed) -> str | None:
    """Only accept leaf identifiers present in the currently displayed universe."""
    if not isinstance(event, Mapping):
        return None
    selection = event.get("selection", {})
    points = selection.get("points", []) if isinstance(selection, Mapping) else []
    for point in points if isinstance(points, (tuple, list)) else []:
        if not isinstance(point, Mapping):
            continue
        custom = point.get("customdata", [])
        candidate = custom[0] if isinstance(custom, (tuple, list)) and custom else point.get("id")
        if isinstance(candidate, str) and candidate in allowed:
            return candidate
    return None


def _render_detail(st, row, frame, market, key):
    import plotly.express as px

    st.markdown(f"**{row['name']} · {row['ticker']}**")
    st.caption(f"종가일 {row['close_date'] or '미제공'} · 비교일 {row['base_date'] or '미제공'} · {row['status']}")
    close, _ = completed_close_series(frame, market)
    if close.notna().sum() >= 2:
        history = close.tail(95).rename("종가").rename_axis("일자").reset_index()
        figure = px.line(history, x="일자", y="종가")
        figure.update_traces(connectgaps=False, line=dict(color="#2563eb", width=2),
                             hovertemplate="%{x|%Y-%m-%d}<br>종가 %{y:,.2f}<extra></extra>")
        figure.update_layout(height=210, margin=dict(t=5, b=5, l=0, r=0),
                             xaxis_title=None, yaxis_title=None)
        st.plotly_chart(figure, width="stretch", key=f"{key}_history_{row['ticker']}",
                        config={"displayModeBar": False, "scrollZoom": False})
    else:
        st.info("종가 추이에 필요한 완료 일봉이 부족합니다.")


def render_market_board(st, *, key="market_board", frames=None) -> str | None:
    """Render one market; return a newly selected ticker or None on ordinary reruns.

    Every widget/state key is namespaced by ``key``. Injected frames never trigger
    network requests or missing-symbol fallbacks. Plotly leaf selection is accepted
    where supported; symbol selection remains available on all clients. Sector
    parent clicks only drill into the chart. Returned selections are consumed once.
    """
    st.subheader("시장판")
    with st.container(horizontal=True, gap="medium"):
        market = st.radio("시장", tuple(MARKET_LABELS), format_func=MARKET_LABELS.get,
                          horizontal=True, key=f"{key}_market")
        period = st.radio("기간", PERIODS, horizontal=True, key=f"{key}_period")
        basis = st.radio("가격 기준", ("장중 포함", "완료 일봉"), horizontal=True, key=f"{key}_basis")
    scope = "basket"
    if market != "CRYPTO":
        view_type = st.radio("표시 대상", ("대표 종목", "섹터 ETF"), horizontal=True, key=f"{key}_scope")
        scope = "stocks" if view_type == "대표 종목" else "basket"
    supplied = (load_market_frames(market) if scope == "basket" else load_market_frames(market, scope)) if frames is None else frames
    if not isinstance(supplied, Mapping):
        supplied = {}
    snapshot = build_market_snapshot(market, supplied, period, include_current=basis == "장중 포함", scope=scope)
    st.caption(f"대표 지수·ETF 및 고정 대표 바스켓 · 배당 제외 · {basis} · 공급처 조회 최대 5분 캐시")
    local = _as_utc().tz_convert(_TIMEZONES[market])
    if basis == "장중 포함" and market != "CRYPTO" and local.weekday() < 5 and local.hour * 60 + local.minute >= (540 if market == "KR" else 570):
        old = snapshot["close_date"].fillna("").lt(local.date().isoformat()).sum()
        if old:
            st.info(f"오늘자 일봉 미수집 {old}개: 과거 상승률을 오늘 값으로 표시하지 않습니다. 직전 마감은 완료 일봉에서 확인할 수 있습니다.")
    elif basis == "완료 일봉":
        st.info("완료 일봉 기준입니다. 장중에는 직전 마감일 등락을 표시합니다.")
    indices = snapshot.loc[snapshot["kind"] == "index"]
    headlines = indices if not indices.empty else snapshot.iloc[:4]
    with st.container(horizontal=True, gap="medium"):
        for row in headlines.to_dict("records"):
            with st.container(width=160):
                st.metric(row["name"], f"{row['close']:,.2f}" if pd.notna(row["close"]) else "미제공",
                          _pct(row["return_pct"]) if pd.notna(row["return_pct"]) else None,
                          help=f"{row['ticker']} · {row['status']} · 비교일 {row['base_date'] or '미제공'}")
                st.caption(f"종가일 {row['close_date'] or '미제공'}")
    if market == "CRYPTO":
        st.caption(f"UTC 일봉 · {basis} · 1D 이전 일봉 대비 / 1W 7일 / 1M·3M 달력 기준")
    else:
        timing = "15:45 KST" if market == "KR" else "16:15 ET (서머타임 자동 반영)"
        st.caption(f"완료 판단 {timing} · 1D 이전 거래봉 대비 / 1W 7일 / 1M·3M 달력 기준 · 진행 중 일봉은 변동 가능")
    basket = snapshot.loc[snapshot["kind"] != "index"]
    namespace = f"{key}_{market}" + ("_stocks" if scope == "stocks" else "")
    group = st.selectbox("섹터 그룹", ["전체", *dict.fromkeys(basket["group"])], key=f"{namespace}_group")
    view = basket if group == "전체" else basket.loc[basket["group"] == group]
    counts = breadth_counts(view)
    st.caption(f"대표 바스켓 {len(view)}개 · 상승 {counts['positive']} · 하락 {counts['negative']} · "
               f"보합 {counts['neutral']} · 결측 {counts['missing']} · 동일 면적 (시가총액 비중 아님)")
    if counts["missing"] == len(view):
        st.info("선택한 대표 바스켓의 비교 가능한 완료 일봉이 없습니다.")
    if market == "KR" and basket["close"].isna().any():
        st.caption(f"한국 {'대표 종목' if scope == 'stocks' else 'ETF'} 종가 미제공 {int(basket['close'].isna().sum())}개")
    chart_key = f"{namespace}_{period}_{group}_tree"
    event = st.plotly_chart(build_treemap(view, period), width="stretch", key=chart_key,
                            on_select="rerun", selection_mode="points",
                            config={"displayModeBar": False, "scrollZoom": False})
    clicked = selected_ticker_from_event(event, set(view["ticker"]))
    event_key = f"{key}_consumed_events"
    consumed = dict(st.session_state.get(event_key, {}))
    new_click = clicked if clicked != consumed.get(chart_key) else None
    consumed[chart_key] = clicked
    st.session_state[event_key] = consumed
    choices = pd.concat([indices, view]).drop_duplicates("ticker")
    labels = {row.ticker: f"{row.sector} · {row.ticker} · {row.name}" for row in choices.itertuples()}
    symbol_key = f"{namespace}_{group}_symbol"
    symbol = st.selectbox("종목", list(labels), index=None, placeholder="종목 선택",
                          format_func=labels.get, key=symbol_key)
    previous_key = f"{symbol_key}_previous"
    new_symbol = symbol if symbol != st.session_state.get(previous_key) else None
    st.session_state[previous_key] = symbol
    selected = new_symbol or new_click
    detail_key = f"{key}_{market}_detail"
    if selected:
        st.session_state[detail_key] = selected
    detail = st.session_state.get(detail_key)
    if detail in set(choices["ticker"]):
        row = choices.loc[choices["ticker"] == detail].iloc[0]
        _render_detail(st, row, supplied.get(detail), market, key)
    order = st.radio("등락 정렬", ("상승순", "하락순"), horizontal=True, key=f"{key}_order")
    table = view.sort_values(["return_pct", "ticker"], ascending=[order == "하락순", True], na_position="last")
    table = table[["sector", "name", "ticker", "close", "return_pct", "close_date", "base_date", "status"]].rename(
        columns={"sector": "섹터", "name": "종목", "ticker": "티커", "close": "종가", "return_pct": "수익률(%)",
                 "close_date": "종가일", "base_date": "비교일", "status": "상태"})
    st.dataframe(table, hide_index=True, width="stretch", height=min(430, 36 + 35 * len(table)),
                 column_config={"종가": st.column_config.NumberColumn(format="%.2f"),
                                "수익률(%)": st.column_config.NumberColumn(format="%+.2f%%")})
    return selected
