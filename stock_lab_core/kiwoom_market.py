"""Provider market observations, deliberately separate from execution gates."""

import math
import re


MARKET_REQUESTS = {
    "turnover": ("/api/dostk/rkinfo", "ka10032", {"mrkt_tp": "000", "mang_stk_incls": "0", "stex_tp": "1"}),
    "themes": ("/api/dostk/thme", "ka90001", {"qry_tp": "0", "date_tp": "10", "flu_pl_amt_tp": "3", "stex_tp": "1"}),
    "theme_members": ("/api/dostk/thme", "ka90002", {"date_tp": "10", "stex_tp": "1"}),
    "sector_kospi": ("/api/dostk/sect", "ka10051", {"mrkt_tp": "0", "amt_qty_tp": "0", "stex_tp": "1"}),
    "sector_kosdaq": ("/api/dostk/sect", "ka10051", {"mrkt_tp": "1", "amt_qty_tp": "0", "stex_tp": "1"}),
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(str(value).replace(",", ""))
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _nonnegative(value):
    value = _number(value)
    return value if value is not None and value >= 0 else None


def _count(value):
    number = _nonnegative(value)
    return int(number) if number is not None and number.is_integer() else None


def normalize_market_rows(payload, kind):
    key = {"turnover": "trde_prica_upper", "themes": "thema_grp", "theme_members": "thema_comp_stk",
           "sector_kospi": "inds_netprps", "sector_kosdaq": "inds_netprps"}.get(kind)
    raw = payload.get(key) if isinstance(payload, dict) and key else None
    if not isinstance(raw, list):
        return {"ok": False, "status": "invalid_response", "rows": []}
    rows, seen = [], set()
    for item in raw[:200]:
        if not isinstance(item, dict):
            continue
        is_stock = kind in {"turnover", "theme_members"}
        is_sector = kind.startswith("sector_")
        code = str(item.get("stk_cd" if is_stock else "inds_cd" if is_sector else "thema_grp_cd", "")).strip()
        pattern = r"[0-9][A-Z0-9]{5}" if is_stock else r"[0-9]{1,6}"
        if not re.fullmatch(pattern, code) or code in seen or (is_stock and code == "000000"):
            continue
        name = item.get("stk_nm" if is_stock else "inds_nm" if is_sector else "thema_nm")
        if not isinstance(name, str) or not name.strip():
            continue
        change = _number(item.get("flu_rt"))
        seen.add(code)
        if is_sector:
            rows.append({
                "코드": code, "업종": name.strip(), "등락률(%)": change,
                "외국인 순매수(억원)": _number(item.get("frgnr_netprps")),
                "기관 순매수(억원)": _number(item.get("orgn_netprps")),
                "개인 순매수(억원)": _number(item.get("ind_netprps")),
            })
        elif kind == "theme_members":
            price = _number(item.get("cur_prc"))
            rows.append({"코드": code, "종목명": name.strip(), "등락률(%)": change,
                         "10일 기간수익률(%)": _number(item.get("dt_prft_rt_n")),
                         "현재가(원)": abs(price) if price else None,
                         "거래량(주)": _count(item.get("acc_trde_qty"))})
        elif kind == "turnover":
            price = _number(item.get("cur_prc"))
            rows.append({
                "코드": code, "종목명": name.strip(), "등락률(%)": change,
                "현재가(원)": abs(price) if price else None,
                "거래대금(백만원)": _nonnegative(item.get("trde_prica")),
                "거래량(주)": _count(item.get("now_trde_qty")),
                "키움순위": _count(item.get("now_rank")),
                "전일순위": _count(item.get("pred_rank")),
                "구분": "거래대금 관찰 · 매수판정 아님",
            })
        else:
            total = _count(item.get("stk_num"))
            rising = _count(item.get("rising_stk_num"))
            falling = _count(item.get("fall_stk_num"))
            breadth = 100 * rising / total if total and rising is not None and rising <= total else None
            if total and rising is not None and falling is not None and rising + falling > total:
                breadth = None
            rows.append({
                "코드": code, "테마": name.strip(), "등락률(%)": change,
                "10일 기간수익률(%)": _number(item.get("dt_prft_rt")),
                "종목수": total, "상승종목수": rising, "하락종목수": falling,
                "상승비율(%)": breadth, "주요종목(키움)": str(item.get("main_stk") or ""),
                "구분": "당일 상승 확산" if change is not None and change > 0 and breadth is not None and breadth >= 60 else "당일 혼조/확산 미확인",
            })
    return {"ok": bool(rows), "status": "available" if rows else "no_data", "rows": rows}


def market_evidence_summary(turnover, themes):
    """Summarize supplied snapshots without converting turnover into net inflow."""
    lines = []
    if turnover.get("ok") and turnover.get("rows"):
        row = turnover["rows"][0]
        change = row.get("등락률(%)")
        change_text = f"{change:+.1f}%" if change is not None else "미제공"
        lines.append(f"거래대금 상위 첫 종목은 {row['종목명']}({row['코드']}), 등락률 {change_text}입니다. 거래대금은 순매수가 아닙니다.")
    if themes.get("ok"):
        broad = [row for row in themes.get("rows", []) if row.get("구분") == "당일 상승 확산"]
        if broad:
            names = ", ".join(f"{row['테마']}({row['등락률(%)']:+.1f}%, 상승 {row['상승비율(%)']:.0f}%)" for row in broad[:3])
            lines.append("조회된 테마 중 상승 확산: " + names + ".")
        else:
            lines.append("조회된 테마에서는 등락률 양수·상승종목 60% 이상이 함께 확인된 축이 없습니다.")
    return lines
