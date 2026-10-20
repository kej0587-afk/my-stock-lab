"""Compare an exported report and timings without loading the app or accounts."""

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stock_lab_core.performance import queue_measurement_details


def audit(report_text, measurement):
    identity = re.search(r"점검 측정ID\s+([0-9a-f]{32})", report_text)
    revision = re.search(r"기준커밋\s+([0-9a-f]+)", report_text)
    functions = {row["name"]: row for row in measurement.get("functions", [])}
    actual_id = measurement.get("measurement_id")
    expected_id = identity[1] if identity else None
    return {
        "report_base_commit": revision[1] if revision else None,
        "report_measurement_id": expected_id, "uploaded_measurement_id": actual_id,
        "measurement_ids_match": bool(expected_id and expected_id == actual_id),
        **queue_measurement_details(measurement),
        "elapsed_seconds": measurement.get("elapsed_seconds"),
        "analyst": functions.get("get_analyst_snapshot"),
        "kr_batch_wait": functions.get("kr_quote_fallback_wait"),
        "naver_single_realtime": functions.get("_fetch_naver_realtime_quote"),
        "transport_events": measurement.get("transport_events"),
        "cold_cache_status": measurement.get("cache_state", "미기록"),
        "conclusion": "동일 완료 계산의 측정값" if expected_id and expected_id == actual_id and queue_measurement_details(measurement)["is_full_today_queue_measurement"]
                      else "측정ID/계산 구간 불일치: 전체 계산의 전후 성능 비교 불가",
        "notes": ["함수 호출 수는 캐시 적중을 포함할 수 있으며 HTTP 요청 수가 아님",
                  "kr_quote_fallback_wait는 병렬 배치 전체 대기시간이며 개별 요청 타임아웃 시간이 아님",
                  "과거 파일에 transport_events가 없으면 타임아웃 발생 여부는 확인 불가"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--performance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.report.read_text(encoding="utf-8-sig"), json.loads(args.performance.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
