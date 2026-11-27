"""Streamlit Cloud runs Python < 3.12: PEP 701 f-strings (same quotes nested) crash the app on import."""

import shutil
import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PY311 = sys.executable if sys.version_info[:2] == (3, 11) else shutil.which("python3.11")

CHECK = """
import ast, pathlib, sys
bad = []
for path in sys.argv[1:]:
    try:
        ast.parse(pathlib.Path(path).read_text(encoding="utf-8-sig"), path)
    except SyntaxError as exc:
        bad.append(f"{path}:{exc.lineno}: {exc.msg}")
print("\\n".join(bad))
sys.exit(1 if bad else 0)
"""


@pytest.mark.skipif(PY311 is None, reason="python3.11 not installed")
def test_sources_parse_on_python311():
    files = [str(p) for p in [ROOT / "app.py", *sorted((ROOT / "stock_lab_core").rglob("*.py"))]]
    result = subprocess.run([PY311, "-c", CHECK, *files], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
