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
