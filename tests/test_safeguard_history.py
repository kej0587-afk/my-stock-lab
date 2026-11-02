from copy import deepcopy
from datetime import datetime

import pandas as pd

from stock_lab_core.market_safeguards import safeguard_events
from stock_lab_core.report_history import update_report_history
from stock_lab_core.safeguard_history import merge_safeguard_history, observed_kr_sessions


NOW = datetime.fromisoformat("2026-11-02T16:00:00+09:00")
DAYS = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"]
NEWS = [{"title": "코스피 매도 사이드카 발동", "published_at": "2026-10-30T10:00:00+09:00",
         "link": "https://news.example/sidecar", "publisher": "Example"}]


class MemoryStore:
    def __init__(self):
        self.database = {}

    def load_sessions(self, dates, *, owner_scope):
        return {us + "/" + kr: deepcopy(row) for (owner, us, kr), row in self.database.items()
                if owner == owner_scope and us <= dates["US"] and kr <= dates["KR"]}

    def upsert_session(self, row, *, owner_scope):
        self.database[(owner_scope, row["dates"]["US"], row["dates"]["KR"])] = deepcopy(row)


def test_weekend_retention_and_fifth_session_expiry():
    events = safeguard_events(NEWS, NOW)
    before = deepcopy(events)
    kept = merge_safeguard_history([], events, DAYS, NOW)
    assert len(kept) == 1 and kept[0]["date"] == "2026-10-30"
    assert kept[0]["retained_from_history"] and kept[0]["status"] == "reported"
    assert merge_safeguard_history([], events, ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
                                   NOW.replace(day=6)) == []
    assert merge_safeguard_history([], events, [], NOW) == []
    assert events == before


def test_dedup_and_observed_sessions_exclude_missing_values():
    events = safeguard_events(NEWS, NOW)
    kept = merge_safeguard_history(events, events, DAYS, NOW)
    assert len(kept) == 1 and not kept[0]["retained_from_history"]
    frame = pd.DataFrame({"Close": [100, float("nan"), 101]},
                         index=pd.to_datetime(["2026-10-30", "2026-10-31", "2026-11-02"]))
    assert observed_kr_sessions({"price_frames": {"^KS11": frame}}) == ["2026-10-30", "2026-11-02"]


def test_remote_history_retains_after_redeploy_without_local_files(tmp_path):
    client = MemoryStore()
    rows = [{"티커": "MSFT", "최종읽기": "대기"}]
    common = dict(owner_scope="alice", store=client)
    update_report_history(rows, {"KR": "2026-10-30", "US": "2026-10-29"}, path=tmp_path / "first.json",
                          generated_at="2026-10-30T16:00:00+09:00", safeguard_news=NEWS,
                          safeguard_session_days=DAYS, **common)
    result = update_report_history(rows, {"KR": "2026-11-02", "US": "2026-10-30"}, path=tmp_path / "fresh.json",
                                   generated_at=NOW.isoformat(), safeguard_news=[], safeguard_session_days=DAYS, **common)
    assert result["history_durable"] and len(result["safeguard_events"]) == 1
    saved = client.database[("alice", "2026-10-30", "2026-11-02")]
    assert saved["safeguard_events"][0]["date"] == "2026-10-30"
    other = update_report_history(rows, {"KR": "2026-11-02", "US": "2026-10-30"}, path=tmp_path / "bob.json",
                                  owner_scope="bob", store=client,
                                  generated_at=NOW.isoformat(), safeguard_news=[], safeguard_session_days=DAYS)
    assert other["safeguard_events"] == []


def test_unavailable_calendar_or_omitted_news_does_not_erase_durable_evidence(tmp_path):
    client = MemoryStore()
    rows = [{"티커": "MSFT", "최종읽기": "대기"}]
    dates = {"KR": "2026-11-02", "US": "2026-10-30"}
    for index, options in enumerate((
        {"safeguard_news": NEWS, "safeguard_session_days": DAYS}, {},
        {"safeguard_news": [], "safeguard_session_days": []},
        {"safeguard_news": [], "safeguard_session_days": ["2026-11-02"]},
        {"safeguard_news": [], "safeguard_session_days": DAYS},
    )):
        result = update_report_history(rows, dates, path=tmp_path / f"restart{index}.json",
                                       owner_scope="alice", store=client,
                                       generated_at=NOW.replace(minute=index).isoformat(), **options)
        assert len(result["safeguard_events"]) == 1
    assert merge_safeguard_history([], result["safeguard_events"], [], NOW) == []


def test_malformed_nested_sources_do_not_crash_history_or_panel():
    from stock_lab_core.report_policy_panel import policy_evidence_lines

    event = safeguard_events(NEWS, NOW)[0]
    for sources in (None, "invalid", [{"source_url": None}], {"source": "invalid"}):
        bad = dict(event, sources=sources)
        merged = merge_safeguard_history([bad], [bad], DAYS, NOW)
        assert merged[0]["sources"][0]["source_url"] == event["source_url"]
        context = {"safeguard_events": [bad], "price_frames": {"^KS11": pd.DataFrame(
            {"Close": [100] * len(DAYS)}, index=pd.to_datetime(DAYS))}}
        assert "최근 5거래일 저장 이력" in "\n".join(policy_evidence_lines(context, [], NOW))
