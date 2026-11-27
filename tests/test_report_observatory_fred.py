"""2026-11-27 priority 5: report reuses the observatory's FRED items without estimating values."""

import pandas as pd

from stock_lab_core import report_dashboard as rd
from stock_lab_core.report_reading import _observatory_value_symbols

NOW = pd.Timestamp("2026-11-27 18:30", tz="Asia/Seoul")


def loader(symbol, years, as_of):
    assert years == 1 and as_of == "2026-11-27"  # observatory default cache key
    if symbol == "WTREGEN":
        return pd.Series(dtype=float), "공급처 HTTP 503 · 값 대체 안 함"
    if symbol == "M2SL":
        raise TimeoutError("slow")
    idx = pd.to_datetime(["2026-11-12", "2026-11-19"])
    return pd.Series([1.0, 1.5], index=idx), ""


def test_reuse_keeps_dates_and_failures_without_filling():
    rows, meta = rd.observatory_fred_observations(NOW, loader=loader)
    assert set(rows) == set(rd.OBSERVATORY_FRED)
    assert rows["STLFSI4"]["값"].startswith("1.50") and rows["STLFSI4"]["관측일"] == "2026-11-19"
    assert rows["WTREGEN"]["값"] == "미연결" and "HTTP 503" in rows["WTREGEN"]["상태"]
    assert rows["M2SL"]["값"] == "미연결" and rows["M2SL"]["상태"] == "TimeoutError"
    assert meta["requested"] == 8 and meta["connected"] == 6 and meta["seconds"] >= 0


def test_table_lines_are_counted_by_the_coverage_status():
    rows, meta = rd.observatory_fred_observations(NOW, loader=loader)
    lines = rd.observatory_fred_table_lines({"observatory_fred": rows, "observatory_fred_meta": meta})
    text = "\n".join(lines)
    assert "금융 스트레스(STLFSI4) | 1.50" in text and "재무부 TGA(WTREGEN) | 미연결" in text
    assert "연결 6/8" in text and "0으로 채우지 않습니다" in text
    shown = _observatory_value_symbols(text)
    assert "STLFSI4" in shown and "WTREGEN" not in shown and "M2SL" not in shown


def test_absent_context_adds_nothing():
    assert rd.observatory_fred_table_lines({}) == []
