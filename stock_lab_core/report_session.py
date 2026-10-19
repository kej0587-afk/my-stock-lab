"""Report time-of-day policy, independent of execution/market-risk gates."""

from zoneinfo import ZoneInfo
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

KST = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")
MODE_LABELS = {"preopen": "개장 전", "intraday": "장중", "closed": "마감 후", "holiday": "휴장일"}


def kst_now(now):
    return now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)


def market_session_states(now, sessions=None):
    """One reporting clock, independent exchange-local regular sessions."""
    from stock_lab_core.prices import _us_equity_market_holidays

    now = kst_now(now)
    result = {}
    for market, zone, opening, closing in (("KR", KST, 540, 930), ("US", NEW_YORK, 570, 960)):
        local = now.astimezone(zone)
        minute = local.hour * 60 + local.minute
        holiday = local.weekday() >= 5 or (market == "US" and local.date() in _us_equity_market_holidays(local.year))
        phase = "holiday" if holiday else "preopen" if minute < opening else "intraday" if minute < closing else "closed"
        label = MODE_LABELS[phase]
        if market == "KR" and phase == "preopen" and (sessions or {}).get("KR"):
            label = "마감 후·다음 개장 전"
        result[market] = {"phase": phase, "label": label, "last_close": (sessions or {}).get(market, ""),
                          "active_date": local.date().isoformat() if phase == "intraday" else "",
                          "local_date": local.date().isoformat(), "as_of": now.isoformat(),
                          "calendar_note": "정규장 시간 기준; 특별 휴장·단축장 별도 확인"}
    return result


def report_mode(now, *, is_trading_day=None):
    local = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    # Missing quotes alone cannot establish a holiday.
    if local.weekday() >= 5 or is_trading_day is False:
        return "holiday"
    minute = local.hour * 60 + local.minute
    return "preopen" if minute < 540 else "intraday" if minute < 930 else "closed"


def next_check(mode):
    return {
        "closed": "오늘 밤 미국장 종가·반도체 흐름과 다음 한국 거래일의 실제 반영을 확인합니다. 오늘의 시나리오 비교는 내일 예측이 아닙니다.",
        "intraday": "오늘 한국장 마감과 오늘 밤 미국장 흐름을 확인합니다. 장중 등락은 종가와 달라질 수 있습니다.",
        "holiday": "다음 미국·한국 거래일의 개장과 최신 종가 반영을 확인합니다. 휴장 중 수치를 오늘 등락으로 해석하지 않습니다.",
        "preopen": "한국 개장 후 실제 등락과 장전 시나리오의 차이를 확인합니다.",
    }[mode]
