"""Reproducible offline after-close report. No live quotes or account access."""

from pathlib import Path
import argparse
import json
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.performance import PerformanceTrace, measure
from stock_lab_core.report_build import get_report_build_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/samples")
    args = parser.parse_args()
    fixture = runpy.run_path(str(ROOT / "tests/test_report_close_session.py"))
    context, rows, flow = fixture["close_case"]()
    with PerformanceTrace(scope="offline_report_render_fixture") as trace:
        with measure("report_render", "build_auto_market_memo"):
            report = build_auto_market_memo(report_context=context, summary_rows=rows,
                                            flow_snapshot={"flow_df": flow}, now=fixture["NOW"])
    preface = ("# 마감 후 표시 검증 예시\n\n"
               "제공된 10/19 16:18 리포트의 가격·제목을 사용했지만, 개별 보유 비중은 가상입니다. "
               "아래 계좌 합계는 실제 사용자 손익이 아닙니다. 한국 반도체 ETF 일간 +0.10%는 화면 검증용입니다. "
               "수집 오류 문구도 검증용으로 주입했으며 현재 API 상태를 나타내지 않습니다.\n\n"
               "실제 첨부 보고서의 집계값으로 표시 선택을 별도 검증했습니다: 최신 종가 -3.00%p, "
               "연결 99.9%를 채택하고 장전 대체 합산 -2.29%p, 연결 24.4%는 헤드라인에서 제외합니다. "
               "개별 비중이 없어 실제 계좌 합계 자체를 재계산한 것은 아닙니다.\n\n"
               "다음 발표일 검증 출처: [BLS 2026년 11월 일정](https://www.bls.gov/schedule/2026/11_sched.htm). "
               "FRED 날짜 전용 응답을 모사한 예시라 발표 시각은 채우지 않았습니다.\n\n")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "market_report_20261019_close.md"
    path.write_text(preface + report, encoding="utf-8")
    measurement = dict(trace.report(), build=get_report_build_info(__file__),
                       is_full_today_queue_measurement=False,
                       input_kind="synthetic_fixture_not_live_account",
                       note="보고서 표시만 새로 측정. 전체 오늘점검/API/실제 계좌 성능과 비교할 수 없음.")
    performance_path = args.output_dir / "report_render_performance.json"
    performance_path.write_text(json.dumps(measurement, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)
    print(performance_path)


if __name__ == "__main__":
    main()
