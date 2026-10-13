"""Cross-view consistency diagnostics; never promote a candidate to a buy."""

import pandas as pd

from stock_lab_core.formatters import normalize_ticker


def cross_view_flags(summary, flow=None, *, excluded_ticker=lambda ticker: False):
    flags = []
    if not isinstance(summary, pd.DataFrame) or summary.empty or "티커" not in summary:
        return flags

    def flag(row, severity, issue, evidence, action):
        flags.append({"등급": severity, "티커": row.get("티커", ""), "종목명": row.get("종목명", ""),
                      "문제": issue, "근거": evidence, "확인/조치": action})

    for row in summary.to_dict("records"):
        gate = str(row.get("게이트상태", ""))
        code = str(row.get("판정코드", ""))
        if code in {"DATA_ERROR", "DATA_UNAVAILABLE", "LIVE_ONLY_DATA"}:
            flag(row, "주의", "종목 판단 실패", str(row.get("데이터상태", "")), "오류를 정상/0점으로 해석하지 않습니다. 로그의 종목·단계를 확인하세요.")
        if gate == "데이터확인" and str(row.get("게이트근거", "")).upper() in {"", "OK", "NORMAL", "정상"}:
            flag(row, "주의", "데이터확인 근거 누락", code, "가격 이력 부족과 조회 실패를 구분하세요.")

    if not isinstance(flow, pd.DataFrame) or flow.empty or "Ticker" not in flow:
        return flags
    today = {normalize_ticker(str(row["티커"])): row for row in summary.to_dict("records")}
    seen = set()
    for item in flow.to_dict("records"):
        ticker = str(item.get("Ticker", ""))
        key = normalize_ticker(ticker)
        if key in seen or excluded_ticker(ticker):
            continue
        seen.add(key)
        row = today.get(key)
        if row is None or row.get("게이트상태") != "방어우선":
            continue
        context = " · ".join(str(item.get(col, "")) for col in ("상태", "테마판정", "판정", "후보군"))
        if not any(word in context for word in ("강세 가속", "고변동", "진입검토")):
            continue
        reason = str(row.get("게이트근거", "") or "")
        flag(row, "참고" if reason else "주의", "돈흐름 강세와 실행 방어 동시 존재",
             context + " / " + reason,
             "흐름은 후보 탐색, 게이트는 현재 실행 조건입니다. 방어 근거가 없거나 시점이 다르면 재계산하세요.")
    return flags
