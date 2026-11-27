"""pytest plugin: record every report_sections() output (hash + full text) per test."""
import hashlib, json, os
import pytest
from stock_lab_core import report_evidence as _re

OUT = os.environ["RS_RECORD_OUT"]  # JSON list of {test, n, sha, len, blob}
_rows = []
_current = {"id": None, "n": 0}
_orig = _re.report_sections

def _wrapped(*a, **k):
    result = _orig(*a, **k)
    blob = repr(result)
    _current["n"] += 1
    _rows.append({"test": _current["id"], "n": _current["n"],
                  "sha": hashlib.sha256(blob.encode()).hexdigest(), "len": len(blob), "blob": blob if os.environ.get("RS_BLOB") else None})
    return result

_re.report_sections = _wrapped

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _current["id"], _current["n"] = item.nodeid, 0
    yield

def pytest_sessionfinish(session):
    with open(OUT, "w") as f:
        json.dump(_rows, f, ensure_ascii=False, indent=0)
