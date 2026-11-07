import io
import json
import pickle
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest
import requests

from stock_lab_core.dart_corporate_codes import fetch_corporate_codes


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
