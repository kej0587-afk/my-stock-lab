from pathlib import Path

import pandas as pd

from stock_lab_core.today_snapshot import (
    load_today_queue_summary_snapshot, save_today_queue_summary_snapshot,
    snapshot_storage_notice,
)


def test_missing_file_is_not_input_mismatch(tmp_path):
    text = snapshot_storage_notice(owner_scope="owner", path=tmp_path / "absent.json")
    assert "서버 저장본 없음" in text
    assert "자동후보" in text
    assert "입력 변경" not in text


def test_notice_does_not_read_contents_or_expose_identity(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.json"
    frame = pd.DataFrame({"티커": ["001234"], "점수": [1.234567]})
    save_today_queue_summary_snapshot(frame, "sig", "at", path=path, owner_scope="private-owner")
    def forbidden(*args, **kwargs):
        raise AssertionError("notice must only stat the file")
    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", forbidden)
        text = snapshot_storage_notice(owner_scope="private-owner", path=path)
    assert "저장 파일 있음" in text
    assert "private-owner" not in text and str(tmp_path) not in text
    actual, sig, at = load_today_queue_summary_snapshot(path=path, owner_scope="private-owner")
    pd.testing.assert_frame_equal(actual, frame)
    assert (sig, at) == ("sig", "at")
    assert "저장본 없음" in snapshot_storage_notice(owner_scope="other", path=path)


def test_new_server_directory_cannot_restore_old_local_file(tmp_path):
    old = tmp_path / "old-server" / "snapshot.json"
    new = tmp_path / "new-server" / "snapshot.json"
    frame = pd.DataFrame({"티커": ["T0"], "판정": ["KEEP"]})
    save_today_queue_summary_snapshot(frame, "sig", "at", path=old, owner_scope="owner")
    assert not load_today_queue_summary_snapshot(path=old, owner_scope="owner")[0].empty
    assert load_today_queue_summary_snapshot(path=new, owner_scope="owner")[0].empty
    assert "저장본 없음" in snapshot_storage_notice(owner_scope="owner", path=new)


def test_access_failure_is_distinct(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("private-path")
    monkeypatch.setattr(Path, "stat", denied)
    text = snapshot_storage_notice(owner_scope="owner", path=tmp_path / "snapshot.json")
    assert "접근 실패" in text and "private-path" not in text


def test_public_session_has_no_personal_notice():
    assert snapshot_storage_notice(owner_scope="") == ""
