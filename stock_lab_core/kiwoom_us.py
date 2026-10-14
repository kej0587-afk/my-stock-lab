"""Read-only US market contracts from Kiwoom's published REST specification."""

import re

from stock_lab_core.kiwoom_market import _count, _nonnegative, _number


US_EXCHANGES = {"ND": "NASDAQ", "NY": "NYSE", "NA": "AMEX"}
US_MARKET_REQUESTS = {
    "us_quote": ("/api/us/mrkcond", "usa20100", {}),
    "us_turnover": ("/api/us/rkinfo", "usa20540", {
        "stex_tp": "0", "inds_cd": "000", "stk_tp": "1", "trde_qty_tp": "0",
        "stk_cnd": "0", "pric_cnd": "0", "trde_prica_cnd": "0",
    }),
    "us_sectors": ("/api/us/sect", "usa23000", {"stex_tp": "0", "inds_cd": "0"}),
}


def us_symbol(value):
    value = value.strip().upper() if isinstance(value, str) else ""
    return value if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value) else ""


def normalize_us_market_rows(payload, kind, *, ticker="", exchange="ND"):
    invalid = {"ok": False, "status": "invalid_response", "rows": []}
    if not isinstance(payload, dict) or kind not in US_MARKET_REQUESTS:
        return invalid
    if kind == "us_quote":
        # Never present a quote for a different symbol/exchange as the requested one.
        if (payload.get("stk_cd") != ticker or payload.get("stex_tp") != exchange
                or payload.get("curr_unit") not in (None, "", "USD")):
            return invalid
        raw = [payload]
    else:
        raw = payload.get("result_list")
    if not isinstance(raw, list):
        return invalid
    rows, seen = [], set()
    for item in raw[:200]:
        if not isinstance(item, dict):
            continue
        if kind == "us_sectors":
            code = str(item.get("inds_cd") or "")
            name = item.get("inds_nm")
            if not code.isdigit() or not isinstance(name, str) or not name.strip() or code in seen:
                continue
            row = {"코드": code, "업종": name.strip()}
            row.update({f"{period.upper()} 수익률(%)": _number(item.get("perf_" + period))
                        for period in ("1d", "5d", "1m", "3m", "6m", "ytd", "1y")})
            if all(v is None for k, v in row.items() if k.endswith("(%)")):
                continue
            seen.add(code)
        else:
            code = us_symbol(item.get("stk_cd"))
            venue = item.get("stex_tp")
            name = item.get("stk_nm") or item.get("stk_enm")
            if not code or not isinstance(venue, str) or venue not in US_EXCHANGES or not isinstance(name, str) or not name.strip():
                continue
            if (venue, code) in seen:
                continue
            price = _number(item.get("cur_prc"))
            if not price:
                continue
            seen.add((venue, code))
            row = {"코드": code, "거래소": US_EXCHANGES[venue], "종목명": name.strip(),
                   "영문명": str(item.get("stk_enm") or ""),
                   "현재가(USD)": abs(price), "등락률(%)": _number(item.get("flu_rt")),
                   "거래량(주)": _count(item.get("acc_trde_qty"))}
            if kind == "us_turnover":
                row.update({"키움순위": _count(item.get("rank")),
                            "거래대금(천USD)": _nonnegative(item.get("trde_prica"))})
            else:
                previous = _number(item.get("base_close_pric"))
                row.update({"전일종가(USD)": abs(previous) if previous else None,
                            "업종": str(item.get("sm_inds_cd") or item.get("lg_inds_cd") or "")})
        rows.append(row)
    return {"ok": bool(rows), "status": "available" if rows else "no_data", "rows": rows}
