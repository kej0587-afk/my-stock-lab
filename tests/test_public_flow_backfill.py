"""Offline daily-feed contracts; no fabricated missing dates/groups or gates."""

from copy import deepcopy
from datetime import datetime
import json
import socket

import pytest
import requests

from stock_lab_core import public_flow_backfill as flow
from stock_lab_core.public_market_flow_history import public_flow_history_lines
from stock_lab_core.report_market_summary import korean_flow_tables

NOW = datetime.fromisoformat("2026-11-06T11:00:00+09:00")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("unexpected network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    flow.load_public_flow_backfill.clear()
    yield
    flow.load_public_flow_backfill.clear()


def provider_row(day, foreign=100_000_000, institution=-100_000_000):
    codes = dict.fromkeys(sum(flow.GROUPS.values(), ()), 0)
    codes.update({"9000": foreign, "1000": institution})
    return {"bizdate": day.replace("-", ""), "time": "", "netAmounts": [
        {"investorGubun": code, "diffValue": str(value),
         "buyPrice": str(max(value, 0)), "sellPrice": str(max(-value, 0))}
        for code, value in codes.items()]}


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self.body = json.dumps(payload).encode()
        self.closed = False

    def iter_content(self, chunk_size=1):
        yield self.body

    def close(self):
        self.closed = True


@pytest.fixture
def days():
    return flow.completed_sessions(NOW.isoformat())[-21:]


@pytest.fixture
def payload(days):
    return {"content": [provider_row(day, -100_000_000 if i == 0 else 100_000_000,
                                    100_000_000 if i == 0 else -100_000_000)
                        for i, day in enumerate(days)]}


@pytest.fixture
def backfill(payload, days):
    return flow.read_public_flow_backfill(days[-1], request=lambda *a, **kw: Response(payload), now=lambda: NOW)


def summarize(backfill):
    return flow.summarize_backfill(backfill, checked_at=NOW.isoformat())[0]


def test_signed_totals_runs_completed_date_and_no_mutation(backfill):
    before = deepcopy(backfill)
    rows = summarize(backfill)
    assert len(rows) == 4
    assert (rows[0]["sum_5"], rows[0]["sum_20"], rows[0]["streak_days"], rows[0]["streak_direction"]) == (5, 20, 20, "buy")
    assert (rows[1]["sum_5"], rows[1]["sum_20"], rows[1]["streak_days"], rows[1]["streak_direction"]) == (-5, -20, 20, "sell")
    assert all(row["asof"] == "2026-11-05" for row in rows)
    assert backfill == before


@pytest.mark.parametrize("at,end", [
    ("2026-11-06T15:49:59+09:00", "2026-11-05"),
    ("2026-11-06T15:50:00+09:00", "2026-11-06"),
    ("2026-11-08T12:00:00+09:00", "2026-11-06"),
    ("2026-10-09T12:00:00+09:00", "2026-10-08"),
])
def test_exchange_calendar_weekend_holiday_and_close_buffer(at, end):
    assert flow.completed_sessions(at)[-1] == end


def test_provider_ignores_cutoff_and_returns_intraday_but_we_exclude_it(payload, days):
    payload["content"] += [provider_row("2026-11-06", 9_000_000_000), provider_row("2026-11-09")]
    before = deepcopy(payload)
    rows, reason = flow.parse_daily_history(payload, end_date=days[-1])
    assert "2026-11-06" not in rows and "2026-11-09" not in rows
    assert not reason and payload == before


@pytest.mark.parametrize("index,five", [(-2, None), (-10, 5)])
def test_missing_date_is_not_skipped_or_replaced_by_zero(backfill, days, index, five):
    del backfill["markets"]["KOSPI"]["rows"][days[index]]
    row = summarize(backfill)[0]
    assert row["sum_5"] == five and row["sum_20"] is None and row["streak_days"] is None
    assert days[index] in row["missing_dates"]["20"]
    assert summarize(backfill)[2]["sum_20"] == 20


def test_zero_ends_streak_and_unknown_start_not_exact_length(backfill, days):
    rows = backfill["markets"]["KOSPI"]["rows"]
    del rows[days[0]]
    assert summarize(backfill)[0]["streak_days"] is None
    rows[days[-3]]["foreign"] = 0
    assert summarize(backfill)[0]["streak_days"] == 2
    rows[days[-1]]["foreign"] = 0
    assert summarize(backfill)[0]["streak_days"] == 0


@pytest.mark.parametrize("kind", ["missing", "mismatch", "bool", "duplicate_code", "negative_buy"])
def test_invalid_component_does_not_become_zero(kind):
    row = provider_row("2026-11-05")
    target = next(x for x in row["netAmounts"] if x["investorGubun"] == "9001")
    if kind == "missing": row["netAmounts"].remove(target)
    elif kind == "mismatch": target["diffValue"] = "1"
    elif kind == "bool": target["diffValue"] = False
    elif kind == "duplicate_code": row["netAmounts"].append(deepcopy(target))
    else: target.update(buyPrice="-1", sellPrice="-1")
    parsed, _ = flow.parse_daily_history({"content": [row]}, end_date="2026-11-05")
    assert "foreign" not in parsed["2026-11-05"]


def test_other_foreign_and_all_institution_subgroups_included_once():
    row = provider_row("2026-11-05", 0, 0)
    for item in row["netAmounts"]:
        item.update(diffValue="100000000", buyPrice="200000000", sellPrice="100000000")
    parsed, _ = flow.parse_daily_history({"content": [row]}, end_date="2026-11-05")
    assert parsed["2026-11-05"] == {"foreign": 200_000_000, "institution": 800_000_000}
    row["netAmounts"] = [x for x in row["netAmounts"] if x["investorGubun"] != "3100"]
    parsed, _ = flow.parse_daily_history({"content": [row]}, end_date="2026-11-05")
    assert "institution" not in parsed["2026-11-05"]


def test_duplicate_dates_invalid_and_intraday_rows_not_history(payload, days):
    payload["content"] += [deepcopy(payload["content"][-1])] * 2
    payload["content"][0]["time"] = "110000"
    rows, _ = flow.parse_daily_history(payload, end_date=days[-1])
    assert days[0] not in rows and days[-1] not in rows


@pytest.mark.parametrize("kind", ["wrong_scope", "stale", "future", "oversized", "http_error"])
def test_cached_invalid_market_does_not_contaminate_other_market(backfill, kind):
    group = backfill["markets"]["KOSPI"]
    if kind == "wrong_scope": group["request_params"]["tradeType"] = "NXT"
    elif kind == "stale": group["fetched_at"] = "2026-11-06T10:48:59+09:00"
    elif kind == "future": group["fetched_at"] = "2026-11-06T11:01:00+09:00"
    elif kind == "oversized": group["rows"] = {str(i): {} for i in range(61)}
    else: group["status"] = "http_error"
    rows = summarize(backfill)
    assert rows[0]["sum_5"] is None and rows[0]["sum_20"] is None
    assert rows[2]["sum_20"] == 20


def test_transport_bounded_and_partial_failure_visible(payload, days):
    calls, responses = [], []
    def get(url, **kw):
        calls.append((url, kw))
        if kw["params"]["marketType"] == "KOSDAQ": raise requests.Timeout()
        result = Response(payload); responses.append(result); return result
    data = flow.read_public_flow_backfill(days[-1], request=get, now=lambda: NOW)
    assert not data["ok"] and len(calls) == 2 and all(r.closed for r in responses)
    assert all(c[0] == flow.DAILY_URL and c[1]["timeout"] == (3, 6) and not c[1]["allow_redirects"] for c in calls)
    assert summarize(data)[0]["sum_20"] == 20 and summarize(data)[2]["sum_20"] is None
    assert "시간 초과" in "\n".join(flow.backfill_lines(data, checked_at=NOW.isoformat()))


def test_report_shows_history_even_when_current_intraday_feed_missing(backfill):
    context = {"public_flow_backfill": backfill, "market_evidence_checked_at": NOW.isoformat()}
    before = deepcopy(context)
    lines = korean_flow_tables(context, {"date": "2026-11-06"})
    assert "KOSPI | 외국인 | 순매수 20거래일 | +5.00 | +20.00 | 2026-11-05" in lines
    assert "완료 거래일 기준" in "\n".join(lines)
    assert lines == public_flow_history_lines(context, session_date="2026-11-06") and context == before


def test_calendar_unavailable_never_uses_weekday_approximation(monkeypatch):
    def fail(*args, **kwargs): raise ValueError("calendar unavailable")
    monkeypatch.setattr(flow, "_exchange_schedule", fail)
    assert "달력 미확보" in flow.collect_public_flow_backfill()["reason"]
    assert "달력 미확보" in "\n".join(flow.backfill_lines({}, checked_at=NOW.isoformat()))


def test_cache_same_completed_date_reuses_collection(monkeypatch, backfill):
    calls = []
    def read(day): calls.append(day); return deepcopy(backfill)
    monkeypatch.setattr(flow, "read_public_flow_backfill", read)
    first = flow.load_public_flow_backfill("2026-11-05")
    first["markets"].clear()
    assert flow.load_public_flow_backfill("2026-11-05")["markets"]
    flow.load_public_flow_backfill("2026-11-06")
    assert calls == ["2026-11-05", "2026-11-06"]


def test_backfill_is_wired_only_in_non_demo_report_collection():
    import ast
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8-sig")
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "_collect_today_report_context")
    branch = next(n for n in fn.body if isinstance(n, ast.If) and ast.unparse(n.test) == "not IS_PUBLIC_DEMO")
    text = ast.unparse(branch)
    assert "context['public_flow_backfill'] = collect_public_flow_backfill()" in text
    assert text.index("collect_public_flow_backfill()") < text.index("load_public_market_evidence(")
