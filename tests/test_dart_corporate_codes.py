import io
import json
import pickle
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest
import requests

from stock_lab_core.dart_corporate_codes import fetch_corporate_codes
from stock_lab_core.dart_corporate_codes import CorporateCodeMap
from stock_lab_core.dart_corporate_snapshot import use_corporate_snapshot, SOURCE, SNAPSHOT_PATH


def response(body, status=200, content_type="application/zip"):
    return SimpleNamespace(content=body, status_code=status, headers={"Content-Type": content_type})


def test_success_retains_mapping_and_diagnostic_through_cache_serialization():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('CORPCODE.xml', '<result><list><corp_code> 00123456 </corp_code><stock_code>329180</stock_code></list><list><corp_code>00000001</corp_code><stock_code> </stock_code></list></result>')
    get = Mock(return_value=response(payload.getvalue()))
    result = fetch_corporate_codes('PRIVATE', get=get)
    assert result == {'329180': '00123456'}
    assert result.diagnostic['cause'] == 'ok'
    restored = pickle.loads(pickle.dumps(result))
    assert restored == result and restored.diagnostic == result.diagnostic
    assert get.call_count == 1


@pytest.mark.parametrize('payload, expected', [
    (b'<result><status>012</status><message>PRIVATE</message></result>', '012'),
    (b'{"status":"020","message":"PRIVATE"}', '020'),
    (b'<html>PRIVATE</html>', None), (b'PRIVATE', None),
    (b'{"status":"PRIVATE"}', None),
])
def test_non_zip_api_errors_are_classified_without_body_or_key(payload, expected):
    result = fetch_corporate_codes('PRIVATE', get=lambda *a, **kw: response(payload))
    assert not result and result.diagnostic['api_status'] == expected
    assert 'PRIVATE' not in json.dumps(result.diagnostic)


@pytest.mark.parametrize('error, cause', [
    (requests.ConnectTimeout('https://example?crtfc_key=PRIVATE'), 'connect_timeout'),
    (requests.ReadTimeout('PRIVATE'), 'read_timeout'),
    (requests.ConnectionError('PRIVATE'), 'transport_error'),
])
def test_transport_failures_do_not_leak_url_or_exception(error, cause):
    result = fetch_corporate_codes('PRIVATE', get=Mock(side_effect=error))
    assert not result and result.diagnostic['cause'] == cause
    assert 'PRIVATE' not in json.dumps(result.diagnostic)


def test_missing_key_and_http_failure_do_not_parse_untrusted_body():
    get = Mock()
    assert fetch_corporate_codes('', get=get).diagnostic['cause'] == 'missing_key'
    get.assert_not_called()
    result = fetch_corporate_codes('PRIVATE', get=lambda *a, **kw: response(b'PRIVATE', 403, 'PRIVATE'))
    assert result.diagnostic['http_status'] == 403
    assert result.diagnostic['cause'] == 'http_error'
    assert 'PRIVATE' not in json.dumps(result.diagnostic)


def snapshot(tmp_path, *, age=0, patch=None):
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    data = {'version': 1, 'source': SOURCE, 'retrieved_at': (now - timedelta(days=age)).isoformat(),
            'codes': {'329180': '00123456', '0001A0': '00123457'}}
    data.update(patch or {})
    path = tmp_path / 'codes.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path, now


def test_transient_outage_uses_dated_identities_without_claiming_live_success(tmp_path):
    path, now = snapshot(tmp_path)
    live = CorporateCodeMap(diagnostic={'cause': 'connect_timeout', 'elapsed_seconds': 8.021})
    result = use_corporate_snapshot(live, path=path, now=now)
    assert result['329180'] == '00123456' and result['0001A0'] == '00123457'
    assert result.get('UNKNOWN') is None
    assert result.diagnostic['cause'] == 'connect_timeout'
    assert result.diagnostic['mapping_source'] == 'official_snapshot'
    assert not live and 'mapping_source' not in live.diagnostic


@pytest.mark.parametrize('age, patch', [
    (8, None), (-1, None), (0, {'source': 'https://untrusted.invalid'}),
    (0, {'codes': {'329180': 'PRIVATE'}}), (0, {'codes': {}}),
    (0, {'retrieved_at': '2026-11-07'}), (0, {'version': 2}),
])
def test_expired_future_or_invalid_snapshot_never_maps(tmp_path, age, patch):
    path, now = snapshot(tmp_path, age=age, patch=patch)
    result = use_corporate_snapshot(CorporateCodeMap(diagnostic={'cause': 'read_timeout'}), path=path, now=now)
    assert not result and result.diagnostic['snapshot_status'] == 'unavailable_or_expired'


@pytest.mark.parametrize('cause', ['missing_key', 'api_error', 'http_error', 'invalid_zip_xml', 'empty_mapping'])
def test_auth_access_and_nontransport_failures_are_not_hidden(tmp_path, cause):
    path, now = snapshot(tmp_path)
    live = CorporateCodeMap(diagnostic={'cause': cause, 'api_status': '012'})
    assert use_corporate_snapshot(live, path=path, now=now) is live


def test_live_success_is_never_replaced_and_bundle_contains_only_public_fields(tmp_path):
    path, now = snapshot(tmp_path)
    live = CorporateCodeMap({'329180': '99999999'}, diagnostic={'cause': 'ok'})
    assert use_corporate_snapshot(live, path=path, now=now) is live
    payload = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
    assert set(payload) == {'version', 'source', 'retrieved_at', 'codes'}
    result = use_corporate_snapshot(CorporateCodeMap(diagnostic={'cause': 'connect_timeout'}),
        now=datetime.fromisoformat(payload['retrieved_at']))
    assert len(result) == len(payload['codes']) > 3000
