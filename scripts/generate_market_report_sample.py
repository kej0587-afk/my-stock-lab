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
from stock_lab_core.today_news import fetch_today_market_story_news
from stock_lab_core.market_board import build_market_snapshot, load_market_frames
from stock_lab_core.prices import load_price_frames_batch
from stock_lab_core.report_evidence import closed_daily_frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/samples/market_report_20261018.md")
    args = parser.parse_args()
    now = datetime.now(KST)
    # These are demonstration positions, not an assertion about the user's account.
    holdings = [
        {"종목명": "S&P500 코어(예시)", "티커": "379800.KS", "보유량": 1,
         "현재비중": 25, "목표비중": 27, "게이트상태": "조건대기"},
        {"종목명": "반도체 3배(예시)", "티커": "SOXL", "보유량": 1,
         "현재비중": 6, "목표비중": 5, "판정코드": "HARD_BLOCK_OVERWEIGHT"},
        {"종목명": "비트코인 2배(예시)", "티커": "BITX", "보유량": 1,
         "현재비중": 2, "목표비중": 3, "게이트상태": "조건대기"},
    ]
    context = collect_report_context(holdings, now=now)
    news = fetch_today_market_story_news(("반도체·AI", "외환/금리", "매크로/중국", "에너지/해운", "실적/대장주", "정책/규제"), per_category=3, days=2)
    sectors = build_market_snapshot("US", load_market_frames("US"), "1D")
    flow = [{"구분": "미국 섹터", "섹터": row.sector, "Ticker": row.ticker,
             "1일수익률": row.return_pct / 100} for row in sectors.itertuples() if row.kind == "basket"]
    macro = {}
    symbols = {"10Y 금리": "^TNX", "유가": "CL=F", "환율": "USDKRW=X", "VIX": "^VIX", "MOVE": "^MOVE"}
    frames = load_price_frames_batch(tuple(symbols.values()), "1y")
    for name, ticker in symbols.items():
        frame = closed_daily_frame(frames.get(ticker), ticker, now)
        if len(frame) >= 22:
            close = frame["Close"]
            macro[name] = {"val": float(close.iloc[-1]), "chg": float(close.iloc[-1] / close.iloc[-22] - 1) * 100,
                           "as_of": str(frame.index[-1].date()), "source": "Yahoo Finance daily"}
    report = build_auto_market_memo(report_context=context, summary_rows=holdings, market_news_rows=news,
                                    flow_snapshot={"flow_df": flow}, macro_data=macro, now=now)
    report = "# 생성 예시\n\n보유 종목·비중은 테스트 예시이며 실제 계좌가 아닙니다. 시세·경제지표·뉴스는 실행 시 수집된 자료이며 누락은 그대로 표시합니다.\n\n" + report
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report saved: {args.output}")
    print(f"Market sessions: {context['sessions']}; news fetched: {len(news)}")
    for row in context["economic_releases"]:
        print(row["indicator"], row["basis"], row["period"], row["actual"], row["status"])


if __name__ == "__main__":
    main()
