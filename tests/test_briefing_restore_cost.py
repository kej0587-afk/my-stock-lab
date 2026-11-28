"""Skip only the existing restore no-op; account changes still restore and stamp."""
from unittest.mock import MagicMock

import pytest

from stock_lab_core import report_latest


@pytest.mark.parametrize("prior", [None, ["ISA"], ["other"]])
def test_briefing_hashes_build_only_when_restore_can_run(app_module, monkeypatch, prior):
    app = app_module
    ui = MagicMock()
    ui.session_state = {"acc_filter": ["ISA"]}
    if prior is not None:
        ui.session_state[report_latest.TRIED_KEY] = report_latest.account_key(prior)
    ui.segmented_control.return_value = "시황"
    build = MagicMock(return_value={"loaded_source_sha256": "fixed-build"})
    local = MagicMock(return_value={"report_text": "fixed-report"})
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "IS_PUBLIC_DEMO", False)
    monkeypatch.setattr(app, "CURRENT_USER_EMAIL", "synthetic@example.test")
    monkeypatch.setattr(app, "supabase", None)
    monkeypatch.setattr(app, "get_report_build_info", build)
    monkeypatch.setattr(app, "_build_today_held_position_meta_map", lambda _: {})
    monkeypatch.setattr(app, "_render_briefing_report_surface", lambda *args: True)
    monkeypatch.setattr(report_latest, "_load_local", local)
    monkeypatch.setattr(report_latest, "last_report_caption", lambda _: "")
    app.render_today_unified_briefing_panel(pending=True)
    expected = 0 if prior == ["ISA"] else 1
    assert build.call_count == local.call_count == expected
    if expected:
        assert ui.session_state[report_latest.MEMO_KEY] == "fixed-report"
        assert ui.session_state[report_latest.ENGINE_KEY] == "fixed-build"
        assert local.call_args.args[1] == "synthetic@example.test"
        assert local.call_args.args[2] == report_latest.account_key(["ISA"])
    before = dict(ui.session_state)
    app.render_today_unified_briefing_panel(pending=True)
    assert build.call_count == local.call_count == expected
    assert ui.session_state == before
