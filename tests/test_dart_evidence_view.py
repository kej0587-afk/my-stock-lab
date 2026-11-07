"""Real Streamlit panel lifecycle with synthetic uploads/identity/storage."""

import ast
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from stock_lab_core.dart_corporate_codes import CorporateCodeMap
from stock_lab_core.dart_evidence import EvidenceError, canonical_bytes, validate_bundle
from stock_lab_core.dart_evidence_preview import resolve_identity, verified_codes, metric_rows
from stock_lab_core.dart_evidence_store import EvidenceStoreError
from tests.test_dart_evidence_store import bundle, NOW, MAP, SCOPE


class MemoryStore:
    def __init__(self, state, owner):
        self.state, self.owner = state, owner

    def insert_bundle(self, payload, *, ticker, owner_scope, corporate_codes, now):
        assert self.owner == owner_scope
        self.state["calls"].append(("insert", owner_scope, ticker))
        if self.state.get("fault"):
            raise EvidenceStoreError(self.state["fault"])
        summary = validate_bundle(payload, corporate_codes=corporate_codes, now=now)
        key = (owner_scope, ticker, summary["sha256"])
        inserted = key not in self.state["database"]
        result = {"payload": deepcopy(payload), "summary": summary, "imported_at": now.isoformat()}
        self.state["database"].setdefault(key, result)
        return {**result, "inserted": inserted}

    def load_latest(self, ticker, *, owner_scope, corporate_codes, now, requested_reports):
        assert self.owner == owner_scope
        self.state["calls"].append(("load", owner_scope, ticker))
        if self.state.get("fault"):
            raise EvidenceStoreError(self.state["fault"])
        for (owner, symbol, _), result in self.state["database"].items():
            if owner == owner_scope and symbol == ticker and result["payload"]["requested_reports"] == requested_reports:
                return deepcopy(result)
        return None


SCRIPT = '''
import streamlit as st
from io import BytesIO
from datetime import timedelta
from stock_lab_core.dart_evidence_view import render_dart_evidence
from tests.test_dart_evidence_view import MemoryStore
from tests.test_dart_evidence_store import NOW, MAP
def identity(ticker):
    st.session_state['calls'].append(('identity',ticker))
    return {'ticker': ticker, 'codes': MAP, 'checked_at': NOW.isoformat(),
            'valid_until': (NOW+timedelta(minutes=10)).isoformat()}
kwargs={}
if st.session_state.get('fake_upload', True):
    kwargs['uploader']=lambda *a, **k: BytesIO(st.session_state['raw']) if st.session_state.get('raw') is not None else None
render_dart_evidence(st, ticker=st.session_state.get('ticker','005930.KS'), owner=st.session_state.get('owner','first@example.invalid'),
    fin_meta=st.session_state['meta'], extract_metrics=lambda df, year, code: {'revenue': 250000, 'ocf': 45000},
    identity_loader=identity, store_factory=lambda owner: MemoryStore(st.session_state, owner),
    is_demo=st.session_state.get('demo',False), now=st.session_state.get('now', NOW), **kwargs)
'''


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("unexpected network"))


def app_with_file(payload=None, **state):
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    for key, value in {"raw": canonical_bytes(payload or bundle()), "calls": [], "database": {},
                       "meta": {"auto_score": 3, "manual_score": 4, "final_score": 4}, **state}.items():
        app.session_state[key] = value
    return app.run()


def button(app, label):
    return next(b for b in app.button if b.label == label)


VERIFY = "기업·상장시장 확인"
IMPORT = "개인 근거로 가져오기 (점수 유지)"
LOAD = "같은 범위의 저장 근거 조회"


def test_preview_has_no_requests_and_preserves_grades():
    app = app_with_file()
    assert not app.exception and not app.session_state["calls"]
    assert button(app, IMPORT).disabled
    assert len(app.dataframe) == 3
    assert app.dataframe[1].value.iloc[0]["수집 상태"] == "수집"
    assert "누적" in app.dataframe[2].value.iloc[0]["금액 기준"]
    assert app.session_state["meta"] == {"auto_score": 3, "manual_score": 4, "final_score": 4}


def test_verify_import_duplicate_and_load_are_explicit():
    app = app_with_file()
    button(app, VERIFY).click().run()
    assert not app.exception and not button(app, IMPORT).disabled
    assert app.session_state["calls"] == [("identity", "005930.KS")]
    button(app, IMPORT).click().run()
    assert any("저장 완료" in s.value for s in app.success)
    button(app, IMPORT).click().run()
    assert any("동일 자료" in s.value for s in app.success)
    button(app, LOAD).click().run()
    assert len(app.dataframe) == 6
    calls = deepcopy(app.session_state["calls"])
    app.run()
    assert app.session_state["calls"] == calls and len(app.session_state["database"]) == 1
    assert app.session_state["meta"]["final_score"] == 4


def test_schema_missing_shows_download_and_does_not_claim_saved():
    app = app_with_file(fault="schema_unavailable")
    button(app, VERIFY).click().run()
    button(app, IMPORT).click().run()
    assert not app.exception and not app.success
    assert any("테이블이 아직" in s.value for s in app.warning)
    assert len(app.get("download_button")) == 1 and not app.session_state["database"]


@pytest.mark.parametrize("state", [{"ticker": "000660.KS"}, {"ticker": "005930.KQ"},
                                    {"raw": b'invalid'}, {"now": NOW+timedelta(days=8)}])
def test_invalid_or_wrong_company_upload_cannot_import(state):
    app = app_with_file(**state)
    button(app, VERIFY).click().run()
    assert not app.exception and button(app, IMPORT).disabled
    assert not app.session_state["database"]


def test_demo_preview_never_offers_write_or_identity_network():
    app = app_with_file(demo=True)
    assert not app.exception and not app.button
    assert len(app.dataframe) == 3 and not app.session_state["calls"]


def test_owner_switch_requires_fresh_verification_and_hides_prior_result():
    app = app_with_file()
    button(app, VERIFY).click().run()
    button(app, IMPORT).click().run()
    button(app, LOAD).click().run()
    app.session_state["owner"] = "second@example.invalid"
    app.run()
    assert len(app.dataframe) == 3 and button(app, IMPORT).disabled
    button(app, VERIFY).click().run()
    button(app, LOAD).click().run()
    assert any("없습니다" in s.value for s in app.info)
    assert len(app.session_state["database"]) == 1


def test_identity_expiry_disables_import_without_background_refresh():
    app = app_with_file()
    button(app, VERIFY).click().run()
    app.session_state["now"] = NOW + timedelta(minutes=11)
    app.run()
    assert button(app, IMPORT).disabled and len(app.session_state["calls"]) == 1


def test_actual_upload_widget_smoke():
    app = app_with_file(fake_upload=False)
    assert not app.exception and len(app.get("file_uploader")) == 1
    assert not app.session_state["calls"] and button(app, IMPORT).disabled


def test_partial_coverage_shown_but_not_saved():
    payload = bundle()
    payload["requested_reports"].append({"year": "2026", "report_code": "11014"})
    payload["attempts"].append({**payload["attempts"][0], "report_code": "11014", "status": "failed",
                                "cause": "transport_error", "http_status": None, "api_status": None})
    app = app_with_file(payload)
    button(app, VERIFY).click().run()
    assert button(app, IMPORT).disabled
    assert list(app.dataframe[1].value["수집 상태"]) == ["수집", "조회 실패"]


def test_official_identity_and_market_resolution():
    def get(url, **kw):
        assert url.endswith("005930/basic") and kw["timeout"] == 5 and not kw["allow_redirects"]
        return SimpleNamespace(status_code=200, json=lambda: {"itemCode": "005930", "stockExchangeType": {"code": "KS"}})
    identity = resolve_identity("005930.KS", lambda: MAP, get=get, now=NOW)
    assert verified_codes(identity, "005930.KS", NOW) == {"005930": MAP["005930"]}
    assert verified_codes(identity, "005930.KQ", NOW) is None
    assert verified_codes(identity, "005930.KS", NOW+timedelta(minutes=10)) is None
    with pytest.raises(EvidenceError):
        resolve_identity("005930.KQ", lambda: MAP, get=get, now=NOW)
    expired = CorporateCodeMap(MAP, diagnostic={"mapping_source": "official_snapshot", "snapshot_valid_until": NOW.isoformat()})
    with pytest.raises(EvidenceError):
        resolve_identity("005930.KS", lambda: expired, get=get, now=NOW)


def test_existing_parser_and_app_functions_preserved(app_module):
    payload = bundle()
    before = deepcopy(payload)
    rows = metric_rows(payload, app_module.extract_dart_metrics)
    assert rows[0]["매출"] == 250000 and "누적" in rows[0]["금액 기준"] and payload == before
    base = subprocess.check_output(['git', 'show', '5cadb203:app.py']).decode('utf-8-sig')
    current = Path('app.py').read_text(encoding='utf-8-sig')
    def functions(text):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(text).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert functions(current) == functions(base)
    assert 'render_dart_evidence(' in current
