"""Public demo entrypoint for Streamlit Community Cloud."""

import os

os.environ.setdefault("AUTH_MODE", "public_demo")

import app  # noqa: F401,E402
