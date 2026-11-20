"""Offline audit contracts using synthetic prices, never private review exports."""

from copy import deepcopy
import hashlib
import json
import socket
from unittest.mock import Mock
import zipfile

import pandas as pd
import pytest

from scripts import audit_daily_bar_consumers as audit
from stock_lab_core.market_board import completed_close_series
from stock_lab_core.report_session import market_session_states


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    guards = []
    for target, name in ((socket, "getaddrinfo"), (socket.socket, "connect"),
                         (socket.socket, "connect_ex")):
        guard = Mock(side_effect=AssertionError("Unexpected network use in offline audit"))
        monkeypatch.setattr(target, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


@pytest.fixture
def capture():
    # Repeating six-bar prices, followed by a large partial bar. These are not
    # recorded GOOGL prices. Frozen indicator values independently anchor replay.
    closes = [float(100 + i % 6) for i in range(60)]
    closes[-1] = 140.
    source = pd.DataFrame({
        "Open": [price - .5 for price in closes],
        "High": [price + 2 for price in closes],
        "Low": [price - 2 for price in closes],
        "Close": closes,
        "Volume": [1000. + 10 * i for i in range(60)],
    }, index=pd.bdate_range(end="2026-11-20", periods=60))
    source.attrs = {"source": "synthetic", "audit_note": {"keep": ["unchanged"]}}
    chart = source.copy(deep=True)
    decision = {
        "cur_p": 140., "rsi": 83.25416640072388, "atr": 6.857142857142857,
        "regular_day_ret": 140 / 104 - 1,
        "rr_ratio": 2.187497721356541, "rr_target": 170.,
        "rr_target_source": "차트 구조: 최근 내부고점", "rr_target_is_projection": False,
        "day_ret": 140 / 104 - 1, "day_ret_label": "synthetic source return",
    }
    return {
        "source": source, "chart": chart, "ticker": "GOOGL", "decision": decision,
        "basis": {"계산시각": "2026-11-21 00:36:10 KST", "가격입력ID":
                  audit.price_input_identity(source, chart, ticker="GOOGL", input_price=140.)},
        "saved_scenario": {"asof": "2026-11-19", "close": 104.},
    }


def write_capture(path, capture, *, result_ticker=None):
    """Write the minimum public-shaped JSON/CSV archive accepted by the CLI."""
    manifest = {"selected_ticker": capture["ticker"],
                "result_ticker": result_ticker or capture["ticker"], "ohlcv": {}}
    sections = {"main_decision": capture["decision"], "context": {
        "signal_basis": capture["basis"], "live_ohlcv_applied": False,
        "scenario_analysis": {"completed_evidence": capture["saved_scenario"]},
    }}
    with zipfile.ZipFile(path, "w") as archive:
        for label, key in (("daily_source", "source"), ("display_chart", "chart")):
            name = label + ".csv"
            frame = capture[key]
            archive.writestr(name, frame.to_csv(index_label="_row_index"))
            manifest["ohlcv"][label] = {"file": name, "attrs": frame.attrs}
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("snapshot.json", json.dumps({"sections": sections}, ensure_ascii=False))
    return path


def test_us_partial_source_and_completed_report_split_without_mutation(capture):
    original = deepcopy(capture)
    result = audit.compare_frames(**capture)
    assert result["calculation_clock"] == "2026-11-21T00:36:10+09:00"
    assert result["completed_session"] == "2026-11-19"
    assert result["source_bar_provisional_by_calendar"] is True
    assert result["saved_numeric_matches"] == dict.fromkeys(
        ("rsi", "atr", "cur_p", "regular_day_ret", "rr_ratio"), True)
    assert result["saved_scenario_date_price_match"] is True
    assert result["decision_source"]["rows"] == 60
    assert result["decision_source"]["last_date"] == "2026-11-20"
    assert result["decision_source"]["close"] == result["decision_quote"] == 140.
    for key in ("scenario_completed", "report_completed_same_source"):
        row = result[key]
        assert (row["rows"], row["last_date"], row["close"]) == (59, "2026-11-19", 104.)
        assert row["rsi"] == pytest.approx(53.6675641731833)
        assert row["atr"] == pytest.approx(4.428571428571429)
    observation = result["report_completed_same_source"]["observation"]
    assert (observation["date"], observation["kind"]) == ("2026-11-19", "확정 종가")
    intraday = result["report_intraday_same_source"]
    assert (intraday["date"], intraday["price"]) == ("2026-11-20", 140.)
    assert intraday["kind"] == "장중 진행·확정 아님"
    assert intraday["return"] == pytest.approx(140 / 104 - 1)
    sensitivity = result["rr_sensitivity"]
    assert sensitivity["available"] is True
    assert (sensitivity["fixed_quote"], sensitivity["fixed_target"]) == (140., 170.)
    assert sensitivity["current_rr"] == pytest.approx(2.187497721356541)
    assert sensitivity["completed_bar_rr"] == pytest.approx(3.38711316345079)
    for key in ("source", "chart"):
        pd.testing.assert_frame_equal(capture[key], original[key], check_exact=True)
        assert capture[key].attrs == original[key].attrs
    for key in ("ticker", "decision", "basis", "saved_scenario"):
        assert capture[key] == original[key]


def test_kr_completed_same_source_consumers_agree_without_claiming_regular_provider(capture):
    capture["ticker"] = "379810.KS"
    capture["basis"]["가격입력ID"] = audit.price_input_identity(
        capture["source"], capture["chart"], ticker=capture["ticker"], input_price=140.)
    capture["saved_scenario"] = {"asof": "2026-11-20", "close": 140.}
    result = audit.compare_frames(**capture)
    assert result["completed_session"] == "2026-11-20"
    assert result["source_bar_provisional_by_calendar"] is False
    assert all(result["saved_numeric_matches"].values())
    assert result["saved_scenario_date_price_match"] is True
    for key in ("scenario_completed", "report_completed_same_source"):
        assert {field: result[key][field] for field in result["decision_source"]} == result["decision_source"]
    assert result["report_intraday_same_source"] == {}
    assert result["rr_sensitivity"]["completed_bar_rr"] == result["rr_sensitivity"]["current_rr"]
    assert any("KR production report uses separate regular-price history" in note for note in result["limits"])


def test_identity_rejects_tampered_id_prices_or_symbol(capture):
    for fault in ("id", "source", "chart", "ticker", "quote"):
        broken = deepcopy(capture)
        if fault == "id":
            broken["basis"]["가격입력ID"] = "invalid"
        elif fault in ("source", "chart"):
            broken[fault].iloc[-1, broken[fault].columns.get_loc("High")] += 1
        elif fault == "ticker":
            broken["ticker"] = "SOXL"
        else:
            broken["decision"]["cur_p"] += 1
        with pytest.raises(ValueError, match="identity mismatch"):
            audit.compare_frames(**broken)


def test_missing_naive_or_invalid_capture_clock_fails_before_calendar(capture, monkeypatch):
    calendar = Mock(side_effect=AssertionError("invalid clock reached calendar"))
    monkeypatch.setattr(audit, "latest_completed_chart_session", calendar)
    for stamp in (None, "", "2026-11-21 00:36:10", "2026-11-21T00:36:10",
                  "2026-11-21 00:36:10 UTC", "2026-02-30 00:36:10 KST"):
        broken = deepcopy(capture)
        if stamp is None:
            broken["basis"].pop("계산시각")
        else:
            broken["basis"]["계산시각"] = stamp
        with pytest.raises((ValueError, KeyError)):
            audit.compare_frames(**broken)
    calendar.assert_not_called()


def test_applied_or_marked_quote_overlays_are_out_of_scope(capture):
    for marker in ("applied", "latest", "historical"):
        broken = deepcopy(capture)
        if marker == "applied":
            broken["applied"] = True
        else:
            broken["chart"]["LiveQuoteOnly"] = False
            at = broken["chart"].index[-1 if marker == "latest" else 0]
            broken["chart"].loc[at, "LiveQuoteOnly"] = True
            broken["basis"]["가격입력ID"] = audit.price_input_identity(
                broken["source"], broken["chart"], ticker="GOOGL", input_price=140.)
        with pytest.raises(ValueError, match="Quote-overlay captures"):
            audit.compare_frames(**broken)


def test_cli_saved_rsi_atr_rr_mismatch_exits_but_preserves_diagnostics(capture, tmp_path):
    for field in ("rsi", "atr", "rr_ratio"):
        capture["decision"][field] += 1
    archive = write_capture(tmp_path / "mismatch.zip", capture)
    output = tmp_path / "diagnostic.json"
    with pytest.raises(SystemExit, match="Replay mismatch"):
        audit.main([str(archive), "--output", str(output)])
    result, = json.loads(output.read_text(encoding="utf-8"))
    assert result["saved_numeric_matches"] == {
        "rsi": False, "atr": False, "rr_ratio": False, "cur_p": True, "regular_day_ret": True}
    assert result["decision_source"]["rsi"] == pytest.approx(83.25416640072388)
    assert result["decision_source"]["atr"] == pytest.approx(6.857142857142857)
    assert result["rr_sensitivity"]["current_rr"] == pytest.approx(2.187497721356541)
    assert result["saved_scenario_date_price_match"] is True


def test_saved_scenario_date_or_price_mismatch_is_not_hidden(capture):
    for field, wrong in (("asof", "2026-11-20"), ("close", 140.)):
        broken = deepcopy(capture)
        broken["saved_scenario"][field] = wrong
        result = audit.compare_frames(**broken)
        assert result["saved_scenario_date_price_match"] is False
        assert all(result["saved_numeric_matches"].values())
        assert result["scenario_completed"]["last_date"] == "2026-11-19"
        assert result["scenario_completed"]["close"] == 104.


def test_cli_replays_synthetic_zip_and_keeps_capture_unchanged(capture, tmp_path, capsys):
    archive = write_capture(tmp_path / "capture.zip", capture)
    original = archive.read_bytes()
    output = tmp_path / "new" / "audit.json"
    audit.main([str(archive), "--output", str(output)])
    result, = json.loads(output.read_text(encoding="utf-8"))
    assert result["input_id"] == capture["basis"]["가격입력ID"]
    assert result["capture_sha256"] == hashlib.sha256(original).hexdigest()
    assert all(result["saved_numeric_matches"].values())
    assert result["saved_scenario_date_price_match"] is True
    assert (result["decision_source"]["rows"], result["scenario_completed"]["rows"]) == (60, 59)
    assert archive.read_bytes() == original
    printed = json.loads(capsys.readouterr().out)
    assert printed["ticker"] == "GOOGL"
    assert printed["saved_numeric_matches"] == result["saved_numeric_matches"]


def test_zip_selected_result_symbol_conflict_is_rejected(capture, tmp_path):
    archive = write_capture(tmp_path / "wrong-symbol.zip", capture, result_ticker="SOXL")
    with pytest.raises(ValueError, match="Selected/result symbol mismatch"):
        audit.audit_zip(archive)


def test_cli_existing_output_rejects_before_reading_capture(tmp_path, monkeypatch, capsys):
    output = tmp_path / "existing.json"
    output.write_bytes(b"preserve existing evidence\n")
    reader = Mock(side_effect=AssertionError("capture must not be opened"))
    monkeypatch.setattr(audit, "audit_zip", reader)
    with pytest.raises(SystemExit) as exc:
        audit.main([str(tmp_path / "not-present.zip"), "--output", str(output)])
    assert exc.value.code == 2
    assert "Preserve existing output" in capsys.readouterr().err
    assert output.read_bytes() == b"preserve existing evidence\n"
    reader.assert_not_called()


def test_cli_blocks_dns_and_socket_connect_before_any_network(tmp_path, monkeypatch):
    def resolve(_path):
        socket.getaddrinfo("example.invalid", 443)

    def connect(_path):
        with socket.socket() as connection:
            connection.connect(("127.0.0.1", 9))

    for attempted_read in (resolve, connect):
        monkeypatch.setattr(audit, "audit_zip", attempted_read)
        output = tmp_path / (attempted_read.__name__ + ".json")
        with pytest.raises(RuntimeError, match="Offline audit: network disabled"):
            audit.main([str(tmp_path / "unused.zip"), "--output", str(output)])
        assert not output.exists()


@pytest.mark.xfail(strict=True, reason="known report cutoff uses normal hours; next task calendar alignment")
def test_known_special_session_report_consumers_should_wait_for_actual_close():
    # Isolated desired behavior: current generic report/board clocks wrongly treat
    # this 16:30 KRX close as finished at 16:00. Do not bless that discrepancy.
    # The separate regular_close_frame production path already has calendar protection.
    now = pd.Timestamp("2026-11-19T16:00+09:00").to_pydatetime()
    source = pd.DataFrame({"Close": [100., 110.]},
                          index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    assert audit.latest_completed_chart_session("379810.KS", now=now) == "2026-11-18"
    report = audit.closed_daily_frame(source, "379810.KS", now)
    board, _ = completed_close_series(source, "KR", now=now)
    actual = (str(report.index[-1].date()), str(board.index[-1].date()),
              market_session_states(now)["KR"]["phase"])
    assert actual == ("2026-11-18", "2026-11-18", "intraday")
