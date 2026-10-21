"""Public October 21 close replay; no login, portfolio DB or private API keys."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.economic_releases import _retail
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.release_calendar import load_release_calendar
from stock_lab_core.today_news import fetch_session_market_news


def generate():
    now = datetime.fromisoformat("2026-10-21T20:15:00+09:00")
    days = {"KR": "2026-10-21", "US": "2026-10-20"}
    sessions = {market: {"date": day, "previous_date": "2026-10-20" if market == "KR" else "2026-10-19"}
                for market, day in days.items()}
    prices = {"^KS11": {"date": days["KR"], "return": .0329, "return_5d": -.0455},
              "^GSPC": {"date": days["US"], "return": .0028},
              "^IXIC": {"date": days["US"], "return": -.0002},
              "^DJI": {"date": days["US"], "return": .0102},
              "SOXX": {"date": days["US"], "return": -.0038},
              "DRAM": {"date": days["US"], "return": -.0126},
              "IGV": {"date": days["US"], "return": .0089}}
    sectors = [{"Ticker": ticker, "섹터": name, "구분": "미국 섹터", "기준일": days["US"],
                "1일수익률": daily, "3개월수익률": medium}
               for ticker, name, daily, medium in (("SOXX", "반도체", -.0038, -.0691),
                                                  ("DRAM", "메모리", -.0126, -.174),
                                                  ("IGV", "소프트웨어", .0089, .2012),
                                                  ("XLE", "에너지", .0025, .148),
                                                  ("XLU", "유틸리티", .0126, -.088))]
    held = [{"티커": ticker, "종목명": name, "보유량": 1, "게이트상태": "방어우선"}
            for ticker, name in (("SOXL", "반도체 노출 예시"), ("RAM", "메모리 노출 예시"))]
    news = fetch_session_market_news(sessions, now=now, sector_rows=sectors, held_exposures=held,
                                     per_category=5, use_cache=True)
    calendar = load_release_calendar(now=now)
    retail = _retail(now, "")
    context = {**news, "sessions": days, "news_sessions": sessions, "prices": prices,
               "sector_rows": sectors, "closed_flow_rows": sectors,
               "calendar_events": calendar["events"], "calendar_sources": calendar["sources"],
               "economic_releases": [retail]}
    notice = ("# 공개 시황 리플레이 · 2026-10-21\n\n"
              "지수·업종 수익률은 첨부본의 10/21 한국·10/20 미국 종가를 재생한 입력입니다. "
              "생성 시점 실시간 시세가 아닙니다. 뉴스·일정·소매판매는 공개 원자료를 조회했습니다. "
              "보유 2행은 노출 연결 검증용 예시이며 실제 계좌·수량·비중이 아닙니다.\n\n"
              "교차 확인: [한국 마감](https://www.yna.co.kr/view/AKR20261021126500008) · "
              "[미국 마감](https://apnews.com/article/0a5ea168499c6ae617c49e10bf48f9c6)\n\n")
    report = notice + build_auto_market_memo(report_context=context, summary_rows=held, now=now)
    audit = {"news": news, "retail": retail, "calendar": calendar, "replay_at": now.isoformat()}
    return report, audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/samples")
    args = parser.parse_args()
    report, audit = generate()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    target = args.output_dir / "market_report_quality_20261021.md"
    target.write_text(report, encoding="utf-8")
    (args.output_dir / "market_report_quality_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(target)
    print(json.dumps({"news_queries": audit["news"].get("news_retrieval"),
                      "retail_status": audit["retail"].get("status"), "retail_actual": audit["retail"].get("actual"),
                      "calendar_sources": [{"name": row["name"], "status": row["status"]} for row in audit["calendar"]["sources"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
