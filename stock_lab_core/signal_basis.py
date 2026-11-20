"""Display provenance for existing signal inputs; never infer a quote session."""

from datetime import datetime
import math
from zoneinfo import ZoneInfo

import pandas as pd
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.signal_input_contract import price_input_identity, source_price_rows

register_loaded_source(__name__, __file__)


def source_date(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return "미확인"
    stamp = frame.index[-1]
    return stamp.strftime("%Y-%m-%d") if pd.notna(stamp) else "미확인"


def build_signal_basis(source, context, *, calculated_at=None, ticker="", input_price=None, manual=False):
    chart, applied, issue = context
    quote = dict(getattr(chart, "attrs", {}).get("live_quote") or {})
    atr_frame = source_price_rows(chart)
    try:
        has_quote = not isinstance(input_price, bool) and math.isfinite(float(input_price)) and float(input_price) > 0
    except (TypeError, ValueError):
        has_quote = bool(applied)
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
        "현재가출처": ("수동 입력 · 공급 시각 없음" if manual else
                    "현재가 단일값 조회 · 공급 시각·세션 미확인" if has_quote else "별도 현재가 미연결 · 가격 이력 기준"),
        "임시봉날짜의미": "계산용 현지 날짜 · 실제 체결 시각/정규장 완료일 아님" if applied else "원자료 봉 날짜",
        # Processing time is not the vendor's quote time.
        "계산시각": calculated_at or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST"),
    }


def quote_display_label(*, manual_price=0, auto_price=0, live_applied=False):
    if manual_price > 0:
        return "수동보정 · 차트 반영" if live_applied else "수동보정 · 차트 미반영"
    if auto_price > 0:
        return "조회 현재가 · 세션 미확인"
    return "가격 이력 기준"


def render_signal_basis(st, basis):
    provisional = "미확정" in basis["가격반영"]
    rows = [
        {"항목": "판정 RSI·이평선", "기준일/봉 날짜": basis["지표마지막봉"],
         "가격 기준": "현재가 반영 임시값 · 시세 세션 미확인" if provisional else "가격 이력 기준"},
        {"항목": "점수카드 RSI·52주 위치", "기준일/봉 날짜": basis["가격자료기준일"],
         "가격 기준": "원자료 종가 · 현재가 보정 제외"},
        {"항목": "ATR(14)·계획 변동폭", "기준일/봉 날짜": basis.get("ATR기준일", "미확인"),
         "가격 기준": ("시세 전용 임시 봉 제외 · 원자료 가격 봉" if basis.get("ATR가격봉수", 0) >= 15
                      else "가격 봉 부족 · ATR 미산출")},
        {"항목": "거래량·MFI", "기준일/봉 날짜": "아래 자료 기준",
         "가격 기준": basis["수급자료기준"]},
    ]
    rows.append({"항목": "현재가 시각·세션", "기준일/봉 날짜": "미확인",
                 "가격 기준": basis.get("현재가출처", "공급 시각·세션 미확인")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"계산 {basis['계산시각']} · 시세 제공시각과 별도")
    if basis.get("가격입력ID"):
        st.caption(f"가격입력 ID {basis['가격입력ID']} · {basis.get('임시봉날짜의미', '')}")
        st.caption("가격입력만 비교하며 매크로·계좌·재무 입력은 별도입니다.")
    if basis.get("자료주의"):
        st.warning(basis["자료주의"])
