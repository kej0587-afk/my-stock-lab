from copy import deepcopy
from datetime import datetime
import json

from stock_lab_core import report_build
from stock_lab_core.market_memo import build_auto_market_memo
from stock_lab_core.performance import PerformanceTrace, measure, queue_measurement_reference
from stock_lab_core.report_evidence import comparison_lines, participant_news_lines, reported_cause
from stock_lab_core.report_history import update_report_history
from stock_lab_core.today_news import partition_session_market_news

NOW = datetime.fromisoformat("2026-10-19T17:16:00+09:00")
SESSIONS = {"KR": {"date": "2026-10-19", "previous_date": "2026-10-16"},
            "US": {"date": "2026-10-16", "previous_date": "2026-10-15"}}


def test_build_records_loaded_and_disk_sources_separately(monkeypatch):
    good = report_build.get_report_build_info("app.py")
    assert not good["restart_required"]
    loaded = good["loaded_source_sha256"]
    original_hash = report_build._file_hash
    monkeypatch.setattr(report_build, "_file_hash",
                        lambda path: "changed" if str(path).endswith("report_evidence.py") else original_hash(path))
    changed = report_build.get_report_build_info("app.py")
    assert changed["restart_required"]
    assert changed["loaded_source_sha256"] == loaded
    assert changed["stale_modules"] == ["stock_lab_core.report_evidence"]


def test_cached_auto_report_invalidates_but_manual_memo_survives():
    state = {"today_market_memo_text": "# Stock Lab 자동 뉴스픽 old", "_today_market_memo_engine_version": "old"}
    assert report_build.invalidate_saved_report(state, "new")
    assert state["today_market_memo_text"] == ""
    assert not report_build.invalidate_saved_report(state, "new")
    state["today_market_memo_text"] = "내 수동 메모"
    assert not report_build.invalidate_saved_report(state, "newer")
    assert state["today_market_memo_text"] == "내 수동 메모"


def test_both_report_paths_have_one_footer_and_new_report_ids():
    context = {"sessions": {"KR": "2026-10-19", "US": "2026-10-16"},
               "entrypoint": "/deployment/app.py", "queue_measurement": {"measurement_id": "queue-1"}}
    reports = [build_auto_market_memo(now=NOW, report_context=value) for value in (None, context, context)]
    for report in reports:
        assert report.count("빌드: 기준커밋") == 1
        assert report.splitlines()[-1].startswith("빌드:")
        assert "market_memo.py" in report.splitlines()[-1]
    assert "queue-1" in reports[1]
    assert reports[1].splitlines()[-1] != reports[2].splitlines()[-1]
    assert reports[1].split("빌드:")[0] == reports[2].split("빌드:")[0]


def test_measurement_identity_references_actual_calculation_not_rerender():
    with PerformanceTrace(scope="today_queue_render_with_calculation") as trace:
        with measure("phase", "summary"):
            pass
        reference = queue_measurement_reference()
    measured = trace.report()
    assert reference["measurement_id"] == measured["measurement_id"]
    assert measured["measurement_started_at"] <= measured["measurement_finished_at"]
    with PerformanceTrace() as rerender:
        reused = queue_measurement_reference(measured)
    assert reused["measurement_id"] == measured["measurement_id"]
    assert reused["measurement_id"] != rerender.report()["measurement_id"]
    assert measured == trace.report()


def test_same_session_history_and_prior_trading_day_are_both_available(tmp_path):
    path = tmp_path / "history.json"
    dates = {key: row["date"] for key, row in SESSIONS.items()}
    before = [{"티커": "AAPL", "최종읽기": "대기", "게이트상태": "대기/관찰"}]
    after = [{"티커": "AAPL", "최종읽기": "대기", "게이트상태": "방어우선"}]
    options = dict(path=path, owner_scope="alice")
    update_report_history(before, dict(KR="2026-10-16", US="2026-10-15"), **options)
    update_report_history(before, dates, generated_at="2026-10-19T16:18:00+09:00", **options)
    result = update_report_history(after, dates, **options)
    assert result["previous_date"] == "2026-10-15/2026-10-16"
    assert result["previous_run_at"] == "2026-10-19T16:18:00+09:00"
    line = "\n".join(comparison_lines(after, result["previous_run_summary"],
                            previous_date=result["previous_run_date"], current_date=result["summary_date"],
                            same_session=True, previous_run_at=result["previous_run_at"]))
    assert "같은 거래일 직전 생성" in line and "게이트 | 대기/관찰 | 방어우선" in line
    assert "previous_run_summary" not in update_report_history(after, dates, path=path, owner_scope="bob")


def test_legacy_same_session_history_without_timestamp_still_compares(tmp_path):
    path = tmp_path / "history.json"
    dates = {"KR": "2026-10-19", "US": "2026-10-16"}
    rows = [{"티커": "AAPL", "최종읽기": "대기"}]
    update_report_history(rows, dates, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sessions"]["2026-10-16/2026-10-19"].pop("generated_at")
    path.write_text(json.dumps(data), encoding="utf-8")
    result = update_report_history(rows, dates, path=path)
    assert result["previous_run_at"] == "저장 시각 미확보"
    assert not result["previous_summary"]
    assert result["previous_run_summary"]


def test_kr_postclose_publication_uses_time_not_title_and_not_causality():
    rows = [dict(title=title, published_at=stamp, market="KR", link="https://example.com/" + str(i))
            for i, (title, stamp) in enumerate([
                ("외인·기관 매수에 코스피 반전", "2026-10-19T15:30:00+09:00"),
                ("연기금 순매수로 코스피 상승", "2026-10-19T16:08:00+09:00"),
                ("제목에 마감 없는 코스피 보도", "2026-10-19T17:15:00+09:00"),
                ("내일 한국장", "2026-10-20T08:00:00+09:00"),
                ("마감이라고 쓴 장전 보도", "2026-10-19T08:13:00+09:00"),
            ])]
    result = partition_session_market_news(rows, SESSIONS, now=NOW)
    assert len(result["session_news"]) == 4
    posts = [r for r in result["session_news"] if r["post_close_context"]]
    assert len(posts) == 3 and all(r["news_timing"] == "마감 후 보도" for r in posts)
    assert not reported_cause(dict(posts[1], published=posts[1]["published_at"]),
                              {key: row["date"] for key, row in SESSIONS.items()})
    following = partition_session_market_news(rows, SESSIONS, now="2026-10-20T08:00:00+09:00")
    assert len(following["next_session_news"]) == 1


def test_multiple_flow_participant_titles_keep_sources_and_deduplicate():
    a = dict(title="코스피 외국인 매도, 기관 매수", market="KR", session_date="2026-10-19",
             publisher="연합뉴스", link="https://example.com/1")
    b = dict(a, title="연기금 순매수에 코스피 반등", publisher="머니투데이", link="https://example.com/2")
    rows = [a, deepcopy(a), b, dict(a, session_date="2026-10-16"), dict(b, market="US")]
    before = deepcopy(rows)
    result = participant_news_lines(rows, "2026-10-19")
    assert len(result) == 1 and "2건" in result[0] and "순매수액 미검증" in result[0]
    assert "연합뉴스" in result[0] and "머니투데이" in result[0]
    assert rows == before
