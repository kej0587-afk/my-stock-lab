"""Generate a live-data example with an explicitly illustrative portfolio."""

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.report_context import collect_report_context
from stock_lab_core.report_evidence import KST


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/samples/market_report_20261020_v7.md")
    parser.add_argument("--as-of", help="Optional ISO timestamp; live bars later than this instant are excluded")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(KST)
    # These are demonstration positions, not an assertion about the user's account.
    holdings = [
        {"종목명": "나스닥100 코어(예시)", "티커": "379810.KS", "보유량": 1,
         "현재비중": 29, "목표비중": 27, "게이트상태": "방어우선"},
        {"종목명": "나스닥100 2배(예시)", "티커": "418660.KS", "보유량": 1,
         "현재비중": 6, "목표비중": 5, "게이트상태": "방어우선"},
        {"종목명": "메모리 2배(예시)", "티커": "RAM", "보유량": 1,
         "현재비중": 8, "목표비중": 5, "게이트상태": "방어우선"},
        {"종목명": "S&P500 코어(예시)", "티커": "379800.KS", "보유량": 1,
         "현재비중": 25, "목표비중": 27, "게이트상태": "조건대기"},
        {"종목명": "반도체 3배(예시)", "티커": "SOXL", "보유량": 1,
         "현재비중": 6, "목표비중": 5, "판정코드": "HARD_BLOCK_OVERWEIGHT"},
        {"종목명": "비트코인 2배(예시)", "티커": "BITX", "보유량": 1,
         "현재비중": 2, "목표비중": 3, "게이트상태": "조건대기"},
        {"종목명": "사이버보안(예시)", "티커": "CIBR", "보유량": 1, "현재비중": 6, "목표비중": 6},
        {"종목명": "빅테크(예시)", "티커": "MAGS", "보유량": 1, "현재비중": 3, "목표비중": 3},
        {"종목명": "한국 반도체 ETF(예시)", "티커": "0167A0.KS", "보유량": 1, "현재비중": 10, "목표비중": 10},
        {"종목명": "TDF(예시)", "티커": "0025N0.KS", "보유량": 1, "현재비중": 4.9, "목표비중": 5},
    ]
    context = collect_report_context(holdings, now=now, include_news=True)
    context.update(summary_date=context.get("sessions", {}).get("US", ""),
                   history_status="샘플 계좌: 개인 전일 비교 이력 저장 안 함")
    report = build_auto_market_memo(report_context=context, summary_rows=holdings, now=now)
    report = "# 생성 예시\n\n보유 종목·비중은 테스트 예시이며 실제 계좌가 아닙니다. 시세·경제지표·뉴스는 실행 시 수집된 자료이며 누락은 그대로 표시합니다.\n\n" + report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report saved: {args.output}")
    print(f"Market sessions: {context['sessions']}; session news: {len(context.get('session_news', []))}; live: {len(context.get('current_session_news', []))}; next: {len(context.get('next_session_news', []))}")
    for row in context["economic_releases"]:
        print(row["indicator"], row["basis"], row["period"], row["actual"], row["status"])


if __name__ == "__main__":
    main()
