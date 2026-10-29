"""Display provenance for existing signal inputs; never infer a quote session."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def source_date(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return "미확인"
    stamp = frame.index[-1]
    return stamp.strftime("%Y-%m-%d") if pd.notna(stamp) else "미확인"


def build_signal_basis(source, context, *, calculated_at=None):
    chart, applied, issue = context
    quote = dict(getattr(chart, "attrs", {}).get("live_quote") or {})
    return {
        "가격자료기준일": source_date(source),
        "지표마지막봉": source_date(chart),
        "가격반영": "조회 현재가 보정 · 미확정" if applied else "가격 이력 기준",
        "수급자료기준": (
            "최신 거래량 미확인 · MFI " + str(quote.get("mfi_asof") or "미확인")[:10]
            if applied else "가격·거래량 원자료"
        ),
        "자료주의": str(issue or ""),
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
    st.caption(
        f"가격자료 {basis['가격자료기준일']} · 지표 마지막 봉 {basis['지표마지막봉']} · {basis['가격반영']}"
    )
    st.caption(f"계산 {basis['계산시각']} · 시세 제공시각과 별도")
    if basis.get("자료주의"):
        st.warning(basis["자료주의"])
