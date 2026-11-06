"""Pure table preparation for theme flow; input ranking and numeric data stay intact."""

import pandas as pd

from stock_lab_core.formatters import finite_num


def prepare_theme_group_display(group_df, state_badges, *, format_pct):
    """Return the existing summary/CSV columns without changing the source frame."""
    show_group = group_df.copy()
    if "상태" in show_group.columns:
        show_group["상태"] = show_group["상태"].map(lambda s: state_badges.get(str(s), str(s)))
    # ── CSV 내보내기까지 올바르게 나오도록 모든 숫자를 문자열로 포맷 ──
    for _col in ["2주수익률", "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률",
                 "6개월수익률", "2주상승비율", "1개월상승비율", "상승종목비율"]:
        if _col in show_group.columns:
            show_group[_col] = show_group[_col].apply(format_pct)
    for _col in ["가속도", "단기가속도", "거래량증가", "상위종목쏠림"]:
        if _col in show_group.columns:
            show_group[_col] = show_group[_col].apply(
                lambda v: f"{v:.2f}" if finite_num(v) else "-"
            )
    if "가격수준" in show_group.columns:
        show_group["가격수준"] = show_group["가격수준"].apply(
            lambda v: f"{v*100:.1f}%" if finite_num(v) else "-"
        )
    if "돈흐름점수" in show_group.columns:
        show_group["돈흐름점수"] = show_group["돈흐름점수"].apply(
            lambda v: f"{v:.1f}" if finite_num(v) else "-"
        )
    # 데이터 없는 컬럼 제거
    for _col in ["이전3개월수익률", "상대3개월수익률", "추격위험"]:
        if _col in show_group.columns:
            _vals = show_group[_col].replace("-", pd.NA).dropna()
            if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                show_group.drop(columns=[_col], inplace=True)
    _sg_show_cols = [c for c in [
        "하위테마", "종목수", "대표주",
        "2주수익률", "1개월수익률", "3개월수익률", "이전3개월수익률", "상대3개월수익률", "6개월수익률",
        "가속도", "단기가속도", "2주상승비율", "상승종목비율", "거래량증가", "상위종목쏠림",
        "가격수준", "돈흐름점수", "상태", "구성종목",
    ] if c in show_group.columns]
    return show_group[_sg_show_cols]
