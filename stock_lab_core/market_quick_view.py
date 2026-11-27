"""Read-only market entry shared by charts and briefing; no decision inputs.

No aggregate cache: reuse provider caches unchanged (daily batch 300/15s,
KR indices and US quotes 60/15s, KR polling 30/10s). Re-evaluate the session
on every render, including after a holiday or an early close.
"""
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from datetime import timedelta

import pandas as pd

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_exchange_clock import exchange_clock, session_on_date
from stock_lab_core.report_quotes import (
    raw_number, regular_quote_observation, extended_quote_observation,
    extended_quote_status, kr_index_observations,
)

register_loaded_source(__name__, __file__)
INDICES = (("^KS11", "코스피", "KR"), ("^KQ11", "코스닥", "KR"),
           ("^GSPC", "S&P 500", "US"), ("^IXIC", "나스닥종합", "US"))
ETFS = (("SPY", "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ · 나스닥100 ETF"))
US_TICKERS = ("^GSPC", "^IXIC", "SPY", "QQQ")


def collect_inputs():
    from stock_lab_core.prices import load_price_frames_batch
    from stock_lab_core.report_live import load_kr_index_history
    from stock_lab_core.report_quotes import load_report_quotes
    from stock_lab_core.performance import submit_with_context
    now = pd.Timestamp.now(tz="UTC")
    with ThreadPoolExecutor(max_workers=4) as pool:
        daily = submit_with_context(pool, load_price_frames_batch, US_TICKERS, "1mo")
        kr = {ticker: submit_with_context(pool, load_kr_index_history, code)
              for ticker, code in (("^KS11", "KOSPI"), ("^KQ11", "KOSDAQ"))}
        quotes = submit_with_context(pool, load_report_quotes, US_TICKERS,
                                     include_kr=exchange_clock("KR", now)["phase"] == "intraday")
        frames = dict(daily.result())
        frames.update({ticker: future.result() for ticker, future in kr.items()})
        return frames, quotes.result()


def last_close(frame, market, now):
    from stock_lab_core.market_board import completed_close_series
    series, _ = completed_close_series(frame, market, now=now)
    if len(series) < 2 or series.iloc[-2:].isna().any():
        return {}
    day, previous = series.index[-1], series.index[-2]
    session = session_on_date(market, day)
    if not session.get("close"):
        return {}
    # Missing intervening sessions must not masquerade as a daily change.
    prior_day = day.date() - timedelta(days=1)
    for _ in range(32):
        prior_session = session_on_date(market, prior_day)
        if not prior_session["known"]:
            return {}
        if prior_session["trading_day"]:
            break
        prior_day -= timedelta(days=1)
    if prior_day != previous.date():
        return {}
    return {"price": float(series.iloc[-1]), "return": float(series.iloc[-1] / series.iloc[-2] - 1),
            "date": str(day.date()), "previous_date": str(previous.date()),
            "as_of": session["close"].isoformat(), "clock_kind": "거래소 마감시각(일봉)",
            "source": frame.attrs.get("source", "Yahoo 일봉"), "kind": "확정 종가"}


def regular_live(row, ticker, now):
    """Current regular trade only; keep it separate from confirmed daily bars."""
    if not isinstance(row, dict) or row.get("symbol") != ticker:
        return {}
    session = exchange_clock("US", now)
    if session["phase"] != "intraday":
        return {}
    try:
        at = pd.Timestamp(raw_number(row.get("regularMarketTime")), unit="s", tz="UTC")
        price, prior = (raw_number(row.get(k)) for k in ("regularMarketPrice", "regularMarketPreviousClose"))
        if (pd.isna(at) or not price or not prior or min(price, prior) <= 0
                or not session["open"] <= at < session["close"] or at > now):
            return {}
    except (TypeError, ValueError, OverflowError):
        return {}
    from stock_lab_core.report_quotes import _quote_direction_issue
    if _quote_direction_issue(row, "regular", price, prior):
        return {}
    delayed = (now - at).total_seconds() > 900
    return {"price": price, "return": price / prior - 1, "date": session["local_date"],
            "as_of": at.isoformat(), "clock_kind": "실제 체결시각", "source": "Yahoo 정규장 시세",
            "kind": "지연 시세 · 정규장" if delayed else "정규장 장중 · 미확정"}


def build_snapshot(frames, quotes, now):
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("Market view requires an aware clock")
    us = quotes.get("US", {})
    kr_live = kr_index_observations(quotes.get("KR", {}), now)
    rows = []
    for ticker, name, market in INDICES:
        close = last_close(frames.get(ticker), market, now)
        if market == "US":
            verified = regular_quote_observation(us.get(ticker, {}), ticker, now)
            if verified and (not close or verified["date"] >= close["date"]):
                close = dict(verified, kind="확정 종가", clock_kind="실제 체결시각")
            live = regular_live(us.get(ticker, {}), ticker, now)
        else:
            live = kr_live.get(ticker, {})
            if live:
                live = dict(live, clock_kind="공급처 응답시각(체결시각 아님)")
        chosen = live or close
        if chosen and not live and exchange_clock(market, now)["phase"] == "intraday":
            chosen = dict(chosen, kind="직전 확정 종가 · 장중 시세 미수신")
        if chosen and not live:
            # Keep a verified old value visible, but never label it as today's close.
            for offset in range(32):
                day = pd.Timestamp(now).tz_convert("Asia/Seoul" if market == "KR" else "America/New_York").date() - timedelta(days=offset)
                expected = session_on_date(market, day)
                if expected.get("trading_day") and expected["close"] <= now:
                    if chosen["date"] != day.isoformat():
                        chosen = dict(chosen, kind="마지막 확인 종가 · 최신 종가 미수신")
                    break
        rows.append(dict(ticker=ticker, name=name, market=market, selected=chosen, close=close,
                         phase=exchange_clock(market, now)["phase"],
                         status="연결" if chosen else "조회 미수신"))
    references = []
    for ticker, name in ETFS:
        row = us.get(ticker, {})
        obs = regular_live(row, ticker, now) or extended_quote_observation(row, ticker, now)
        if not obs:
            obs = extended_quote_observation(row, ticker, now, allow_delayed=True)
            if obs:
                obs = dict(obs, kind="지연 시세 · " + obs["kind"])
        references.append(dict(ticker=ticker, name=name, selected=obs,
                               status="연결" if obs else extended_quote_status(row, ticker, now)))
    return {"checked_at": now.isoformat(), "quote_assembly_at": quotes.get("retrieved_at"),
            "provider_retrieved_at": {ticker: row.get("_retrieved_at") for ticker, row in us.items()},
            "indices": rows, "references": references}


def display_rows(rows):
    result = []
    for row in rows:
        obs = row["selected"]
        at = pd.Timestamp(obs["as_of"]).tz_convert("Asia/Seoul").strftime("%m/%d %H:%M:%S KST") if obs else "—"
        result.append({"지수·상품": row["name"] + " (" + row["ticker"] + ")",
                       "값": f'{obs["price"]:,.2f}' if obs else "미수신",
                       "등락률": f'{obs["return"] * 100:+.2f}%' if obs else "—",
                       "기준": obs.get("kind", row["status"]), "기준일": obs.get("date", "—"),
                       "등락 비교일": obs.get("previous_date", "직전 정규장 종가") if obs else "—",
                       "기준시각(KST)": at, "시각 의미": obs.get("clock_kind", "실제 체결시각") if obs else "—",
                       "출처": obs.get("source", "—")})
    return result


def render_market_quick_view(st, *, key="market_quick", script_started=None):
    import json
    start = perf_counter()
    st.subheader("주요 시장 지금 보기")
    st.button("시장 시세 다시 확인", key=key + "_refresh", help="기존 공급처 캐시 유효기간을 유지합니다.")
    frames, quotes = collect_inputs()
    snapshot = build_snapshot(frames, quotes, pd.Timestamp.now(tz="UTC"))
    st.dataframe(pd.DataFrame(display_rows(snapshot["indices"])), hide_index=True, width="stretch")
    elapsed = perf_counter() - start
    count = st.session_state.get("_today_full_calculation_count", 0)
    snapshot.update(load_render_seconds=elapsed, today_calculations_in_session=count,
                    script_to_market_seconds=perf_counter() - script_started if script_started is not None else None)
    st.caption(f"이번 세션 오늘점검 완료 {count}회 · 시장 조회·표시 {elapsed:.2f}초 · "
               f"앱 확인 {pd.Timestamp(snapshot['checked_at']).tz_convert('Asia/Seoul'):%m/%d %H:%M:%S} KST")
    st.markdown("**ETF 참고 시세 · 현물지수와 별도**")
    st.dataframe(pd.DataFrame(display_rows(snapshot["references"])), hide_index=True, width="stretch")
    st.caption("나스닥종합(^IXIC)과 나스닥100 추종 ETF(QQQ)는 다른 상품입니다. ETF 가격 단위 USD. "
               "정규장 밖 현물은 확인된 종가, ETF는 해당 세션 체결을 표시합니다. 일봉 시각은 실제 체결시각이 아닙니다.")
    with st.expander("시장 연결 진단"):
        st.download_button("시장 조회 진단 JSON", json.dumps(snapshot, ensure_ascii=False, indent=2),
                           file_name="market_quick_view.json", mime="application/json", key=key + "_audit", on_click="ignore")
    return snapshot
