"""Labeled display fixture, optionally validated against bounded public RSS."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.today_news import fetch_session_market_news


def build_sample(*, live_news=False):
    fixture = runpy.run_path(str(ROOT / "tests/test_report_market_summary.py"))
    context, _ = fixture["case"]()
    context["prices"]["SOXX"].update({"return": .0173, "return_5d": -.08})
    now = fixture["NOW"]
    rows = [{"티커": "SOXX", "종목명": "반도체 ETF", "현재비중": 1, "보유량": 1,
             "게이트상태": "방어우선", "최종읽기": "방어우선: 추가매수 보류"},
            {"티커": "DDOG", "종목명": "Datadog", "현재비중": 0, "게이트상태": "방어우선",
             "최종읽기": "방어우선: 추가매수 보류", "저장사유": ["가격급락"]},
            {"티커": "030530.KS", "종목명": "원익홀딩스", "현재비중": 0, "게이트상태": "데이터확인",
             "최종읽기": "데이터확인: 판단 보류", "저장사유": ["개별 위험사유 없음"]}]
    old = deepcopy(rows)
    old[1]["저장사유"] = ["개별 위험사유 없음"]
    old[2].update(게이트상태="방어우선", 최종읽기="방어우선: 추가매수 보류")
    context.update(previous_summary=old, previous_date="2026-10-16/2026-10-19",
                   previous_run_summary=deepcopy(old), previous_run_date="2026-10-19/2026-10-20",
                   previous_run_at="2026-10-20T14:48:32+00:00", summary_date="2026-10-19/2026-10-20")
    context["sector_rows"] = [{"Ticker": ticker, "섹터": label, "구분": "미국 섹터", "기준일": "2026-10-19",
                               "1일수익률": daily, "3개월수익률": medium}
                              for ticker, label, daily, medium in (("SOXX", "반도체", .0173, -.077),
                                                                   ("XLE", "에너지", -.005, .10))]
    audit = None
    if live_news:
        news_sessions = {key: {"date": day, "previous_date": "2026-10-19" if key == "KR" else "2026-10-16"}
                         for key, day in context["sessions"].items()}
        current = {"US": {"date": "2026-10-20", "previous_date": "2026-10-19", "is_active": True}}
        audit = fetch_session_market_news(news_sessions, now=now, current_sessions=current,
                                          sector_rows=context["sector_rows"], held_exposures=rows,
                                          per_category=5, use_cache=True)
        context.update(audit, news_sessions=news_sessions, current_news_sessions=current)
    notice = ("# 시황 가독성 검증 예시\n\n가격·매크로·보유비중·판정 이력은 회귀 테스트 입력이며 실제 계좌/최신 시세가 아닙니다. "
              + ("뉴스만 공개 RSS를 조회했습니다. 날짜·출처 검증에서 탈락한 기사는 근거로 쓰지 않습니다."
                 if live_news else "기사도 회귀 테스트 입력이며 URL은 예시입니다.") + "\n\n")
    return notice + build_auto_market_memo(report_context=context, summary_rows=rows, now=now), audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-news", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/samples")
    args = parser.parse_args()
    report, audit = build_sample(live_news=args.live_news)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "market_report_readability_20261021.md"
    report_path.write_text(report, encoding="utf-8")
    print(report_path)
    if audit is not None:
        (args.output_dir / "market_news_readability_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({key: len(audit[key]) for key in ("session_news", "current_session_news", "next_session_news")}, ensure_ascii=False))
        print(json.dumps(audit.get("news_retrieval", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
