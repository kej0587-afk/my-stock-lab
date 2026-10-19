"""Shared pytest fixtures.

`calc_scores_and_decision` (the function targeted for the upcoming
guard -> policy -> signal -> sizing decomposition) lives inside app.py,
which is a Streamlit script with module-level UI/auth code. Importing it
outside of `streamlit run` works ("bare mode") as long as
STOCK_LAB_FORCE_AUTH_MODE=public_demo is set *before* the import, so that
require_login()/init_db() short-circuit without needing real secrets or a
Supabase connection.

The import is slow (~10s, loads sector maps etc.) so it is session-scoped.
"""
import os
import sys
import pathlib

import pytest

os.environ.setdefault("STOCK_LAB_FORCE_AUTH_MODE", "public_demo")

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def app_module():
    import app  # noqa: WPS433 (intentional late import, see module docstring)
    return app


@pytest.fixture(autouse=True)
def isolate_yahoo_metadata_cache(monkeypatch):
    from stock_lab_core.yahoo_metadata import yahoo_metadata_reader as reader

    reader.clear_cache()
    monkeypatch.setattr(reader, "_retry_after", 0.0)
    monkeypatch.setattr(reader, "_rate_limit_streak", 0)
    monkeypatch.setattr(reader, "_last_started", float("-inf"))
    monkeypatch.setattr(reader, "_min_interval", 0)
    yield
    reader.clear_cache()


@pytest.fixture(autouse=True)
def isolate_public_economic_disk_cache(monkeypatch, tmp_path):
    from stock_lab_core import economic_cache

    monkeypatch.setattr(economic_cache, "CACHE_PATH", tmp_path / "economic_last_success.json")
