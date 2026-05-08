"""Public demo entrypoint for Streamlit Community Cloud."""

import os

os.environ["STOCK_LAB_FORCE_AUTH_MODE"] = "public_demo"
os.environ["AUTH_MODE"] = "public_demo"

import app  # noqa: F401,E402
