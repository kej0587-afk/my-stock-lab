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


def _sector_change(item):
    raw = str(item.get("flu_rt") if item.get("flu_rt") is not None else "").strip()
    text = raw.replace(",", "")
    value = _number(text)

    def result(value, reason):
        return value, f"등락률 확인: {reason} · 원값 {raw or '미제공'}"

    if value is None or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return result(None, "유효한 수치 미제공")
    price, delta = _number(item.get("cur_prc")), _number(item.get("pred_pre"))
    if price is None or delta is None:
        if "." in text and value >= -100:
            return result(value, "명시된 소수점 백분율")
        return result(None, "배율 대조 근거 미제공")
    delta_text = str(item.get("pred_pre")).strip().replace(",", "")
    sign = str(item.get("pre_smbol") or "").strip()
    expected_signs = {"1", "2"} if delta > 0 else {"4", "5"} if delta < 0 else {"3"}
    if (delta != 0 and not re.fullmatch(r"[+-]\d+(?:\.\d+)?", delta_text)) or (sign and sign not in expected_signs):
        return result(None, "전일대비 부호 미확인/불일치")
    previous = abs(price) - delta
    if abs(price) <= 0 or previous <= 0 or not math.isfinite(previous):
        return result(None, "현재가/전일 기준값 불일치")
    derived = delta / previous * 100
    # Both price fields share a scale; rates round to two decimal places.
    candidates = {candidate for candidate in (value, value / 100)
                  if abs(candidate - derived) <= 0.005 + 1e-9}
    if len(candidates) != 1:
        return result(None, "배율 모호/전일대비 대조 불일치")
    matched = candidates.pop()
    return result(matched, "전일대비 대조 일치" if matched == value else "전일대비 대조 일치(원값/100)")


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
            change, change_reason = _sector_change(item)
            rows.append({
                "코드": code, "업종": name.strip(), "등락률(%)": change,
                "외국인 순매수(억원)": _number(item.get("frgnr_netprps")),
                "기관 순매수(억원)": _number(item.get("orgn_netprps")),
                "개인 순매수(억원)": _number(item.get("ind_netprps")),
                "구분": change_reason,
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
