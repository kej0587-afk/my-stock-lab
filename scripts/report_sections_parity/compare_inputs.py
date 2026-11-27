"""Call report_sections on fixed synthetic inputs and print a hash + full repr per input."""
import hashlib, sys
from datetime import datetime
from stock_lab_core.report_evidence import report_sections

releases = [
    dict(indicator="US_CPI", period="2026-10", basis="MoM", unit="%", actual=0.3, previous=0.2, forecast=0.2,
         forecast_basis="YoY", forecast_source="TE", forecast_source_url="https://x", forecast_period="2026-10",
         forecast_verified_at="2026-11-13", actual_minus_forecast=0.1, status="released", release_at="2026-11-13T22:30:00+09:00",
         verification="검산 통과", source="BLS", source_url="https://bls"),
    dict(indicator="US_FED_TARGET_UPPER", period="2026-11-20", basis="level", unit="%", actual=4.0, previous=4.25,
         status="stale", last_success_at="2026-11-20T09:00:00+09:00", release_at="2026-11-20", release_precision="date",
         release_metadata_mode="verified_snapshot", release_source="FOMC", release_source_url="https://fed"),
    dict(indicator="KR_EXPORTS", period="2026-10", basis="YoY", unit="%", actual=12.5, previous=8.0, status="released",
         raw_actual=65000.0, raw_year_ago=57777, raw_year_ago_period="2025-10", raw_unit="백만달러",
         release_at="2026-11-01T09:00:00+09:00", bulletin_request_metadata={"bulletin": {"origin": "live", "http_status": 200},
                                                                         "motir": {"attempted": True, "exception_type": "Timeout", "failure_stage": "connect"}},
         last_success_at="2026-11-01T09:00:00+09:00"),
    dict(indicator="KR_EXPORTS", period="2026-11", basis="YoY", unit="%", actual=5.0, status="released",
         data_vintage="preliminary_bulletin", raw_actual=21000, raw_unit="백만달러"),
    dict(indicator="US_RETAIL_SALES", period="2026-10", basis="MoM", unit="%", actual=None, status="failed",
         api_key_configured=False, request_metadata={"http_status": 500, "response_status": "error",
         "parameters": {"get": "cell_value", "secret": "x", "time": "2026"}, "response_summary": {"rows": 0}, "rejected_rows": {"bad": 2}}),
    dict(indicator="US_NONFARM_PAYROLLS", period="2026-10", basis="level", unit="thousand persons", actual=150, previous=120,
         previous_unit="thousand persons", status="verified_snapshot", verified_at="2026-11-07", expires_at="2026-12-07",
         history=[100, 110, 120, 150]),
    dict(indicator="US_UNEMPLOYMENT", period="2026-11", basis="level", unit="%", actual=None, status="scheduled"),
    dict(indicator="KR_CPI", period="2026-10", basis="YoY", unit="%", actual=None, status="failed",
         official_comparison_unavailable=True, api_key_configured=True),
]
news = [
    dict(title="코스피 반등 성공, 외국인 순매수 전환", market="KR", session_date="2026-11-26", source="연합뉴스",
         published_at="2026-11-26T16:00:00+09:00", url="https://a/1", news_bucket="current_session_news"),
    dict(title="뉴욕증시, 엔비디아 실적 앞두고 반도체 약세", market="US", session_date="2026-11-25", source="연합뉴스",
         published_at="2026-11-26T07:00:00+09:00", url="https://a/2"),
    dict(title="코스피, 전날 급락 뒤 3거래일 만에 반등", market="KR", session_date="2026-11-26", source="뉴스1",
         published_at="2026-11-26T15:40:00+09:00", url="https://a/3"),
]
prices = {t: dict(date=d, **{"return": r, "return_5d": r * 2, "previous_return": -r, "down_days": 1})
          for t, d, r in (("^KS11", "2026-11-26", .012), ("^KQ11", "2026-11-26", -.004), ("^GSPC", "2026-11-25", .003),
                          ("^IXIC", "2026-11-25", .006), ("^DJI", "2026-11-25", -.001), ("SOXX", "2026-11-25", .021),
                          ("IGV", "2026-11-25", -.011), ("SOXL", "2026-11-25", .062))}
sector_rows = [
    {"Ticker": t, "섹터": n, "구분": g, "1일수익률": r, "기준일": d, "3M수익률": (r or 0) * 10}
    for t, n, g, r, d in (("XLK", "기술", "미국 섹터", .011, "2026-11-25"), ("XLE", "에너지", "미국 섹터", -.018, "2026-11-25"),
                          ("SOXX", "반도체", "미국 섹터", .021, "2026-11-25"), ("SMH", "반도체2", "미국 섹터", .02, "2026-11-25"),
                          ("SOXL", "반도체 3배", "미국 섹터", .062, "2026-11-25"), ("091160.KS", "KODEX 반도체", "한국 섹터", .061, "2026-11-26"),
                          ("XLU", "유틸리티", "미국 섹터", None, "2026-11-25"))]
summary = [
    {"티커": "SOXL", "보유": True, "보유수량": 3, "평단": 30, "현재가": 33, "Adj점수": 60},
    {"티커": "AAPL", "보유": False, "Adj점수": 80, "판정": "관망", "등급": "A"},
    {"티커": "MSFT", "보유": False, "Adj점수": 70, "판정": "보류", "등급": "S"},
    {"티커": "NVDA", "보유": False, "Adj점수": 90},
    {"티커": "AMD", "보유": False, "Adj점수": None},
]
base_ctx = dict(prices=prices, sessions={"KR": "2026-11-26", "US": "2026-11-25"}, economic_releases=releases,
                sector_rows=sector_rows, kr_is_trading_day=True,
                consensus_diagnostics={"attached_count": 1, "attached_rows": [dict(indicator="US_CPI", period="2026-10", basis="MoM",
                    forecast_source="TE", forecast_period="2026-10", release_at="2026-11-13")], "verified_survey_coverage": "2026-09",
                    "verified_survey_used": False, "verified_survey_count": 0, "reason": "api_key_required"},
                intraday_prices={"XLK": {"return": .004, "as_of": "2026-11-26T23:50:00+09:00", "date": "2026-11-26"}})
cases = {
    "closed_1810": (base_ctx, datetime(2026, 11, 26, 18, 10)),
    "us_intraday_2350": (base_ctx, datetime(2026, 11, 26, 23, 50)),
    "kr_intraday_1030": (base_ctx, datetime(2026, 11, 27, 10, 30)),
    "empty_0630": ({}, datetime(2026, 11, 27, 6, 30)),
    "no_releases_1600": (dict(base_ctx, economic_releases=[], sector_rows=[]), datetime(2026, 11, 26, 16, 0)),
}
for name, (ctx, now) in cases.items():
    for n, s in ((news, summary), ([], [])):
        try:
            out = repr(report_sections(context=dict(ctx), news=[dict(r) for r in n], flow_rows=[], event_rows=[],
                                       summary_rows=[dict(r) for r in s], now=now))
        except Exception as exc:  # record failures too: they must match
            out = "EXC " + type(exc).__name__ + ": " + str(exc)
        print(name, len(n), hashlib.sha256(out.encode()).hexdigest()[:16], len(out))
        with open(f"{sys.argv[1]}/{name}_{len(n)}.txt", "w") as f:
            f.write(out)
