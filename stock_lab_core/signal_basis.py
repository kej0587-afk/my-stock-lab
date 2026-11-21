"""Display provenance for existing signal inputs; never infer a quote session."""

from datetime import datetime
import math
import re
from zoneinfo import ZoneInfo

import pandas as pd
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.signal_input_contract import price_input_identity, source_price_rows
from stock_lab_core.quote_observation import quote_provenance

register_loaded_source(__name__, __file__)

_SESSION_LABELS = {"regular": "정규장", "pre": "프리마켓", "post": "애프터마켓",
                   "overnight": "오버나이트", "day": "공급사 day 시세 · 정규장 여부 미확인"}


def selection_basis(*, is_free, has_position, selection_type):
    """Record the actual call mode separately from price identity and ownership."""
    return {
        "자유입력여부": is_free if isinstance(is_free, bool) else None,
        "분석경로": "자유입력" if is_free is True else "계좌기준" if is_free is False else "미확인",
        "보유확인": "보유" if has_position is True else "미보유" if has_position is False else "미확인",
        "선택유형": selection_type if selection_type in {"today", "free", "watchlist", "preset"} else "unknown",
    }


def source_bar_observation(frame, provenance, ticker):
    """Audit daily rows against the *selected* quote, never discard/reclassify them."""
    date = source_date(frame)
    stamp = provenance.get("observed_at")
    if date == "미확인" or not stamp:
        return "원자료 봉 완료 여부 미확인 · 시세 관측시각 미연결"
    symbol = str(ticker).strip().upper()
    zone = "Asia/Seoul" if symbol.endswith((".KS", ".KQ")) else (
        "America/New_York" if re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z])?", symbol) else None)
    if not zone:
        return "원자료 봉 완료 여부 미확인 · 시장 시간대 미확인"
    observed = pd.Timestamp(stamp)
    if pd.isna(observed) or observed.tzinfo is None:
        return "원자료 봉 완료 여부 미확인 · 시세 시간대 미확인"
    quote_date = observed.tz_convert(zone).strftime("%Y-%m-%d")
    if date > quote_date:
        return "시세 관측일보다 뒤인 원자료 봉 · 기준일 확인 필요"
    if date < quote_date:
        return "시세 관측일 이전 원자료 봉 · 종가 확정은 별도 확인"
    if provenance.get("session") == "regular":
        return "정규장 시세와 같은 날짜의 원자료 봉 · 장중 미완성 가능"
    return "시세 관측일과 같은 원자료 봉 · 완료 여부 미확인"


def _quote_basis(input_price, ticker, manual, has_quote):
    provenance = quote_provenance(input_price, ticker=ticker) if not manual else {}
    observed = provenance.get("observed_at", "")
    stamp_kind = {"trade": "공급 시세 시각", "bar_start": "분봉 시작시각 · 체결시각 아님"}.get(
        provenance.get("timestamp_kind"), "시각 종류 미확인")
    session = _SESSION_LABELS.get(provenance.get("session"), "미확인")
    source = ("수동 입력 · 공급 시각 없음" if manual else
              str(provenance.get("source") or "현재가 단일값 조회 · 공급 시각·세션 미확인")
              if has_quote else "별도 현재가 미연결 · 가격 이력 기준")
    at = pd.Timestamp(observed).tz_convert("Asia/Seoul").strftime("%Y-%m-%d %H:%M:%S KST") if observed else "미확인"
    return provenance, {"현재가출처": source, "현재가관측시각": at, "현재가관측UTC": observed,
                        "현재가세션": session, "현재가시각종류": stamp_kind}


def source_date(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return "미확인"
    stamp = frame.index[-1]
    return stamp.strftime("%Y-%m-%d") if pd.notna(stamp) else "미확인"


def source_return_basis(source, ticker, calculated_at):
    """Describe the actual source pair; never recalculate or select a return."""
    result = {"등락비교기준": "원자료 비교쌍 미확인", "등락봉시간상태": "완료 여부 미확인"}
    if (not isinstance(source, pd.DataFrame) or len(source) < 2 or "Close" not in source
            or not isinstance(source.index, pd.DatetimeIndex)):
        return result
    dates = source.index[-2:].tz_localize(None).normalize()
    values = pd.to_numeric(source.Close.iloc[-2:], errors="coerce")
    if (dates.isna().any() or dates[0] >= dates[1]
            or not all(pd.notna(v) and math.isfinite(v) and v > 0 for v in values)):
        return result
    previous, current = dates.strftime("%Y-%m-%d")
    result["등락비교기준"] = f"원자료 Close {previous} → {current}"
    symbol = str(ticker).strip().upper()
    market = "KR" if symbol.endswith((".KS", ".KQ")) or symbol in {"^KS11", "^KQ11"} else (
        "US" if re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z])?", symbol) else None)
    if not market:
        return result
    try:
        raw = str(calculated_at)
        # Only an explicit KST suffix or aware clock may establish a time boundary.
        clock = (pd.Timestamp(raw[:-4]).tz_localize("Asia/Seoul") if raw.endswith(" KST")
                 else pd.Timestamp(calculated_at))
        if pd.isna(clock) or clock.tzinfo is None:
            return result
        from stock_lab_core.report_exchange_clock import session_on_date
        session = session_on_date(market, current)
        if not session["known"]:
            result["등락봉시간상태"] = "거래일정 미확인"
        elif not session["trading_day"]:
            result["등락봉시간상태"] = "비거래일 날짜의 원자료 · 확인 필요"
        elif clock < session["open"]:
            result["등락봉시간상태"] = "개장 전 날짜의 원자료 · 확인 필요"
        elif clock < session["close"]:
            result["등락봉시간상태"] = "장중 원자료 · 미확정"
        else:
            result["등락봉시간상태"] = "마감시각 경과 · 공급처 확정 여부 미확인"
    except (TypeError, ValueError, OverflowError):
        pass
    return result


def build_signal_basis(source, context, *, calculated_at=None, ticker="", input_price=None, manual=False):
    chart, applied, issue = context
    quote = dict(getattr(chart, "attrs", {}).get("live_quote") or {})
    atr_frame = source_price_rows(chart)
    try:
        has_quote = not isinstance(input_price, bool) and math.isfinite(float(input_price)) and float(input_price) > 0
    except (TypeError, ValueError):
        has_quote = bool(applied)
    provenance, quote_fields = _quote_basis(input_price, ticker, manual, has_quote)
    calculated_at = calculated_at or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")
    return_basis = source_return_basis(source, ticker, calculated_at)
    latest_basis = (f"선택 현재가 / {source_date(source)} 원자료 Close · "
                    f"시세시각 {quote_fields['현재가관측시각']} · 세션 {quote_fields['현재가세션']}"
                    if has_quote and return_basis["등락비교기준"] != "원자료 비교쌍 미확인" else "비교기준 미확인")
    return {
        "가격자료기준일": source_date(source),
        "지표마지막봉": source_date(chart),
        "가격반영": "조회 현재가 보정 · 미확정" if applied else "가격 이력 기준",
        "수급자료기준": (
            "최신 거래량 미확인 · MFI " + str(quote.get("mfi_asof") or "미확인")[:10]
            if applied else "가격·거래량 원자료"
        ),
        "자료주의": str(issue or ""),
        "ATR기준일": source_date(atr_frame),
        "ATR가격봉수": len(atr_frame) if isinstance(atr_frame, pd.DataFrame) else 0,
        "가격입력ID": price_input_identity(source, chart, ticker=ticker, input_price=input_price),
        **quote_fields,
        **return_basis,
        "최신가비교기준": latest_basis,
        "원자료봉상태": source_bar_observation(atr_frame, provenance, ticker),
        "임시봉날짜의미": "계산용 현지 날짜 · 실제 체결 시각/정규장 완료일 아님" if applied else "원자료 봉 날짜",
        # Processing time is not the vendor's quote time.
        "계산시각": calculated_at,
    }


def quote_display_label(*, manual_price=0, auto_price=0, live_applied=False):
    if manual_price > 0:
        return "수동보정 · 차트 반영" if live_applied else "수동보정 · 차트 미반영"
    if auto_price > 0:
        session = _SESSION_LABELS.get(quote_provenance(auto_price).get("session"))
        return f"조회 현재가 · {session}" if session else "조회 현재가 · 세션 미확인"
    return "가격 이력 기준"


def render_signal_basis(st, basis):
    provisional = "미확정" in basis["가격반영"]
    rows = [
        {"항목": "판정 RSI·이평선", "기준일/봉 날짜": basis["지표마지막봉"],
         "가격 기준": f"현재가 반영 임시값 · {basis.get('현재가세션', '세션 미확인')}" if provisional else "가격 이력 기준"},
        {"항목": "점수카드 RSI·52주 위치", "기준일/봉 날짜": basis["가격자료기준일"],
         "가격 기준": "원자료 종가 · 현재가 보정 제외"},
        {"항목": "ATR(14)·계획 변동폭", "기준일/봉 날짜": basis.get("ATR기준일", "미확인"),
         "가격 기준": ("시세 전용 임시 봉 제외 · 원자료 가격 봉" if basis.get("ATR가격봉수", 0) >= 15
                      else "가격 봉 부족 · ATR 미산출")},
        {"항목": "거래량·MFI", "기준일/봉 날짜": "아래 자료 기준",
         "가격 기준": basis["수급자료기준"]},
    ]
    rows.append({"항목": "현재가 시각·세션", "기준일/봉 날짜": basis.get("현재가관측시각", "미확인"),
                 "가격 기준": " · ".join([basis.get("현재가출처", "공급 시각·세션 미확인"),
                                       basis.get("현재가세션", "미확인"), basis.get("현재가시각종류", "")])})
    rows.append({"항목": "원자료 일봉 확인", "기준일/봉 날짜": basis.get("ATR기준일", "미확인"),
                 "가격 기준": basis.get("원자료봉상태", "완료 여부 미확인")})
    if basis.get("등락비교기준"):
        rows.append({"항목": "일간 등락 비교", "기준일/봉 날짜": basis["등락비교기준"],
                     "가격 기준": basis.get("등락봉시간상태", "완료 여부 미확인")})
        rows.append({"항목": "최신가 비교가 표시될 때", "기준일/봉 날짜": basis.get("가격자료기준일", "미확인"),
                     "가격 기준": basis.get("최신가비교기준", "비교기준 미확인")})
    if basis.get("분석경로"):
        rows.append({"항목": "판정 선택 경로", "기준일/봉 날짜": basis["분석경로"],
                     "가격 기준": f"{basis.get('보유확인', '미확인')} · 자유입력도 실제 보유 종목일 수 있음"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"계산 {basis['계산시각']} · 시세 제공시각과 별도")
    if basis.get("가격입력ID"):
        st.caption(f"가격입력 ID {basis['가격입력ID']} · {basis.get('임시봉날짜의미', '')}")
        st.caption("가격입력만 비교하며 매크로·계좌·재무 입력은 별도입니다.")
    if basis.get("자료주의"):
        st.warning(basis["자료주의"])
