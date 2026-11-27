"""SOXL short-term screen: three strategies kept apart (2026-11-27, user request 4).

Display only. Facts come from completed daily bars and fixed research records; nothing here grants an entry,
changes the existing gate or turns a research rule into an operating signal."""

from __future__ import annotations

import pandas as pd

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

SUPPORT = "SOXX 1시간 지지 반응 · SOXL 눌림 관찰"
DROP = "SOXL 직전 20일 최고 종가 대비 −20% 급락 반등 연구"
VOLUME = "거래량 돌파 후보"
STRATEGIES = (SUPPORT, DROP, VOLUME)

# Fixed research records (#108 protocol 5ada8a50, #110 phase 2). Not recomputed here.
DROP_RULE = {"threshold": -0.20, "lookback": 20, "stop": -0.10, "targets": (0.10, 0.20), "max_hold": 10,
             "entry": "신호 종가 확인 다음 정규장 시가(+0.10% 슬리피지)"}
DROP_PHASE2 = {"overlap": 16, "price_mismatch": 12, "missing": 4, "confirmed": 0, "independent": 0}


def _completed_closes(daily):
    if daily is None or getattr(daily, "empty", True) or "Close" not in daily:
        return pd.Series(dtype="float64")
    frame = daily
    if "LiveQuoteOnly" in frame:
        frame = frame.loc[~frame["LiveQuoteOnly"].astype("boolean").fillna(False).astype(bool)]
    return pd.to_numeric(frame["Close"], errors="coerce").dropna()


def drop_rebound_status(daily, *, gate_text):
    """Condition of the −20% study on the latest daily close; hypothetical prices only when it is met."""
    close = _completed_closes(daily)
    if len(close) < DROP_RULE["lookback"] + 1:
        return {"met": None, "summary": f"일봉 {len(close)}개 · 직전 20일 최고 종가 계산 불가", "next": "일봉 자료 확인",
                "prices": [], "gate": gate_text}
    last, at = float(close.iloc[-1]), close.index[-1]
    ref = close.iloc[-DROP_RULE["lookback"] - 1:-1]
    peak, peak_at = float(ref.max()), ref.idxmax()
    dd = last / peak - 1
    line = peak * (1 + DROP_RULE["threshold"])
    met = dd <= DROP_RULE["threshold"]
    day = lambda t: pd.Timestamp(t).strftime("%Y-%m-%d")
    summary = (f"{day(at)} 종가 ${last:,.2f} · 직전 20일 최고 종가 ${peak:,.2f}({day(peak_at)}) 대비 {dd * 100:+.1f}% · "
               f"−20% 기준선 ${line:,.2f} → {'충족' if met else '미충족'}")
    nxt = ("다음 정규장 시가(연구 진입 대용값)와 실제 시장방어 유지 여부 확인" if met
           else f"다음 완료 일봉 종가가 그날 기준 직전 20일 최고 종가의 80% 이하인지 확인")
    prices = []
    if met:
        prices = [{"항목": "가정 진입 기준", "가격": f"${last:,.2f}", "근거": "신호 종가 · 실제 연구 진입은 다음 시가"},
                  {"항목": "가정 손절", "가격": f"${last * (1 + DROP_RULE['stop']):,.2f}", "근거": "진입가 −10% · 갭이면 시가 청산(최대손실 보장 아님)"}]
        prices += [{"항목": f"가정 익절 +{int(t * 100)}%", "가격": f"${last * (1 + t):,.2f}", "근거": "진입가 기준"}
                   for t in DROP_RULE["targets"]]
        prices.append({"항목": "최대 보유", "가격": "-", "근거": "10거래일(진입일 포함) 뒤 종가 청산"})
    return {"met": met, "summary": summary, "next": nxt, "prices": prices, "gate": gate_text}


def volume_breakout_status(daily, *, gate_text):
    """Observed facts only: no entry/exit rule or performance check exists for this candidate yet."""
    close = _completed_closes(daily)
    if daily is None or getattr(daily, "empty", True) or "Volume" not in daily or len(close) < 21:
        return {"met": None, "summary": "거래량·20일 기준 계산 불가", "next": "일봉 자료 확인", "gate": gate_text}
    vol = pd.to_numeric(daily["Volume"], errors="coerce").reindex(close.index)
    last_vol, base = vol.iloc[-1], vol.iloc[-21:-1]
    ratio = (float(last_vol) / float(base.mean())) if pd.notna(last_vol) and base.notna().all() and base.mean() > 0 else None
    high20 = float(close.iloc[-21:-1].max())
    last = float(close.iloc[-1])
    summary = (f"{pd.Timestamp(close.index[-1]).strftime('%Y-%m-%d')} 거래량/직전 20봉 평균 "
               f"{'미확인' if ratio is None else f'{ratio:.2f}배'} · 종가 ${last:,.2f} / 직전 20일 최고 종가 ${high20:,.2f}")
    return {"met": None, "summary": summary,
            "next": "돌파 판정 기준(거래량 배수·종가 돌파·확인봉 수) 미정 → 규칙 고정과 과거 검증 후 판정",
            "gate": gate_text}


def strategy_rows():
    return [
        {"전략": SUPPORT, "기준 종목·봉": "지지 확인 SOXX 60분 · 손익 계산 SOXL 60분/5분",
         "검증 단계": "과거 60분 재생 있음(시장방어 과거 입력 미확보) · 독립 표본 0건"},
        {"전략": DROP, "기준 종목·봉": "SOXL 일봉 종가 · 2차 검증 SOXL 분봉",
         "검증 단계": f"일봉 연구(#108·#114) · 2차 분봉 중첩 {DROP_PHASE2['overlap']}건 중 가격 불일치 "
                     f"{DROP_PHASE2['price_mismatch']}·결측 {DROP_PHASE2['missing']} → 순서 확정 {DROP_PHASE2['confirmed']}건, "
                     "2차 승률 미산출 · 독립 표본 0건"},
        {"전략": VOLUME, "기준 종목·봉": "SOXL 일봉 거래량·패턴·매물대",
         "검증 단계": "진입·청산 규칙 및 성과 검증 전"},
    ]
