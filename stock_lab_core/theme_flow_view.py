"""Pure table preparation for theme flow; input ranking and numeric data stay intact."""

import pandas as pd

from stock_lab_core.formatters import finite_num, format_currency


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


def prepare_theme_stock_display(stock_view, state_badges, *, format_pct):
    """Format the already classified/ordered stock table without altering it."""
    show_stock = stock_view.copy()
    # 투자유형은 이미 stock_view에 있음 — 포맷 유지
    if "상태" in show_stock.columns:
        show_stock["상태"] = show_stock["상태"].map(lambda s: state_badges.get(str(s), str(s)))
    # 현재가 포맷 (국내: 정수, 해외: 소수 2자리)
    show_stock["현재가"] = show_stock.apply(
        lambda r: format_currency(r["현재가"], r["Ticker"]) if finite_num(r["현재가"]) else "-",
        axis=1,
    )
    # ── CSV 내보내기까지 올바르게 나오도록 모든 숫자를 문자열로 포맷 ──
    for _col in ["1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률"]:
        if _col in show_stock.columns:
            show_stock[_col] = show_stock[_col].apply(format_pct)
    for _col in ["가속도", "거래량증가"]:
        if _col in show_stock.columns:
            show_stock[_col] = show_stock[_col].apply(
                lambda v: f"{v:.2f}" if finite_num(v) else "-"
            )
    if "가격수준" in show_stock.columns:
        show_stock["가격수준"] = show_stock["가격수준"].apply(
            lambda v: f"{v*100:.1f}%" if finite_num(v) else "-"
        )
    if "돈흐름점수" in show_stock.columns:
        show_stock["돈흐름점수"] = show_stock["돈흐름점수"].apply(
            lambda v: f"{v:.1f}" if finite_num(v) else "-"
        )
    # 데이터 없는 컬럼 제거
    for _col in ["상대3개월수익률", "추격위험"]:
        if _col in show_stock.columns:
            _vals = show_stock[_col].replace("-", pd.NA).dropna()
            if _vals.empty or (_vals.astype(str).str.strip() == "").all():
                show_stock.drop(columns=[_col], inplace=True)
    _it_show_cols = [c for c in [
        "투자유형", "하위테마", "종목명", "Ticker", "현재가", "상태",
        "가격수준", "돈흐름점수",
        "1개월수익률", "3개월수익률", "상대3개월수익률", "6개월수익률",
        "가속도", "거래량증가",
    ] if c in show_stock.columns]
    return show_stock[_it_show_cols]
