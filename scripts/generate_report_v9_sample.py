"""V9 acceptance sample: supplied returns, normalized paths, public CPI only."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import runpy
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.economic_bulletins import load_kr_cpi_bulletin
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.performance import PerformanceTrace, measure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/samples")
    parser.add_argument("--live-official-cpi", action="store_true")
    args = parser.parse_args()
    now = datetime.fromisoformat("2026-10-20T22:00:00+09:00")
    fixture = runpy.run_path(str(ROOT / "tests/test_report_v9_alignment.py"))
    frames, prices = fixture["cumulative_case"]()
    frames["379800.KS"] = pd.DataFrame({"Close": [100, 99.4, 99.4 * .9948]},
                                      index=pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-20"]))
    frames["^GSPC"] = pd.DataFrame({"Close": [100, 98.91, 98.91 * 1.0041]},
                                  index=pd.to_datetime(["2026-10-15", "2026-10-16", "2026-10-19"]))
    prices.update({"379800.KS": {"date": "2026-10-20", "return": -.0052},
                   "^GSPC": {"date": "2026-10-19", "previous_date": "2026-10-16", "return": .0041},
                   "^KS11": {"date": "2026-10-20", "previous_date": "2026-10-19", "return": -.0373},
                   "SOXX": {"date": "2026-10-19", "return": .0173},
                   "IGV": {"date": "2026-10-19", "return": .0158}})
    rows = [{"티커": ticker, "종목명": name, "보유여부": True, "현재비중": 1,
             "최종읽기": "기존 판정 유지(표시 검증용)", "게이트상태": "방어우선"}
            for ticker, name in (("379810.KS", "KODEX 미국나스닥100"), ("379800.KS", "KODEX 미국S&P500"),
                                 ("418660.KS", "TIGER 미국나스닥100레버리지(합성)"))]
    sectors = [{"Ticker": ticker, "섹터": name, "구분": "한국 섹터", "기준일": "2026-10-20",
                "1일수익률": value} for ticker, name, value in
               (("139250.KS", "에너지", -.0717), ("305540.KS", "2차전지", -.0572), ("396500.KS", "한국 반도체", -.0501))]
    for row in sectors:
        prices[row["Ticker"]] = {"date": row["기준일"], "return": row["1일수익률"]}
    original = args.source_report.read_text(encoding="utf-8-sig")
    news = []
    pattern = r"^\d+\. \[[^\]]+\]\s+(.*?) · (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) KST.*?\[([^\]]+) · 원문\]\((https?://[^)]+)\)"
    for match in re.finditer(pattern, original, re.M):
        title, published, publisher, link = match.groups()
        news.append({"title": title, "published_at": published.replace(" ", "T") + ":00+09:00",
                     "publisher": publisher, "link": link, "market": "KR"})
    releases = [
        {"indicator": "US_PPI", "period": "2026-09", "basis": "MoM", "unit": "%", "actual": 1.3,
         "previous": .5, "release_at": "2026-10-15T08:30:00-04:00", "status": "released", "source": "BLS",
         "source_url": "https://www.bls.gov/news.release/archives/ppi_10152026.htm"},
        {"indicator": "US_NONFARM_PAYROLLS", "period": "2026-09", "basis": "MoM", "unit": "thousand persons",
         "actual": 29, "previous": 133, "release_at": "2026-10-02T08:30:00-04:00", "status": "released", "source": "BLS",
         "source_url": "https://www.bls.gov/news.release/archives/empsit_10022026.htm"},
    ]
    cpi = load_kr_cpi_bulletin(now) if args.live_official_cpi else {
        "indicator": "KR_CPI", "basis": "YoY", "unit": "%", "actual": None,
        "source": "Bank of Korea ECOS", "status": "unavailable", "missing_reason": "public_fetch_not_requested"}
    releases.append(cpi)
    context = {"prices": prices, "price_frames": frames, "sessions": {"KR": "2026-10-20", "US": "2026-10-19"},
               "news_sessions": {"KR": {"date": "2026-10-20", "previous_date": "2026-10-19"},
                                 "US": {"date": "2026-10-19", "previous_date": "2026-10-16"}},
               "session_news": news, "sector_rows": sectors, "economic_releases": releases,
               "scenario_observations": {"latest_status": {key: "검증 예시에서 실시간 시세 미수집" for key in ("NQ=F", "ES=F")}}}
    with PerformanceTrace(scope="offline_report_v9_render_only") as trace:
        with measure("report_render", "build_auto_market_memo"):
            report = build_auto_market_memo(report_context=context, summary_rows=rows, now=now)
    preface = ("# 9차 표시·계산 검증 샘플\n\n"
               "첨부 10/20 22:00 리포트의 등락과 앞서 제공된 10/19 등락으로 기준가 100 경로를 재구성했습니다. "
               "실제 시세를 새로 조회한 계좌 리포트가 아닙니다. 보유 비중은 검증용 각 1%로 실제 계좌 손익을 계산하지 않습니다. "
               "한국 CPI만 공개 ECOS 원지수를 실제 조회해 계산합니다(--live-official-cpi 사용 시). "
               "미국 선물은 이 예시에서 조회하지 않았으므로 미수집 사유를 표시합니다. "
               "아래 렌더 시간은 Cloud 오늘점검 전체 성능과 비교할 수 없습니다.\n\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "market_report_v9_20261020.md"
    path.write_text(preface + report, encoding="utf-8")
    for name, value in (("report_v9_cpi_public.json", cpi), ("report_v9_render_only.json", dict(trace.report(), is_full_today_queue_measurement=False))):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    story = report.split("## 오늘의 시장 스토리", 1)[1].split("## 경제지표", 1)[0]
    acceptance = {"cumulative_minus_191_minus_132": "실제 -1.91%" in report and "누적 -1.32%" in report,
                  "sector_excess_column": "시장 대비 초과" in report,
                  "cpi_previous_31": cpi.get("previous") == 3.1,
                  "old_ppi_payrolls_absent_from_story": "미국 PPI" not in story and "비농업고용" not in story}
    (args.output_dir / "report_v9_acceptance.json").write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    print(json.dumps(acceptance, ensure_ascii=False))


if __name__ == "__main__":
    main()
