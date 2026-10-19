"""Offline acceptance example: uploaded prices/headline, fictional account weights."""

from datetime import datetime
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.economic_bulletins import apply_official_bulletins
from stock_lab_core.market_memo import build_auto_market_memo


def main():
    now = datetime.fromisoformat("2026-10-19T10:47:00+09:00")
    context, rows = runpy.run_path(str(ROOT / "tests/test_report_oct19.py"))["review_case"]()
    for ticker, name, value in (("XLK", "기술", -.0302), ("IGV", "소프트웨어", -.048)):
        context["prices"][ticker] = {"date": "2026-10-16", "return": value}
        context["sector_rows"].append({"Ticker": ticker, "섹터": name, "구분": "미국 섹터", "기준일": "2026-10-16", "1일수익률": value})
    context["prices"]["^KS11"].update(previous_return=-.0757, return_5d=-.1446, down_days=0)
    context["intraday_prices"] = {"^KS11": {"date": "2026-10-19", "return": -.0002, "retrieved_at": now.isoformat()}}
    context["session_news"] = [{
        "title": "[굿모닝 증시]美 AI주 중심 약세 마감…韓 변동성 장세 예상",
        "publisher": "아시아경제", "market": "KR", "published_at": "2026-10-19T08:13:00+09:00",
        "link": "https://news.google.com/rss/articles/CBMiYkFVX3lxTFB0bno2U3kycE9lRGtZMjlraUhpXzV3eHl5N3U5WmVFdUU2VWVDTHRzQUg5YlFWSEphU1RfRi1hZVBSZndXMi1kbDN0VW41aHRKNTBSZzdCaExxVWtYcHZDbTFn?oc=5",
    }]
    context["economic_releases"] = apply_official_bulletins([
        {"indicator": key, "actual": None, "basis": "YoY", "status": "unavailable", "missing_reason": "request_failed:ReadTimeout"}
        for key in ("KR_CPI", "KR_EXPORTS")], now)
    report = build_auto_market_memo(report_context=context, summary_rows=rows, now=now)
    preface = ("# 검증용 시황 예시\n\n가격·기사 제목은 제공받은 10/19 리포트 기준입니다. "
               "보유 종목 비중(SOXL 10%, 나스닥 ETF 30%)은 가상이며, 합계는 사용자 실제 계좌 손익이 아닙니다. "
               "한국 통계는 10/19 공식 문서 재확인값입니다. 실시간 API 성공을 의미하지 않습니다.\n\n")
    path = ROOT / "docs/samples/market_report_20261019_recovery.md"
    path.write_text(preface + report, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
