"""Runtime and refresh-status helpers for the Streamlit app."""

from stock_lab_core.formatters import clean_float


SPEED_CHECK_INFO_TEXT = "평소에는 현재가만 새로고침하면 충분합니다. 차트/기술, 뉴스/리포트, 재무점수는 필요할 때만 눌러야 덜 버벅입니다."

SPEED_CHECK_ROW_SPECS = (
    {
        "key": "latest_price_refresh_time",
        "구분": "현재가",
        "체감속도": "빠름",
        "캐시": "60초",
        "사용 위치": "보유자산 평가금액, 정밀관측소 현재가",
        "버튼": "전체 현재가 새로고침",
    },
    {
        "key": "chart_price_refresh_time",
        "구분": "차트/기술",
        "체감속도": "중간",
        "캐시": "5분",
        "사용 위치": "전광판, 정밀관측소 차트/기술점수, 단기 흐름",
        "버튼": "전체 차트/기술 새로고침",
    },
    {
        "key": "news_report_refresh_time",
        "구분": "뉴스/리포트",
        "체감속도": "중간",
        "캐시": "뉴스 10분 / 목표가 6시간",
        "사용 위치": "정밀관측소 뉴스, 증권사/애널리스트 링크",
        "버튼": "전체 뉴스/리포트 새로고침",
    },
    {
        "key": "fin_macro_refresh_time",
        "구분": "재무점수/매크로",
        "체감속도": "무거움",
        "캐시": "재무 6시간 / 매크로 5분",
        "사용 위치": "재무점수, 후보등급, 매크로 패널티",
        "버튼": "전체 재무점수/매크로 새로고침",
    },
)


def _count_label(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 0
    return f"{max(count, 0)}개"


def build_speed_check_rows(refresh_times=None):
    refresh_times = refresh_times or {}
    rows = []
    for spec in SPEED_CHECK_ROW_SPECS:
        row = {k: v for k, v in spec.items() if k != "key"}
        row["마지막 수동갱신"] = str(refresh_times.get(spec["key"], "-") or "-")
        rows.append(row)
    return rows


def build_speed_check_snapshot(refresh_times=None, holdings_count=0, watchlist_count=0, current_asset=0.0, generated_at="-"):
    return {
        "rows": build_speed_check_rows(refresh_times),
        "metrics": [
            {"label": "보유종목", "value": _count_label(holdings_count)},
            {"label": "전광판", "value": _count_label(watchlist_count)},
            {"label": "현금 포함 자산", "value": f"{clean_float(current_asset, 0.0):,.0f}원"},
            {"label": "화면 생성", "value": str(generated_at or "-")},
        ],
        "info": SPEED_CHECK_INFO_TEXT,
    }
