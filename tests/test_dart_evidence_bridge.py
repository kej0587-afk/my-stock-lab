"""Synthetic local bridge tests; no real keys, accounts, API or DB access."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import socket
import subprocess
import sys

import pytest
import requests

from stock_lab_core import dart_evidence as evidence
from stock_lab_core.dart_evidence_collector import collect_evidence


NOW = datetime(2026, 11, 7, 9, tzinfo=timezone.utc)
MAP = {"005930": "00126380"}
KEY = "synthetic-credential-never-save"
SCOPE = [{"year": "2026", "report_code": "11012"}]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("unexpected network"))


def row(**changes):
    return {"rcept_no": "20260814000001", "corp_code": MAP["005930"], "bsns_year": "2026",
            "reprt_code": "11012", "sj_div": "IS", "account_id": "ifrs-full_Revenue",
            "account_nm": "매출액", "thstrm_amount": "100,000", "thstrm_add_amount": "250,000",
            "frmtrm_amount": "80,000", "currency": "KRW", "ord": "1", **changes}


class Response:
    def __init__(self, data=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(data).encode()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        yield self.raw


def feed(*responses):
    calls = []
    queue = iter(responses)

    def get(url, **kwargs):
        calls.append((url, kwargs))
        response = next(queue)
        if isinstance(response, Exception):
            raise response
        return response

    return get, calls


def collect(*responses, scope=None):
    get, calls = feed(*responses)
    result = collect_evidence("005930.KS", scope or SCOPE, KEY, MAP, get=get, clock=lambda: NOW)
    return result, calls


@pytest.fixture
def bundle():
    return collect(Response({"status": "000", "list": [row()]}))[0]


def test_raw_cumulative_amounts_and_request_contract(bundle):
    response = Response({"status": "000", "list": [row()]})
    payload, calls = collect(response)
    assert payload["reports"] == bundle["reports"]  # Wall time is deliberately measured, not fixed.
    assert response.closed
    url, args = calls[0]
    assert url == evidence.ENDPOINT
    assert args["params"]["fs_div"] == "CFS"
    assert args["timeout"] == (8, 15) and args["stream"] and not args["allow_redirects"]
    assert payload["reports"][0]["rows"][0]["thstrm_add_amount"] == "250,000"
    assert KEY not in evidence.canonical_bytes(payload).decode()
    before = deepcopy(payload)
    summary = evidence.validate_bundle(payload, now=NOW, corporate_codes=MAP)
    assert summary["eligible"] and summary["request_count"] == summary["report_count"] == 1
    assert payload == before


def test_ofs_only_after_explicit_cfs_no_data():
    payload, calls = collect(Response({"status": "013"}), Response({"status": "000", "list": [row()]}))
    assert [call[1]["params"]["fs_div"] for call in calls] == ["CFS", "OFS"]
    assert payload["reports"][0]["fs_div"] == "OFS"
    assert evidence.validate_bundle(payload, now=NOW)["request_count"] == 2


def test_complete_no_data_is_not_evidence():
    payload, _ = collect(Response({"status": "013"}), Response({"status": "013"}))
    summary = evidence.validate_bundle(payload, now=NOW, corporate_codes=MAP)
    assert summary["complete"] and not summary["eligible"] and not summary["report_count"]


@pytest.mark.parametrize("response,cause", [
    (requests.ConnectTimeout("?crtfc_key=" + KEY), "transport_error"),
    (requests.ReadTimeout(KEY), "transport_error"),
    (Response(status=302), "http_error"),
    (Response(status=403), "http_error"),
    (Response({"status": "010", "message": KEY}), "api_error"),
    (Response({"status": "012"}), "api_error"),
    (Response({"status": "020"}), "api_error"),
    (Response(raw=b"not json"), "invalid_response"),
    (Response({"status": "000", "list": []}), "invalid_response"),
    (Response({"status": "000", "list": [row(corp_code="99999999")]}), "invalid_response"),
    (Response({"status": "000", "list": [row(account_nm=KEY)]}), "invalid_response"),
    (Response(raw=b'{"status":"000","status":"013"}'), "invalid_response"),
])
def test_failure_stops_without_fallback_and_never_leaks_key(response, cause):
    scope = SCOPE + [{"year": "2025", "report_code": "11011"}]
    payload, calls = collect(response, scope=scope)
    assert len(calls) == 1 and payload["reports"] == []
    assert payload["attempts"][0]["cause"] == cause
    summary = evidence.validate_bundle(payload, now=NOW, corporate_codes=MAP)
    assert not summary["complete"] and not summary["eligible"] and summary["unattempted_count"] == 1
    assert KEY not in evidence.canonical_bytes(payload).decode()


def test_partial_preserves_success_and_accounts_for_unattempted():
    scope = SCOPE + [{"year": "2025", "report_code": "11011"}, {"year": "2024", "report_code": "11011"}]
    payload, calls = collect(Response({"status": "000", "list": [row()]}), requests.Timeout(KEY), scope=scope)
    summary = evidence.validate_bundle(payload, now=NOW, corporate_codes=MAP)
    assert len(calls) == 2 and summary["report_count"] == 1 and summary["unattempted_count"] == 1
    assert not summary["eligible"]


@pytest.mark.parametrize("age,label,eligible", [(0, "recent", True), (1, "recent", True),
                                                   (2, "stale", True), (7, "stale", True), (8, "expired", False)])
def test_expiry_uses_collection_not_import_time(bundle, age, label, eligible):
    summary = evidence.validate_bundle(bundle, now=NOW + timedelta(days=age), corporate_codes=MAP)
    assert summary["freshness"] == label and summary["eligible"] is eligible


def test_map_is_independent_and_hash_not_authentication(bundle):
    assert not evidence.validate_bundle(bundle, now=NOW)["identity_verified"]
    assert not evidence.validate_bundle(bundle, now=NOW)["eligible"]
    with pytest.raises(evidence.EvidenceError):
        evidence.validate_bundle(bundle, now=NOW, corporate_codes={"005930": "99999999"})


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schema_version=True),
    lambda p: p.update(schema_version=2),
    lambda p: p.update(owner_email="private@example.invalid"),
    lambda p: p.update(endpoint="https://example.invalid"),
    lambda p: p.update(collected_at=(NOW + timedelta(minutes=6)).isoformat()),
    lambda p: p.update(collected_at="2026-11-07T09:00:00"),
    lambda p: p["requested_reports"].append(dict(SCOPE[0])),
    lambda p: p["requested_reports"].append({"year": "2025", "report_code": "11011"}),
    lambda p: p["reports"].append(deepcopy(p["reports"][0])),
    lambda p: p["reports"].clear(),
    lambda p: p["reports"][0].update(fs_div="OFS"),
    lambda p: p["reports"][0]["rows"][0].update(crtfc_key="forbidden"),
    lambda p: p["reports"][0]["rows"][0].update(rcept_no="bad"),
    lambda p: p["reports"][0]["rows"][0].update(bsns_year="2025"),
    lambda p: p["reports"][0]["rows"].append(row(currency="USD")),
    lambda p: p["reports"][0]["rows"].append(row(rcept_no="20260814000002")),
    lambda p: p["attempts"][0].update(elapsed_seconds=float("inf")),
    lambda p: p["attempts"][0].update(elapsed_seconds=True),
    lambda p: p["attempts"][0].update(status="success", api_status="013"),
    lambda p: p["attempts"][0].update(fs_div="OFS"),
])
def test_invalid_bundles_rejected(bundle, mutation):
    mutation(bundle)
    with pytest.raises(evidence.EvidenceError):
        evidence.validate_bundle(bundle, now=NOW)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[' * 1100, b'\xff'])
def test_json_parser_rejects_ambiguous_or_invalid_input(raw):
    with pytest.raises(evidence.EvidenceError):
        evidence.decode_json(raw)


def test_caps_and_raw_missing_values(bundle, monkeypatch):
    bundle["reports"][0]["rows"][0]["thstrm_amount"] = None
    assert evidence.validate_bundle(bundle, now=NOW)["row_count"] == 1
    monkeypatch.setattr(evidence, "MAX_BYTES", 100)
    with pytest.raises(evidence.EvidenceError):
        evidence.decode_json(b" " * 101)
    with pytest.raises(evidence.EvidenceError):
        evidence.validate_bundle(bundle, now=NOW)


def test_exclusive_write_roundtrip_preserves_existing_on_failure(tmp_path, bundle):
    path = tmp_path / "evidence.json"
    expected = evidence.write_bundle(path, bundle, now=NOW)
    raw = path.read_bytes()
    payload, actual = evidence.read_bundle(path, now=NOW)
    assert payload == bundle and actual == expected
    with pytest.raises(FileExistsError):
        evidence.write_bundle(path, bundle, now=NOW)
    partial, _ = collect(requests.Timeout(KEY))
    with pytest.raises(FileExistsError):
        evidence.write_bundle(path, partial, now=NOW)
    assert path.read_bytes() == raw


def test_filing_revision_changes_content_identity(bundle):
    before = evidence.validate_bundle(bundle, now=NOW)["sha256"]
    bundle["reports"][0]["rows"][0]["rcept_no"] = "20261107000002"
    assert evidence.validate_bundle(bundle, now=NOW)["sha256"] != before


def test_no_ui_database_or_scoring_imports():
    code = "import stock_lab_core.dart_evidence_collector; import sys; assert not any(x in sys.modules for x in ['app', 'streamlit', 'supabase', 'stock_lab_core.financial_score'])"
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_same_rows_keep_existing_parser_output(app_module, bundle):
    import pandas as pd

    raw = [row(), row(sj_div="CF", account_id="ifrs-full_CashFlowsFromUsedInOperatingActivities",
                      account_nm="영업활동현금흐름", thstrm_amount="20,000", thstrm_add_amount="45,000")]
    payload, _ = collect(Response({"status": "000", "list": raw}))
    before = app_module.extract_dart_metrics(pd.DataFrame(raw), "2026", "11012")
    after = app_module.extract_dart_metrics(pd.DataFrame(payload["reports"][0]["rows"]), "2026", "11012")
    pd.testing.assert_series_equal(pd.Series(before), pd.Series(after))
    assert after["revenue"] == 250000 and after["ocf"] == 45000


def test_cli_offline_validate_and_invalid_scope_do_not_fetch(tmp_path, bundle, monkeypatch, capsys):
    from scripts import collect_dart_evidence as cli

    monkeypatch.setattr(cli, "fetch_corporate_codes", lambda *a, **k: pytest.fail("unexpected lookup"))
    monkeypatch.setattr(cli, "read_bundle", lambda path: evidence.read_bundle(path, now=NOW))
    path = tmp_path / "sample.json"
    evidence.write_bundle(path, bundle, now=NOW)
    assert cli.main(["validate", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["identity_verified"] is False
    assert cli.main(["collect", "--ticker", "005930.KS", "--report", "2026:bad"]) == 1
    assert "invalid_report_code" in capsys.readouterr().out


def test_cli_refuses_public_output_before_any_request(tmp_path, monkeypatch, capsys):
    from scripts import collect_dart_evidence as cli

    monkeypatch.setattr(cli, "fetch_corporate_codes", lambda *a, **k: pytest.fail("unexpected lookup"))
    assert cli.main(["collect", "--ticker", "005930.KS", "--report", "2026:11012",
                     "--output", str(tmp_path / "not_private.json")]) == 1
    assert "output_must_be_private_cache" in capsys.readouterr().out


def test_invalid_scope_and_identity_make_no_statement_requests():
    get = lambda *a, **k: pytest.fail("unexpected request")
    for scope, codes in [(SCOPE + SCOPE, MAP), (SCOPE, {})]:
        with pytest.raises(evidence.EvidenceError):
            collect_evidence("005930.KS", scope, KEY, codes, get=get, clock=lambda: NOW)


def test_inconsistent_no_data_is_a_failure():
    payload, calls = collect(Response({"status": "013", "list": [row()]}))
    assert len(calls) == 1 and payload["attempts"][0]["status"] == "failed"


def test_response_size_limit_closes_connection(monkeypatch):
    from stock_lab_core import dart_evidence_collector as collector

    monkeypatch.setattr(collector, "MAX_BYTES", 32)
    response = Response(raw=b" " * 33)
    payload, calls = collect(response)
    assert response.closed and len(calls) == 1
    assert payload["attempts"][0]["cause"] == "invalid_response"


def test_failed_response_does_not_replace_good_file_through_cli(tmp_path, bundle, monkeypatch, capsys):
    from scripts import collect_dart_evidence as cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    path = tmp_path / "cache/financial_evidence/good.json"
    evidence.write_bundle(path, bundle, now=NOW)
    raw = path.read_bytes()
    monkeypatch.setattr(cli, "fetch_corporate_codes", lambda *a, **k: pytest.fail("unexpected request"))
    assert cli.main(["collect", "--ticker", "005930.KS", "--report", "2026:11012", "--output", str(path)]) == 1
    assert "output_exists" in capsys.readouterr().out and path.read_bytes() == raw
